"""routes_subscriptions — abbonamenti mensili (fase 2a).

Blueprint `subscriptions`: `/api/subscription` (stato), `/api/subscription/checkout`,
`/account/subscription/return` (ritorno dall'approvazione), `/api/subscription/cancel`
e il webhook firmato di PayPal (`WEBHOOK_PATH`, l'unico percorso esente da CSRF).
La logica vive in `subscriptions`; il fornitore si raggiunge da
`subscriptions.PROVIDERS`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata,
`current_account`, `account_gate` (None o la risposta 404 degli account
spenti), `client_ip`, `ip_rl_check` e `base_url`. Non importa `audiobook_app`.
"""
import json

from flask import Blueprint, abort, jsonify, redirect, request

import subscriptions

bp = Blueprint("subscriptions", __name__)

WEBHOOK_PATH = "/api/billing/paypal/webhook"
FUNCS = ("current_account", "account_gate", "client_ip", "ip_rl_check", "base_url")
_cfg = {}

_CHECKOUT_ERRORS = {
    "bad_plan": ("bad_plan", "Unknown plan", 400),
    "terms_required": ("terms_required", "Terms and immediate start must be accepted", 400),
    "exists": ("subscription_exists", "A subscription is already active", 409),
    "disabled": ("subscriptions_disabled", "Subscriptions are not available", 404),
    "error": ("provider_error", "Payment provider unavailable, please retry", 502),
}


def configure(**fns):
    missing = [n for n in FUNCS if n not in fns]
    assert not missing, f"routes_subscriptions.configure: mancano {missing}"
    _cfg.update(fns)


def _err(code, msg, status, **extra):
    return jsonify({"error": msg, "error_code": code, **extra}), status


def _account():
    """(account, None) o (None, risposta d'errore)."""
    gate = _cfg["account_gate"]()
    if gate:
        return None, gate
    acct = _cfg["current_account"]()
    if not acct:
        return None, _err("unauthorized", "Sign in required", 401)
    return acct, None


@bp.route("/api/subscription", methods=["GET"])
def api_subscription_status():
    """Stato per l'Area personale; con un abbonamento in attivazione lo
    ricontrolla subito presso il fornitore (`subscriptions.poke`), cosi' la
    pagina che aspetta la conferma la vede appena c'e'."""
    acct, err = _account()
    if err:
        return err
    subscriptions.poke(acct)
    return jsonify(subscriptions.status_for(acct))


@bp.route("/api/subscription/checkout", methods=["POST"])
def api_subscription_checkout():
    acct, err = _account()
    if err:
        return err
    if not subscriptions.enabled():
        return _err(*_CHECKOUT_ERRORS["disabled"])
    allowed, retry = _cfg["ip_rl_check"]("sub_checkout", _cfg["client_ip"](), 10, 30)
    if not allowed:
        return _err("rate_limited", "Too many requests", 429, retry_after=retry)
    data = request.get_json(silent=True) or {}
    base = (_cfg["base_url"]() or "").rstrip("/")
    status, url = subscriptions.start_checkout(
        acct, str(data.get("plan") or ""),
        accepted_terms=data.get("accept_terms") is True,
        waived_withdrawal=data.get("waive_withdrawal") is True,
        return_url=f"{base}/account/subscription/return",
        cancel_url=f"{base}/account?sub=cancelled")
    if status != "ok":
        return _err(*_CHECKOUT_ERRORS[status])
    return jsonify({"approve_url": url})


@bp.route("/account/subscription/return", methods=["GET"])
def account_subscription_return():
    """Ritorno dall'approvazione: decide lo stato remoto, mai il solo ritorno."""
    acct, err = _account()
    if err:
        return redirect("/account")
    sub = subscriptions.get(request.args.get("sid") or "")
    if not sub or sub["account_id"] != acct["id"]:
        abort(404)
    ext = request.args.get("subscription_id")
    if ext and ext != sub["external_id"]:
        abort(404)
    sub = subscriptions.reconcile_one(sub["id"])
    notice = {"active": "ok", "activating": "pending", "pending": "pending"}.get(sub["status"])
    return redirect("/account" + (f"?sub={notice}" if notice else ""))


@bp.route("/api/subscription/cancel", methods=["POST"])
def api_subscription_cancel():
    acct, err = _account()
    if err:
        return err
    data = request.get_json(silent=True) or {}
    if data.get("confirm") is not True:
        return _err("confirm_required", "Confirmation required", 400)
    out = subscriptions.request_cancel(acct["id"], "user")
    if out is None:
        return _err("no_subscription", "No active subscription", 404)
    return jsonify({"ok": True, **out})


@bp.route(WEBHOOK_PATH, methods=["POST"])
def paypal_webhook():
    """Webhook PayPal: firma verificata dal fornitore, poi `handle_event`
    (idempotente per id evento). 500 su errore di elaborazione: PayPal ritenta."""
    allowed, _retry = _cfg["ip_rl_check"]("paypal_webhook", _cfg["client_ip"](), 120, 3000)
    if not allowed:
        return _err("rate_limited", "Too many requests", 429)
    try:
        event = json.loads(request.get_data(cache=False) or b"")
    except ValueError:
        return _err("bad_request", "Invalid JSON", 400)
    provider = subscriptions.PROVIDERS["paypal"]
    if not isinstance(event, dict) or not provider.verify_webhook(request.headers, event):
        print(f"[subscriptions] webhook rifiutato: firma non valida "
              f"({str(event.get('id') if isinstance(event, dict) else '')[:40]})", flush=True)
        return _err("bad_signature", "Invalid signature", 400)
    ev = provider.parse_webhook(event)
    if ev is None:
        return jsonify({"outcome": "ignored"})
    try:
        outcome = subscriptions.handle_event("paypal", ev)
    except Exception as e:  # noqa: BLE001 - l'evento resta da processare
        print(f"[subscriptions] webhook {ev.event_id} {ev.raw_type}: {type(e).__name__}: {e}",
              flush=True)
        return _err("processing_error", "Retry later", 500)
    print(f"[subscriptions] webhook {ev.event_id} {ev.raw_type} -> {outcome}", flush=True)
    return jsonify({"outcome": outcome})
