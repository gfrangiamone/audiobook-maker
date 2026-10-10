"""routes_mobile — API dell'app mobile: i miei job, trasferimento e
condivisione (E3, seam mobile, 2026-10-10).

Blueprint `mobile`: `/api/my_jobs`, `/api/transfer/claim/<token>`,
`/api/share/create`, `/api/share/finalize`, `/api/share/claim/<token>`,
`/s/<token>/dl`, `/api/transfer_qr/<job_id>`, `/api/metrics/app_open`;
con la ricostruzione del record di download admin e del file pronto, la
verifica di una share e del suo file. Spostato pari pari da
`audiobook_app`; i token vivono in `token_store`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata
(i test le sostituiscono sulla app), gli helper in FUNCS e i valori
`jobs`, `UPLOAD_DIR`, i TTL/cap delle share, la mappa email dei client;
per riferimento il lock dei job e il modulo `generation_engine`. Non
importa `audiobook_app`.
"""
import os
import secrets
import time
import uuid
from pathlib import Path

from flask import Blueprint, jsonify, redirect, request

import metrics_store
import storage_backend
import storage_tiering
import token_store as _tkstore
from env_utils import env_str

bp = Blueprint("mobile", __name__)

_cfg = {}
_jobs_lock = None
generation_engine = None

FUNCS = ['_get_client_id', '_log_activity', 'client_ip', '_client_platform', '_share_link_for', '_safe_share_filename', '_effective_retention_for_token_info', '_qr_data_uri', '_transfer_payload_for', '_check_job_owner', '_find_files_in_outputs', '_job_original_filename', '_send_file_throttled']
VALUES = ('jobs', 'upload_dir', 'share_ttl_sec', 'share_max_bytes', 'share_upload_ttl_sec', 'client_emails_map')


def configure(*, _jobs_lock, generation_engine, **fns):
    """`fns`: una funzione per ogni nome in FUNCS e VALUES (la app passa
    lambda che risolvono i suoi globali a ogni chiamata)."""
    missing = [n for n in FUNCS + list(VALUES) if n not in fns]
    assert not missing, f"routes_mobile.configure: mancano {missing}"
    _cfg.update(fns)
    globals()["_jobs_lock"] = _jobs_lock
    globals()["generation_engine"] = generation_engine


# Valori della app usati dal codice spostato: risolti a ogni chiamata.
def _jobs():
    return _cfg["jobs"]()

def _upload_dir():
    return _cfg["upload_dir"]()

def _share_ttl_sec():
    return _cfg["share_ttl_sec"]()

def _share_max_bytes():
    return _cfg["share_max_bytes"]()

def _share_upload_ttl_sec():
    return _cfg["share_upload_ttl_sec"]()

def _client_emails_map():
    return _cfg["client_emails_map"]()


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _get_client_id(*a, **k):
    return _cfg["_get_client_id"](*a, **k)

def _log_activity(*a, **k):
    return _cfg["_log_activity"](*a, **k)

def client_ip(*a, **k):
    return _cfg["client_ip"](*a, **k)

def _client_platform(*a, **k):
    return _cfg["_client_platform"](*a, **k)

def _share_link_for(*a, **k):
    return _cfg["_share_link_for"](*a, **k)

def _safe_share_filename(*a, **k):
    return _cfg["_safe_share_filename"](*a, **k)

def _effective_retention_for_token_info(*a, **k):
    return _cfg["_effective_retention_for_token_info"](*a, **k)

def _qr_data_uri(*a, **k):
    return _cfg["_qr_data_uri"](*a, **k)

def _transfer_payload_for(*a, **k):
    return _cfg["_transfer_payload_for"](*a, **k)

def _check_job_owner(*a, **k):
    return _cfg["_check_job_owner"](*a, **k)

def _find_files_in_outputs(*a, **k):
    return _cfg["_find_files_in_outputs"](*a, **k)

def _job_original_filename(*a, **k):
    return _cfg["_job_original_filename"](*a, **k)

def _send_file_throttled(*a, **k):
    return _cfg["_send_file_throttled"](*a, **k)


_MY_JOBS_LIVE_STATUSES = (
    "analyzed", "optimizing", "optimized", "translating", "generating",
    "done", "partial", "error", "cancelled", "interrupted",
)


