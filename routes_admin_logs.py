"""routes_admin_logs — console del log attivita' (E3, seam admin, parte 2, 2026-10-10).

Blueprint `admin_logs`: `/admin/log-activity` (pagina con le card delle
sessioni, lazy per giorno), `/admin/log-activity/day`, `/admin/log-activity/
export` (CSV) e `/api/admin/funnel`; con la cache delle sessioni per mese,
l'HTML delle card, il funnel e i power user. Spostato pari pari da
`audiobook_app`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata (i
test le sostituiscono sulla app): la guardia `admin_required`, il token
admin, l'autenticazione e la pagina di gate, `_parse_log_sessions`,
`_activity_log_dir`, `_get_browser_lang`; e, per riferimento, `jobs` e il
favicon. Non importa `audiobook_app`.
"""
import functools
import html as html_mod
import json
import re
import threading
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, request

import activity_log
import free_tts_quota
import metrics_store
import user_stats
from env_utils import env_int
from page_brand import render_page as _render_page
from routes_admin_audit import _ACTIVE_JOB_STATUSES

bp = Blueprint("admin_logs", __name__)

_cfg = {}
FAVICON_B64 = ""


def configure(*, admin_required, admin_token, admin_auth_ok, admin_auth_from_request,
              render_admin_gate, parse_log_sessions, activity_log_dir, get_browser_lang,
              jobs, favicon):
    """Funzioni (risolte a ogni chiamata) e oggetti condivisi dalla app."""
    _cfg.update(admin_required=admin_required, admin_token=admin_token, admin_auth_ok=admin_auth_ok,
                admin_auth_from_request=admin_auth_from_request, render_admin_gate=render_admin_gate,
                parse_log_sessions=parse_log_sessions, activity_log_dir=activity_log_dir,
                get_browser_lang=get_browser_lang)
    _cfg["jobs"] = jobs
    globals()["FAVICON_B64"] = favicon


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _admin_token():
    return _cfg["admin_token"]()


def _jobs():
    # `jobs` come funzione: i test ribindano `audiobook_app.jobs`.
    return _cfg["jobs"]()


def _admin_auth_ok(provided):
    return _cfg["admin_auth_ok"](provided)


def _admin_auth_from_request():
    return _cfg["admin_auth_from_request"]()


def _render_admin_gate(title, target_url):
    return _cfg["render_admin_gate"](title, target_url)


def _parse_log_sessions(ym):
    return _cfg["parse_log_sessions"](ym)


def _activity_log_dir():
    return _cfg["activity_log_dir"]()


def _get_browser_lang():
    return _cfg["get_browser_lang"]()


