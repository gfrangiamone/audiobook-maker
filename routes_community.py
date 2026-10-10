"""routes_community — API pubbliche della community e del supporto (E3, seam
community pubblica, 2026-10-10).

Blueprint `community`: `/api/community/stats/{today,month}`,
`/api/community/news` (GET), `/api/community/feedback` (GET, POST, DELETE
del proprio), `/api/support/contact`; con la pulizia del testo
(`_sanitize_text`, usata anche dall'admin), i limiti per IP del feedback,
l'avviso all'admin di un nuovo feedback e la sua moderazione/traduzione
in background. Spostato pari pari da `audiobook_app`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app), i contatori delle statistiche,
`_hash_ip`, `_ip_rl_check`, `client_ip` e l'email admin. Non importa
`audiobook_app`.
"""
import hashlib
import hmac
import html as html_mod
import re
import secrets
import threading
import time
import uuid

from flask import Blueprint, jsonify, request

import community_moderator
import community_store
import community_translator
import email_service
import i18n as _i18n
from env_utils import env_int

bp = Blueprint("community", __name__)

_cfg = {}

FUNCS = ['_stats_today_count', '_stats_month_by_lang', '_hash_ip', '_ip_rl_check', 'client_ip']
VALUES = ('admin_email',)


def configure(**fns):
    """`fns`: una funzione per ogni nome in FUNCS e VALUES (la app passa
    lambda che risolvono i suoi globali a ogni chiamata)."""
    missing = [n for n in FUNCS + list(VALUES) if n not in fns]
    assert not missing, f"routes_community.configure: mancano {missing}"
    _cfg.update(fns)


# Valori della app usati dal codice spostato: risolti a ogni chiamata.
def _admin_email():
    return _cfg["admin_email"]()


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _stats_today_count(*a, **k):
    return _cfg["_stats_today_count"](*a, **k)

def _stats_month_by_lang(*a, **k):
    return _cfg["_stats_month_by_lang"](*a, **k)

def _hash_ip(*a, **k):
    return _cfg["_hash_ip"](*a, **k)

def _ip_rl_check(*a, **k):
    return _cfg["_ip_rl_check"](*a, **k)

def client_ip(*a, **k):
    return _cfg["client_ip"](*a, **k)


@bp.route("/api/community/stats/today")
def api_community_stats_today():
    """Conteggio audiolibri completati oggi (cache 60s)."""
    return jsonify({"count": _stats_today_count()})


@bp.route("/api/community/stats/month")
def api_community_stats_month():
    """Aggregato mensile per lingua TTS (cache 5min).
    Schema: {monthly: int, top: [{lang, count}, ...], other: int}."""
    return jsonify(_stats_month_by_lang())


# ─── COMMUNITY: NEWS ────────────────────────────────────────────────
_NEWS_TAGS = {"feature", "fix", "info"}
_NEWS_LANGS = set(_i18n.LANGS)


def _sanitize_text(s, maxlen, keep_newlines=False):
    """Strip HTML tags + collapse whitespace + truncate.

    ``keep_newlines=True`` (body delle news, scritto in Markdown-lite) conserva
    gli a capo: collassa solo gli spazi orizzontali e comprime le righe vuote
    consecutive a una sola. I tag HTML restano vietati in ogni caso: il markup
    lo genera il renderer client (``static/js/news_md.js``) a partire dai
    marker Markdown, mai il testo inserito.
    """
    if not isinstance(s, str):
        return ""
    s = re.sub(r"<[^>]+>", "", s)
    if keep_newlines:
        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"[^\S\n]+", " ", s)     # spazi/tab, mai gli a capo
        s = re.sub(r"\n{3,}", "\n\n", s)     # max una riga vuota di stacco
        s = "\n".join(line.strip() for line in s.split("\n")).strip()
    else:
        s = re.sub(r"\s+", " ", s).strip()
    return s[:maxlen]