@bp.route("/api/my_jobs")
def api_my_jobs():
    """Job del client chiamante: attivi (in-memory) + completati (token su disco).

    Usato dall'app mobile per ricostruire la tab Attivita' a ogni avvio.
    """
    cid = _get_client_id()
    if not cid:
        return jsonify({"jobs": []})
    now = time.time()
    out = {}

    with _jobs_lock:
        snapshot = list(_jobs().items())
    for jid, job in snapshot:
        # Copia amministrativa PENDING: il cid (app admin) e' agganciato via QR
        # a un job di un altro utente ancora in corso (api_transfer_claim ramo
        # admin_copy). Senza questo ramo l'app confermava "job aggiunto" ma la
        # tab Attivita' restava vuota fino al COMPLETE: il job pending deve
        # comparire subito; il download token admin-owned arriva al COMPLETE
        # (_materialize_admin_copies).
        _is_admin_pending = cid in (job.get("admin_copy_cids") or [])
        if job.get("client_id") != cid and not _is_admin_pending:
            continue
        status = job.get("status", "")
        if job.get("server_interrupted"):
            status = "interrupted"
        if status == "partial":
            # Terminale e gia' consegnato (alcuni chunk saltati oltre soglia):
            # per chi legge questa lista e' un job pronto al download, non uno
            # stato a se'. Stessa normalizzazione del ramo su download token.
            status = "done"
        if status not in _MY_JOBS_LIVE_STATUSES:
            continue
        info = job.get("info")
        entry = {
            "job_id": jid,
            "status": status,
            "title": (getattr(info, "title", "") or
                      job.get("original_filename", "")),
            "output_format": job.get("output_format", ""),
            "created_at": job.get("start_time") or job.get("last_poll") or 0,
            # Il job e' ancora in memoria: e' l'unica condizione che permette
            # allo stream SSE di seguirlo. Le voci ricostruite piu' sotto dai
            # soli download token non hanno questo flag, e la SPA non prova a
            # riagganciarle dopo un refresh (vedi _restoreActiveJob in app.js).
            "live": True,
            # Stato che il reload della pagina azzera e solo il server conosce:
            # senza, il pannello finale ricostruito dopo un F5 offrirebbe i
            # bottoni del formato di default invece di quelli del job.
            "single_file": bool(job.get("single_file",
                                        job.get("opt_single_file", True))),
            "total_chapters": int(job.get("total_chapters")
                                  or len(getattr(info, "chapters", None) or [])),
            "email_registered": bool(job.get("notify_email")),
        }
        if _is_admin_pending:
            entry["admin_copy"] = True
        if status == "generating":
            entry.update({
                "progress_current": job.get("progress_current", 0),
                "progress_total": job.get("progress_total", 0),
                "progress_message": job.get("progress_message", ""),
            })
        elif status == "optimizing":
            entry.update({
                "opt_processed_chars": job.get("opt_processed_chars", 0),
                "opt_total_chars": job.get("opt_total_chars", 0),
            })
        elif status == "translating":
            entry.update({
                "tr_progress_current": job.get("tr_progress_current", 0),
                "tr_progress_total": job.get("tr_progress_total", 0),
            })
        out[jid] = entry

    for token, tinfo in list(_tkstore.download_tokens.items()):
        if not isinstance(tinfo, dict) or tinfo.get("client_id") != cid:
            continue
        created = tinfo.get("created_at", 0)
        retention = _effective_retention_for_token_info(tinfo)
        if (now - created) > retention:
            continue
        jid = tinfo.get("job_id", "")
        entry = out.setdefault(jid, {"job_id": jid, "created_at": created})
        entry.update({
            "status": "done",
            "title": tinfo.get("book_title") or entry.get("title", ""),
            "output_format": tinfo.get("output_format",
                                       entry.get("output_format", "")),
            "download_token": token,
            "expires_at": created + retention,
            "downloaded_at": tinfo.get("downloaded_at") or None,
            "formats": {
                "m4b": bool(tinfo.get("output_m4b")),
                "zip": bool(tinfo.get("output_zip")),
                "mp3": bool(tinfo.get("output_file")),
                "abm": bool(tinfo.get("optimized_abm_path")),
            },
        })

    ordered = sorted(out.values(),
                     key=lambda e: -(e.get("created_at") or 0))
    return jsonify({"jobs": ordered})