def admin_required(fn=None, *, as_json=True):
    """La guardia admin della app, applicata a ogni richiesta (le route del
    blueprint si decorano all'import, prima di `configure`)."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            return _cfg["admin_required"](as_json=as_json)(f)(*args, **kwargs)
        return wrapper
    return deco(fn) if fn is not None else deco


_LOG_SESSIONS_CACHE = {}
_LOG_SESSIONS_CACHE_MAX = 4
_LOG_SESSIONS_LOCK = threading.Lock()


def _log_sessions_cached(ym):
    fp = activity_log.fingerprint(ym)
    if fp is None:
        return _parse_log_sessions(ym)
    # La cartella nella chiave: la firma del modo db (ultimo id, righe) non
    # distingue due activity.db diversi con lo stesso numero di righe.
    key = (ym, str(_activity_log_dir()), fp)
    with _LOG_SESSIONS_LOCK:
        hit = _LOG_SESSIONS_CACHE.get(key)
    if hit is not None:
        return hit
    result = _parse_log_sessions(ym)
    with _LOG_SESSIONS_LOCK:
        # Una sola voce per mese: la versione precedente del mese corrente
        # non servira' piu'.
        for k in [k for k in _LOG_SESSIONS_CACHE if k[0] == ym]:
            del _LOG_SESSIONS_CACHE[k]
        while len(_LOG_SESSIONS_CACHE) >= _LOG_SESSIONS_CACHE_MAX:
            _LOG_SESSIONS_CACHE.pop(next(iter(_LOG_SESSIONS_CACHE)))
        _LOG_SESSIONS_CACHE[key] = result
    return result


def _m4b_subbar_html(job):
    """Ritorna HTML per la sotto-barra M4B, o stringa vuota se non applicabile."""
    if not job or job.get("m4b_progress_total", 0) <= 0:
        return ""
    cur = job.get("m4b_progress_current", 0)
    tot = job["m4b_progress_total"]
    msg = job.get("m4b_progress_message", "")
    pct = int(cur / tot * 100) if tot > 0 else 0
    return f'''<div class="card-m4b-progress">
  <span class="lbl">M4B</span>
  <progress value="{cur}" max="{tot}"></progress>
  <span class="msg">{pct}% · {msg}</span>
</div>'''


def _session_completed(s):
    """Return True if session reached generation completion (includes download scenarios)."""
    _completed_ops = {"COMPLETE", "DOWNLOAD", "DOWNLOAD_EMAIL",
                      "DOWNLOAD_EMAIL_PODCAST", "DOWNLOAD_PODCAST",
                      # Traduzione e ottimizzazione AI come percorsi a sé:
                      # un job concluso in questi flussi è "completato" anche
                      # se non sfocia in una generazione TTS.
                      "TR_COMPLETE", "TRANSLATE_ADOPT", "DOWNLOAD_TRANSLATION",
                      "OPT_COMPLETE"}
    return bool(set(s["events"]) & _completed_ops)


def _session_in_progress(s, sid):
    """Return True if session has an active AI optimization or TTS generation.

    Lo stato runtime del job (`jobs[sid]["status"]`) e' la fonte autoritativa:
    se il job e' ancora in memoria in uno stato attivo (optimizing, optimized
    in attesa di auto-gen, generating, running, ecc.) la sessione e' in corso
    indipendentemente da cosa contiene il log. Questo evita il bug per cui
    un job auto-gen (OPT_COMPLETE -> generazione TTS) appariva "non in corso"
    in attesa che l'evento GENERATE venisse scritto, perche' OPT_COMPLETE
    chiudeva il ramo opt_live e GENERATE non era ancora presente nel log.

    Fallback (job non piu' in memoria, es. dopo restart server): si guarda al
    log eventi e si applica la regola conservativa "start senza terminator e
    senza cancel", ma siccome il job manca, si ritorna comunque False per
    evitare falsi positivi su sessioni storiche zombie.
    """
    job = _jobs().get(sid)
    if job:
        st = job.get("status", "")
        # Unione di _ACTIVE_JOB_STATUSES (Gemini audit, vedi 3838) e degli
        # stati intermedi del flusso ottimizzazione/auto-gen.
        active_states = set(_ACTIVE_JOB_STATUSES) | {"optimizing", "optimized",
                                                      "translating"}
        return st in active_states
    return False


def _last_n_days(n):
    today = datetime.now().date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(n)]


def _funnel_data(days):
    raw = metrics_store.read_range(days)
    out = {}
    for event in ("app_open", "web_visit_from_app", "payment_from_app"):
        ev = raw.get(event, {})
        a, i, u = int(ev.get("android", 0)), int(ev.get("ios", 0)), int(ev.get("unknown", 0))
        out[event] = {"android": a, "ios": i, "unknown": u, "total": a + i + u}
    web_total = out["web_visit_from_app"]["total"]
    pay_total = out["payment_from_app"]["total"]
    out["conversion_rate"] = (pay_total / web_total) if web_total else 0.0
    return out


# Soglia di avvii a voce standard nelle 24h oltre cui un client compare nella
# sezione "power user" del digest admin (0 = sezione disattivata).
POWER_USER_JOBS_PER_DAY = env_int("ABM_ADMIN_POWER_USER_JOBS_PER_DAY", 5)


def _power_users_data():
    """Righe per il blocco power user del digest: client con >= soglia avvii
    a voce standard nelle ultime 24h, dal business log del mese corrente (piu'
    il precedente a cavallo del mese) + quota caratteri del mese."""
    if POWER_USER_JOBS_PER_DAY <= 0:
        return None
    now = datetime.now()
    since = now - timedelta(hours=24)
    # Dall'inizio del mese di `since`: i contatori mensili (books_month,
    # starts_month) contano tutto il mese, non solo le ultime 24h.
    month_start = since.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        qt = free_tts_quota.month_table()
    except Exception:
        qt = {}
    rows = user_stats.power_users(activity_log.iter_rows(month_start), since,
                                  min_jobs=POWER_USER_JOBS_PER_DAY,
                                  quota_table=qt, top=10,
                                  month_ym=now.strftime("%Y-%m"))
    return {"rows": rows, "min_jobs": POWER_USER_JOBS_PER_DAY,
            "quota_limit_chars": free_tts_quota.limit_chars(), "window_hours": 24}


_LOG_EVENT_ICONS: dict[str, str] = {
    "ANALYZE": "🔍", "GENERATE": "⚙️", "COMPLETE": "✅",
    "DOWNLOAD": "📥", "DOWNLOAD_EMAIL": "📧📥",
    "DOWNLOAD_EMAIL_PODCAST": "🎙️📥", "DOWNLOAD_PODCAST": "🎙️📥",
    "EMAIL_REGISTERED": "📧", "EMAIL_SENT": "📨",
    "EMAIL_FAILED": "❌", "CANCEL": "🚫",
    "ADMIN_CANCEL": "⛔",
    "RESET_CHAPTERS": "🔄", "EXPORT_ABM": "📦",
    "OPTIMIZE": "✨", "OPT_COMPLETE": "✨✅", "OPT_CANCEL": "✨🚫",
    "TRANSLATE": "🌍", "TR_COMPLETE": "🌍✅", "TR_CANCEL": "🌍🚫",
    "TRANSLATE_ADOPT": "🌍📖", "DOWNLOAD_TRANSLATION": "🌍📥",
    "TR_EMAIL_SENT": "🌍📨",
}
_LOG_OP_COLORS = {
    "ANALYZE": ("#6b7280", "#f3f4f6"), "GENERATE": ("#2563eb", "#eff6ff"),
    "COMPLETE": ("#16a34a", "#f0fdf4"), "DOWNLOAD": ("#7c3aed", "#f5f3ff"),
    "DOWNLOAD_EMAIL": ("#7c3aed", "#f5f3ff"),
    "DOWNLOAD_EMAIL_PODCAST": ("#7c3aed", "#f5f3ff"),
    "DOWNLOAD_PODCAST": ("#7c3aed", "#f5f3ff"),
    "EMAIL_REGISTERED": ("#0891b2", "#ecfeff"),
    "EMAIL_SENT": ("#0d9488", "#f0fdfa"),
    "EMAIL_FAILED": ("#dc2626", "#fef2f2"),
    "CANCEL": ("#dc2626", "#fef2f2"),
    "ADMIN_CANCEL": ("#b91c1c", "#fee2e2"),
    "RESET_CHAPTERS": ("#f59e0b", "#fffbeb"),
    "EXPORT_ABM": ("#6366f1", "#eef2ff"),
    "OPTIMIZE": ("#d97706", "#fffbeb"), "OPT_COMPLETE": ("#16a34a", "#f0fdf4"),
    "OPT_CANCEL": ("#dc2626", "#fef2f2"),
    "TRANSLATE": ("#0ea5e9", "#e0f2fe"), "TR_COMPLETE": ("#0284c7", "#e0f2fe"),
    "TR_CANCEL": ("#dc2626", "#fef2f2"),
    "TRANSLATE_ADOPT": ("#0284c7", "#e0f2fe"),
    "DOWNLOAD_TRANSLATION": ("#0369a1", "#e0f2fe"),
    "TR_EMAIL_SENT": ("#0d9488", "#f0fdfa"),
}


_LOG_EAGER_DAYS = 2   # giorni piu recenti renderizzati subito in /admin/log-activity

_LOG_TR_OPS = frozenset({"TRANSLATE", "TR_COMPLETE", "TR_CANCEL",
                         "TRANSLATE_ADOPT", "DOWNLOAD_TRANSLATION",
                         "TR_EMAIL_SENT", "TR_EMAIL_FAILED"})


def _log_session_filters(sid, s, client_session_count):
    """Attributi di filtro di una sessione: i data-* della scheda e, per i
    giorni non ancora caricati, i conteggi per filtro dell'intestazione."""
    if _session_in_progress(s, sid):
        status = "in_progress"
    elif _session_completed(s):
        status = "completed"
    else:
        status = "cancelled"
    cid = s.get("client_id", "")
    return {
        "status": status,
        "email": "EMAIL_SENT" in s["events"],
        "recurring": bool(cid) and client_session_count.get(cid, 0) >= 2,
        "identified": bool(cid),
        "gemini": bool(s.get("premium_started")),
        "translation": bool(set(s["events"]) & _LOG_TR_OPS),
        "platform": s.get("platform", "") or "",
        "transferred": bool(s.get("transferred", False)),
    }


def _log_filter_names(f):
    """Filtri di filterCards() che mostrano una scheda con attributi `f`
    (stessa logica del JS, vedi filterCards)."""
    names = ["all", f["status"]]
    names += [k for k in ("identified", "recurring", "translation",
                          "gemini", "transferred") if f[k]]
    if f["platform"] in ("android", "ios"):
        names.append("mobile")
    return names


def _log_client_color_map(client_session_count):
    """Colore per client ricorrente, nell'ordine di prima apparizione nel mese
    (lo stesso per la pagina e per i giorni caricati dopo)."""
    colors = ["#38bdf8", "#a78bfa", "#f472b6", "#34d399", "#fbbf24",
              "#fb923c", "#22d3ee", "#c084fc", "#f87171", "#4ade80"]
    recurring = [cid for cid, n in client_session_count.items() if n >= 2]
    return {cid: colors[i % len(colors)] for i, cid in enumerate(recurring)}


def _log_card_html(sid, s, client_session_count, client_color_map, now):
    """Scheda HTML di una sessione di /admin/log-activity (pagina e
    caricamento del singolo giorno)."""
    job = None
    f = _log_session_filters(sid, s, client_session_count)
    card_status = f["status"]
    is_progress = card_status == "in_progress"
    cid = s.get("client_id", "")
    cid_count = client_session_count.get(cid, 0) if cid else 0

    first = s["first_dt"].strftime("%H:%M")
    last = s["last_dt"].strftime("%H:%M")

    is_paid = False
    if is_progress:
        job = _jobs().get(sid)
        # Job con pagamento (PayPal o voucher, indifferente): la card
        # in corso viene evidenziata in giallo acceso invece del rosso.
        _paym = (job or {}).get("payment") or {}
        try:
            is_paid = float(_paym.get("total_eur", 0) or 0) > 0
        except (TypeError, ValueError):
            is_paid = bool(_paym)
        pct_html = ""
        if job:
            st = job.get("status", "")
            if st == "optimizing":
                total_chars = job.get("opt_total_chars", 1)
                done_chars = job.get("opt_processed_chars", 0)
                cur_ch_chars = job.get("opt_current_chapter_chars", 0)
                streamed = min(job.get("opt_streamed_chars", 0), cur_ch_chars)
                worked = done_chars + streamed
                pct = min(99, int(worked / total_chars * 100))
                pct_html = f' <span class="card-pct" data-sid="{sid}">({pct}%)</span>'
            elif st == "generating":
                cur = job.get("progress_current", 0)
                tot = job.get("progress_total", 0)
                if tot > 0:
                    pct = int(cur / tot * 100)
                    pct_html = f' <span class="card-pct" data-sid="{sid}">({pct}%)</span>'
            elif st == "translating":
                cur = job.get("tr_progress_current", 0)
                tot = job.get("tr_progress_total", 0)
                if tot > 0:
                    pct = int(cur / tot * 100)
                    pct_html = f' <span class="card-pct" data-sid="{sid}">({pct}%)</span>'

        delta = now - s["first_dt"]
        total_sec = int(delta.total_seconds())
        elapsed = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}:{total_sec % 60:02d}"
        start_iso = s["first_dt"].strftime("%Y-%m-%dT%H:%M:%S")
        elapsed_html = f'<span class="live-timer" data-start="{start_iso}">{elapsed}</span>{pct_html} ⏱️'
        last = " - "
    else:
        delta = s["last_dt"] - s["first_dt"]
        total_sec = int(delta.total_seconds())
        elapsed = f"{total_sec // 3600:02d}:{(total_sec % 3600) // 60:02d}"
        elapsed_html = elapsed

    title = s["filename"]
    for ext in (".epub", ".txt", ".pdf"):
        if title.lower().endswith(ext):
            title = title[:-len(ext)]
    display_title = html_mod.escape(title[:80] + ("..." if len(title) > 80 else ""))

    op = s["last_op"]
    fg, bg = _LOG_OP_COLORS.get(op, ("#6b7280", "#f3f4f6"))
    timeline = "  →  ".join(_LOG_EVENT_ICONS.get(e, e) or "" for e in s["events"])

    cip = s.get("client_ip", "")
    cid_short = cid[:8] if cid else " - "
    cid_color = client_color_map.get(cid, "var(--text-dim)")
    cid_badge = f' <span class="cid-count" style="color:{cid_color}">({cid_count})</span>' if cid_count >= 2 else ""
    cid_style = f'color:{cid_color};font-weight:600' if cid in client_color_map else 'color:var(--text-dim)'

    voice_raw = s.get("voice", "")
    voice_short = ""
    if voice_raw:
        parts_v = voice_raw.split("-")
        if len(parts_v) >= 3:
            # Escape OBBLIGATORIO: voice_raw arriva dal parametro
            # `voice` della richiesta utente via Activity Log; senza
            # escape un id voce forgiato (es. "x-y-<img onerror=...>")
            # diventa stored XSS nel browser admin.
            voice_short = html_mod.escape(
                parts_v[-1].replace("Neural", "").replace("Multilingual", ""))
            voice_lang = html_mod.escape("-".join(parts_v[:2]))
            voice_short = f'{voice_short} <span class="voice-lang">{voice_lang}</span>'
        else:
            voice_short = html_mod.escape(voice_raw)

    # Sessioni di traduzione: il campo `voice` del log porta
    # "src>dst [+AI]" (vedi _log_activity TRANSLATE/TR_COMPLETE). Per
    # queste card sostituiamo la riga voce TTS con lingue + evidenza
    # della scelta ottimizzazione AI.
    is_translation = f["translation"]
    tr_lang_html = " - "
    tr_ai_html = ""
    if is_translation:
        _vr = voice_raw or ""
        _ai_chosen = "+AI" in _vr
        _langs = _vr.replace("+AI", "").strip()
        if ">" in _langs:
            _a, _b = _langs.split(">", 1)
            tr_lang_html = (f'{html_mod.escape(_a.strip().upper())} → '
                            f'{html_mod.escape(_b.strip().upper())}')
        if not _vr:
            # Log storici (prima del descrittore lingue/AI): scelta ignota.
            tr_ai_html = '<span style="color:var(--text-dim)">✨ AI ?</span>'
        elif _ai_chosen:
            tr_ai_html = '<span style="color:#16a34a">✨ AI ✓</span>'
        else:
            tr_ai_html = '<span style="color:var(--text-dim)">✨ AI ✗</span>'

    if is_translation:
        tr_meta_html = (
            f'<div class="meta-row"><span class="meta-label">🌍</span>'
            f'<span class="card-voice">{tr_lang_html}</span></div>\n'
            f'<div class="meta-row"><span class="meta-label">✨</span>'
            f'<span class="card-voice">{tr_ai_html}</span></div>'
        )
    else:
        tr_meta_html = (
            f'<div class="meta-row"><span class="meta-label">🎙️</span>'
            f'<span class="card-voice" title="{html_mod.escape(voice_raw)}">'
            f'{voice_short or " - "}</span></div>'
        )

    blang = html_mod.escape(s.get("browser_lang", "") or "")
    blang_display = f'<span class="card-blang">{blang}</span>' if blang else " - "

    if is_progress and is_paid:
        card_cls = "card card-in-progress card-paid"
    elif is_progress:
        card_cls = "card card-in-progress"
    else:
        card_cls = "card"
    data_attrs = (
        f'data-status="{card_status}" '
        f'data-email="{int(f["email"])}" '
        f'data-recurring="{int(f["recurring"])}" '
        f'data-identified="{int(f["identified"])}" '
        f'data-gemini="{int(f["gemini"])}" '
        f'data-translation="{int(f["translation"])}" '
        f'data-platform="{html_mod.escape(f["platform"])}" '
        f'data-transferred="{int(f["transferred"])}"'
    )
    m4b_subbar = _m4b_subbar_html(job) if is_progress and job and job.get("m4b_progress_total", 0) > 0 else ""

    kill_btn = (
        f'<button class="kill-btn" data-sid="{sid}" '
        f'data-title="{html_mod.escape(s["filename"])}" '
        f'title="Interrompi job (admin)">⛔</button>'
    ) if is_progress else ""
    return f"""<div class="{card_cls}" {data_attrs}>
<div class="card-top">
<span class="card-title" title="{html_mod.escape(s['filename'])}">{display_title}</span>
<span class="badge" style="color:{fg};background:{bg}">{op}</span>{kill_btn}
</div>
<div class="card-timeline">{timeline}</div>
<div class="card-meta">
<div class="meta-row"><span class="meta-label">⌚</span><span>{first}  →  {last} ({elapsed_html})</span></div>
<div class="meta-row"><span class="meta-label">🆔</span><code class="sid">{sid}</code></div>
<div class="meta-row"><span class="meta-label">👤</span><code style="{cid_style}">{cid_short}</code>{cid_badge}<span class="card-ip">{cip or ""}</span></div>
{tr_meta_html}
<div class="meta-row"><span class="meta-label">🌐</span>{blang_display}<button class="qr-btn" data-sid="{sid}" title="Copia il job sull'app (QR) a scopo di indagine — non altera il flusso dell'utente"><svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M3 3h8v8H3V3zm2 2v4h4V5H5zm8-2h8v8h-8V3zm2 2v4h4V5h-4zM3 13h8v8H3v-8zm2 2v4h4v-4H5zm8-2h2v2h-2v-2zm4 0h2v2h-2v-2zm2 2h2v2h-2v-2zm-6 2h2v2h-2v-2zm2 2h2v2h-2v-2zm2 0h2v2h-2v-2zm2 0h2v2h-2v-2z"/></svg>QR</button></div>
</div>
{m4b_subbar}
</div>
"""


