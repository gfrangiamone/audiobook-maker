"""routes_admin_jobs — strumenti admin sui job (E3, seam admin, parte 4, 2026-10-10).

Blueprint `admin_jobs`: `/api/admin/suspend` (sospensione del servizio),
`/admin/api/job/<id>/copy-qr` (copia amministrativa verso l'app),
`/admin/job/<id>/forensic.zip`, `/api/admin/load_stats`,
`/api/admin/user_stats` (con cache per mese), `/api/admin/jobs_progress`,
`/api/paypal_debug_order/<id>`, `/api/active_jobs`; con gli helper della
copia amministrativa. Spostato pari pari da `audiobook_app`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app): guardia, token, auth, gate,
`_log_activity`, `client_ip`, `_qr_data_uri`, `UPLOAD_DIR`, `jobs`,
`_client_emails` (ribindato dai `_load_*`), `MAX_CONCURRENT_GLOBAL`,
`_job_progress`, `_effective_retention_for_token_info`,
`_reconstruct_admin_download_record`, `PAYPAL_API_BASE`,
`_paypal_available`, `_paypal_get_access_token`; per riferimento il lock
dei job, il lock della sospensione e la regex del mese. Non importa
`audiobook_app` ne' `generation_engine`.
"""
import functools
import os
import re
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

import activity_log
import assembly_queue
import load_metrics
import payment
import pending_jobs
import token_store as _tkstore
import user_stats
from env_utils import env_str

bp = Blueprint("admin_jobs", __name__)

_cfg = {}
_jobs_lock = None
_suspend_lock = None
_YM_RE = None


def configure(*, admin_required, admin_token, admin_auth_ok, admin_auth_from_request, render_admin_gate,
              log_activity, client_ip, qr_data_uri, upload_dir, jobs, jobs_lock, suspend_lock, client_emails,
              max_concurrent_global, job_progress, effective_retention_for_token_info,
              reconstruct_admin_download_record, paypal_api_base, paypal_available, paypal_get_access_token,
              ym_re):
    """Funzioni (risolte a ogni chiamata) e oggetti condivisi dalla app."""
    _cfg.update(admin_required=admin_required, admin_token=admin_token, admin_auth_ok=admin_auth_ok,
                admin_auth_from_request=admin_auth_from_request, render_admin_gate=render_admin_gate,
                log_activity=log_activity, client_ip=client_ip, qr_data_uri=qr_data_uri, upload_dir=upload_dir,
                jobs=jobs, client_emails=client_emails, max_concurrent_global=max_concurrent_global,
                job_progress=job_progress,
                effective_retention_for_token_info=effective_retention_for_token_info,
                reconstruct_admin_download_record=reconstruct_admin_download_record,
                paypal_api_base=paypal_api_base, paypal_available=paypal_available,
                paypal_get_access_token=paypal_get_access_token)
    globals()["_jobs_lock"] = jobs_lock
    globals()["_suspend_lock"] = suspend_lock
    globals()["_YM_RE"] = ym_re


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _admin_token():
    return _cfg["admin_token"]()


def _jobs():
    return _cfg["jobs"]()


def _client_emails():
    return _cfg["client_emails"]()


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


def _qr_data_uri(text):
    return _cfg["qr_data_uri"](text)


def _job_progress(*a, **k):
    return _cfg["job_progress"](*a, **k)


def _effective_retention_for_token_info(info):
    return _cfg["effective_retention_for_token_info"](info)


def _reconstruct_admin_download_record(*a, **k):
    return _cfg["reconstruct_admin_download_record"](*a, **k)


def _paypal_available():
    return _cfg["paypal_available"]()


def _paypal_get_access_token():
    return _cfg["paypal_get_access_token"]()


def _upload_dir():
    return _cfg["upload_dir"]()


def _max_concurrent_global():
    return _cfg["max_concurrent_global"]()


def _paypal_api_base():
    return _cfg["paypal_api_base"]()


def admin_required(fn=None, *, as_json=True):
    """La guardia admin della app, applicata a ogni richiesta (le route del
    blueprint si decorano all'import, prima di `configure`)."""
    def deco(f):
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            return _cfg["admin_required"](as_json=as_json)(f)(*args, **kwargs)
        return wrapper
    return deco(fn) if fn is not None else deco