@bp.route("/api/transfer/claim/<token>", methods=["POST"])
def api_transfer_claim(token):
    """L'app reclama un job via transfer token: lo riassocia al cid chiamante."""
    info = _tkstore.transfer_tokens.get(token)
    if not isinstance(info, dict):
        return jsonify({"error": "invalid_token"}), 404
    cid = _get_client_id()
    if not cid:
        return jsonify({"error": "no_cid", "error_code": "no_cid"}), 400
    job_id = info.get("job_id", "")

    # ── Copia AMMINISTRATIVA (indagine) ────────────────────────────────────
    # Token con flag admin_copy: l'admin vuole una COPIA del job sull'app senza
    # alterare il flusso dell'utente originale. NON riassegnamo job["client_id"],
    # NON impostiamo transferred_to_mobile/email_registered, NON riassegnamo i
    # download token esistenti. Cloniamo lo snapshot di un download token del job
    # sotto un nuovo token di proprietà del cid chiamante (l'app admin), così il
    # job compare in /api/my_jobs dell'admin ed è scaricabile per l'indagine.
    if info.get("admin_copy"):
        base_rec = None
        non_admin_rec = None
        any_rec = None
        for _tok, _rec in list(_tkstore.download_tokens.items()):
            if isinstance(_rec, dict) and _rec.get("job_id") == job_id:
                any_rec = any_rec or _rec
                if not _rec.get("admin_copy"):
                    non_admin_rec = non_admin_rec or _rec
        base_rec = non_admin_rec or any_rec
        created_temp = None
        if base_rec is None:
            with _jobs_lock:
                _job = _jobs().get(job_id)
                _status = _job.get("status") if _job else None
            if _status in ("done", "optimized"):
                # Job completato in RAM ma senza token: creane uno snapshot dal job.
                # newtok verrà rimosso dopo il clone per non rendere il job visibile
                # all'utente originale (flusso invariato).
                newtok = generation_engine._create_download_token(job_id)
                if newtok:
                    base_rec = _tkstore.download_tokens.get(newtok)
                    created_temp = newtok
            elif _job is not None:
                # Job ANCORA IN CORSO: aggancia la copia admin e consegna a fine job.
                # Registra il cid chiamante; al COMPLETE il download token admin-owned
                # viene materializzato (generation_engine._materialize_admin_copies),
                # SENZA alterare job/ownership/flusso dell'utente originale.
                with _jobs_lock:
                    _job2 = _jobs().get(job_id)
                    if _job2 is not None:
                        _lst = _job2.setdefault("admin_copy_cids", [])
                        if cid not in _lst:
                            _lst.append(cid)
                _log_activity(job_id, "", "ADMIN_COPY_PENDING", client_id=cid,
                              client_ip=client_ip(), platform=_client_platform())
                print(f"[transfer] admin copy PENDING (job in corso) {job_id} cid {cid}")
                return jsonify({"ok": True, "job_id": job_id, "admin_copy": True,
                                "pending": True})
            else:
                # Job finalizzato ma non più in RAM (deploy/restart) e senza token:
                # ricostruisci lo snapshot dagli output ancora presenti su disco
                # (hot) o cold (R2). None solo se i file sono davvero spariti.
                base_rec = _reconstruct_admin_download_record(job_id)
        if not base_rec:
            return jsonify({"error": "job_unavailable",
                            "error_code": "job_unavailable"}), 410
        clone = dict(base_rec)
        clone["client_id"] = cid
        clone["admin_copy"] = True
        clone["created_at"] = time.time()
        clone_tok = str(uuid.uuid4())
        _tkstore.download_tokens[clone_tok] = clone
        if created_temp:
            # Rimuovi il token base creato solo per estrarre lo snapshot: lasciarlo
            # esporrebbe il job nell'app dell'utente originale (flusso invariato).
            _tkstore.download_tokens.pop(created_temp, None)
        _tkstore.save_tokens()
        _log_activity(job_id, "", "ADMIN_COPY", client_id=cid,
                      client_ip=client_ip(), platform=_client_platform())
        print(f"[transfer] admin copy claimed for job {job_id} by cid {cid}")
        return jsonify({"ok": True, "job_id": job_id, "admin_copy": True})

    moved = False
    job_done = False
    with _jobs_lock:
        job = _jobs().get(job_id)
        if job is not None:
            # NB: `gen_owner_cid` NON viene toccato. Il transfer cambia il
            # proprietario del risultato, non chi ha avviato la generazione:
            # riassegnarlo libererebbe lo slot del client web a metà lavoro e
            # basterebbe trasferire ogni job all'app per annullare il tetto di
            # generazioni contemporanee.
            # Il cid precedente (browser da cui è partito il job) resta
            # autorizzato: senza, il bottone di download del sito risponde 403
            # appena l'app reclama il job e l'utente ricompra il libro
            # (ticket 26/09/2026, job LE42lL_KTu5EnYr0A8k80A).
            _prev_cid = job.get("client_id", "")
            if _prev_cid and _prev_cid != cid:
                _prior = job.setdefault("prior_client_ids", [])
                if _prev_cid not in _prior:
                    _prior.append(_prev_cid)
            job["client_id"] = cid
            # Il job è ora dell'app: marcalo email_registered così (a) il cleanup
            # non lo tratta come download diretto usa-e-getta (rimozione 5 min dopo
            # il download) e (b) al COMPLETE viene creato un download token anche
            # se il job NON era né batch né email (job gratuito del sito).
            job["email_registered"] = True
            job["transferred_to_mobile"] = True
            job_done = job.get("status") in ("done", "optimized")
            moved = True
    # Job già completato senza download token (caso del sito senza email/batch):
    # creane uno ORA, altrimenti l'app non vede i formati e non può scaricare, e
    # il job/file verrebbero ripuliti poco dopo. _create_download_token è
    # idempotente e usa job["client_id"] (appena impostato) come owner.
    if job_done:
        try:
            generation_engine._create_download_token(job_id)
        except Exception as e:
            print(f"[transfer] download token creation failed for {job_id}: {e}")
    # riassocia tutti i download token del job al cid (per la sezione "Pronti")
    changed = False
    for tok, tinfo in list(_tkstore.download_tokens.items()):
        if isinstance(tinfo, dict) and tinfo.get("job_id") == job_id:
            tinfo["client_id"] = cid
            changed = True
    if changed:
        _tkstore.save_tokens()
    if not moved and not changed:
        # job non più in memoria e nessun token (es. scaduto): nulla da agganciare
        return jsonify({"error": "job_unavailable", "error_code": "job_unavailable"}), 410
    if moved or changed:
        _log_activity(job_id, _job_original_filename(job_id), "TRANSFER",
                      client_id=cid, client_ip=client_ip(),
                      platform=_client_platform())
    return jsonify({"ok": True, "job_id": job_id})


