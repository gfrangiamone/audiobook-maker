"""token_store — download, transfer e share token (E3, primo seam, 2026-10-09).

Stato condiviso del processo, spostato pari pari da `audiobook_app`: tre
dict in memoria, tre lock, tre file JSON sotto la data dir. I dict si
mutano in place e non si ribindano mai (`generation_engine` e il cleanup
tengono lo stesso oggetto ricevuto da `configure`); le funzioni leggono i
globali del modulo a ogni chiamata, cosi' i test che sostituiscono
`token_store.download_tokens` o `token_store.save_tokens` vengono visti
da tutti.

`configure(upload_dir_fn, retention_fn, cold_available_fn)` riceve dalla app
la cartella (come funzione) e le due policy che restano sue: la retention effettiva di un
token (`_effective_retention_for_token_info`: dipende dalla voce premium e
dal primo download) e la disponibilita' di un file su cold storage
(`_cold_object_available`). Importa solo `fileio`; non importa
`audiobook_app`.
"""
import json
import secrets
import threading
import time
from pathlib import Path

from fileio import atomic_write_json, load_json

download_tokens = {}   # token -> {job_id, created_at, download_type, base_url, ...}
tokens_lock = threading.Lock()
TOKENS_FILE = None     # Path, da configure()

transfer_tokens = {}   # transfer_token -> {"job_id":..., "created_at":...}
transfer_lock = threading.Lock()
TRANSFER_TOKENS_FILE = None

share_tokens = {}      # share_token -> {"kind":"ready"|"upload", ...}
share_lock = threading.Lock()
SHARE_TOKENS_FILE = None

_upload_dir_fn = None
_retention_fn = None
_cold_available_fn = None


def configure(upload_dir_fn, retention_fn, cold_available_fn):
    """Cartella dati (funzione: la app la ribinda nei test) e policy della app
    (retention effettiva del token, disponibilita' su cold), anch'esse
    funzioni risolte a ogni chiamata. I tre file JSON si fissano qui una
    volta; i test li ribindano direttamente (`TOKENS_FILE`)."""
    global _upload_dir_fn, _retention_fn, _cold_available_fn
    global TOKENS_FILE, TRANSFER_TOKENS_FILE, SHARE_TOKENS_FILE
    _upload_dir_fn = upload_dir_fn
    _retention_fn = retention_fn
    _cold_available_fn = cold_available_fn
    d = Path(upload_dir_fn())
    TOKENS_FILE = d / "_download_tokens.json"
    TRANSFER_TOKENS_FILE = d / "_transfer_tokens.json"
    SHARE_TOKENS_FILE = d / "_share_tokens.json"


def _retention(info):
    return _retention_fn(info) if _retention_fn else 0


# --- transfer token (deep link /t/<token> verso l'app) ----------------------

def load_transfer_tokens():
    data = load_json(TRANSFER_TOKENS_FILE, None,
                     on_error=lambda e: print(f"[transfer] load failed: {e}"))
    if data is not None:
        transfer_tokens.clear()
        transfer_tokens.update(data)


def save_transfer_tokens():
    try:
        with transfer_lock:
            atomic_write_json(TRANSFER_TOKENS_FILE, transfer_tokens, indent=2)
    except Exception as e:
        print(f"[transfer] save failed: {e}")


def ensure_transfer_token(job_id):
    """Ritorna (idempotente) il transfer token per il job, creandolo se assente."""
    with transfer_lock:
        for tok, info in transfer_tokens.items():
            if isinstance(info, dict) and info.get("job_id") == job_id:
                return tok
        tok = secrets.token_urlsafe(24)
        transfer_tokens[tok] = {"job_id": job_id, "created_at": time.time()}
    save_transfer_tokens()
    return tok


def ensure_admin_copy_token(job_id):
    """Ritorna (idempotente) un transfer token dedicato alla COPIA AMMINISTRATIVA
    del job verso l'app (indagine). Distinto dal transfer token utente: reca il
    flag `admin_copy` così il claim non riassegna il job all'app chiamante e non
    tocca lo stato dell'utente originale (vedi api_transfer_claim)."""
    with transfer_lock:
        for tok, info in transfer_tokens.items():
            if (isinstance(info, dict) and info.get("job_id") == job_id
                    and info.get("admin_copy")):
                return tok
        tok = secrets.token_urlsafe(24)
        transfer_tokens[tok] = {"job_id": job_id, "created_at": time.time(),
                                "admin_copy": True}
    save_transfer_tokens()
    return tok