# --- suspend ------------------------------------------------------------
@bp.route("/api/admin/suspend", methods=["GET", "POST"])
def admin_api_suspend():
    """GET: restituisce stato sospensione (pubblico). POST: imposta sospensione (richiede admin token)."""
    global _suspend_new_jobs
    if request.method == "POST":
        token = _admin_auth_from_request()
        if not _admin_auth_ok(token):
            return jsonify({"error": "Unauthorized"}), 401
        data = request.json or {}
        with _suspend_lock:
            _suspend_new_jobs = bool(data.get("suspend", False))
        return jsonify({"suspended": _suspend_new_jobs})
    with _suspend_lock:
        suspended = _suspend_new_jobs
    return jsonify({"suspended": suspended})


# --- copyqr ------------------------------------------------------------
@bp.route("/admin/api/job/<path:job_id>/copy-qr", methods=["GET"])
@admin_required
def admin_api_job_copy_qr(job_id):
    """Restituisce un QR (data-URI PNG) + deep link per copiare il job sull'app
    'Audiobook Maker & Player' a scopo di indagine admin. Il claim del token
    NON altera il job dell'utente originale (vedi api_transfer_claim, ramo
    admin_copy)."""
    if not job_id or "/" in job_id or "\\" in job_id or ".." in job_id:
        return jsonify({"error": "invalid job_id"}), 400
    # Il QR ha senso solo se la copia è effettivamente consegnabile all'app: job
    # in RAM (in corso/done), token esistente, o output ancora presente hot/cold.
    # Per job definitivamente spariti non proponiamo un QR che darebbe 410.
    base = env_str("ABM_BASE_URL", "").rstrip("/")   # pattern env inline vietato nei moduli nuovi
    if not base:
        try:
            base = request.url_root.rstrip("/")
        except Exception:
            base = ""
    # Link /dl utente + destinatario della notifica: servono anche quando il QR
    # non è proponibile (job non copiabile), perché sono l'unico modo di
    # rimediare a mano quando la mail di completamento non arriva a destinazione.
    extra = {"notify_email": _admin_notify_email_for_job(job_id)}
    dl = _admin_user_dl_link(job_id)
    if dl:
        extra["dl_url"] = f"{base}/dl/{dl['token']}"
        extra["dl_expires_at"] = dl["expires_at"]
        extra["dl_downloaded"] = bool(dl["downloaded_at"])
    if not _admin_copy_recoverable(job_id):
        return jsonify({"available": False, "job_id": job_id, **extra}), 200
    tok = _tkstore.ensure_admin_copy_token(job_id)
    url = f"{base}/t/{tok}"
    qr = _qr_data_uri(url)
    return jsonify({"available": True, "url": url, "qr": qr, "job_id": job_id, **extra})


@bp.route("/admin/job/<path:job_id>/forensic.zip", methods=["GET"])
def admin_forensic_zip(job_id):
    """Scarica ZIP della work_dir di un job Gemini fallito per analisi post-mortem.
    Richiede admin auth via cookie HttpOnly (set da /admin/login) o header
    X-Admin-Token. Disponibile finché la dir è protetta dal marker forense
    (default 7 giorni dal refund; ABM_GEMINI_FORENSIC_RETENTION_DAYS).
    """
    if not _admin_token():
        return ("Admin disabled.", 404, {"Content-Type": "text/plain; charset=utf-8"})
    token = _admin_auth_from_request()
    if not _admin_auth_ok(token):
        return ("Unauthorized. Effettua login su /admin/audit-premium e ritorna a questo link.",
                401, {"Content-Type": "text/plain; charset=utf-8"})
    if "/" in job_id or "\\" in job_id or ".." in job_id:
        return ("Invalid job_id", 400, {"Content-Type": "text/plain; charset=utf-8"})
    work_dir = _upload_dir() / job_id
    if not work_dir.exists() or not work_dir.is_dir():
        return ("Work dir not found (cleanup completed or never existed).",
                404, {"Content-Type": "text/plain; charset=utf-8"})
    import io
    import zipfile
    buf = io.BytesIO()
    try:
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for root, _dirs, files in os.walk(str(work_dir)):
                for fn in files:
                    fp = Path(root) / fn
                    try:
                        arc = fp.relative_to(work_dir.parent)
                        zf.write(str(fp), str(arc))
                    except (OSError, ValueError):
                        continue
    except OSError as e:
        return (f"Zip build failed: {e}", 500, {"Content-Type": "text/plain; charset=utf-8"})
    payload = buf.getvalue()
    safe = re.sub(r'[^a-zA-Z0-9_-]', '_', job_id).strip("_") or "job"
    return Response(
        payload,
        mimetype="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="forensic_{safe}.zip"',
            "Content-Length": str(len(payload)),
            "Cache-Control": "no-store",
        },
    )