@bp.route("/api/share/create", methods=["POST"])
def api_share_create():
    """Crea una condivisione. Se il job indicato è ancora scaricabile e di
    proprietà del cid → share "ready" (nessun upload). Altrimenti → presigned
    PUT per l'upload del file ("upload")."""
    cid = _get_client_id()
    if not cid:
        return jsonify({"error": "no_cid", "error_code": "no_cid"}), 400
    body = request.get_json(silent=True) or {}
    job_id = (body.get("job_id") or "").strip()
    filename = _safe_share_filename(body.get("filename") or "audiolibro.m4b")
    fingerprint = (body.get("fingerprint") or "").strip()
    now = time.time()

    # Riuso: se esiste già una share viva dello stesso file (cid+fingerprint) e
    # il file è ancora recuperabile, resetta il TTL e ritorna lo stesso link —
    # niente nuovo upload né nuovo token.
    reuse_tok, reuse_info = _find_reusable_share(cid, fingerprint, now)
    if reuse_tok:
        with _tkstore.share_lock:
            reuse_info["created_at"] = now
            reuse_info["ttl_sec"] = _share_ttl_sec()
        _tkstore.save_share_tokens()
        return jsonify({"mode": "ready", "share_token": reuse_tok,
                        "link": _share_link_for(reuse_tok),
                        "ttl_sec": _share_ttl_sec()})

    if job_id:
        dltok = _tkstore.find_available_download_token(job_id, cid, now)
        if dltok:
            stok = secrets.token_urlsafe(24)
            # Nome download col titolo del libro (se risolvibile), così il
            # destinatario salva con un nome sensato invece di "audiolibro.m4b".
            _, ready_name = _resolve_ready_file(dltok)
            with _tkstore.share_lock:
                _tkstore.share_tokens[stok] = {
                    "kind": "ready", "download_token": dltok,
                    "client_id": cid, "created_at": now,
                    "ttl_sec": _share_ttl_sec(),
                    "filename": ready_name or filename,
                    "fingerprint": fingerprint,
                }
            _tkstore.save_share_tokens()
            return jsonify({"mode": "ready", "share_token": stok,
                            "link": _share_link_for(stok),
                            "ttl_sec": _share_ttl_sec()})

    if not storage_backend.is_enabled():
        return jsonify({"error": "upload_unavailable",
                        "error_code": "upload_unavailable"}), 503
    share_id = secrets.token_urlsafe(16)
    key = f"shares/{share_id}/{filename}"
    try:
        url = storage_backend.presigned_put_url(key, ttl=_share_upload_ttl_sec())
    except Exception as e:
        print(f"[share] presign put failed: {e}")
        return jsonify({"error": "presign_failed",
                        "error_code": "presign_failed"}), 502
    with _tkstore.share_lock:
        _tkstore.share_tokens[share_id] = {
            "kind": "pending", "s3_key": key, "filename": filename,
            "client_id": cid, "created_at": now, "ttl_sec": _share_upload_ttl_sec(),
            "fingerprint": fingerprint,
        }
    _tkstore.save_share_tokens()
    return jsonify({"mode": "upload", "share_id": share_id, "filename": filename,
                    "upload_url": url, "max_bytes": _share_max_bytes(),
                    "ttl_sec": _share_ttl_sec()})


