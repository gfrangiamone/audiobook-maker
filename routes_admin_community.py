"""routes_admin_community — news, feedback, pagina community e reset
anti-abuso (E3, seam admin, parte 5, 2026-10-10).

Blueprint `admin_community`: `/admin/api/news` (crea, con traduzione in
background), `/admin/api/news/<id>`, `/admin/api/news/list`,
`/admin/api/feedback/list`, `/admin/api/feedback/translate-missing`,
`/admin/api/feedback/<id>`, `/admin/api/feedback/<id>/reply` (POST e
DELETE), `/admin/community` (pagina con gate), `/admin/api/abuse/clear/
<group>`. Spostato pari pari da `audiobook_app`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app): guardia, token, auth, gate,
`_sanitize_text`; per riferimento le lingue e i tag delle news e la regex
dei gruppi anti-abuso. Non importa `audiobook_app`.
"""
import functools
import threading
import time

from flask import Blueprint, jsonify, request

import abuse_watch
import community_store
import community_translator
from page_brand import page_template as _page_template

bp = Blueprint("admin_community", __name__)

_cfg = {}
_NEWS_LANGS = ()
_NEWS_TAGS = ()
_ABUSE_GROUP_RE = None


def configure(*, admin_required, admin_token, admin_auth_ok, admin_auth_from_request, render_admin_gate,
              sanitize_text, news_langs, news_tags, abuse_group_re):
    """Funzioni (risolte a ogni chiamata) e costanti condivise dalla app."""
    _cfg.update(admin_required=admin_required, admin_token=admin_token, admin_auth_ok=admin_auth_ok,
                admin_auth_from_request=admin_auth_from_request, render_admin_gate=render_admin_gate,
                sanitize_text=sanitize_text)
    globals()["_NEWS_LANGS"] = news_langs
    globals()["_NEWS_TAGS"] = news_tags
    globals()["_ABUSE_GROUP_RE"] = abuse_group_re


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


def _sanitize_text(*a, **k):
    return _cfg["sanitize_text"](*a, **k)