# --- stats ------------------------------------------------------------
@bp.route("/api/admin/load_stats")
@admin_required
def api_admin_load_stats():
    """Statistiche di CARICO aggregate sulla finestra richiesta.

    Alimenta il pannello Stats di /admin/log-activity. Richiede admin token:
    espone la capacita' residua e lo stato di salute dell'istanza, che non
    devono essere leggibili dall'esterno.
    """
    window = (request.args.get("window") or "24h").strip()
    try:
        slots = assembly_queue.MAX_CONCURRENT_ASSEMBLY
    except Exception:
        slots = 0
    data = load_metrics.query(window,
                              global_cap=_max_concurrent_global(),
                              assembly_slots=slots)
    data["meta"]["global_cap"] = _max_concurrent_global()
    data["meta"]["assembly_slots"] = slots
    return jsonify(data)


# Cache dell'analisi utenza: la scansione di un mese pieno costa ~1s e il
# pannello viene aperto e richiuso di continuo. Chiave = (ym, impronta del
# mese in activity_log, impronta dei pagamenti): un log che cresce invalida da solo.
_USER_STATS_CACHE = {}
_USER_STATS_CACHE_MAX = 6


@bp.route("/api/admin/user_stats")
@admin_required
def api_admin_user_stats():
    """Analisi dell'utenza (concentrazione free/premium) del mese richiesto.

    Alimenta la modale "Statistiche utente" di /admin/log-activity.
    Sorgente: il business log mensile, non la telemetria di carico.
    Coorte PREMIUM = voce a pagamento OPPURE pagamento incassato sul job.
    La concentrazione in valore incrocia gli incassi di `_payments.json`
    (il log non riporta gli importi) via job_id; le email dei clienti
    restano nel record e non escono mai da qui.
    """
    ym = (request.args.get("ym") or "").strip()
    if not _YM_RE.match(ym):
        return jsonify({"error": "Invalid month (expected YYYY-MM)"}), 400
    log_name = f"activity_{ym}.log"
    fp = activity_log.fingerprint(ym)
    if fp is None:
        data = user_stats.empty_result(log_name)
        data["ym"] = ym
        data["log_missing"] = True
        return jsonify(data)

    # Gli incassi arrivano dalla memoria di `payment`, che e' l'unica copia
    # sempre allineata (il file su disco e' solo la sua persistenza).
    pay_records = list(getattr(payment, "_payments", {}).values())
    # Impronta dei pagamenti: un incasso nuovo deve invalidare la cache anche
    # se il log del mese non e' cambiato.
    pay_key = (len(pay_records),
               max((r.get("captured_at") or 0 for r in pay_records), default=0))
    key = (ym, fp, pay_key)
    if key in _USER_STATS_CACHE:
        return jsonify(_USER_STATS_CACHE[key])

    t0 = time.time()
    try:
        data = user_stats.analyze(activity_log.month_rows(ym), ym=ym,
                                  payments=pay_records)
    except Exception as e:
        print(f"[admin] user_stats {ym} failed: {e}", flush=True)
        return jsonify({"error": f"Analysis failed: {e}"}), 500
    data["ym"] = ym
    data["file"] = log_name  # mai il path assoluto del server
    data["elapsed_sec"] = round(time.time() - t0, 2)
    if len(_USER_STATS_CACHE) >= _USER_STATS_CACHE_MAX:
        _USER_STATS_CACHE.pop(next(iter(_USER_STATS_CACHE)), None)
    _USER_STATS_CACHE[key] = data
    return jsonify(data)


# --- progress ------------------------------------------------------------
_JOBS_PROGRESS_MAX_IDS = 500


@bp.route("/api/admin/jobs_progress")
@admin_required
def api_admin_jobs_progress():
    """Avanzamento di N job in UNA richiesta, per il polling di /admin/log-activity.

    Prima la pagina apriva una fetch per ogni card in corso ogni 5 s: con
    decine di job vivi il burst superava il limit_req di nginx (10 r/s,
    burst 20 per IP) e le richieste successive dallo stesso IP, fra cui
    quella del pannello Stats, ricevevano 503. Qui il costo e' una
    richiesta per tick, qualunque sia il numero di card.

    Risposta: {job_id: {"status", "pct"}}; gli id sconosciuti sono omessi.
    """
    raw = request.args.get("ids", "") or ""
    ids = [s.strip() for s in raw.split(",")]
    ids = [s for s in ids if s][:_JOBS_PROGRESS_MAX_IDS]
    out = {}
    for jid in ids:
        job = _jobs().get(jid)
        if not job:
            continue
        st, _cur, _tot, pct = _job_progress(job)
        out[jid] = {"status": st, "pct": pct}
    return jsonify(out)