@bp.route("/api/community/news", methods=["GET"])
def api_community_news():
    """Lista news pubbliche (top 10 non archiviate, sort desc per created_at)."""
    items = community_store.news().all(include_archived=False)
    items = sorted(items, key=lambda x: x.get("created_at", 0), reverse=True)[:10]
    out = []
    for it in items:
        out.append({
            "id": it.get("id"),
            "tag": it.get("tag", "info"),
            "title": it.get("title", ""),
            "body": it.get("body", ""),
            "lang": it.get("lang", "en"),
            "title_i18n": it.get("title_i18n") or {},
            "body_i18n": it.get("body_i18n") or {},
            "banner": bool(it.get("banner", False)),
            "created_at": it.get("created_at", 0),
        })
    return jsonify({"items": out})


# E3 (seam admin, parte 5): news admin in routes_admin_community.
_feedback_rate_lock = threading.Lock()
_feedback_rate: dict[str, list[float]] = {}  # ip_hash -> list[ts]
_FB_LIMIT_HOUR = 1
_FB_LIMIT_DAY = 5
_feedback_email_lock = threading.Lock()
_feedback_email_last = 0.0
_FB_EMAIL_THROTTLE = 1800.0  # 30 min


def _feedback_check_rate(ip_hash: str) -> bool:
    """True se il client può inviare ora; False se sopra il limite."""
    now = time.time()
    # consulta il persistent store: i feedback cancellati (hard-delete)
    # non devono bloccare il re-inserimento
    items = community_store.feedback().all(include_archived=False)
    recent = [it for it in items if it.get("ip_hash") == ip_hash and (now - it.get("created_at", 0)) < 86400]
    last_hour = sum(1 for it in recent if (now - it.get("created_at", 0)) < 3600)
    last_day = len(recent)
    if last_hour >= _FB_LIMIT_HOUR or last_day >= _FB_LIMIT_DAY:
        return False
    with _feedback_rate_lock:
        hist = _feedback_rate.get(ip_hash, [])
        hist = [t for t in hist if now - t < 86400]
        hist.append(now)
        _feedback_rate[ip_hash] = hist
    return True


def _notify_admin_new_feedback(item: dict, comment_it: str | None = None, unvalidated: bool = False) -> None:
    """Throttled (30 min) email all'admin per nuovo feedback.

    Se ``comment_it`` è fornito, viene usato come corpo del commento
    (tipicamente la traduzione italiana prodotta dall'LLM); altrimenti
    si usa il commento originale presente in ``item``.
    """
    global _feedback_email_last
    if not _admin_email():
        return
    now = time.time()
    with _feedback_email_lock:
        if now - _feedback_email_last < _FB_EMAIL_THROTTLE:
            return
        _feedback_email_last = now
    try:
        rating = int(item.get("rating", 0))
        unvalidated_flag = unvalidated or bool(item.get("moderation_unvalidated", False))
        stars = "★" * rating + "☆" * (5 - rating)
        name = html_mod.escape(item.get("name") or "Anonimo")
        original = item.get("comment") or ""
        chosen_text = comment_it if (comment_it and comment_it.strip()) else original
        comment = html_mod.escape(chosen_text)
        # mostra anche l'originale se diverso dalla traduzione usata
        original_block = ""
        if comment_it and original and comment_it.strip() != original.strip():
            original_block = (
                f"<p style='font-size:.9em;color:#666;margin-top:10px'>"
                f"<b>Originale:</b></p>"
                f"<p style='border-left:3px solid #ccc;padding-left:8px;color:#666'>"
                f"{html_mod.escape(original)}</p>"
            )
        unvalidated_banner = ""
        if unvalidated_flag:
            unvalidated_banner = (
                "<p style='background:#fff3cd;border:1px solid #ffc107;padding:8px 12px;"
                "border-radius:4px;color:#856404;margin-bottom:12px'>"
                "<b>Attenzione:</b> questo commento non è stato validato dal sistema LLM."
                "</p>"
            )
        body = (
            f"{unvalidated_banner}"
            f"<p><b>Nuovo feedback ricevuto:</b></p>"
            f"<p>Voto: <span style='font-size:1.2em'>{stars}</span> ({rating}/5)</p>"
            f"<p>Nome: {name}</p>"
            f"<p>Commento (IT):</p><p style='border-left:3px solid #d9a441;padding-left:8px'>"
            f"{comment or '<i>(nessun commento)</i>'}</p>"
            f"{original_block}"
            f"<p style='font-size:.85em;color:#888'>ID: {item.get('id','')}</p>"
        )
        subject = f"[ABM] Nuovo feedback: {rating}★"
        if unvalidated_flag:
            subject = "[NON VALIDATO — LLM offline] " + subject
        email_service._send_email(_admin_email(), subject, body)
    except Exception as e:
        print(f"[feedback] admin email failed: {e!s}")