def admin_required(fn=None, *, as_json=True):
    """La guardia admin della app, applicata a ogni richiesta (le route del
    blueprint si decorano all'import, prima di `configure`)."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            return _cfg["admin_required"](as_json=as_json)(f)(*args, **kwargs)
        return wrapper
    return deco(fn) if fn is not None else deco


# --- news ------------------------------------------------------------
def _translate_news_async(item_id: str, title: str, body: str) -> None:
    """Background: translate a news item title+body, persist."""
    payload = {}
    if title and title.strip():
        payload["title"] = title
    if body and body.strip():
        payload["body"] = body
    if not payload:
        return
    if not community_translator.is_available():
        return
    result = community_translator.translate(payload)
    if not result:
        return
    patch: dict = {}
    if "title" in payload:
        patch["title_i18n"] = {
            lg: (result.get(lg) or {}).get("title", "")
            for lg in community_translator.LANGS
        }
    if "body" in payload:
        patch["body_i18n"] = {
            lg: (result.get(lg) or {}).get("body", "")
            for lg in community_translator.LANGS
        }
    if patch:
        try:
            community_store.news().update(item_id, patch)
        except Exception as e:
            print(f"[news] translation persist failed for {item_id}: {e!s}")


@bp.route("/admin/api/news", methods=["POST"])
@admin_required(as_json=False)
def admin_api_news_create():
    body = request.get_json(silent=True) or {}
    tag = (body.get("tag") or "info").strip().lower()
    if tag not in _NEWS_TAGS:
        return jsonify({"error": "invalid tag"}), 400
    title = _sanitize_text(body.get("title"), 200)
    if not title:
        return jsonify({"error": "title required"}), 400
    # Markdown-lite: gli a capo e i marker sopravvivono, i tag HTML no.
    text = _sanitize_text(body.get("body"), 2000, keep_newlines=True)
    lang = (body.get("lang") or "en").strip().lower()
    if lang not in _NEWS_LANGS:
        return jsonify({"error": "invalid lang"}), 400
    banner = bool(body.get("banner", False))
    item = community_store.news().add({
        "tag": tag, "title": title, "body": text,
        "lang": lang, "banner": banner,
    })
    # translate title+body into all UI langs (best-effort, async)
    threading.Thread(
        target=_translate_news_async,
        args=(item["id"], title, text),
        daemon=True,
    ).start()
    return jsonify(item), 200


@bp.route("/admin/api/news/<item_id>", methods=["POST"])
@admin_required(as_json=False)
def admin_api_news_update(item_id):
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    store = community_store.news()
    if action == "archive":
        ok = store.archive(item_id)
    elif action == "unarchive":
        ok = store.unarchive(item_id)
    elif action == "delete":
        ok = store.delete(item_id)
    elif action == "toggle_banner":
        cur = store.get(item_id)
        if not cur:
            return ("not found", 404)
        ok = store.update(item_id, {"banner": not cur.get("banner", False)}) is not None
    else:
        return jsonify({"error": "invalid action"}), 400
    return ("ok", 200) if ok else ("not found", 404)


@bp.route("/admin/api/news/list", methods=["GET"])
@admin_required(as_json=False)
def admin_api_news_list():
    items = community_store.news().all(include_archived=True)
    items = sorted(items, key=lambda x: x.get("created_at", 0), reverse=True)
    return jsonify({"items": items})


# ─── COMMUNITY: FEEDBACK ────────────────────────────────────────────


# --- community ------------------------------------------------------------
@bp.route("/admin/api/feedback/list", methods=["GET"])
@admin_required(as_json=False)
def admin_api_feedback_list():
    items = community_store.feedback().all(include_archived=True)
    items = sorted(items, key=lambda x: x.get("created_at", 0), reverse=True)
    return jsonify({"items": items})


@bp.route("/admin/api/feedback/translate-missing", methods=["POST"])
@admin_required(as_json=False)
def admin_api_feedback_translate_missing():
    """Backfill: translate any feedback items that have a comment but no
    populated comment_i18n. Synchronous; returns a summary so the admin
    can confirm what happened.
    """
    if not community_translator.is_available():
        return jsonify({"error": "llm unavailable"}), 503
    items = community_store.feedback().all(include_archived=True)
    updated = 0
    failed = 0
    skipped = 0
    for it in items:
        comment = (it.get("comment") or "").strip()
        if not comment:
            skipped += 1
            continue
        i18n = it.get("comment_i18n") or {}
        # Si ritraduce anche quando il set e' incompleto o contiene copie
        # dell'originale in lingue diverse dalla sorgente (il modello a volte
        # ricopia il verbatim nello slot sbagliato).
        if not community_translator.needs_translation(
                comment, i18n, it.get("comment_lang") or ""):
            skipped += 1
            continue
        try:
            result = community_translator.translate({"comment": comment})
        except Exception as e:
            print(f"[feedback-backfill] translate raised for {it.get('id')}: {e!s}")
            result = None
        if not result:
            failed += 1
            continue
        patch = {
            "comment_lang": result.get("source_lang") or "",
            "comment_i18n": {
                lg: (result.get(lg) or {}).get("comment", "")
                for lg in community_translator.LANGS
            },
        }
        try:
            community_store.feedback().update(it.get("id"), patch)
            updated += 1
        except Exception as e:
            print(f"[feedback-backfill] persist failed for {it.get('id')}: {e!s}")
            failed += 1
    return jsonify({"updated": updated, "failed": failed, "skipped": skipped,
                    "total": len(items)})


@bp.route("/admin/api/feedback/<item_id>", methods=["POST"])
@admin_required(as_json=False)
def admin_api_feedback_update(item_id):
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    store = community_store.feedback()
    if action == "archive":
        ok = store.archive(item_id)
    elif action == "unarchive":
        ok = store.unarchive(item_id)
    elif action == "delete":
        ok = store.delete(item_id)
    else:
        return jsonify({"error": "invalid action"}), 400
    return ("ok", 200) if ok else ("not found", 404)


@bp.route("/admin/api/feedback/<item_id>/reply", methods=["POST"])
@admin_required(as_json=False)
def admin_api_feedback_reply(item_id):
    """Create or update an admin reply to a feedback item.
    Translates the reply into all 7 UI languages via LLM.
    First call creates the reply, subsequent calls edit it (preserving
    the original `admin_reply_at` timestamp and tracking edits with
    `admin_reply_edited_at`).
    """
    body = request.get_json(silent=True) or {}
    reply_text = (body.get("reply") or "").strip()
    if not reply_text:
        return jsonify({"error": "reply text required"}), 400
    if len(reply_text) > 2000:
        return jsonify({"error": "reply text exceeds 2000 characters"}), 400
    store = community_store.feedback()
    existing = store.get(item_id)
    if not existing:
        return jsonify({"error": "feedback item not found"}), 404
    if not community_translator.is_available():
        return jsonify({"error": "llm unavailable"}), 503
    try:
        result = community_translator.translate({"reply": reply_text})
    except Exception as e:
        print(f"[feedback-reply] translate raised for {item_id}: {e!s}")
        result = None
    if not result:
        return jsonify({"error": "translation failed, please retry"}), 500
    now = int(time.time())
    prior_at = int(existing.get("admin_reply_at", 0) or 0)
    patch = {
        "admin_reply_text": reply_text,
        "admin_reply_lang": "it",
        "admin_reply_i18n": {
            lg: (result.get(lg) or {}).get("reply", "")
            for lg in community_translator.LANGS
        },
        "admin_reply_at": prior_at if prior_at > 0 else now,
    }
    if prior_at > 0:
        patch["admin_reply_edited_at"] = now
    try:
        community_store.feedback().update(item_id, patch)
    except Exception as e:
        print(f"[feedback-reply] persist failed for {item_id}: {e!s}")
        return jsonify({"error": "persist failed"}), 500
    return jsonify({"ok": True, "at": patch["admin_reply_at"], "edited": prior_at > 0})


@bp.route("/admin/api/feedback/<item_id>/reply", methods=["DELETE"])
@admin_required(as_json=False)
def admin_api_feedback_reply_delete(item_id):
    """Remove an admin reply from a feedback item."""
    store = community_store.feedback()
    existing = store.get(item_id)
    if not existing:
        return jsonify({"error": "feedback item not found"}), 404
    patch = {
        "admin_reply_text": "",
        "admin_reply_lang": "",
        "admin_reply_i18n": {},
        "admin_reply_at": 0,
        "admin_reply_edited_at": 0,
    }
    try:
        community_store.feedback().update(item_id, patch)
    except Exception as e:
        print(f"[feedback-reply] delete failed for {item_id}: {e!s}")
        return jsonify({"error": "persist failed"}), 500
    return jsonify({"ok": True})


@bp.route("/admin/community", methods=["GET"])
def admin_community_page():
    if not _admin_token():
        return ("Admin community UI disabled.", 404,
                {"Content-Type": "text/plain; charset=utf-8"})
    token = _admin_auth_from_request()
    if not _admin_auth_ok(token):
        return (_render_admin_gate("Community Admin", "/admin/community"),
                200, {"Content-Type": "text/html; charset=utf-8"})
    html = _page_template("admin_community")
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.route("/admin/api/abuse/clear/<group>", methods=["POST"])
@admin_required
def admin_abuse_clear(group):
    """Ripristino di un gruppo bloccato dalla moderazione anti-abuso: azzera il
    verdetto. L'utente rilancia dal job in `analyzed` con riuso dei chunk.
    Nessun refund: il job non era pagato."""
    if not _ABUSE_GROUP_RE.match(group or ""):
        return jsonify({"error": "invalid group"}), 400
    try:
        cleared = bool(abuse_watch.clear_verdict(group))
    except Exception as e:
        return jsonify({"error": f"clear failed: {e}"}), 500
    print(f"[admin] abuse_watch clear {group}: {'ok' if cleared else 'no verdict'}", flush=True)
    return jsonify({"ok": True, "group": group, "cleared": cleared})


# E3 (seam admin, parte 4): stats in routes_admin_jobs.