# --- copyhelpers ------------------------------------------------------------
def _admin_copy_recoverable(job_id):
    """True se una copia amministrativa del job è consegnabile all'app: job ancora
    in RAM (in corso → aggancio e consegna a fine job; done → clone immediato),
    OPPURE un download token esiste già, OPPURE l'output è ancora presente su
    disco/cold (job finalizzato ricostruibile). False → il job è definitivamente
    sparito e il QR non deve nemmeno essere proposto."""
    with _jobs_lock:
        if _jobs().get(job_id) is not None:
            return True
    for _tok, _rec in list(_tkstore.download_tokens.items()):
        if isinstance(_rec, dict) and _rec.get("job_id") == job_id:
            return True
    return _reconstruct_admin_download_record(job_id) is not None


def _admin_user_dl_link(job_id, now=None):
    """Snapshot del download token DELL'UTENTE per [job_id] (quello recapitato
    via email), a uso della UI admin: permette di reinviare manualmente il link
    quando l'email di completamento non arriva a destinazione.

    Esclude i token `admin_copy` (cloni creati dall'indagine, di proprietà
    dell'app admin) e quelli già oltre la retention effettiva. Se il job ha più
    token utente validi ritorna quello che scade più tardi.
    Ritorna dict {token, created_at, expires_at, downloaded_at} oppure None."""
    now = now or time.time()
    best = None
    for tok, tinfo in list(_tkstore.download_tokens.items()):
        if not isinstance(tinfo, dict) or tinfo.get("job_id") != job_id:
            continue
        if tinfo.get("admin_copy"):
            continue
        created = tinfo.get("created_at", 0) or 0
        ret = _effective_retention_for_token_info(tinfo)
        if (now - created) > ret:
            continue
        cand = {"token": tok, "created_at": created, "expires_at": created + ret,
                "downloaded_at": tinfo.get("downloaded_at") or 0}
        if best is None or cand["expires_at"] > best["expires_at"]:
            best = cand
    return best


def _admin_notify_email_for_job(job_id):
    """Indirizzo a cui è stata (o sarà) inviata la notifica di completamento del
    job, per la UI admin. Sorgenti in ordine: job in RAM, descrittore di recupero
    pending, mappa client_id→email. "" se nessuna notifica è prevista."""
    with _jobs_lock:
        job = _jobs().get(job_id)
        if job:
            email = (job.get("notify_email") or "").strip()
            client_id = job.get("client_id", "")
        else:
            email, client_id = "", ""
    if email:
        return email
    # Job non più in RAM: il descrittore di recupero (rimosso solo dopo l'invio
    # della mail) conserva l'indirizzo di notifica.
    try:
        for rec in pending_jobs.orphans():
            if isinstance(rec, dict) and rec.get("id") == job_id:
                email = (rec.get("notify_email") or "").strip()
                client_id = client_id or rec.get("client_id", "")
                break
    except Exception:
        email = ""
    if email:
        return email
    if client_id:
        return (_client_emails().get(client_id) or "").strip()
    return ""


# --- paypaldebug ------------------------------------------------------------
@bp.route("/api/paypal_debug_order/<order_id>", methods=["GET"])
@admin_required
def api_paypal_debug_order(order_id):
    """Diagnostic: fetch order from PayPal to inspect payee/status/etc.
    Admin-only: returns payer PII (email, name, address) — must never be public."""
    import requests
    if not _paypal_available():
        return jsonify({"error": "PayPal not configured"}), 503
    try:
        token = _paypal_get_access_token()
        r = requests.get(
            f"{_paypal_api_base()}/v2/checkout/orders/{order_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        return jsonify({"status_code": r.status_code, "body": r.json()}), r.status_code
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# --- active ------------------------------------------------------------
@bp.route("/api/active_jobs")
@admin_required
def api_active_jobs():
    """Return list of currently generating jobs (for admin monitor).
    Protected by admin token.
    """

    with _jobs_lock:
        snapshot = list(_jobs().items())
    active = []
    for jid, job in snapshot:
        if job.get("status") in ("generating", "analyzed", "optimizing", "optimized"):
            info = job.get("info")
            title = ""
            if info:
                title = getattr(info, "title", "") or ""
            if not title:
                title = job.get("original_filename", jid)
            start_ts = job.get("start_time", 0)
            active.append({
                "title": title,
                "started": datetime.fromtimestamp(start_ts).strftime("%Y-%m-%d %H:%M:%S") if start_ts else " - ",
                "status": job.get("status", ""),
                "progress": job.get("progress_current", 0),
                "total": job.get("progress_total", 0),
                "chapter": job.get("current_chapter", ""),
            })
    return jsonify({"jobs": active, "count": len(active)})
