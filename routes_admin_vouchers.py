"""routes_admin_vouchers — pagina e API dei voucher (E3, seam admin, parte 3, 2026-10-10).

Blueprint `admin_vouchers`: `/admin/vouchers` (pagina con gate),
`/admin/api/vouchers` (lista e creazione), `/admin/api/vouchers/<code>/
revoke`, `/admin/api/vouchers/<code>/notify` (email con il codice).
Spostato pari pari da `audiobook_app`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app): la guardia `admin_required`, il token
admin, l'autenticazione e la pagina di gate, `_log_activity`, `client_ip`.
I voucher stessi vivono in `payment` (importato direttamente, come fa la
app). Non importa `audiobook_app`.
"""
import functools
import re
import secrets
import time

from flask import Blueprint, jsonify, request

import email_service
import payment
from email_service import _smtp_available
from page_brand import page_template as _page_template
from payment import VOUCHER_EXPIRY_DAYS, _create_voucher, _save_vouchers, _voucher_remaining

bp = Blueprint("admin_vouchers", __name__)

_cfg = {}


def configure(*, admin_required, admin_token, admin_auth_ok, admin_auth_from_request,
              render_admin_gate, log_activity, client_ip):
    """Funzioni della app, risolte a ogni chiamata."""
    _cfg.update(admin_required=admin_required, admin_token=admin_token, admin_auth_ok=admin_auth_ok,
                admin_auth_from_request=admin_auth_from_request, render_admin_gate=render_admin_gate,
                log_activity=log_activity, client_ip=client_ip)


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _admin_token():
    return _cfg["admin_token"]()


def _admin_auth_ok(provided):
    return _cfg["admin_auth_ok"](provided)


def _admin_auth_from_request():
    return _cfg["admin_auth_from_request"]()


def _render_admin_gate(title, target_url):
    return _cfg["render_admin_gate"](title, target_url)


def _log_activity(*a, **k):
    return _cfg["log_activity"](*a, **k)


def client_ip():
    return _cfg["client_ip"]()