@bp.route("/admin/log-activity/day")
@admin_required(as_json=False)
def admin_logs_day():
    """Schede di un giorno di /admin/log-activity (frammento HTML), chieste
    dalla pagina quando si apre un giorno non renderizzato in apertura."""
    ym = request.args.get("ym", "")
    day = request.args.get("day", "")
    if (not re.fullmatch(r"\d{4}-\d{2}", ym)
            or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day)
            or not day.startswith(ym + "-")):
        return "Bad request", 400
    try:
        sessions, client_session_count = _log_sessions_cached(ym)
    except Exception as e:
        return f"Errore lettura log: {e}", 500
    color_map = _log_client_color_map(client_session_count)
    now = datetime.now()
    # Stesso ordine della pagina: sessioni piu' recenti per prime.
    parts = [_log_card_html(sid, s, client_session_count, color_map, now)
             for sid, s in reversed(list(sessions.items()))
             if s["first_dt"].strftime("%Y-%m-%d") == day]
    return "".join(parts), 200, {"Content-Type": "text/html; charset=utf-8",
                                 "Cache-Control": "no-store"}


@bp.route("/admin/log-activity")
def admin_logs():
    if not _admin_token(): return "Logs UI disabled.", 404
    token = _admin_auth_from_request()
    if not _admin_auth_ok(token): return _render_admin_gate("Log Activity", "/admin/log-activity"), 200, {"Content-Type": "text/html; charset=utf-8"}
    _log_i18n = {
        "it": {
            "sessions": "Sessioni", "gen_completed": "Gen. completata",
            "in_progress": "In corso", "cancelled": "Cancellati",
            "email_sent": "Email inviate", "unique_clients": "Client unici",
            "recurring": "Ricorrenti", "months": "Mesi",
            "collapse": "Aggrega", "expand": "Mostra tutti",
            "no_activity": "Nessuna attività registrata per",
            "gemini_started": "PREMIUM", "translations": "Traduzioni",
            "eta_label": "Stima completamento gen.",
        },
        "en": {
            "sessions": "Sessions", "gen_completed": "Gen. completed",
            "in_progress": "In progress", "cancelled": "Cancelled",
            "email_sent": "Emails sent", "unique_clients": "Unique clients",
            "recurring": "Returning", "months": "Months",
            "collapse": "Collapse", "expand": "Show all",
            "no_activity": "No activity recorded for",
            "gemini_started": "PREMIUM", "translations": "Translations",
            "eta_label": "ETA",
        },
        "fr": {
            "sessions": "Sessions", "gen_completed": "Gén. terminée",
            "in_progress": "En cours", "cancelled": "Annulées",
            "email_sent": "Emails envoyés", "unique_clients": "Clients uniques",
            "recurring": "Récurrents", "months": "Mois",
            "collapse": "Regrouper", "expand": "Tout afficher",
            "no_activity": "Aucune activité enregistrée pour",
            "gemini_started": "PREMIUM", "translations": "Traductions",
            "eta_label": "ETA",
        },
        "de": {
            "sessions": "Sitzungen", "gen_completed": "Gen. abgeschlossen",
            "in_progress": "Laufend", "cancelled": "Abgebrochen",
            "email_sent": "E-Mails gesendet", "unique_clients": "Einzelne Clients",
            "recurring": "Wiederkehrend", "months": "Monate",
            "collapse": "Zusammenklappen", "expand": "Alle anzeigen",
            "no_activity": "Keine Aktivitäten aufgezeichnet für",
            "gemini_started": "PREMIUM", "translations": "Übersetzungen",
            "eta_label": "ETA",
        },
        "es": {
            "sessions": "Sesiones", "gen_completed": "Gen. completada",
            "in_progress": "En curso", "cancelled": "Canceladas",
            "email_sent": "Emails enviados", "unique_clients": "Clientes únicos",
            "recurring": "Recurrentes", "months": "Meses",
            "collapse": "Agrupar", "expand": "Mostrar todos",
            "no_activity": "No hay actividad registrada para",
            "gemini_started": "PREMIUM", "translations": "Traducciones",
            "eta_label": "ETA",
        },
        "zh": {
            "sessions": "会话", "gen_completed": "生成完成",
            "in_progress": "进行中", "cancelled": "已取消",
            "email_sent": "邮件已发送", "unique_clients": "唯一客户",
            "recurring": "常客", "months": "月份",
            "collapse": "收起", "expand": "全部显示",
            "no_activity": "没有活动记录",
            "gemini_started": "PREMIUM", "translations": "翻译",
            "eta_label": "预计剩余",
        },
        "hi": {
            "sessions": "सत्र", "gen_completed": "जनरेशन पूर्ण",
            "in_progress": "प्रगति पर", "cancelled": "रद्द",
            "email_sent": "भेजे गए ईमेल", "unique_clients": "अनोखे क्लाइंट",
            "recurring": "नियमित", "months": "महीने",
            "collapse": "संक्षिप्त करें", "expand": "सभी दिखाएं",
            "no_activity": "कोई गतिविधि दर्ज नहीं",
            "gemini_started": "PREMIUM", "translations": "अनुवाद",
            "eta_label": "शेष",
        },
    }
    _blang = _get_browser_lang()
    t = _log_i18n.get(_blang, _log_i18n["en"])

    ym = None
    for key in request.args:
        if re.match(r'^\d{4}-\d{2}$', key):
            ym = key
            break
    if not ym:
        ym = datetime.now().strftime("%Y-%m")

    try:
        sessions, client_session_count = _log_sessions_cached(ym)
    except Exception as e:
        return f"Errore lettura log: {e}", 500

    _client_color_map = _log_client_color_map(client_session_count)

    total_sessions = len(sessions)
    gen_completed = sum(1 for s in sessions.values() if _session_completed(s))
    # Giorni con sessioni in corso: sempre renderizzati (timer, ETA e polling
    # dell'avanzamento lavorano sulle schede presenti nel DOM).
    live = [s for sid, s in sessions.items() if _session_in_progress(s, sid)]
    live_days = {s["first_dt"].strftime("%Y-%m-%d") for s in live}
    gen_in_progress = len(live)
    gen_cancelled = total_sessions - gen_completed - gen_in_progress
    # Sessioni che hanno realmente avviato il libro con voci PREMIUM (Gemini,
    # Speechify/Simba o VoxCPM: stessa tasca di pagamento/rimborso) — esclude
    # le anteprime. Il flag e' calcolato in _parse_log_sessions su GENERATE o
    # su OPTIMIZE con voce (wizard combinato, ancora in ottimizzazione AI).
    gemini_started = sum(1 for s in sessions.values() if s.get("premium_started"))
    # Sessioni di traduzione: qualunque evento del flusso traduzione.
    tr_count = sum(1 for s in sessions.values()
                   if set(s["events"]) & _LOG_TR_OPS)
    # Sessioni originatesi da piattaforma mobile (android/ios).
    mobile_count = sum(
        1 for s in sessions.values()
        if s.get("platform", "") in ("android", "ios")
    )
    # Sessioni web trasferite alla mobile app (evento TRANSFER).
    transferred_count = sum(1 for s in sessions.values() if s.get("transferred", False))
    unique_clients = len(set(s.get("client_id", "") for s in sessions.values() if s.get("client_id")))
    returning_clients = sum(1 for c in client_session_count.values() if c >= 2)

    days = defaultdict(list)
    for sid, s in reversed(list(sessions.items())):
        day_key = s["first_dt"].strftime("%Y-%m-%d")
        days[day_key].append((sid, s))

    # Pezzi in lista e un solo join finale: con += su una stringa da decine di
    # MB (agosto 2026: 17k sessioni) ogni aggiunta ricopiava tutto, costo
    # quadratico che su Windows bloccava la pagina per minuti.
    cards_parts = []
    now = datetime.now()
    day_keys = sorted(days.keys(), reverse=True)
    # Solo gli ultimi _LOG_EAGER_DAYS giorni (piu' quelli con sessioni in
    # corso) arrivano con le schede: gli altri le chiedono a
    # /admin/log-activity/day quando vengono aperti. Un mese intero sono
    # decine di MB di HTML che quasi mai si guardano.
    eager = set(day_keys[:_LOG_EAGER_DAYS]) | live_days
    for day_key in day_keys:
        day_sessions = days[day_key]
        day_count = len(day_sessions)
        day_completed = sum(1 for sid, s in day_sessions if _session_completed(s))
        try:
            day_dt = datetime.strptime(day_key, "%Y-%m-%d")
            day_label = day_dt.strftime("%d/%m/%Y")
        except ValueError:
            day_label = day_key

        if day_key in eager:
            lazy_attrs = ""
        else:
            # Conteggi per filtro: filterCards() nasconde e numera il giorno
            # senza avere le schede.
            counts = Counter()
            for sid, s in day_sessions:
                counts.update(_log_filter_names(
                    _log_session_filters(sid, s, client_session_count)))
            lazy_attrs = (' data-lazy="1" data-counts="'
                          + html_mod.escape(json.dumps(counts, sort_keys=True))
                          + '"')
        cards_parts.append(f"""<div class="day-group collapsed" data-day="{day_key}"{lazy_attrs}>
<div class="day-header" onclick="toggleDay(this.parentElement)">
<span class="day-label">{day_label}</span>
<span class="day-count">{day_count}<span class="day-sep">/</span><span class="day-completed">{day_completed}</span></span>
<span class="day-chevron">›</span>
</div>
<div class="day-cards">
""")
        if day_key in eager:
            for sid, s in day_sessions:
                cards_parts.append(_log_card_html(
                    sid, s, client_session_count, _client_color_map, now))
        cards_parts.append("</div></div>\n")
    cards_html = "".join(cards_parts)

    # Il vecchio istogramma orario per lingua e' stato sostituito dal pannello
    # di carico (/api/admin/load_stats): niente piu' aggregazione qui.

    available_months = activity_log.months()

    # Niente token in query string: l'auth admin viaggia via cookie HttpOnly
    # abm_admin_session (inviato automaticamente sulle navigazioni <a>). Un
    # `?token=` in chiaro finirebbe in access log nginx / history / Referer
    # e oltretutto il server lo ignora gia' (vedi _admin_auth_from_request).
    months_nav = ""
    for m in available_months:
        active_cls = ' class="active"' if m == ym else ""
        months_nav += f'<a href="/admin/log-activity?{m}"{active_cls}>{m}</a> '

    # Barra mesi della modale "Statistiche utente": l'analisi e' per definizione
    # mensile (legge activity_YYYY-MM.log), quindi qui si sceglie il mese e non
    # una finestra temporale come nel pannello di carico.
    us_months_nav = ""
    for m in available_months:
        _cls = "lsw-btn usw-btn active" if m == ym else "lsw-btn usw-btn"
        us_months_nav += (f'<button class="{_cls}" data-usym="{m}" '
                          f"onclick=\"loadUserStats('{m}',this)\">{m}</button>")

    _funnel = _funnel_data(_last_n_days(30))
    _f_open = _funnel["app_open"]["total"]
    _f_open_a = _funnel["app_open"]["android"]
    _f_open_i = _funnel["app_open"]["ios"]
    _f_web = _funnel["web_visit_from_app"]["total"]
    _f_web_a = _funnel["web_visit_from_app"]["android"]
    _f_web_i = _funnel["web_visit_from_app"]["ios"]
    _f_pay = _funnel["payment_from_app"]["total"]
    _f_pay_a = _funnel["payment_from_app"]["android"]
    _f_pay_i = _funnel["payment_from_app"]["ios"]
    _f_conv = f"{_funnel['conversion_rate'] * 100:.1f}%"

    html = _render_page("admin_log_activity", {"__P0__": (FAVICON_B64), "__P1__": (ym), "__P2__": ("<span class='label'>" + t["months"] + ":</span>" + months_nav if months_nav else ""), "__P3__": (t["collapse"]), "__P4__": (total_sessions), "__P5__": (t["sessions"]), "__P6__": (gen_completed), "__P7__": (t["gen_completed"]), "__P8__": (gen_in_progress), "__P9__": (t["in_progress"]), "__P10__": (gen_cancelled), "__P11__": (t["cancelled"]), "__P12__": (unique_clients), "__P13__": (t["unique_clients"]), "__P14__": (returning_clients), "__P15__": (t["recurring"]), "__P16__": (tr_count), "__P17__": (t["translations"]), "__P18__": (gemini_started), "__P19__": (t["gemini_started"]), "__P20__": (mobile_count), "__P21__": (transferred_count), "__P22__": (_f_open), "__P23__": (_f_open_a), "__P24__": (_f_open_i), "__P25__": (_f_web), "__P26__": (_f_web_a), "__P27__": (_f_web_i), "__P28__": (_f_pay), "__P29__": (_f_pay_a), "__P30__": (_f_pay_i), "__P31__": (_f_conv), "__P32__": (cards_html if cards_html else "<div class='empty'><div class='icon'>📮</div><p>" + t["no_activity"] + " <strong>" + ym + "</strong></p></div>"), "__P33__": (us_months_nav), "__P34__": (t["expand"]), "__P35__": (t["eta_label"])})
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