# --- share token (/s/<token>) ------------------------------------------------

def load_share_tokens():
    data = load_json(SHARE_TOKENS_FILE, None,
                     on_error=lambda e: print(f"[share] load failed: {e}"))
    if data is not None:
        share_tokens.clear()
        share_tokens.update(data)


def save_share_tokens():
    try:
        with share_lock:
            atomic_write_json(SHARE_TOKENS_FILE, share_tokens, indent=2)
    except Exception as e:
        print(f"[share] save failed: {e}")


# --- download token (/dl/<token>) --------------------------------------------

def has_active_download_tokens(job_id, now=None):
    """True se esiste almeno un download token non scaduto per il job_id.

    Protegge job in stato analysed/cancelled dalla rimozione prematura
    della directory quando esistono ancora link email validi.
    I token vengono confrontati con la retention effettiva (+300s di
    margine come nel resto del cleanup)."""
    if now is None:
        now = time.time()
    try:
        for _t, info in list(download_tokens.items()):
            if info.get("job_id") != job_id:
                continue
            if (now - info.get("created_at", 0)) <= _retention(info) + 300:
                return True
    except Exception:
        pass
    return False


def find_available_download_token(job_id, cid, now=None):
    """Download token del job ancora valido e di proprietà di [cid], o None.
    Stessa logica di retention di /api/my_jobs."""
    now = now or time.time()
    for tok, tinfo in list(download_tokens.items()):
        if not isinstance(tinfo, dict):
            continue
        if tinfo.get("job_id") != job_id or tinfo.get("client_id") != cid:
            continue
        created = tinfo.get("created_at", 0)
        if (now - created) <= _retention(tinfo):
            return tok
    return None


def token_cold_available(token_info):
    """True se almeno uno degli output snapshottati nel token esiste su cold."""
    if not isinstance(token_info, dict):
        return False
    for k in ("output_m4b", "output_file", "output_zip", "optimized_abm_path",
              "output_m4b_fallback_zip", "translated_path"):
        if _cold_available_fn and _cold_available_fn(token_info.get(k, "")):
            return True
    return False


def read_tokens_file():
    """Read raw token dict from disk. Returns {} on missing/invalid file."""
    return load_json(TOKENS_FILE, {},
                     on_error=lambda e: print(f"[tokens] Failed to read tokens file: {e}"))


def merge_tokens_from_disk():
    """Pick up tokens persisted by other workers (Gunicorn multi-worker safety).

    Each worker keeps its own in-memory `download_tokens`; the only shared
    state is `TOKENS_FILE`. Without periodic merge, worker B's cleanup loop
    cannot see tokens created by worker A and would delete their job dirs as
    orphan. In-memory entries always win on conflict (worker may have data
    not yet flushed to disk).
    """
    disk = read_tokens_file()
    if not disk:
        return
    now = time.time()
    with tokens_lock:
        for tok, info in disk.items():
            try:
                created = float(info.get("created_at", 0) or 0)
            except (TypeError, ValueError):
                continue
            # Per token PREMIUM (is_gemini) la retention e' GEMINI_FILE_RETENTION_SEC,
            # raddoppiata se non risulta alcun download (retention effettiva).
            if (now - created) > _retention(info) + 300:
                continue
            if tok not in download_tokens:
                download_tokens[tok] = info