@bp.route("/api/share/finalize", methods=["POST"])
def api_share_finalize():
    """Conferma che l'upload presigned è completo: verifica esistenza e
    dimensione su R2, poi registra la share. Oltre il limite → cancella + 413.
    Solo il cid che ha creato il pending record può finalizzare."""
    cid = _get_client_id()
    if not cid:
        return jsonify({"error": "no_cid", "error_code": "no_cid"}), 400
    body = request.get_json(silent=True) or {}
    share_id = (body.get("share_id") or "").strip()
    if not share_id:
        return jsonify({"error": "bad_request", "error_code": "bad_request"}), 400
    pending = _tkstore.share_tokens.get(share_id)
    if not isinstance(pending, dict) or pending.get("kind") != "pending":
        return jsonify({"error": "not_found", "error_code": "not_found"}), 404
    if pending.get("client_id") != cid:
        return jsonify({"error": "forbidden", "error_code": "forbidden"}), 403
    key = pending["s3_key"]
    filename = pending.get("filename")
    try:
        size = storage_backend.object_size(key)
    except Exception as e:
        print(f"[share] object_size failed for {key}: {e}")
        return jsonify({"error": "storage_error", "error_code": "storage_error"}), 502
    if size is None:
        return jsonify({"error": "not_uploaded", "error_code": "not_uploaded"}), 400
    if size > _share_max_bytes():
        try:
            storage_backend.delete_object(key)
        except Exception as e:
            print(f"[share] delete oversize failed: {e}")
        with _tkstore.share_lock:
            _tkstore.share_tokens.pop(share_id, None)
        _tkstore.save_share_tokens()
        return jsonify({"error": "too_large", "error_code": "too_large",
                        "max_bytes": _share_max_bytes()}), 413
    stok = secrets.token_urlsafe(24)
    now = time.time()
    with _tkstore.share_lock:
        _tkstore.share_tokens.pop(share_id, None)
        _tkstore.share_tokens[stok] = {
            "kind": "upload", "s3_key": key, "filename": filename,
            "client_id": cid, "created_at": now, "ttl_sec": _share_ttl_sec(),
            "fingerprint": pending.get("fingerprint"),
        }
    _tkstore.save_share_tokens()
    return jsonify({"share_token": stok, "link": _share_link_for(stok),
                    "ttl_sec": _share_ttl_sec()})