def _csv_safe(val):
    """Sanitizza un valore per esportazioni CSV/XLSX contro CSV-injection.

    Excel/LibreOffice interpretano celle che iniziano con =, +, -, @, TAB, CR
    come formule. Prefissiamo con apostrofo ('), che disabilita l'interpretazione
    e non viene mostrato nella cella.
    """
    if val is None:
        return ""
    s = str(val)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


@bp.route("/admin/log-activity/export")
def admin_logs_export():
    """Export activity log as Excel (.xlsx) file."""
    if not _admin_token(): return "Export disabled.", 404
    token = _admin_auth_from_request()
    if not _admin_auth_ok(token): return "Unauthorized", 401
    import io, csv

    ym = None
    for key in request.args:
        if re.match(r'^\d{4}-\d{2}$', key):
            ym = key
            break
    if not ym:
        ym = datetime.now().strftime("%Y-%m")

    try:
        sessions, client_session_count = _log_sessions_cached(ym)
    except Exception as e:
        return f"Errore lettura log: {e}", 500

    output = io.StringIO()
    writer = csv.writer(output, delimiter="#")
    writer.writerow([
        "Session ID", "Date Start", "Date End", "Duration (min)",
        "Filename", "Last Status", "Events", "Client ID", "Client IP",
        "Voice", "Browser Lang", "Completed", "In Progress", "Recurring Client"
    ])
    for sid, s in sessions.items():
        delta = s["last_dt"] - s["first_dt"]
        duration_min = round(delta.total_seconds() / 60, 1)
        completed = "Yes" if _session_completed(s) else "No"
        in_progress = "Yes" if _session_in_progress(s, sid) else "No"
        cid = s.get("client_id", "")
        recurring = "Yes" if client_session_count.get(cid, 0) >= 2 else "No"
        writer.writerow([
            _csv_safe(sid), s["first_dt"].strftime("%Y-%m-%d %H:%M:%S"),
            s["last_dt"].strftime("%Y-%m-%d %H:%M:%S"), duration_min,
            _csv_safe(s["filename"]), _csv_safe(s["last_op"]),
            _csv_safe("  →  ".join(s["events"])),
            _csv_safe(cid), _csv_safe(s.get("client_ip", "")),
            _csv_safe(s.get("voice", "")),
            _csv_safe(s.get("browser_lang", "")), completed, in_progress, recurring,
        ])

    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment
        from openpyxl.utils import get_column_letter

        wb = Workbook()
        ws = wb.active
        ws.title = f"Log {ym}"

        total_s = len(sessions)
        gen_c = sum(1 for s_ in sessions.values() if _session_completed(s_))
        gen_p = sum(1 for sid_, s_ in sessions.items() if _session_in_progress(s_, sid_))
        gen_x = total_s - gen_c - gen_p
        em_s = sum(1 for s_ in sessions.values() if "EMAIL_SENT" in s_["events"])
        uniq = len(set(s_.get("client_id", "") for s_ in sessions.values() if s_.get("client_id")))
        ret = sum(1 for c in client_session_count.values() if c >= 2)

        ws.merge_cells("A1:B1")
        ws["A1"] = f"Audiobook Maker  -  Activity Log {ym}"
        ws["A1"].font = Font(name="Arial", bold=True, color="38bdf8", size=14)
        summary = [("Sessioni", total_s), ("Gen. completata", gen_c), ("In corso", gen_p),
                   ("Cancellati", gen_x), ("Email inviate", em_s), ("Client unici", uniq),
                   ("Ricorrenti", ret)]
        for i, (lbl, val) in enumerate(summary):
            ws.cell(row=2, column=1 + i * 2, value=lbl).font = Font(name="Arial", color="94a3b8", size=10)
            ws.cell(row=2, column=2 + i * 2, value=val).font = Font(name="Arial", bold=True, color="e2e8f0", size=12)

        headers = ["Session ID", "Data inizio", "Data fine", "Durata (min)", "Contenuto",
                   "Ultimo stato", "Timeline eventi", "Client ID", "IP", "Voce",
                   "Lingua browser", "Completato", "In corso", "Client ricorrente"]
        hdr_fill = PatternFill("solid", fgColor="334155")
        hdr_font = Font(name="Arial", bold=True, color="e2e8f0", size=10)
        for col_idx, h in enumerate(headers, 1):
            c = ws.cell(row=4, column=col_idx, value=h)
            c.font = hdr_font; c.fill = hdr_fill; c.alignment = Alignment(horizontal="center")

        data_font = Font(name="Arial", size=10, color="e2e8f0")
        for row_idx, (sid, s) in enumerate(reversed(list(sessions.items())), 5):
            delta = s["last_dt"] - s["first_dt"]
            row_data = [_csv_safe(sid), s["first_dt"].strftime("%Y-%m-%d %H:%M:%S"),
                        s["last_dt"].strftime("%Y-%m-%d %H:%M:%S"),
                        round(delta.total_seconds() / 60, 1),
                        _csv_safe(s["filename"]), _csv_safe(s["last_op"]),
                        _csv_safe("  →  ".join(s["events"])),
                        _csv_safe(s.get("client_id", "")), _csv_safe(s.get("client_ip", "")),
                        _csv_safe(s.get("voice", "")), _csv_safe(s.get("browser_lang", "")),
                        "✅" if _session_completed(s) else "❌",
                        "✅" if _session_in_progress(s, sid) else "",
                        "✅" if client_session_count.get(s.get("client_id", ""), 0) >= 2 else ""]
            for col_idx, val in enumerate(row_data, 1):
                c = ws.cell(row=row_idx, column=col_idx, value=val)
                c.font = data_font
                if row_idx % 2 == 0:
                    c.fill = PatternFill("solid", fgColor="1e293b")

        col_widths = [12, 20, 20, 12, 45, 18, 50, 14, 16, 25, 10, 12, 10, 14]
        for i, w in enumerate(col_widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w
        ws.auto_filter.ref = f"A4:N{4 + len(sessions)}"

        xlsx_io = io.BytesIO()
        wb.save(xlsx_io)
        xlsx_io.seek(0)
        return Response(xlsx_io.getvalue(),
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="activity_log_{ym}.xlsx"'})
    except ImportError:
        csv_bytes = output.getvalue().encode("utf-8-sig")
        return Response(csv_bytes, mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="activity_log_{ym}.csv"'})


@bp.route("/api/admin/funnel")
@admin_required
def api_admin_funnel():
    days = max(1, min(365, int(request.args.get("days", 30))))
    return jsonify(_funnel_data(_last_n_days(days)))
