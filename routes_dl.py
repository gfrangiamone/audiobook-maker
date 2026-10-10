"""routes_dl — pagina e download via token, serving dei file, /api/download*
(E3, seam /dl + serving, 2026-10-10).

Blueprint `dl`: `/dl/<token>` (pagina di download con stato, scadenza,
link app), `/dl/<token>/{download,m4b,abm,translated}`, `/api/download/
<job_id>`, `/api/download_podcast/<job_id>`, `/api/download_translation/
<job_id>`; con il serving dell'audio (M4B, kit MP3, ZIP capitoli) e del
podcast (RSS, index, cover, ZIP), le pagine di scadenza/cancellazione/
attesa e il fallback cold storage. Spostato pari pari da `audiobook_app`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app), i 25 helper qui sotto piu' `jobs`,
`UPLOAD_DIR`, `BASE_URL`, `EMAIL_FILE_RETENTION_SEC`; per riferimento il
favicon, i testi delle pagine dl e il modulo `generation_engine` (un
modulo di route non lo importa). Non importa `audiobook_app`.
"""
import html as html_mod
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from flask import Blueprint, after_this_request, jsonify, request

import i18n as _i18n
import token_store as _tkstore
from page_brand import render_page as _render_page

bp = Blueprint("dl", __name__)

_cfg = {}
FAVICON_B64 = ""
_DL_PAGES_I18N = {}
generation_engine = None

FUNCS = ['_send_file_throttled', '_log_activity', '_is_resume_or_probe_request', '_mark_token_downloaded', '_mark_token_redirected', '_safe_filename', '_try_cold_serve', '_cold_op', '_cold_object_available', '_cold_m4b_valid', '_iter_output_dirs', '_find_files_in_outputs', '_check_job_owner', '_effective_retention_for_token_info', '_android_intent_url', '_app_scheme_url', '_extract_cover_for_preview', '_extract_cover_from_epub', '_generate_fallback_cover', '_generate_podcast_rss', '_qr_data_uri', '_transfer_payload_for', '_ua_is_android', '_ua_is_ios', '_ua_is_mobile']
VALUES = ("jobs", "upload_dir", "base_url", "email_file_retention_sec")


def configure(*, favicon, dl_pages_i18n, engine, **fns):
    """`fns`: una funzione per ogni nome in FUNCS e VALUES (la app passa
    lambda che risolvono i suoi globali a ogni chiamata)."""
    missing = [n for n in FUNCS + list(VALUES) if n not in fns]
    assert not missing, f"routes_dl.configure: mancano {missing}"
    _cfg.update(fns)
    globals()["FAVICON_B64"] = favicon
    globals()["_DL_PAGES_I18N"] = dl_pages_i18n
    globals()["generation_engine"] = engine


# Valori della app usati dal codice spostato: risolti a ogni chiamata.
def _jobs():
    return _cfg["jobs"]()


def _upload_dir():
    return _cfg["upload_dir"]()


def _base_url():
    return _cfg["base_url"]()


def _email_file_retention_sec():
    return _cfg["email_file_retention_sec"]()


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _send_file_throttled(*a, **k):
    return _cfg["_send_file_throttled"](*a, **k)

def _log_activity(*a, **k):
    return _cfg["_log_activity"](*a, **k)

def _is_resume_or_probe_request(*a, **k):
    return _cfg["_is_resume_or_probe_request"](*a, **k)

def _mark_token_downloaded(*a, **k):
    return _cfg["_mark_token_downloaded"](*a, **k)

def _mark_token_redirected(*a, **k):
    return _cfg["_mark_token_redirected"](*a, **k)

def _safe_filename(*a, **k):
    return _cfg["_safe_filename"](*a, **k)

def _try_cold_serve(*a, **k):
    return _cfg["_try_cold_serve"](*a, **k)

def _cold_op(*a, **k):
    return _cfg["_cold_op"](*a, **k)

def _cold_object_available(*a, **k):
    return _cfg["_cold_object_available"](*a, **k)

def _cold_m4b_valid(*a, **k):
    return _cfg["_cold_m4b_valid"](*a, **k)

def _iter_output_dirs(*a, **k):
    return _cfg["_iter_output_dirs"](*a, **k)

def _find_files_in_outputs(*a, **k):
    return _cfg["_find_files_in_outputs"](*a, **k)

def _check_job_owner(*a, **k):
    return _cfg["_check_job_owner"](*a, **k)

def _effective_retention_for_token_info(*a, **k):
    return _cfg["_effective_retention_for_token_info"](*a, **k)

def _android_intent_url(*a, **k):
    return _cfg["_android_intent_url"](*a, **k)

def _app_scheme_url(*a, **k):
    return _cfg["_app_scheme_url"](*a, **k)

def _extract_cover_for_preview(*a, **k):
    return _cfg["_extract_cover_for_preview"](*a, **k)

def _extract_cover_from_epub(*a, **k):
    return _cfg["_extract_cover_from_epub"](*a, **k)

def _generate_fallback_cover(*a, **k):
    return _cfg["_generate_fallback_cover"](*a, **k)

def _generate_podcast_rss(*a, **k):
    return _cfg["_generate_podcast_rss"](*a, **k)

def _qr_data_uri(*a, **k):
    return _cfg["_qr_data_uri"](*a, **k)

def _transfer_payload_for(*a, **k):
    return _cfg["_transfer_payload_for"](*a, **k)

def _ua_is_android(*a, **k):
    return _cfg["_ua_is_android"](*a, **k)

def _ua_is_ios(*a, **k):
    return _cfg["_ua_is_ios"](*a, **k)

def _ua_is_mobile(*a, **k):
    return _cfg["_ua_is_mobile"](*a, **k)