def save_tokens():
    """Persist download tokens to disk (survives restart).

    Re-reads the file first and merges to avoid clobbering tokens written by
    other workers since our last sync.
    """
    merge_tokens_from_disk()
    try:
        with tokens_lock:
            # Save only serializable data
            data = {}
            for tok, info in download_tokens.items():
                data[tok] = {
                    "job_id": info["job_id"],
                    "created_at": info["created_at"],
                    "download_type": info.get("download_type", "audio"),
                    "base_url": info.get("base_url", ""),
                    # Snapshot of job data needed for download after restart
                    "book_title": info.get("book_title", ""),
                    "output_zip": info.get("output_zip", ""),
                    "output_name": info.get("output_name", ""),
                    "output_file": info.get("output_file", ""),
                    "epub_path": info.get("epub_path", ""),
                    "podcast_safe_name": info.get("podcast_safe_name", ""),
                    "podcast_ready": info.get("podcast_ready", False),
                    "podcast_mp3s": info.get("podcast_mp3s", []),
                    "podcast_info_title": info.get("podcast_info_title", ""),
                    "podcast_info_author": info.get("podcast_info_author", ""),
                    "podcast_info_language": info.get("podcast_info_language", ""),
                    "original_filename": info.get("original_filename", ""),
                    "lang": info.get("lang", "en"),
                    "optimized_abm_path": info.get("optimized_abm_path", ""),
                    "optimized_abm_name": info.get("optimized_abm_name", ""),
                    # Traduzione libro (download_type="translated"): senza questi
                    # due campi il token sopravvive al restart ma DIMENTICA dove
                    # sta il file, e /dl/<token> mostra la pagina "traduzione
                    # pronta" SENZA bottone (incidente 04/09/2026, job
                    # 6t4YV4oSBMbxAyxjLB6T3Q: restart 3h dopo l'email -> link
                    # pagato e mai scaricabile).
                    "translated_path": info.get("translated_path", ""),
                    "translated_name": info.get("translated_name", ""),
                    # Kit di ripiego M4B (ZIP con MP3 + capitoli): stessa classe
                    # di perdita, il bottone spariva dopo un restart.
                    "output_m4b_fallback_zip": info.get("output_m4b_fallback_zip", ""),
                    # Marker per scegliere retention: True se job ha generato con voce PREMIUM.
                    "is_gemini": bool(info.get("is_gemini", False)),
                    # Timestamp primo download reale del file via /dl/<token>/*.
                    # 0/None = mai scaricato (attiva protezione 2x per voci PREMIUM).
                    "downloaded_at": info.get("downloaded_at") or 0,
                    # Timestamp del primo redirect 302 al cold storage: traccia
                    # il tentativo, NON conta come download (vedi
                    # _mark_token_redirected) e non riduce la retention.
                    "redirected_at": info.get("redirected_at") or 0,
                    # Fields required by /dl/<token> rendering after worker restart
                    # or cross-worker token merge (Gunicorn multi-process).
                    "output_format": info.get("output_format", ""),
                    "output_m4b": info.get("output_m4b", ""),
                    "ai_optimized": info.get("ai_optimized", False),
                    # Mobile: client identifier for job reconstruction after restart
                    "client_id": info.get("client_id", ""),
                }
            # Atomic write (tmp + fsync + rename) per evitare corruzione su crash
            atomic_write_json(TOKENS_FILE, data, indent=2)
    except Exception as e:
        print(f"[tokens] Failed to save tokens: {e}")


def load_tokens():
    """Reload download tokens from disk on startup."""
    if TOKENS_FILE is None or not TOKENS_FILE.exists():
        return
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        now = time.time()
        loaded = 0
        expired = 0
        for tok, info in data.items():
            # Skip expired tokens (retention dipende da is_gemini sul token,
            # raddoppiata se downloaded_at non e' settato).
            if (now - info.get("created_at", 0)) > _retention(info) + 300:
                expired += 1
                continue
            # Verify that job files still exist locally OR on cold storage.
            # Con tiering S3 il locale può essere stato evacuato/rimosso mentre
            # la copia cold è ancora servibile: in quel caso il token va
            # MANTENUTO, altrimenti smette di proteggere la dir e l'orphan
            # cleanup ne purgherebbe locale + cold (perdita totale PREMIUM).
            job_dir = Path(_upload_dir_fn()) / info.get("job_id", "")
            if not job_dir.exists() and not token_cold_available(info):
                expired += 1
                continue
            download_tokens[tok] = info
            loaded += 1
        if loaded or expired:
            print(f"[tokens] Loaded {loaded} tokens from disk ({expired} expired/invalid)")
    except Exception as e:
        print(f"[tokens] Failed to load tokens: {e}")