def _share_alive(info, now=None):
    now = now or time.time()
    return (isinstance(info, dict) and
            (now - info.get("created_at", 0)) <= info.get("ttl_sec", _share_ttl_sec()))


def _share_file_recoverable(info):
    """True se il file dietro una share è ancora recuperabile (per decidere il
    riuso): ready → file locale/cold risolvibile; upload → oggetto R2 esistente."""
    try:
        kind = info.get("kind")
        if kind == "ready":
            path, _ = _resolve_ready_file(info.get("download_token", ""))
            return path is not None
        if kind == "upload":
            return (storage_backend.is_enabled()
                    and storage_backend.object_exists(info.get("s3_key", "")))
    except Exception:
        pass
    return False


def _find_reusable_share(cid, fingerprint, now=None):
    """Token di una share viva dello stesso file (cid+fingerprint) con file
    ancora recuperabile, o (None, None). Permette di riusare la condivisione
    invece di ri-caricare/ri-generare. fingerprint vuoto → nessun riuso."""
    if not fingerprint:
        return None, None
    now = now or time.time()
    for stok, info in list(_tkstore.share_tokens.items()):
        if (isinstance(info, dict)
                and info.get("client_id") == cid
                and info.get("fingerprint") == fingerprint
                and info.get("kind") in ("ready", "upload")
                and _share_alive(info, now)
                and _share_file_recoverable(info)):
            return stok, info
    return None, None


def _file_available(path):
    """True se il file e' servibile da _send_file_throttled: presente in locale
    OPPURE evacuato su cold storage (R2). Senza questo controllo una share 'ready'
    di un job ancora scaricabile online (ma con file in cold tier) darebbe 410."""
    try:
        if os.path.exists(path):
            return True
        if storage_backend.is_enabled():
            key = storage_tiering.key_for_path(path)
            return bool(key and storage_backend.object_exists(key))
    except Exception:
        pass
    return False


def _reconstruct_admin_download_record(job_id):
    """Ricostruisce uno snapshot 'download token' per un job FINALIZZATO non più
    in RAM, localizzando l'output primario (m4b>mp3>abm>zip) su disco locale (hot)
    o su cold storage (R2). Ritorna un dict record (NON ancora inserito in
    _tkstore.download_tokens) oppure None se nessun output è disponibile.

    Serve alla copia amministrativa (indagine): dopo un deploy/restart la RAM è
    azzerata e i job gratuiti/diretti non hanno un download token, ma i file
    possono essere ancora presenti (hot o cold). Senza questa ricostruzione il
    claim admin restituirebbe 410 anche per job appena completati con file
    ancora scaricabili."""
    job_dir = _upload_dir() / job_id
    fields = (("output_m4b", "m4b"), ("output_file", "mp3"),
              ("optimized_abm_path", "abm"), ("output_zip", "zip"))
    found = {}
    title = ""
    # HOT: scan delle output dir locali (newest-first via _iter_output_dirs).
    for field, ext in fields:
        hits = _find_files_in_outputs(job_dir, f"*.{ext}")
        if hits:
            found[field] = str(hits[0])
            if not title:
                title = hits[0].stem
    # COLD: se nulla in locale, elenca il prefisso del job su R2 e mappa le chiavi
    # sui path canonici locali (key_for_path li ritradurrà in chiavi cold e
    # _send_file_throttled farà il redirect 302 al presigned URL).
    if not found and storage_backend.is_enabled():
        keys = storage_backend.list_prefix(f"{job_id}/")
        for field, ext in fields:
            for k in keys:
                if k.lower().endswith("." + ext):
                    found[field] = str(_upload_dir() / k)
                    if not title:
                        title = Path(k).stem
                    break
    if not found:
        return None
    rec = {
        "job_id": job_id,
        "created_at": time.time(),
        "download_type": "audio",
        "book_title": title or "audiolibro",
        "is_gemini": False,
    }
    rec.update(found)
    return rec