# --- translation ------------------------------------------------------------
@bp.route("/api/download_translation/<job_id>")
def api_download_translation(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    path = job.get("translated_path", "")
    name = job.get("translated_name", "translated")
    if not path or not os.path.exists(path):
        _cold = _try_cold_serve(path, download_name=name)
        if _cold is not None:
            return _cold
        return jsonify({"error": "File not available"}), 404
    _log_activity(job_id, job.get("original_filename", ""),
                  "DOWNLOAD_TRANSLATION", job.get("client_id", ""),
                  job.get("client_ip", ""), "", "")
    return _send_file_throttled(path, as_attachment=True,
                                download_name=name, no_cache=True)


# --- serving ------------------------------------------------------------
def _with_mp3_fallback_header(resp):
    """Segnala al client che al posto dell'M4B arriva l'MP3 (header
    `X-Fallback: mp3`, esposto al JS via CORS). Mai fatale."""
    try:
        resp.headers["X-Fallback"] = "mp3"
        prev = resp.headers.get("Access-Control-Expose-Headers", "")
        resp.headers["Access-Control-Expose-Headers"] = (prev + ", X-Fallback").lstrip(", ")
    except Exception:
        pass
    return resp


def _check_dl_token(token):
    """Validazione comune degli endpoint file /dl/<token>/*: esistenza del token
    e retention effettiva. Ritorna (token_info, None) se valido, altrimenti
    (None, (body, 410)) con il token gia' rimosso e persistito se scaduto.
    La pagina /dl/<token> NON usa questo helper (risposta renderizzata, non
    plain-text)."""
    token_info = _tkstore.download_tokens.get(token)
    if not token_info:
        return None, ("Link scaduto", 410)
    _ret = _effective_retention_for_token_info(token_info)
    if time.time() - token_info["created_at"] > _ret:
        _tkstore.download_tokens.pop(token, None)
        _tkstore.save_tokens()
        return None, (f"Link scaduto  -  i file sono stati cancellati dopo {_ret // 3600} ore", 410)
    return token_info, None


def _resolve_snapshot_path(path_snap, job_dir=None, legacy_flat=False):
    """Risolve un path assoluto snapshotato in un download token.

    Ordine: path originale se esiste; ricostruzione per-epoch
    job_dir/<epoch_dir>/<basename> (data-dir migrata); opzionale fallback
    legacy flat job_dir/<basename> (layout pre per-epoch). Ritorna il path
    esistente (str) oppure "" se il file non e' reperibile in locale (il
    chiamante prova poi il cold tier). job_dir=None disabilita ogni
    ricostruzione (es. token senza job_id)."""
    if not path_snap:
        return ""
    if os.path.exists(path_snap):
        return str(path_snap)
    if job_dir is None:
        return ""
    cand = job_dir / Path(path_snap).parent.name / Path(path_snap).name
    if cand.exists():
        return str(cand)
    if legacy_flat:
        alt = job_dir / os.path.basename(path_snap)
        if alt.exists():
            return str(alt)
    return ""


@bp.route("/dl/<token>")
def token_download_page(token):
    """Serve download page for email-linked token."""
    token_info = _tkstore.download_tokens.get(token)
    if not token_info:
        return _render_dl_expired_page(), 410

    lang = token_info.get("lang", "en")
    created_at = token_info["created_at"]
    elapsed = time.time() - created_at
    # Retention per-token: PREMIUM (is_gemini) usa GEMINI_FILE_RETENTION_SEC.
    # Usa la retention EFFETTIVA (×2 no-download per PREMIUM mai scaricato),
    # allineata al cleanup: altrimenti la pagina dichiara "scaduto" e rimuove
    # il token tra 48h e 96h mentre i file esistono ancora su disco.
    _ret = _effective_retention_for_token_info(token_info)

    # Check retention expiration
    if elapsed > _ret:
        _tkstore.download_tokens.pop(token, None)
        _tkstore.save_tokens()
        return _render_dl_expired_page(lang, retention_hours=round(_ret / 3600)), 410

    # Check job exists in memory OR files still on disk
    job_id = token_info["job_id"]
    job_dir = _upload_dir() / job_id
    dl_type = token_info.get("download_type", "audio")
    job_in_memory = job_id in _jobs() and _jobs()[job_id].get("status") in ("done", "optimized")
    files_on_disk = job_dir.exists()
    # Cold-aware: se il locale è assente ma esiste ancora una copia su cold
    # storage, il download NON è scaduto (gli endpoint /dl/<token>/m4b|abm
    # servono dal presigned URL). Senza questo check la pagina dichiarava
    # "scaduto in anticipo" dopo eviction/rimozione del locale.
    cold_available = _tkstore.token_cold_available(token_info) if not files_on_disk else False

    if not job_in_memory and not files_on_disk and not cold_available:
        _tkstore.download_tokens.pop(token, None)
        _tkstore.save_tokens()
        return _render_dl_expired_page(lang, retention_hours=round(_ret / 3600)), 410

    remaining_sec = max(60, int(_ret - elapsed))
    remaining_h = remaining_sec // 3600
    remaining_m = (remaining_sec % 3600) // 60
    if remaining_h > 0:
        remaining_str = f"~{remaining_h}h {remaining_m}min" if remaining_m > 0 else f"~{remaining_h}h"
    else:
        remaining_str = f"~{remaining_m} min"

    # Book title: from job in memory or from token snapshot
    if job_in_memory and _jobs()[job_id].get("info"):
        book_title = _jobs()[job_id]["info"].title or ""
    else:
        book_title = token_info.get("book_title", "")

    # M4B availability: regola di precedenza per non rompere l'isolamento
    # per-epoch (un token email punta a UNA specifica generazione, il job vivo
    # può aver prodotto altri file con epoche più nuove):
    #   1) token snapshot -> output_m4b (path assoluto)
    #   2) ricostruzione per basename dentro la cartella per-epoch del token
    #   3) (legacy) job vivo -> output_m4b
    #   4) (legacy) glob ricorsivo nella cartella del job, SOLO se il token
    #      NON ha info di epoch (token vecchi creati prima del layout per-epoch).
    m4b_available = False
    m4b_path_snap = token_info.get("output_m4b", "")
    if m4b_path_snap:
        # Include la ricostruzione per-epoch: output_{epoch}/<basename>.m4b
        m4b_available = bool(_resolve_snapshot_path(m4b_path_snap, job_dir))
    else:
        # Token legacy senza snapshot M4B: live job o glob ricorsivo come
        # last-resort. Non rompe l'isolamento per-epoch perche' arriva qui
        # solo se il token NON aveva originariamente un output_m4b.
        if job_in_memory:
            m4b_path_mem = _jobs()[job_id].get("output_m4b", "")
            if m4b_path_mem and os.path.exists(m4b_path_mem):
                m4b_available = True
        if not m4b_available:
            m4bs = list(job_dir.glob("**/*.m4b"))
            m4b_available = len(m4bs) > 0
    # Cold fallback: locale evacuato/rimosso ma copia cold presente.
    if not m4b_available and _cold_object_available(m4b_path_snap):
        m4b_available = True

    # Kit di ripiego M4B (ZIP con MP3 + capitoli): disponibile se l'M4B vero manca.
    kit_snap = token_info.get("output_m4b_fallback_zip", "")
    m4b_kit_available = bool(_resolve_snapshot_path(kit_snap, job_dir))
    if not m4b_kit_available and kit_snap and _cold_object_available(kit_snap):
        m4b_kit_available = True

    abm_path_snap = token_info.get("optimized_abm_path", "")
    has_abm = bool(_resolve_snapshot_path(abm_path_snap, job_dir))
    if not has_abm and _cold_object_available(abm_path_snap):
        has_abm = True

    output_format = token_info.get("output_format", "")
    if not output_format and job_in_memory:
        output_format = _jobs()[job_id].get("output_format", "")

    # Traduzione: disponibilità del file tradotto (locale per-epoch o cold).
    translated_available = False
    if dl_type == "translated":
        tr_path_snap = token_info.get("translated_path", "")
        # legacy_flat: mirrors token_do_download_translated
        translated_available = bool(_resolve_snapshot_path(tr_path_snap, job_dir,
                                                           legacy_flat=True))
        if not translated_available and _cold_object_available(tr_path_snap):
            translated_available = True

    # QR di trasferimento job sull'app mobile (best-effort). Escluso per i
    # download di sola traduzione: l'app gestisce solo audiolibri, non i file
    # di testo tradotto, quindi il QR "trasferisci sull'app" non ha senso lì.
    _transfer_qr = ""
    _transfer_url = ""
    if dl_type != "translated":
        try:
            _qr_payload, _ = _transfer_payload_for(job_id)
            _transfer_url = _qr_payload
            _transfer_qr = _qr_data_uri(_qr_payload)
        except Exception:
            _transfer_qr = ""
            _transfer_url = ""

    return _render_dl_page(token, book_title, remaining_str,
                           token_info["download_type"], lang,
                           m4b_available=m4b_available, has_abm=has_abm,
                           output_format=output_format,
                           retention_hours=round(_ret / 3600),
                           m4b_kit_available=m4b_kit_available,
                           translated_available=translated_available,
                           transfer_qr=_transfer_qr,
                           transfer_url=_transfer_url,
                           is_mobile=_ua_is_mobile(),
                           is_android=_ua_is_android(),
                           is_ios=_ua_is_ios())


@bp.route("/dl/<token>/abm")
def token_do_download_abm(token):
    """Serve the optimized .abm file for a token (when available)."""
    token_info, _err = _check_dl_token(token)
    if _err:
        return _err
    job_id = token_info.get("job_id", "")
    abm_name = token_info.get("optimized_abm_name", "optimized.abm")
    # Always serve the .abm captured in this token's snapshot. Each generation
    # epoch writes its own output_{epoch}/foo_optimized.abm; regenerating from
    # the live job state would overwrite with the latest cumulative selection
    # and break per-epoch isolation across sibling email tokens.
    abm_path = _resolve_snapshot_path(token_info.get("optimized_abm_path", ""),
                                      (_upload_dir() / job_id) if job_id else None,
                                      legacy_flat=True)
    if not abm_path:
        _cold = _try_cold_serve(token_info.get("optimized_abm_path", ""), download_name=abm_name)
        if _cold is not None:
            return _cold
        return "File not available", 404
    if not _is_resume_or_probe_request():
        _log_activity(token_info.get("job_id", ""), token_info.get("original_filename", ""),
                      "DOWNLOAD_OPT_ABM", "", "", "", "")
    _mark_token_downloaded(token_info)
    return _send_file_throttled(abm_path, as_attachment=True, download_name=abm_name, no_cache=True, conditional=True)


@bp.route("/dl/<token>/translated")
def token_do_download_translated(token):
    """Serve the translated book file for a token (download_type=translated)."""
    token_info, _err = _check_dl_token(token)
    if _err:
        return _err
    job_id = token_info.get("job_id", "")
    name = token_info.get("translated_name", "translated")
    # Always serve the file captured in this token's snapshot (per-epoch
    # isolation, same rationale as /dl/<token>/abm).
    path = _resolve_snapshot_path(token_info.get("translated_path", ""),
                                  (_upload_dir() / job_id) if job_id else None,
                                  legacy_flat=True)
    if not path:
        _cold = _try_cold_serve(token_info.get("translated_path", ""), download_name=name)
        if _cold is not None:
            return _cold
        return "File not available", 404
    if not _is_resume_or_probe_request():
        _log_activity(token_info.get("job_id", ""), token_info.get("original_filename", ""),
                      "DOWNLOAD_TRANSLATION_TOKEN", "", "", "", "")
    _mark_token_downloaded(token_info)
    return _send_file_throttled(path, as_attachment=True, download_name=name, no_cache=True)


@bp.route("/dl/<token>/m4b")
def token_do_download_m4b(token):
    """Execute the actual M4B file download via token.

    Allineato a /api/download/<job>?type=m4b:
    - glob ricorsivo ("**/*.m4b") sulla job dir
    - fallback su MP3 con header X-Fallback se M4B non esiste
    - sync di job["output_m4b"] quando il file è trovato via glob
    """
    token_info, _err = _check_dl_token(token)
    if _err:
        return _err

    job_id = token_info["job_id"]

    # Per-epoch isolation: il token email punta a UNA specifica generazione.
    # Non usiamo MAI lo stato del job vivo (job["output_m4b"]) come fonte
    # primaria, perche' una rigenerazione successiva potrebbe averlo aggiornato
    # a un'epoch piu' nuova, esponendo file diversi al link email.
    job = _jobs().get(job_id)
    if job:
        job["last_poll"] = time.time()
        job["downloaded_at"] = time.time()

    job_dir = _upload_dir() / job_id

    # 1) Path snapshot + reconstruction per-epoch: cerca il basename del file
    # dentro la cartella output_{epoch}/ catturata nello snapshot del token.
    m4b_path = _resolve_snapshot_path(token_info.get("output_m4b", ""), job_dir)

    # 2) Legacy fallback: per token CREATI PRIMA dell'introduzione del layout
    # per-epoch (snapshot privo di output_m4b), usiamo un glob ricorsivo come
    # ultima spiaggia. Non rompe l'isolamento: ci arriviamo solo se il token
    # non aveva originariamente un path snapshotato.
    if (not m4b_path) and (not token_info.get("output_m4b")):
        m4bs = list(job_dir.glob("**/*.m4b"))
        if m4bs:
            m4b_path = str(m4bs[0])

    safe_name = _safe_filename(token_info.get("book_title", "audiolibro"))

    if m4b_path and os.path.exists(m4b_path):
        if request.method != "HEAD" and not request.headers.get("Range"):
            _log_activity(job_id, token_info.get("original_filename", ""), "DOWNLOAD_M4B_TOKEN",
                          "", "", "", "")
        _mark_token_downloaded(token_info)
        return _send_file_throttled(m4b_path, as_attachment=True, download_name=f"{safe_name}.m4b", conditional=True)

    # F4 — Il M4B locale è evacuato: PRIMA del fallback MP3, prova a servire il
    # M4B da cold (presigned 302), ma solo se è FINALIZZATO (atom moov presente):
    # così l'utente riceve il vero M4B invece dell'MP3 quando il locale è stato
    # solo evictato, senza però servire un eventuale m4b cold troncato (legacy).
    _m4b_snap = token_info.get("output_m4b", "")
    if _cold_m4b_valid(_m4b_snap):
        _cold = _try_cold_serve(_m4b_snap, download_name=f"{safe_name}.m4b")
        if _cold is not None:
            if request.method != "HEAD" and not request.headers.get("Range"):
                _log_activity(job_id, token_info.get("original_filename", ""),
                              _cold_op("DOWNLOAD_M4B_TOKEN"), "", "", "", "")
            _mark_token_redirected(token_info)
            return _cold

    # M4B fallito ma esiste un kit di ripiego (ZIP con MP3 + capitoli + script):
    # serviamo quello invece del solo MP3, così l'utente può ricostruire l'M4B.
    kit_snap = token_info.get("output_m4b_fallback_zip", "")
    kit_path = _resolve_snapshot_path(kit_snap, job_dir)
    if not kit_path:
        _kits = list(job_dir.glob("**/*_audiolibro_capitoli.zip"))
        if _kits:
            kit_path = str(_kits[0])
    if kit_path and os.path.exists(kit_path):
        if request.method != "HEAD" and not request.headers.get("Range"):
            _log_activity(job_id, token_info.get("original_filename", ""),
                          "DOWNLOAD_M4B_KIT_TOKEN", "", "", "", "")
        _mark_token_downloaded(token_info)
        return _send_file_throttled(kit_path, as_attachment=True,
                                    download_name=f"{safe_name}_audiolibro+capitoli.zip", conditional=True)

    # Fallback MP3 (coerente con /api/download): l'M4B non c'è (conversione fallita
    # o non ancora pronta), serviamo l'MP3 segnalandolo al client via X-Fallback.
    print(f"[dl] M4B totally missing for job {job_id}. Falling back to MP3.")
    mp3_path = ""
    if job:
        mp3_path = (job.get("output_files") or [""])[0]
    if not mp3_path or not os.path.exists(mp3_path):
        mp3s = list(job_dir.glob("**/*.mp3"))
        if mp3s:
            mp3_path = str(mp3s[0])

    if mp3_path and os.path.exists(mp3_path):
        if request.method != "HEAD" and not request.headers.get("Range"):
            _log_activity(job_id, token_info.get("original_filename", ""), "DOWNLOAD_M4B_TOKEN_FALLBACK_MP3",
                          "", "", "", "")
        _mark_token_downloaded(token_info)
        resp = _send_file_throttled(mp3_path, as_attachment=True, download_name=f"{safe_name}.mp3", conditional=True)
        _with_mp3_fallback_header(resp)
        return resp

    # Cold tier: il locale (m4b e mp3) è evacuato; se esiste la copia cold del
    # M4B snapshotato, redirect 302 al presigned URL prima del 404.
    _cold = _try_cold_serve(token_info.get("output_m4b", ""), download_name=f"{safe_name}.m4b")
    if _cold is not None:
        if request.method != "HEAD" and not request.headers.get("Range"):
            _log_activity(job_id, token_info.get("original_filename", ""),
                          _cold_op("DOWNLOAD_M4B_TOKEN"), "", "", "", "")
        _mark_token_redirected(token_info)
        return _cold

    # Diagnostica completa: nessun M4B e nessun MP3 disponibile.
    print(f"[dl/m4b] 404 token={token} job={job_id} "
          f"token_m4b={token_info.get('output_m4b','')!r} "
          f"output_dirs={[d.name for d in _iter_output_dirs(job_dir)]}")
    return "M4B file not available", 404


@bp.route("/dl/<token>/download")
def token_do_download(token):
    """Execute the actual file download via token."""
    token_info, _err = _check_dl_token(token)
    if _err:
        return _err

    job_id = token_info["job_id"]

    # Try to get data from job in memory, otherwise use token snapshot
    job = _jobs().get(job_id)
    if job:
        job["last_poll"] = time.time()
        job["downloaded_at"] = time.time()

    dl_type = token_info.get("download_type", "audio")

    # Diagnostic logging
    job_dir = _upload_dir() / job_id
    print(f"[dl] Token download: job={job_id}, type={dl_type}, "
          f"job_in_memory={job is not None}, "
          f"job_dir_exists={job_dir.exists()}, "
          f"stored_zip={token_info.get('output_zip', '')[:80]}, "
          f"UPLOAD_DIR={_upload_dir()}")

    try:
        #  -  -  OPTIMIZED ABM download  -  -
        if dl_type == "optimized_abm":
            abm_name = token_info.get("optimized_abm_name", "optimized.abm")
            # Serve the .abm captured in this token's snapshot — see
            # /dl/<token>/abm comment for the per-epoch isolation rationale.
            abm_path = _resolve_snapshot_path(token_info.get("optimized_abm_path", ""),
                                              job_dir, legacy_flat=True)
            if abm_path:
                if job:
                    job["downloaded_at"] = time.time()
                if not _is_resume_or_probe_request():
                    _log_activity(job_id, token_info.get("original_filename", ""),
                                  "DOWNLOAD_OPT_ABM", "", "", "", "")
                _mark_token_downloaded(token_info)
                # Route through _send_file_throttled (bypass_throttle: il token è
                # già la chiave d'accesso) per coerenza con la chokepoint cold.
                return _send_file_throttled(abm_path, as_attachment=True,
                                            download_name=abm_name, no_cache=True,
                                            bypass_throttle=True, conditional=True)
            _cold = _try_cold_serve(token_info.get("optimized_abm_path", ""), download_name=abm_name)
            if _cold is not None:
                if not _is_resume_or_probe_request():
                    _log_activity(job_id, token_info.get("original_filename", ""),
                                  _cold_op("DOWNLOAD_OPT_ABM"), "", "", "", "")
                _mark_token_redirected(token_info)
                return _cold
            return "File not found", 404

        #  -  -  PODCAST download  -  -
        is_podcast = dl_type == "podcast" and (
            (job and job.get("podcast_ready")) or token_info.get("podcast_ready"))

        if is_podcast:
            return _serve_podcast_download(token_info, job, job_id)

        #  -  -  AUDIO download  -  - 
        return _serve_audio_download(token_info, job, job_id)

    except Exception as e:
        print(f"[dl/{token}] ERROR in download: {e}")
        import traceback
        traceback.print_exc()
        return f"Errore durante il download. Riprova tra qualche istante.", 500


def _serve_audio_download(token_info, job, job_id):
    """Serve audio download bound to this token's epoch.

    The token snapshot holds absolute paths into `output_{epoch}/`. We always
    try those first; only fall back to live job state or directory scans if
    the snapshot path is genuinely gone (e.g. data-dir migration). This keeps
    sibling email tokens from leaking each other's files.
    """
    output_name = token_info.get("output_name", "audiobook.zip")
    orig = token_info.get("original_filename", "")
    job_dir = _upload_dir() / job_id

    def _do_log(cold=False):
        if _is_resume_or_probe_request():
            return
        _log_activity(job_id, orig, _cold_op("DOWNLOAD_EMAIL") if cold else "DOWNLOAD_EMAIL",
                      job.get("client_id", "") if job else "",
                      job.get("client_ip", "") if job else "",
                      job.get("voice", "") if job else "",
                      job.get("browser_lang", "") if job else "")
        # Disattiva la protezione no-download per voci PREMIUM (cleanup loop),
        # ma SOLO su consegna reale: un redirect al cold non prova nulla.
        if cold:
            _mark_token_redirected(token_info)
        else:
            _mark_token_downloaded(token_info)

    output_zip = token_info.get("output_zip", "")
    output_file = token_info.get("output_file", "")

    # 1. Exact paths from token snapshot
    if output_zip and os.path.exists(output_zip):
        _do_log()
        return _send_file_throttled(output_zip, as_attachment=True, download_name=output_name, conditional=True)
    if output_file and os.path.exists(output_file):
        _do_log()
        return _send_file_throttled(output_file, as_attachment=True, download_name=output_name, conditional=True)

    # 2. Path reconstruction within the snapshot's epoch dir (data-dir moved)
    for p in (output_zip, output_file):
        if not p:
            continue
        cand = job_dir / Path(p).parent.name / Path(p).name
        if cand.exists():
            print(f"[dl] Path reconstructed: {p} -> {cand}")
            _do_log()
            return _send_file_throttled(str(cand), as_attachment=True, download_name=output_name, conditional=True)

    # 3. Live job state (only when snapshot path missing — older runs may have
    #    been cleaned up; we still try to serve *something* for this job).
    if job:
        orig = job.get("original_filename", orig)
        if job.get("output_zip") and os.path.exists(job["output_zip"]):
            print(f"[dl] Snapshot missing; falling back to live job output_zip")
            _do_log()
            return _send_file_throttled(job["output_zip"], as_attachment=True,
                             download_name=job.get("output_name", output_name), conditional=True)
        if job.get("output_files") and os.path.exists(job["output_files"][0]):
            print(f"[dl] Snapshot missing; falling back to live job output_files[0]")
            _do_log()
            return _send_file_throttled(job["output_files"][0], as_attachment=True,
                             download_name=job.get("output_name", output_name), conditional=True)

    # 4. Cold tier: il file snapshotato vive ancora su cold (locale evacuato a
    #    fine finestra calda). È la copia AUTORITATIVA e va tentata PRIMA dello
    #    scan di directory: quest'ultimo è un'euristica di last-resort che può
    #    raccogliere file non-deliverable lasciati nella job root (es.
    #    preview_*.mp3), servendo contenuto sbagliato. (Incidente 2026-06-10,
    #    job K9v-PxIXyUVUKqVkg3vjZg: zip evacuato → servito uno zip di preview.)
    for _p in (output_zip, output_file):
        _cold = _try_cold_serve(_p, download_name=output_name)
        if _cold is not None:
            _do_log(cold=True)
            return _cold

    # 5. Fallback: scan job directory for downloadable files
    if job_dir.exists():
        print(f"[dl] Scanning {job_dir} for downloadable files...")
        zips = sorted(job_dir.glob("*.zip")) + sorted(_find_files_in_outputs(job_dir, "*.zip"))
        # Escludi gli zip NON canonici: podcast e zip transitori di download
        # (download.zip / dl_*.zip). Questi ultimi sono temporanei e non vanno
        # mai ri-serviti né lasciati sul disco (in passato un download.zip
        # orfano da 28GB ha saturato il volume).
        zips = [z for z in zips
                if "_podcast" not in z.name
                and z.name != "download.zip"
                and not z.name.startswith("dl_")]
        if zips:
            found = str(zips[0])
            print(f"[dl] Fallback: found ZIP {found}")
            _do_log()
            return _send_file_throttled(found, as_attachment=True,
                             download_name=output_name or os.path.basename(found), conditional=True)
        # Look for MP3s across all output dirs, then root.
        # Escludi i preview_*.mp3 (campioni voce generati da /api/preview_audio,
        # lasciati nella job root): NON sono parte dell'audiolibro e non vanno
        # mai serviti (incidente 2026-06-10: zip di preview consegnato).
        mp3s = sorted(_find_files_in_outputs(job_dir, "*.mp3"))
        if not mp3s:
            mp3s = sorted(job_dir.glob("*.mp3"))
        mp3s = [m for m in mp3s if not m.name.startswith("preview_")]
        if len(mp3s) == 1:
            found = str(mp3s[0])
            print(f"[dl] Fallback: found single MP3 {found}")
            _do_log()
            return _send_file_throttled(found, as_attachment=True,
                             download_name=output_name or os.path.basename(found), conditional=True)
        elif len(mp3s) > 1:
            # Multiple MP3s: crea uno ZIP al volo da SOLI i file mp3.
            # NON usare make_archive sull'intera dir: se gli mp3 sono nella job
            # root, zipperebbe la cartella in sé stessa (incluso lo zip in
            # crescita) → esplosione di dimensione. Aggiungiamo i singoli file
            # con arcname=basename, in un file temporaneo rimosso dopo l'invio.
            import tempfile, zipfile as _zf
            _fd, tmp_zip = tempfile.mkstemp(suffix=".zip", prefix="dl_", dir=str(job_dir))
            os.close(_fd)
            try:
                with _zf.ZipFile(tmp_zip, "w", _zf.ZIP_DEFLATED, allowZip64=True) as zf:
                    for _m in mp3s:
                        zf.write(str(_m), arcname=os.path.basename(str(_m)))
            except Exception:
                try: os.remove(tmp_zip)
                except OSError: pass
                raise

            @after_this_request
            def _cleanup_dl_zip(resp, _p=tmp_zip):
                # unlink dopo l'invio: su Linux l'FD aperto da send_file resta
                # valido fino a fine streaming, lo spazio si libera alla chiusura.
                try: os.remove(_p)
                except OSError: pass
                return resp

            print(f"[dl] Fallback: created ZIP from {len(mp3s)} MP3s -> {tmp_zip}")
            _do_log()
            return _send_file_throttled(tmp_zip, as_attachment=True,
                             download_name=output_name or "audiobook.zip", conditional=True)

    # Cold tier: il locale è evacuato (finestra calda scaduta). Se la copia cold
    # del file snapshotato (zip o single-file) esiste, redirect 302 al presigned.
    for _p in (output_zip, output_file):
        _cold = _try_cold_serve(_p, download_name=output_name)
        if _cold is not None:
            _do_log(cold=True)
            return _cold

    print(f"[dl] No files found for job {job_id} (job_dir exists: {job_dir.exists()})")
    print(f"[dl]   stored output_zip: {output_zip}")
    print(f"[dl]   stored output_file: {output_file}")
    print(f"[dl]   _upload_dir(): {_upload_dir()}")
    return "File non più disponibili", 410


def _generate_podcast_index_html(podcast_dir, title, author, cover_file, rss_fname, mp3_files, language="en"):
    """Generate an index.html landing page for the podcast folder (required by Netlify)."""
    lang = language[:2] if language else "en"
    _labels = {
        "it": {"heading": "Podcast", "by": "di", "subscribe": "Iscriviti al Podcast",
               "copy": "Copia URL feed", "copied": "Copiato!",
               "episodes": "Episodi", "listen": "Ascolta",
               "instructions": "Copia l'URL del feed RSS e incollalo nella tua app podcast preferita (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Generato con Audiobook Maker"},
        "en": {"heading": "Podcast", "by": "by", "subscribe": "Subscribe to Podcast",
               "copy": "Copy feed URL", "copied": "Copied!",
               "episodes": "Episodes", "listen": "Listen",
               "instructions": "Copy the RSS feed URL and paste it in your favorite podcast app (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Generated with Audiobook Maker"},
        "fr": {"heading": "Podcast", "by": "de", "subscribe": "S'abonner au Podcast",
               "copy": "Copier l'URL du flux", "copied": "Copié !",
               "episodes": "Épisodes", "listen": "Écouter",
               "instructions": "Copiez l'URL du flux RSS et collez-la dans votre app podcast (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Généré avec Audiobook Maker"},
        "es": {"heading": "Podcast", "by": "de", "subscribe": "Suscríbete al Podcast",
               "copy": "Copiar URL del feed", "copied": "¡Copiado!",
               "episodes": "Episodios", "listen": "Escuchar",
               "instructions": "Copia la URL del feed RSS y pégala en tu app de podcast favorita (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Generado con Audiobook Maker"},
        "de": {"heading": "Podcast", "by": "von", "subscribe": "Podcast abonnieren",
               "copy": "Feed-URL kopieren", "copied": "Kopiert!",
               "episodes": "Episoden", "listen": "Anhören",
               "instructions": "Kopieren Sie die RSS-Feed-URL und fügen Sie sie in Ihre Podcast-App ein (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...).",
               "footer": "Erstellt mit Audiobook Maker"},
        "zh": {"heading": "播客", "by": "作者", "subscribe": "订阅播客",
               "copy": "复制订阅URL", "copied": "已复制！",
               "episodes": "章节", "listen": "收听",
               "instructions": "复制RSS订阅URL并将其粘贴到您的播客应用程序中（Pocket Casts，Apple Podcasts，AntennaPod，Overcast...）。",
               "footer": "由Audiobook Maker生成"},
        "hi": {"heading": "पॉडकास्ट", "by": "लेखक", "subscribe": "पॉडकास्ट सब्सक्राइब करें",
               "copy": "फ़ीड URL कॉपी करें", "copied": "कॉपी हो गया!",
               "episodes": "एपिसोड", "listen": "सुनें",
               "instructions": "RSS फ़ीड URL कॉपी करें और इसे अपने पसंदीदा पॉडकास्ट ऐप (Pocket Casts, Apple Podcasts, AntennaPod, Overcast...) में पेस्ट करें।",
               "footer": "Audiobook Maker से जनरेट किया गया"},
    }
    lb = _i18n.pick(_labels, lang, merge=False)

    # Build episode list
    sorted_mp3 = sorted([os.path.basename(f) for f in mp3_files if os.path.exists(f)])
    episodes_html = ""
    for i, mp3 in enumerate(sorted_mp3, 1):
        display_name = mp3.rsplit(".", 1)[0].replace("_", " ").replace("-", " ")
        episodes_html += f'<tr><td style="padding:10px 12px;border-bottom:1px solid #eee;color:#666;width:40px;text-align:center">{i}</td><td style="padding:10px 12px;border-bottom:1px solid #eee">{display_name}</td><td style="padding:10px 12px;border-bottom:1px solid #eee;text-align:right"><a href="{mp3}" style="color:#2c7bb6;text-decoration:none">&#9654; {lb["listen"]}</a></td></tr>'

    cover_tag = ""
    if cover_file:
        cover_tag = f'<img src="{cover_file}" alt="Cover" style="width:200px;height:200px;object-fit:cover;border-radius:12px;box-shadow:0 4px 20px rgba(0,0,0,.15)">'

    safe_title = (title or "Audiobook").replace('"', '&quot;').replace('<', '&lt;')
    safe_author = (author or "").replace('"', '&quot;').replace('<', '&lt;')

    html = _render_page("podcast_index", {"__P0__": (lang), "__P1__": (safe_title), "__P2__": (lb["heading"]), "__P3__": (cover_tag), "__P4__": (f'<div class="author">{lb["by"]} {safe_author}</div>' if safe_author else ''), "__P5__": (lb["subscribe"]), "__P6__": (rss_fname), "__P7__": (lb["copy"]), "__P8__": (lb["instructions"]), "__P9__": (lb["episodes"]), "__P10__": (len(sorted_mp3)), "__P11__": (episodes_html), "__P12__": (lb["footer"]), "__P13__": (lb["copied"])})

    index_path = os.path.join(str(podcast_dir), "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(html)
    return index_path


def _build_podcast_zip(job_id, podcast_dir, mp3_files, epub_path, info, safe_name, base_url,
                       language, zip_base):
    """Pacchetto podcast costruito in `podcast_dir` (poi rimossa): MP3,
    copertina (EPUB a 1400px, poi estrazione grezza, poi generata), feed RSS
    e index.html; ritorna il path dello ZIP `<zip_base>.zip`. Usato dal
    download diretto (`/api/download_podcast`) e da quello via token email."""
    podcast_dir = Path(podcast_dir)
    podcast_dir.mkdir(parents=True, exist_ok=True)
    try:
        for mp3 in mp3_files:
            if os.path.exists(mp3):
                shutil.copy2(mp3, str(podcast_dir / os.path.basename(mp3)))
        cover_file = ""
        cover_path = str(podcast_dir / "cover.jpg")
        has_epub = bool(epub_path) and os.path.exists(epub_path)
        # Strategia 1: Pillow a 1400px quadrati (iTunes)
        if has_epub and _extract_cover_from_epub(epub_path, cover_path, target_size=1400):
            cover_file = "cover.jpg"
            print(f"[{job_id}] Podcast cover: Pillow 1400px ({os.path.getsize(cover_path)} bytes)")
        else:
            # Strategia 2: estrazione grezza (funziona anche senza Pillow)
            raw_path, raw_mime = ("", "")
            if has_epub:
                print(f"[{job_id}] Podcast cover: _extract_cover_from_epub failed, trying raw extraction")
                raw_path, raw_mime = _extract_cover_for_preview(epub_path, str(podcast_dir))
            if raw_path and os.path.exists(raw_path):
                ext = ".png" if raw_mime == "image/png" else ".jpg"
                final_cover = str(podcast_dir / ("cover" + ext))
                if raw_path != final_cover:
                    shutil.move(raw_path, final_cover)
                cover_file = "cover" + ext
                print(f"[{job_id}] Podcast cover: raw extraction OK ({os.path.getsize(final_cover)} bytes)")
            else:
                # Strategia 3: copertina generata
                print(f"[{job_id}] Podcast cover: raw extraction failed, generating fallback")
                _generate_fallback_cover(cover_path, title=info.title or "", author=info.author or "")
                if os.path.exists(cover_path) and os.path.getsize(cover_path) > 0:
                    cover_file = "cover.jpg"
                    print(f"[{job_id}] Podcast cover: fallback generated ({os.path.getsize(cover_path)} bytes)")
                else:
                    print(f"[{job_id}] Podcast cover: all strategies failed, no cover in podcast")
        rss_fname = f"{safe_name}_podcast.xml"
        rss_path = str(podcast_dir / rss_fname)
        _generate_podcast_rss(info, mp3_files, rss_path,
                              base_url=base_url, cover_filename=cover_file,
                              rss_filename=rss_fname)
        _generate_podcast_index_html(podcast_dir, info.title, info.author,
                                     cover_file, rss_fname, mp3_files, language=language)
        print(f"[{job_id}] Podcast ZIP contents: {[f.name for f in podcast_dir.iterdir()]}")
        return shutil.make_archive(str(zip_base), "zip", str(podcast_dir))
    finally:
        shutil.rmtree(str(podcast_dir), ignore_errors=True)


def _serve_podcast_download(token_info, job, job_id):
    """Serve podcast download from job in memory or token snapshot on disk."""

    # If output ZIP already has RSS embedded (zip_rss format), serve it directly
    output_zip = token_info.get("output_zip", "")
    if output_zip and os.path.exists(output_zip):
        # Check if RSS is embedded (job in memory) or trust the zip_rss output
        if (job and job.get("podcast_rss_included")) or not job:
            print(f"[dl] Podcast: serving existing ZIP with embedded RSS: {output_zip}")
            if job:
                job["last_poll"] = time.time()
                job["downloaded_at"] = time.time()
            orig = token_info.get("original_filename", job.get("original_filename", "") if job else "")
            if not _is_resume_or_probe_request():
                _log_activity(job_id, orig, "DOWNLOAD_EMAIL_PODCAST",
                              job.get("client_id", "") if job else "",
                              job.get("client_ip", "") if job else "",
                              job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
            _mark_token_downloaded(token_info)
            return _send_file_throttled(output_zip, as_attachment=True,
                             download_name=os.path.basename(output_zip))

    base_url = token_info.get("base_url", "")

    # Always source paths from the token snapshot (per-epoch isolation). The
    # live job state reflects the LATEST generation only and would cause
    # sibling email tokens to serve each other's files.
    mp3_files = token_info.get("podcast_mp3s", [])
    safe_name = token_info.get("podcast_safe_name", "audiolibro")
    epub_path = token_info.get("epub_path", "")
    p_info_title = token_info.get("podcast_info_title", "")
    p_info_author = token_info.get("podcast_info_author", "")
    p_info_lang = token_info.get("podcast_info_language", "")

    # Reconstruct epub_path if stored path doesn't exist (data dir may have changed)
    if epub_path and not os.path.exists(epub_path):
        reconstructed = str(_upload_dir() / job_id / os.path.basename(epub_path))
        if os.path.exists(reconstructed):
            print(f"[dl] epub_path reconstructed: {epub_path} -> {reconstructed}")
            epub_path = reconstructed

    # Verify MP3 files exist; fallback: reconstruct paths under any output_{epoch}/ dir
    mp3_files = [f for f in mp3_files if os.path.exists(f)]
    if not mp3_files:
        job_dir = _upload_dir() / job_id
        raw_mp3s = token_info.get("podcast_mp3s", [])
        for d in _iter_output_dirs(job_dir):
            candidates = []
            for old_path in raw_mp3s:
                cand = d / os.path.basename(old_path)
                if cand.exists():
                    candidates.append(str(cand))
            if candidates:
                mp3_files = candidates
                print(f"[dl] Podcast path reconstruction: {len(mp3_files)} MP3s found in {d}")
                break
    if not mp3_files:
        # Final fallback: scan all output dirs for any MP3s (newest first)
        job_dir = _upload_dir() / job_id
        for d in _iter_output_dirs(job_dir):
            found = sorted([str(f) for f in d.glob("*.mp3")])
            if found:
                mp3_files = found
                print(f"[dl] Podcast scan fallback: found {len(mp3_files)} MP3s in {d}")
                break
    if not mp3_files:
        return "File non più disponibili", 410

    # Create a minimal info object for RSS generation
    # Use real info object when job is in memory (has chapters for RSS titles),
    # otherwise create minimal stub for token-based downloads
    if job and job.get("podcast_info"):
        info = job["podcast_info"]
    else:
        class _MiniInfo:
            pass
        info = _MiniInfo()
        info.title = p_info_title
        info.author = p_info_author
        info.language = p_info_lang
        info.chapters = []  # No chapter objects available; RSS will use "Episode N" fallback

    # Place cached & temp podcast artifacts inside this epoch's output dir so
    # sibling email tokens don't share a single zip at work_dir root.
    epoch_dir = Path(mp3_files[0]).parent if mp3_files else _upload_dir() / job_id
    work_dir = epoch_dir

    # If a podcast zip was already built for this epoch, serve it directly
    cached_zip = epoch_dir / f"{safe_name}_podcast.zip"
    if cached_zip.exists() and cached_zip.stat().st_size > 0:
        print(f"[dl] Serving cached podcast zip: {cached_zip}")
        _mark_token_downloaded(token_info)
        return _send_file_throttled(str(cached_zip), as_attachment=True,
                         download_name=f"{safe_name}_podcast.zip")

    # Pacchetto in una cartella temporanea unica (niente race fra download paralleli)
    podcast_zip = _build_podcast_zip(
        job_id, epoch_dir / f"podcast_{uuid.uuid4().hex[:8]}", mp3_files, epub_path, info,
        safe_name, base_url, getattr(info, 'language', '') or token_info.get('language', 'en'),
        work_dir / f"{safe_name}_podcast")
    orig = token_info.get("original_filename", job.get("original_filename", "") if job else "")
    if not _is_resume_or_probe_request():
        _log_activity(job_id, orig, "DOWNLOAD_EMAIL_PODCAST",
                      job.get("client_id", "") if job else "",
                      job.get("client_ip", "") if job else "",
                      job.get("voice", "") if job else "", job.get("browser_lang", "") if job else "")
    _mark_token_downloaded(token_info)
    return _send_file_throttled(podcast_zip, as_attachment=True,
                     download_name=f"{safe_name}_podcast.zip")


def _render_dl_expired_page(lang="en", retention_hours=0):
    expired_t = _DL_PAGES_I18N.get("expired", {})
    t = expired_t.get(lang, expired_t.get("en", {}))
    # Se il chiamante non passa la retention reale del token (es. token gia`
    # rimosso e non recuperabile), usa il default standard come fallback.
    # Vale come "almeno X ore sono passate"; per token Gemini il caller passa 48.
    if not retention_hours:
        retention_hours = int(_email_file_retention_sec() / 3600)
    p1_text = t['p1'].replace("{h}", str(int(retention_hours)))
    return _render_page("dl_expired", {"__P0__": (lang), "__P1__": (FAVICON_B64), "__P2__": (t['title']), "__P3__": (t['h2']), "__P4__": (p1_text), "__P5__": (t['p2'])})


def _render_dl_deleted_page(lang="en"):
    deleted_t = _DL_PAGES_I18N.get("deleted", {})
    t = deleted_t.get(lang, deleted_t.get("en", {}))
    return _render_page("dl_deleted", {"__P0__": (lang), "__P1__": (FAVICON_B64), "__P2__": (t['title']), "__P3__": (t['h2']), "__P4__": (t['p1']), "__P5__": (t['p2'])})


def _render_dl_cooldown_page(lang="en", seconds=60, back_url=None):
    cooldown_t = _DL_PAGES_I18N.get("cooldown", {})
    t = cooldown_t.get(lang, cooldown_t.get("en", {}))
    p2 = t['p2'].format(s=seconds)
    auto_refresh_ms = max(seconds + 2, 5) * 1000
    # Al termine del countdown torniamo alla pagina con i bottoni di download (non al
    # file URL che ha generato il cooldown — altrimenti il timer riparte all'infinito).
    if back_url is None:
        try:
            path = request.path or ""
            m = re.match(r'^(/dl/[^/]+)(?:/.*)?$', path)
            if m:
                back_url = m.group(1)
            else:
                ref = request.referrer or ""
                same_origin = ref.startswith(request.host_url) if ref else False
                back_url = ref if same_origin else "/"
        except Exception:
            back_url = "/"
    import json as _json
    back_url_js = _json.dumps(back_url)
    return _render_page("dl_cooldown", {"__P0__": (lang), "__P1__": (FAVICON_B64), "__P2__": (t['title']), "__P3__": (t['h2']), "__P4__": (t['p1']), "__P5__": (p2), "__P6__": (seconds), "__P7__": (t['auto']), "__P8__": (back_url_js), "__P9__": (auto_refresh_ms)})


def _render_dl_page(token, book_title, remaining_str, dl_type, lang="en", m4b_available=False, has_abm=False, output_format="", retention_hours=0, m4b_kit_available=False, translated_available=False, transfer_qr="", transfer_url="", is_mobile=False, is_android=False, is_ios=False):
    download_t = _DL_PAGES_I18N.get("download", {})
    t = dict(download_t.get(lang, download_t.get("en", {})))

    # Whitelist della lingua prima di interpolarla in contesti JS/HTML della pagina
    # (difesa XSS): `lang` arriva dal token e dovrebbe essere un codice a 2 lettere,
    # ma non vogliamo dipendere da quella garanzia in un literal JavaScript.
    _SUPPORTED_DL_LANGS = ("en", "it", "fr", "es", "de", "zh", "hi")
    safe_lang = lang if lang in _SUPPORTED_DL_LANGS else "en"

    # Sec (XSS): book_title proviene dai metadati EPUB/PDF (controllati dall'autore del file).
    # Tutte le interpolazioni nel template devono passare per html.escape, altrimenti un
    # `<dc:title>` malevolo iniettato lato uploader produce XSS sulla pagina /dl/<token>.
    book_title = html_mod.escape(str(book_title or ""), quote=True)
    remaining_str = html_mod.escape(str(remaining_str or ""), quote=True)

    # Single audio button matching post-generation page style
    # SVG download icon for single-file formats, emoji for ZIP

    audio_btn_html = ""
    type_label = ""

    _format_labels = {
        "m4b": {
            "it": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>Scarica audiolibro (M4B)</span>', "Audiobook (M4B)"),
            "en": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>Download audiobook (M4B)</span>', "Audiobook (M4B)"),
            "fr": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>T&eacute;l&eacute;charger l&rsquo;audiobook (M4B)</span>', "Audiobook (M4B)"),
            "es": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>Descargar audiolibro (M4B)</span>', "Audiobook (M4B)"),
            "de": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>H&ouml;rbuch herunterladen (M4B)</span>', "Audiobook (M4B)"),
            "zh": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>下载有声读物 (M4B)</span>', "Audiobook (M4B)"),
            "hi": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>ऑडियोबुक डाउनलोड करें (M4B)</span>', "Audiobook (M4B)"),
        },
        "mp3": {
            "it": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>Scarica audiolibro (MP3)</span>', "Audiobook (MP3)"),
            "en": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>Download audiobook (MP3)</span>', "Audiobook (MP3)"),
            "fr": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>T&eacute;l&eacute;charger l&rsquo;audiobook (MP3)</span>', "Audiobook (MP3)"),
            "es": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>Descargar audiolibro (MP3)</span>', "Audiobook (MP3)"),
            "de": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>H&ouml;rbuch herunterladen (MP3)</span>', "Audiobook (MP3)"),
            "zh": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>下载有声读物 (MP3)</span>', "Audiobook (MP3)"),
            "hi": ('<svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg> <span>ऑडियोबुक डाउनलोड करें (MP3)</span>', "Audiobook (MP3)"),
        },
        "zip": {
            "it": ("&#x2B07;&#xFE0F; <span>Scarica audiolibro (ZIP)</span>", "Audiobook (ZIP)"),
            "en": ("&#x2B07;&#xFE0F; <span>Download audiobook (ZIP)</span>", "Audiobook (ZIP)"),
            "fr": ("&#x2B07;&#xFE0F; <span>T&eacute;l&eacute;charger l&rsquo;audiobook (ZIP)</span>", "Audiobook (ZIP)"),
            "es": ("&#x2B07;&#xFE0F; <span>Descargar audiolibro (ZIP)</span>", "Audiobook (ZIP)"),
            "de": ("&#x2B07;&#xFE0F; <span>H&ouml;rbuch herunterladen (ZIP)</span>", "Audiobook (ZIP)"),
            "zh": ("&#x2B07;&#xFE0F; <span>下载有声读物 (ZIP)</span>", "Audiobook (ZIP)"),
            "hi": ("&#x2B07;&#xFE0F; <span>ऑडियोबुक डाउनलोड करें (ZIP)</span>", "Audiobook (ZIP)"),
        },
        # Kit di ripiego (M4B fallito): MP3 + capitoli + script per ricostruire l'M4B.
        "m4b_kit": {
            "it": ("&#x2B07;&#xFE0F; <span>Scarica audiolibro + capitoli (ZIP)</span>", "Audiobook (MP3 + capitoli)"),
            "en": ("&#x2B07;&#xFE0F; <span>Download audiobook + chapters (ZIP)</span>", "Audiobook (MP3 + chapters)"),
            "fr": ("&#x2B07;&#xFE0F; <span>T&eacute;l&eacute;charger l&rsquo;audiobook + chapitres (ZIP)</span>", "Audiobook (MP3 + chapitres)"),
            "es": ("&#x2B07;&#xFE0F; <span>Descargar audiolibro + cap&iacute;tulos (ZIP)</span>", "Audiobook (MP3 + cap&iacute;tulos)"),
            "de": ("&#x2B07;&#xFE0F; <span>H&ouml;rbuch + Kapitel herunterladen (ZIP)</span>", "Audiobook (MP3 + Kapitel)"),
            "zh": ("&#x2B07;&#xFE0F; <span>下载有声读物 + 章节 (ZIP)</span>", "Audiobook (MP3 + 章节)"),
            "hi": ("&#x2B07;&#xFE0F; <span>ऑडियोबुक + अध्याय डाउनलोड करें (ZIP)</span>", "Audiobook (MP3 + अध्याय)"),
        },
    }

    if dl_type == "translated":
        # Pagina a pulsante singolo: scarica il libro tradotto.
        # Testi dal blocco "translated" (aggiunto in Task 10), con fallback
        # sul blocco "download" e infine su stringhe IT/EN hardcoded, cosi'
        # la pagina funziona anche prima che le traduzioni esistano.
        tr_t = _DL_PAGES_I18N.get("translated", {})
        tr_block = tr_t.get(lang, tr_t.get("en", {}))
        _tr_btn_fallback = {
            "it": "&#x1F4D6; Scarica traduzione",
            "en": "&#x1F4D6; Download translation",
            "fr": "&#x1F4D6; T&eacute;l&eacute;charger la traduction",
            "es": "&#x1F4D6; Descargar traducci&oacute;n",
            "de": "&#x1F4D6; &Uuml;bersetzung herunterladen",
            "zh": "&#x1F4D6; 下载译文",
            "hi": "&#x1F4D6; अनुवाद डाउनलोड करें",
        }
        btn_label = tr_block.get("btn") or _i18n.pick(_tr_btn_fallback, lang, merge=False)
        _tr_type_fallback = {
            "it": "Traduzione", "en": "Translation", "fr": "Traduction",
            "es": "Traducción", "de": "Übersetzung", "zh": "译文",
            "hi": "अनुवाद",
        }
        type_label = tr_block.get("type_label") or _i18n.pick(_tr_type_fallback, lang, merge=False)
        if translated_available:
            audio_btn_html = f'<p><a href="/dl/{token}/translated" class="btn">{btn_label}</a></p>'
        else:
            # Nessun bottone = vicolo cieco: la pagina diceva "traduzione pronta"
            # e non offriva nulla, lasciando l'utente a credere di aver sbagliato
            # click (incidente 04/09/2026). Meglio dichiarare l'indisponibilita'.
            _tr_unavail = {
                "it": "Il file di questa traduzione non &egrave; pi&ugrave; disponibile. Contattaci rispondendo all&rsquo;email di consegna: rifacciamo la traduzione senza costi aggiuntivi.",
                "en": "The file for this translation is no longer available. Reply to the delivery email and we will redo the translation at no extra cost.",
                "fr": "Le fichier de cette traduction n&rsquo;est plus disponible. R&eacute;pondez &agrave; l&rsquo;email de livraison : nous refaisons la traduction sans frais suppl&eacute;mentaires.",
                "es": "El archivo de esta traducci&oacute;n ya no est&aacute; disponible. Responde al email de entrega: rehacemos la traducci&oacute;n sin coste adicional.",
                "de": "Die Datei dieser &Uuml;bersetzung ist nicht mehr verf&uuml;gbar. Antworte auf die Zustell-E-Mail: Wir erstellen die &Uuml;bersetzung ohne Zusatzkosten neu.",
                "zh": "该译文文件已不可用。请回复交付邮件，我们将免费重新翻译。",
                "hi": "&#2311;&#2360; &#2309;&#2344;&#2369;&#2357;&#2366;&#2342; &#2325;&#2368; &#2347;&#2364;&#2366;&#2311;&#2354; &#2309;&#2348; &#2313;&#2346;&#2354;&#2348;&#2381;&#2343; &#2344;&#2361;&#2368;&#2306; &#2361;&#2376;&#2404; &#2337;&#2367;&#2354;&#2367;&#2357;&#2352;&#2368; &#2311;&#2350;&#2375;&#2354; &#2325;&#2366; &#2313;&#2340;&#2381;&#2340;&#2352; &#2342;&#2375;&#2306;: &#2361;&#2350; &#2348;&#2367;&#2344;&#2366; &#2309;&#2340;&#2367;&#2352;&#2367;&#2325;&#2381;&#2340; &#2358;&#2369;&#2354;&#2381;&#2325; &#2325;&#2375; &#2309;&#2344;&#2369;&#2357;&#2366;&#2342; &#2342;&#2379;&#2348;&#2366;&#2352;&#2366; &#2325;&#2352;&#2375;&#2306;&#2327;&#2375;&#2404;",
            }
            _msg = _i18n.pick(_tr_unavail, lang, merge=False)
            audio_btn_html = (
                '<p style="color:#b00020;font-weight:600;line-height:1.5">'
                f'&#9888;&#65039; {_msg}</p>')
            print(f"[dl] translated file NOT available for token {token}", flush=True)
    elif dl_type == "optimized_abm":
        type_label = "Optimized Project (.abm)"
    elif dl_type == "podcast":
        # Podcast: ZIP with chapter MP3s + RSS
        audio_btn_html = '<a href="/dl/{}/download" class="btn">{}</a>'.format(
            token, t.get("btn_no_m4b", "&#x2B07;&#xFE0F; Download podcast"))
        type_label = "Podcast"
    elif dl_type in ("audio", "chapters"):
        # Determine format: prefer output_format from job, fallback to m4b detection.
        # "chapters" è inviato dal frontend per gli output multi-file (ZIP per capitoli):
        # forza fmt="zip" per saltare la rilevazione M4B quando il formato esplicito
        # mancasse dal token (es. token persistiti prima del fix di _tkstore.save_tokens).
        fmt = output_format if output_format in ("m4b", "mp3", "zip", "zip_rss") else None
        if not fmt and dl_type == "chapters":
            fmt = "zip"
        elif not fmt and m4b_available:
            fmt = "m4b"
        elif not fmt:
            fmt = "zip"

        # Coerenza con la realtà del filesystem: se l'utente aveva chiesto M4B ma
        # il file non esiste (es. conversione PCM->AAC fallita su Gemini, oppure
        # output_format snapshottato come 'm4b' senza che il muxing sia avvenuto),
        # degradiamo l'etichetta/route a MP3 anziché esporre un link M4B che il
        # backend dovrà servire via fallback silenzioso.
        if fmt == "m4b" and not m4b_available:
            # Se l'M4B non c'è ma esiste il kit di ripiego, offri il kit (ZIP);
            # altrimenti degrada al solo MP3.
            fmt = "m4b_kit" if m4b_kit_available else "mp3"

        if fmt == "m4b":
            label_data = _format_labels["m4b"]
            btn_url = f"/dl/{token}/m4b"
        elif fmt == "m4b_kit":
            # Il kit viene servito dallo stesso endpoint /m4b (che ripiega sul kit
            # quando l'M4B non esiste).
            label_data = _format_labels["m4b_kit"]
            btn_url = f"/dl/{token}/m4b"
        elif fmt == "mp3":
            label_data = _format_labels["mp3"]
            btn_url = f"/dl/{token}/download"
        else:
            label_data = _format_labels["zip"]
            btn_url = f"/dl/{token}/download"

        btn_label, type_label = label_data.get(lang, label_data.get("en", label_data.get("it")))
        audio_btn_html = f'<p><a href="{btn_url}" class="btn">{btn_label}</a></p>'

    # ABM button (only if AI optimization was active)
    abm_btn_html = ""
    if has_abm:
        _abm_labels = {
            "it": "&#x1F4DD;&#xFE0F; Scarica testo ottimizzato (.abm)",
            "en": "&#x1F4DD;&#xFE0F; Download optimized text (.abm)",
            "fr": "&#x1F4DD;&#xFE0F; T&eacute;l&eacute;charger le texte optimis&eacute; (.abm)",
            "es": "&#x1F4DD;&#xFE0F; Descargar texto optimizado (.abm)",
            "de": "&#x1F4DD;&#xFE0F; Optimierten Text herunterladen (.abm)",
            "zh": "&#x1F4DD;&#xFE0F; 下载优化文本 (.abm)",
            "hi": "&#x1F4DD;&#xFE0F; ऑप्टिमाइज़्ड टेक्स्ट डाउनलोड करें (.abm)",
        }
        abm_label = _i18n.pick(_abm_labels, lang, merge=False)
        abm_btn_html = f'<p><a href="/dl/{token}/abm" class="btn btn-abm">{abm_label}</a></p>'

    # Retention totale: deve riflettere _ret reale del token (es. Gemini=48h,
    # standard=18h), non un valore hardcoded. Senza questo, la riga "Dopo X ore"
    # mostrava sempre "24" anche quando il countdown sopra reportava ~48h.
    warn_text = t["warn"].replace("{r}", remaining_str).replace("{h}", str(int(retention_hours)))

    share_url = _base_url() or "https://audiobook-maker.com"
    share_text_js = t.get("share_text", "").replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

    # QR di trasferimento job sull'app mobile (best-effort: vuoto se assente).
    transfer_html = ""
    if transfer_qr or (is_mobile and transfer_url):
        _transfer_t = _DL_PAGES_I18N.get("transfer", {})
        _transfer_fallback = {
            "en": ("Transfer to the app", "Scan the QR with the AudioBook Maker &amp; Player app"),
            "it": ("Trasferisci sull&rsquo;app", "Inquadra il QR con l&rsquo;app AudioBook Maker &amp; Player"),
            "fr": ("Transf&eacute;rer vers l&rsquo;application", "Scannez le QR avec l&rsquo;application AudioBook Maker &amp; Player"),
            "es": ("Transferir a la app", "Escanea el QR con la app AudioBook Maker &amp; Player"),
            "de": ("An die App &uuml;bertragen", "Scanne den QR mit der App AudioBook Maker &amp; Player"),
            "zh": ("传输到应用", "用 AudioBook Maker &amp; Player 应用扫描二维码"),
            "hi": ("ऐप में स्थानांतरित करें", "AudioBook Maker &amp; Player ऐप से QR स्कैन करें"),
        }
        # Label del bottone mobile ("Scarica su AudioBook Maker & Player").
        _transfer_cta = {
            "en": "Download to AudioBook Maker &amp; Player",
            "it": "Scarica su AudioBook Maker &amp; Player",
            "fr": "T&eacute;l&eacute;charger dans AudioBook Maker &amp; Player",
            "es": "Descargar en AudioBook Maker &amp; Player",
            "de": "In AudioBook Maker &amp; Player herunterladen",
            "zh": "下载到 AudioBook Maker &amp; Player",
            "hi": "AudioBook Maker &amp; Player में डाउनलोड करें",
        }
        # Label del link secondario iOS "Apri nell'app" (custom scheme abm://).
        _transfer_open_in_app = {
            "en": "Open in app",
            "it": "Apri nell&rsquo;app",
            "fr": "Ouvrir dans l&rsquo;application",
            "es": "Abrir en la app",
            "de": "In der App &ouml;ffnen",
            "zh": "在应用中打开",
            "hi": "ऐप में खोलें",
        }
        _tr_block = _transfer_t.get(lang, _transfer_t.get("en", {}))
        _title = _tr_block.get("title") or _i18n.pick(_transfer_fallback, lang, merge=False)[0]
        _hint = _tr_block.get("hint") or _i18n.pick(_transfer_fallback, lang, merge=False)[1]
        _app_name = "AudioBook Maker &amp; Player"
        if is_mobile and transfer_url:
            # Mobile/tablet: bottone che apre il deep link /t/<token> (App Link);
            # niente QR (inutile sul dispositivo stesso), niente hint "scan the QR".
            # Target e label del bottone unico per piattaforma:
            # - iOS: custom scheme abm:// (unico gancio affidabile same-origin in
            #   Safari; se l'app manca Safari erra, scelta accettata) -> "Apri nell'app"
            # - Android: intent:// (apre l'app o va al sito) -> "Scarica su ..."
            # - altro: https diretto -> "Scarica su ..."
            if is_ios:
                _open_url = _app_scheme_url(transfer_url)
                _btn_label = _i18n.pick(_transfer_open_in_app, lang, merge=False)
            elif is_android:
                _open_url = _android_intent_url(transfer_url)
                _btn_label = _i18n.pick(_transfer_cta, lang, merge=False)
            else:
                _open_url = transfer_url
                _btn_label = _i18n.pick(_transfer_cta, lang, merge=False)
            # href escapato per difesa in profondità: l'URL deriva da ABM_BASE_URL
            # (config fidata) + token server-side, ma non lo riflettiamo mai grezzo.
            _safe_url = html_mod.escape(_open_url, quote=True)
            transfer_html = (
                '<div style="text-align:center;margin:28px auto;max-width:320px;">'
                f'<h3 style="font-size:1rem;margin:0 0 12px;">{_title}</h3>'
                f'<a href="{_safe_url}" '
                'style="display:inline-block;padding:12px 20px;background:#2563eb;'
                'color:#fff;text-decoration:none;border-radius:8px;font-weight:600;">'
                f'{_btn_label}</a>'
                '</div>'
            )
        else:
            _app_link = (f'<a href="{_base_url()}/get-app" '
                         f'style="color:inherit;text-decoration:underline;">{_app_name}</a>')
            _hint_html = _hint.replace(_app_name, _app_link)
            transfer_html = (
                '<div style="text-align:center;margin:28px auto;max-width:320px;">'
                f'<h3 style="font-size:1rem;margin:0 0 8px;">{_title}</h3>'
                f'<img src="{transfer_qr}" alt="QR" style="width:200px;height:200px;"/>'
                f'<p style="font-size:.8rem;color:#777;margin-top:8px;">{_hint_html}</p>'
                '</div>'
            )

    return _render_page("dl_page", {"__P0__": (lang), "__P1__": (FAVICON_B64), "__P2__": (t['title']), "__P3__": (t['h2']), "__P4__": (book_title), "__P5__": (type_label), "__P6__": (audio_btn_html), "__P7__": (abm_btn_html), "__P8__": (transfer_html), "__P9__": (warn_text), "__P10__": (t['share']), "__P11__": (t['copied']), "__P12__": (safe_lang), "__P13__": (share_url), "__P14__": (share_text_js)})


@bp.route("/api/download/<job_id>")
def api_download(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return ("Job not found" if sc == 404 else "Forbidden"), sc
    if job.get("status") != "done":
        return "Not ready", 400

    # Necessario per i fallback fisici (ricerca file su disco). In assenza di
    # questa definizione il ramo M4B->MP3 sollevava NameError -> HTTP 500.
    job_dir = _upload_dir() / job_id

    download_type = request.args.get("type", "").lower()
    
    # Refresh heartbeat  -  evita che il cleanup rimuova il job durante il download
    job["last_poll"] = time.time()
    
    log_type = "DOWNLOAD"
    if download_type == "m4b":
        log_type = "DOWNLOAD_M4B"
    elif download_type == "m4bkit":
        log_type = "DOWNLOAD_M4B_KIT"
    elif download_type == "zip":
        log_type = "DOWNLOAD_ZIP"
    elif download_type == "abm":
        log_type = "DOWNLOAD_ABM"

    def _do_log(cold=False):
        if _is_resume_or_probe_request():
            return
        _log_activity(job_id, job.get("original_filename", ""),
                      _cold_op(log_type) if cold else log_type,
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))
        # `downloaded_at` disattiva la protezione no-download PREMIUM: va settato
        # solo su consegna reale. Sul redirect al cold i byte non passano da noi
        # e un presigned rifiutato non deve dimezzare la finestra (incidente
        # 2026-08-25, filtro IP client sul token R2).
        if not cold:
            job["downloaded_at"] = time.time()

    if download_type == "abm":
        # Always regenerate from cumulative in-memory state to avoid stale chapters
        if job.get("ai_optimized"):
            try:
                opt_ch = job.get("optimized_chapters", [])
                print(f"[{job_id}] ABM download: regenerating (optimized_chapters={opt_ch})")
                abm_path, abm_name = generation_engine._generate_optimized_abm(job_id)
                job["optimized_abm_path"] = abm_path
                job["optimized_abm_name"] = abm_name
                _do_log()
                return _send_file_throttled(abm_path, as_attachment=True, download_name=abm_name, no_cache=True, bypass_throttle=True, conditional=True)
            except Exception as e:
                print(f"[{job_id}] On-demand ABM generation failed: {e}")
        # Fallback: serve existing file if any (pre-regeneration or non-AI-optimized)
        abm_path = job.get("optimized_abm_path")
        if abm_path and os.path.exists(abm_path):
            _do_log()
            safe_name = _safe_filename(job["info"].title) or "progetto"
            return _send_file_throttled(abm_path, as_attachment=True, download_name=f"{safe_name}.abm", no_cache=True, bypass_throttle=True, conditional=True)
        return "Optimized ABM project file not found", 404

    if download_type == "m4bkit":
        # Kit di ripiego (M4B fallito): ZIP con MP3 + chapters.json + ffmetadata +
        # cover + script ffmpeg. Se per qualunque motivo il kit non esiste, ripiega
        # sull'MP3 sciolto (coerente con il vecchio comportamento).
        kit_path = job.get("output_m4b_fallback_zip", "")
        if not kit_path or not os.path.exists(kit_path):
            cur_out = job.get("output_dir")
            if cur_out and os.path.isdir(cur_out):
                _kits = list(Path(cur_out).glob("*_audiolibro_capitoli.zip"))
                if _kits:
                    kit_path = str(_kits[0])
                    job["output_m4b_fallback_zip"] = kit_path
        safe_name = _safe_filename(job["info"].title) or "audiolibro"
        if kit_path and os.path.exists(kit_path):
            _do_log()
            return _send_file_throttled(kit_path, as_attachment=True,
                                        download_name=f"{safe_name}_audiolibro+capitoli.zip",
                                        no_cache=True, bypass_throttle=True, conditional=True)
        # Fallback MP3 se il kit manca
        _out_files = job.get("output_files") or []
        mp3_path = _out_files[0] if _out_files else ""
        if not mp3_path or not os.path.exists(mp3_path):
            mp3s = list(job_dir.glob("**/*.mp3"))
            if mp3s:
                mp3_path = str(mp3s[0])
        if mp3_path and os.path.exists(mp3_path):
            resp = _send_file_throttled(mp3_path, as_attachment=True,
                                        download_name=f"{safe_name}.mp3",
                                        no_cache=True, bypass_throttle=True, conditional=True)
            _with_mp3_fallback_header(resp)
            return resp
        return "File not found", 404

    if download_type == "m4b":
        m4b_path = job.get("output_m4b")
        print(f"[debug] Download M4B requested. Path in job: {m4b_path}")

        if m4b_path and os.path.exists(m4b_path):
            _do_log()
            safe_name = _safe_filename(job["info"].title) or "audiolibro"
            print(f"[debug] M4B file found! Serving: {m4b_path}")
            return _send_file_throttled(m4b_path, as_attachment=True, download_name=f"{safe_name}.m4b", no_cache=True, bypass_throttle=True, conditional=True)
        else:
            # Physical search fallback: SOLO dentro output_dir della run corrente,
            # mai uno scan globale su tutti gli output_*/ (servirebbe un m4b di
            # una run precedente).
            print(f"[debug] M4B not found at registered path. Searching in current output_dir...")
            cur_out = job.get("output_dir")
            m4b_files = []
            if cur_out and os.path.isdir(cur_out):
                m4b_files = list(Path(cur_out).glob("*.m4b"))
            if m4b_files:
                actual_m4b = str(m4b_files[0])
                job["output_m4b"] = actual_m4b
                print(f"[debug] M4B found via physical search: {actual_m4b}")
                _do_log()
                safe_name = _safe_filename(job["info"].title) or "audiolibro"
                return _send_file_throttled(actual_m4b, as_attachment=True, download_name=f"{safe_name}.m4b", no_cache=True, bypass_throttle=True, conditional=True)

            # Cold tier: locale evacuato da hot-evict ma copia cold del M4B
            # snapshotato valida (moov presente) → redirect 302 al presigned URL
            # PRIMA del fallback MP3/404 (allinea /api/download a /dl, cold-aware).
            _m4b_snap = job.get("output_m4b", "")
            if _cold_m4b_valid(_m4b_snap):
                safe_name = _safe_filename(job["info"].title) or "audiolibro"
                _cold = _try_cold_serve(_m4b_snap, download_name=f"{safe_name}.m4b")
                if _cold is not None:
                    print(f"[debug] M4B served from cold storage: {_m4b_snap}")
                    _do_log(cold=True)
                    return _cold

            print(f"[debug] M4B totally missing. Falling back to MP3.")
            # Fallback to single MP3 if M4B is missing
            # output_files puo' essere [] (assembly fallito): evita IndexError.
            _out_files = job.get("output_files") or []
            mp3_path = _out_files[0] if _out_files else ""
            if not mp3_path or not os.path.exists(mp3_path):
                mp3s = list(job_dir.glob("**/*.mp3"))
                if mp3s:
                    mp3_path = str(mp3s[0])
            if mp3_path and os.path.exists(mp3_path):
                resp = _send_file_throttled(mp3_path, as_attachment=True,
                                            download_name=f"{_safe_filename(job['info'].title)}.mp3",
                                            no_cache=True, bypass_throttle=True, conditional=True)
                _with_mp3_fallback_header(resp)
                return resp
            return "File not found", 404

    if download_type == "zip":
        if "output_zip" in job and os.path.exists(job["output_zip"]):
            _do_log()
            zip_name = job.get("output_name", "audiobook.zip")
            if not zip_name.endswith(".zip"):
                 zip_name = _safe_filename(job["info"].title) + ".zip"
            return _send_file_throttled(job["output_zip"], as_attachment=True, download_name=zip_name, no_cache=True, bypass_throttle=True, conditional=True)
        return "ZIP file not found", 404

    # Default logic (compatibility or auto-detect)
    # Prefer M4B if it seems to be the intended primary output
    if job.get("output_name", "").endswith(".m4b") and job.get("output_m4b") and os.path.exists(job["output_m4b"]):
        _do_log()
        return _send_file_throttled(job["output_m4b"], as_attachment=True, download_name=job["output_name"], no_cache=True, bypass_throttle=True, conditional=True)

    if "output_zip" in job and os.path.exists(job["output_zip"]):
        _do_log()
        return _send_file_throttled(job["output_zip"], as_attachment=True, download_name=job["output_name"], no_cache=True, bypass_throttle=True, conditional=True)

    if job.get("output_files") and os.path.exists(job["output_files"][0]):
        _do_log()
        return _send_file_throttled(job["output_files"][0], as_attachment=True, download_name=job["output_name"], no_cache=True, bypass_throttle=True, conditional=True)

    return "File not found", 404

@bp.route("/api/download_podcast/<job_id>")
def api_download_podcast(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return ("Job not found" if sc == 404 else "Forbidden"), sc
    if job.get("status") != "done":
        return "Not ready", 400
    if not job.get("podcast_ready"):
        return "Podcast not available for this job", 400

    # If RSS already embedded in output ZIP (zip_rss format), serve it directly
    if job.get("podcast_rss_included") and job.get("output_zip") and os.path.exists(job["output_zip"]):
        print(f"[{job_id}] Podcast download: serving existing ZIP with embedded RSS")
        job["last_poll"] = time.time()
        job["downloaded_at"] = time.time()
        if not _is_resume_or_probe_request():
            _log_activity(job_id, job.get("original_filename", ""), "DOWNLOAD_PODCAST",
                          job.get("client_id", ""), job.get("client_ip", ""),
                          job.get("voice", ""), job.get("browser_lang", ""))
        return _send_file_throttled(job["output_zip"], as_attachment=True,
                         download_name=job.get("output_name", "podcast.zip"), no_cache=True, bypass_throttle=True)

    # Sec (SSRF / content injection): il base_url degli <enclosure> del feed RSS è critico.
    # Se accettato dal client, un attaccante può fare pubblicare/usare il feed con enclosure
    # puntate a un host arbitrario (phishing podcast, malware audio). Forziamo il valore
    # server-side da ABM_BASE_URL e ignoriamo qualunque parametro utente.
    base_url = (_base_url() or "").rstrip("/")
    if not base_url:
        return "Server misconfigured: ABM_BASE_URL not set", 503

    job["last_poll"] = time.time()
    job["downloaded_at"] = time.time()

    info = job["podcast_info"]
    mp3_files = job["podcast_mp3s"]
    safe_name = job["podcast_safe_name"]
    work_dir = Path(job["epub_path"]).parent

    # ZIP costruito al volo col base URL del server
    podcast_zip = _build_podcast_zip(
        job_id, work_dir / "podcast", mp3_files, job["epub_path"], info, safe_name, base_url,
        getattr(info, 'language', 'en'), work_dir / f"{safe_name}_podcast")

    # work_dir è la root del job (fuori da output*/): lo zip podcast NON viene
    # gestito dal tiering, quindi rimuovilo dopo l'invio per non lasciarlo orfano.
    @after_this_request
    def _cleanup_podcast_zip(resp, _p=podcast_zip):
        try: os.remove(_p)
        except OSError: pass
        return resp

    if not _is_resume_or_probe_request():
        _log_activity(job_id, job.get("original_filename", ""), "DOWNLOAD_PODCAST",
                      job.get("client_id", ""), job.get("client_ip", ""),
                      job.get("voice", ""), job.get("browser_lang", ""))
    return _send_file_throttled(podcast_zip, as_attachment=True,
                     download_name=f"{safe_name}_podcast.zip", no_cache=True, bypass_throttle=True)