def admin_required(fn=None, *, as_json=True):
    """La guardia admin della app, applicata a ogni richiesta (le route del
    blueprint si decorano all'import, prima di `configure`)."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            return _cfg["admin_required"](as_json=as_json)(f)(*args, **kwargs)
        return wrapper
    return deco(fn) if fn is not None else deco


@bp.route("/admin/vouchers", methods=["GET"])
def admin_vouchers_page():
    if not _admin_token(): return ("Admin voucher UI disabled.", 404, {"Content-Type": "text/plain; charset=utf-8"})
    token = _admin_auth_from_request()
    if not _admin_auth_ok(token): return _render_admin_gate("Voucher Admin", "/admin/vouchers"), 200, {"Content-Type": "text/html; charset=utf-8"}
    html = _page_template("admin_vouchers")
    return html, 200, {"Content-Type": "text/html; charset=utf-8",
                       "X-Robots-Tag": "noindex, nofollow"}


@bp.route("/admin/api/vouchers", methods=["GET", "POST"])
@admin_required
def admin_api_vouchers():
    """GET: elenca voucher. POST: crea nuovo voucher.

    Autenticazione via header X-Admin-Token (confronto costante-time).
    """

    ip = client_ip()

    if request.method == "GET":
        items = []
        for code, v in payment._vouchers.items():
            items.append({
                "code": code,
                "email": v.get("email", ""),
                "amount_eur": v.get("amount_eur", 0),
                "remaining_eur": _voucher_remaining(v),
                "base_amount_eur": v.get("base_amount_eur", 0),
                "created_at": v.get("created_at"),
                "expires_at": v.get("expires_at"),
                "used": bool(v.get("used")),
                "used_at": v.get("used_at"),
                "uses": v.get("uses", []),
                "kind": v.get("kind", "refund"),
                "note": v.get("note", ""),
                "created_by": v.get("created_by", ""),
                "origin_order_id": v.get("origin_order_id"),
                "revoked": bool(v.get("revoked")),
            })
        return jsonify({"vouchers": items, "count": len(items)})

    # POST  →  create
    data = request.json or {}
    email = (data.get("email") or "").strip().lower()
    try:
        amount = float(data.get("amount_eur") or 0)
    except (TypeError, ValueError):
        amount = 0
    try:
        days = int(data.get("days") or 180)
    except (TypeError, ValueError):
        days = 180
    kind = (data.get("kind") or "promo").strip().lower()
    note = (data.get("note") or "").strip()
    origin_job_id = (data.get("job_id") or "").strip()
    origin_order_id = (data.get("order_id") or "").strip()
    if not email or not re.match(r'^[^\s@]+@[^\s@]+\.[^\s@]{2,}$', email):
        return jsonify({"error": "invalid email"}), 400
    if amount <= 0:
        return jsonify({"error": "amount must be > 0"}), 400
    if days <= 0 or days > 3650:
        return jsonify({"error": "days out of range (1..3650)"}), 400
    if kind not in ("promo", "gift", "refund"):
        return jsonify({"error": "invalid kind"}), 400

    # Rimborsi manuali: devono restare tracciabili al job d'origine, altrimenti
    # payment.has_refund_for_job() non li vede e il rimborso automatico (recovery
    # orfani, refund Gemini) ne emette un secondo sullo stesso job.
    if kind == "refund":
        if not origin_job_id:
            # Fallback: job id (22 char base64url) citato nella causale interna.
            m_job = re.search(r'\b([A-Za-z0-9_-]{22})\b', note)
            if m_job:
                origin_job_id = m_job.group(1)
        if origin_job_id and not origin_order_id:
            for _oid, _pay in payment._payments.items():
                if origin_job_id in (_pay.get("used_for_job"), _pay.get("job_id")):
                    origin_order_id = _oid
                    break
    else:
        origin_job_id = origin_order_id = ""

    # Codice con prefisso a seconda del tipo
    prefix = "PROMO-" if kind == "promo" else ("GIFT-" if kind == "gift" else "")
    # _generate_voucher_code dà core XXXX-XXXX-XXXX; per prefisso lo componiamo manualmente
    _alpha = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    custom_code = None
    if prefix:
        for _ in range(20):
            core = "-".join("".join(secrets.choice(_alpha) for _ in range(4)) for _ in range(3))
            cand = prefix + core
            if cand not in payment._vouchers:
                custom_code = cand
                break
        if not custom_code:
            return jsonify({"error": "code generation failed"}), 500

    code, bonus_amount = _create_voucher(
        email, amount,
        origin_order_id=origin_order_id or None,
        origin_job_id=origin_job_id or None,
        kind=kind,
        note=note,
        created_by="admin",
        expiry_days=days,
        apply_bonus=False,       # promo/gift: importo nominale, niente +10%
        code=custom_code,
    )
    _log_activity("", "", f"ADMIN_VOUCHER_CREATE:{kind}", "", ip, code[:8] + "...", email)
    print(f"[admin] voucher created via UI: {code} kind={kind} email={email} "
          f"amount={amount:.2f} days={days} job={origin_job_id or '-'} "
          f"order={origin_order_id or '-'} ip={ip}")
    return jsonify({
        "code": code,
        "amount_eur": bonus_amount,
        "expires_at": payment._vouchers[code].get("expires_at"),
        "kind": kind,
        "origin_job_id": origin_job_id or None,
        "origin_order_id": origin_order_id or None,
    })


@bp.route("/admin/api/vouchers/<code>/revoke", methods=["POST"])
@admin_required
def admin_api_voucher_revoke(code):
    """Revoca (marca usato) un voucher."""
    code = (code or "").strip().upper()
    reason = ((request.json or {}).get("reason") or "").strip()[:200]
    with payment._vouchers_lock:
        if code not in payment._vouchers:
            return jsonify({"error": "Not found"}), 404
        v = payment._vouchers[code]
        v["used"] = True
        v["used_at"] = time.time()
        v["remaining_eur"] = 0.0
        v["revoked"] = True
        v["revoke_reason"] = reason or "admin revoke"
        _save_vouchers()
    _log_activity("", "", "ADMIN_VOUCHER_REVOKE", "", client_ip(), code[:8] + "...", reason[:40])
    print(f"[admin] voucher revoked via UI: {code} reason={reason!r}")
    return jsonify({"ok": True, "code": code})


@bp.route("/admin/api/vouchers/<code>/notify", methods=["POST"])
@admin_required
def admin_api_voucher_notify(code):
    """Invia al destinatario un'email (in inglese) con i dati del voucher."""
    if not _smtp_available():
        return jsonify({"error": "SMTP not configured"}), 503
    code = (code or "").strip().upper()
    with payment._vouchers_lock:
        v = payment._vouchers.get(code)
        if not v:
            return jsonify({"error": "Not found"}), 404
        email = (v.get("email") or "").strip()
        amount_eur = float(v.get("amount_eur") or 0)
        created_at = v.get("created_at") or time.time()
        expires_at = v.get("expires_at")
    if not email or "@" not in email:
        return jsonify({"error": "voucher has no recipient email"}), 400
    if expires_at:
        valid_days = max(1, round((float(expires_at) - float(created_at)) / 86400))
    else:
        valid_days = VOUCHER_EXPIRY_DAYS
    ok = email_service._send_voucher_notification_email(
        code, email, amount_eur, valid_days, created_at
    )
    if not ok:
        return jsonify({"error": "send failed"}), 502
    _log_activity("", "", "ADMIN_VOUCHER_NOTIFY", "", client_ip(), code[:8] + "...", email)
    print(f"[admin] voucher notification email sent: {code} -> {email}")
    return jsonify({"ok": True, "code": code, "email": email})