def _resolve_ready_file(dltok):
    """Path del file da servire per una share 'ready' + nome download.
    Preferenza: m4b > mp3 > abm > zip. Considera disponibili anche i file
    evacuati su cold storage (_send_file_throttled fa il redirect a R2).
    (None, None) se token assente o nessun file disponibile."""
    info = _tkstore.download_tokens.get(dltok)
    if not isinstance(info, dict):
        return None, None
    title = info.get("book_title") or "audiolibro"
    for field, ext in (("output_m4b", "m4b"), ("output_file", "mp3"),
                       ("optimized_abm_path", "abm"), ("output_zip", "zip")):
        path = info.get(field)
        if path and _file_available(path):
            return path, f"{_safe_share_filename(title)}.{ext}"
    return None, None


@bp.route("/api/share/claim/<token>")
def api_share_claim(token):
    """Valida la share e ritorna l'URL di download share-scoped (/s/<token>/dl)
    che impone il TTL. 404 sconosciuta, 410 scaduta."""
    info = _tkstore.share_tokens.get(token)
    if not isinstance(info, dict) or info.get("kind") not in ("ready", "upload"):
        return jsonify({"error": "invalid", "error_code": "invalid"}), 404
    now = time.time()
    if not _share_alive(info, now):
        return jsonify({"error": "expired", "error_code": "expired"}), 410
    remaining = int(info.get("ttl_sec", _share_ttl_sec()) - (now - info.get("created_at", 0)))
    base = env_str("ABM_BASE_URL", "").rstrip("/")   # pattern env inline vietato nei moduli nuovi
    if not base:
        try:
            base = request.url_root.rstrip("/")
        except Exception:
            base = ""
    return jsonify({"download_url": f"{base}/s/{token}/dl",
                    "filename": info.get("filename"),
                    "ttl_sec_remaining": max(0, remaining)})


@bp.route("/s/<token>/dl")
def share_download(token):
    """Consegna il file della share validando il TTL. ready → file locale via
    _send_file_throttled; upload → redirect alla presigned GET su R2."""
    info = _tkstore.share_tokens.get(token)
    if (not isinstance(info, dict)
            or info.get("kind") not in ("ready", "upload")
            or not _share_alive(info)):
        return ("Condivisione scaduta o inesistente", 410,
                {"Content-Type": "text/plain; charset=utf-8"})
    if info.get("kind") == "ready":
        path, dl_name = _resolve_ready_file(info.get("download_token", ""))
        if not path:
            return ("File non più disponibile", 410,
                    {"Content-Type": "text/plain; charset=utf-8"})
        return _send_file_throttled(path, as_attachment=True,
                                    download_name=dl_name, bypass_throttle=True)
    key = info.get("s3_key", "")
    if not storage_backend.is_enabled():
        return ("File non più disponibile", 410,
                {"Content-Type": "text/plain; charset=utf-8"})
    try:
        exists = storage_backend.object_exists(key)
    except Exception as e:
        print(f"[share] object_exists failed for {key}: {e}")
        return ("Errore temporaneo, riprova", 502,
                {"Content-Type": "text/plain; charset=utf-8"})
    if not exists:
        return ("File non più disponibile", 410,
                {"Content-Type": "text/plain; charset=utf-8"})
    now = time.time()
    remaining = int(info.get("ttl_sec", _share_ttl_sec()) - (now - info.get("created_at", 0)))
    url = storage_backend.presigned_get_url(
        key, download_name=info.get("filename"), ttl=max(60, remaining))
    return redirect(url, code=302)


@bp.route("/api/transfer_qr/<job_id>")
def api_transfer_qr(job_id):
    """QR di trasferimento per la SPA (avvio/completamento). Ownership via cookie."""
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    payload, tok = _transfer_payload_for(job_id)
    return jsonify({"qr": _qr_data_uri(payload), "token": tok})


@bp.route("/api/metrics/app_open", methods=["POST"])
def api_metrics_app_open():
    data = request.get_json(silent=True) or {}
    platform = data.get("platform")
    try:
        metrics_store.incr("app_open", platform)
    except Exception:
        pass  # best-effort, mai bloccante
    return jsonify({"ok": True})