@bp.route("/api/community/feedback", methods=["GET"])
def api_community_feedback_list():
    """Lista feedback pubblici + statistiche aggregate."""
    items = community_store.feedback().all(include_archived=False)
    items = sorted(items, key=lambda x: x.get("created_at", 0), reverse=True)
    total = len(items)
    if total > 0:
        avg = round(sum(int(it.get("rating", 0)) for it in items) / total, 2)
    else:
        avg = 0.0
    histogram = [0, 0, 0, 0, 0]  # rating 1..5 -> idx 0..4
    for it in items:
        r = int(it.get("rating", 0))
        if 1 <= r <= 5:
            histogram[r - 1] += 1
    public_items = []
    for it in items[:50]:
        public_items.append({
            "id": it.get("id"),
            "rating": it.get("rating"),
            "name": it.get("name") or "",
            "comment": it.get("comment") or "",
            "comment_lang": it.get("comment_lang") or "",
            "comment_i18n": it.get("comment_i18n") or {},
            "created_at": it.get("created_at", 0),
            "admin_reply_at": it.get("admin_reply_at", 0),
            "admin_reply_lang": it.get("admin_reply_lang") or "",
            "admin_reply_text": it.get("admin_reply_text") or "",
            "admin_reply_i18n": it.get("admin_reply_i18n") or {},
        })
    return jsonify({"items": public_items, "avg": avg, "total": total, "histogram": histogram})


def _process_new_feedback(item: dict) -> None:
    """Background: translate the comment (best-effort), persist the i18n
    fields, then send the admin email using the Italian translation.

    Always emails the admin (subject to the existing throttle), even if
    translation is unavailable or empty.
    """
    item_id = item.get("id") or ""
    comment = (item.get("comment") or "").strip()
    print(f"[feedback] post-process id={item_id} comment_len={len(comment)} "
          f"llm_available={community_translator.is_available()}")
    comment_it: str | None = None
    if comment and community_translator.is_available():
        try:
            result = community_translator.translate({"comment": comment})
        except Exception as e:
            print(f"[feedback] translation call raised: {e!s}")
            result = None
        print(f"[feedback] translation result id={item_id}: "
              f"{'ok' if result else 'FAILED'}")
        if result:
            patch = {
                "comment_lang": result.get("source_lang") or "",
                "comment_i18n": {
                    lg: (result.get(lg) or {}).get("comment", "")
                    for lg in community_translator.LANGS
                },
            }
            try:
                community_store.feedback().update(item_id, patch)
            except Exception as e:
                print(f"[feedback] translation persist failed for {item_id}: {e!s}")
            comment_it = (patch["comment_i18n"].get("it") or "").strip() or None
    # admin email — always, throttled internally
    try:
        _notify_admin_new_feedback(item, comment_it=comment_it, unvalidated=item.get("moderation_unvalidated", False))
    except Exception as e:
        print(f"[feedback] admin notify failed: {e!s}")


@bp.route("/api/community/feedback", methods=["POST"])
def api_community_feedback_create():
    body = request.get_json(silent=True) or {}
    # honeypot
    if body.get("website"):
        return ("", 204)
    # validate rating
    try:
        rating = int(body.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0
    if rating < 1 or rating > 5:
        return jsonify({"error": "missing_rating"}), 400
    raw_name = (body.get("name") or "").strip()
    if len(raw_name) > 100:
        return jsonify({"error": "name_too_long"}), 400
    raw_comment = (body.get("comment") or "").strip()
    if len(raw_comment) > 500:
        return jsonify({"error": "comment_too_long"}), 400
    name = _sanitize_text(raw_name, 100)
    comment = _sanitize_text(raw_comment, 500)
    # rate limit
    ip = client_ip()
    ip_hash = _hash_ip(ip)
    if not _feedback_check_rate(ip_hash):
        return jsonify({"error": "rate_limit"}), 429
    # moderation gate
    mod_result = community_moderator.validate(name, comment)
    if not mod_result.get("approved", True):
        return jsonify({"error": "inappropriate_content"}), 400
    delete_token = secrets.token_urlsafe(24)
    item = community_store.feedback().add({
        "rating": rating,
        "name": name,
        "comment": comment,
        "ip_hash": ip_hash,
        "delete_token": delete_token,
        "moderation_unvalidated": mod_result.get("unvalidated", False),
    })
    # background: translate comment (if any) then email admin with IT version
    threading.Thread(target=_process_new_feedback, args=(item,), daemon=True).start()
    # Return the delete_token so the client can store it locally (only the
    # original poster, who has it, can later delete the comment).
    return jsonify({"id": item["id"], "delete_token": delete_token}), 200


@bp.route("/api/community/feedback/<item_id>", methods=["DELETE"])
def api_community_feedback_delete(item_id: str):
    """Self-delete: requires the delete_token returned at creation time."""
    body = request.get_json(silent=True) or {}
    token = (body.get("token") or request.headers.get("X-Delete-Token") or "").strip()
    if not token:
        return jsonify({"error": "missing token"}), 400
    item = community_store.feedback().get(item_id)
    if not item:
        return jsonify({"error": "not found"}), 404
    expected = item.get("delete_token") or ""
    if not expected or not hmac.compare_digest(expected, token):
        return jsonify({"error": "forbidden"}), 403
    community_store.feedback().delete(item_id)
    return jsonify({"ok": True}), 200


# ─── Form "Contatta supporto" (footer del sito) ────────────────────
# Inoltra la richiesta alla casella di assistenza. Nessuna persistenza:
# la richiesta vive nella mailbox, non nei nostri store.
_SUPPORT_RL_PER_MIN = env_int("ABM_SUPPORT_RL_PER_MIN", 2)
_SUPPORT_RL_PER_HOUR = env_int("ABM_SUPPORT_RL_PER_HOUR", 6)
_SUPPORT_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_SUPPORT_MSG_MIN = 10


@bp.route("/api/support/contact", methods=["POST"])
def api_support_contact():
    """Richiesta di assistenza dal form pubblico -> email a SUPPORT_EMAIL."""
    body = request.get_json(silent=True) or {}
    # honeypot: rispondiamo ok senza inviare nulla, il bot non impara nulla
    if body.get("website"):
        return jsonify({"ok": True}), 200
    email_addr = _sanitize_text(body.get("email"), 320)
    if not _SUPPORT_EMAIL_RE.match(email_addr):
        return jsonify({"error": "invalid_email"}), 400
    plan = (body.get("plan") or "").strip().lower()
    if plan not in ("free", "premium"):
        return jsonify({"error": "invalid_plan"}), 400
    title = _sanitize_text(body.get("book_title"), 300)
    if not title:
        return jsonify({"error": "missing_title"}), 400
    message = _sanitize_text(body.get("message"), 4000, keep_newlines=True)
    if len(message) < _SUPPORT_MSG_MIN:
        return jsonify({"error": "missing_message"}), 400
    link = _sanitize_text(body.get("download_link"), 500)
    ui_lang = (body.get("lang") or "").strip().lower()[:5]
    ip = client_ip()
    allowed, retry = _ip_rl_check("support", ip,
                                  _SUPPORT_RL_PER_MIN, _SUPPORT_RL_PER_HOUR)
    if not allowed:
        return jsonify({"error": "rate_limit", "retry_after": retry}), 429
    sent = email_service.send_support_request(
        email_addr, plan, title, link, message,
        ui_lang=ui_lang, ip_hash=_hash_ip(ip),
    )
    if not sent:
        return jsonify({"error": "send_failed"}), 502
    return jsonify({"ok": True}), 200
