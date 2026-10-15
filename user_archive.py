# user_archive.py
"""Archivio dell'app: libri archiviati dalla libreria dello smartphone di un
utente con abbonamento di archivio.

Un libro entra nell'archivio in due modi:
- collegamento: e' gia' nell'archivio dell'account (stesso fingerprint di un
  libro gia' archiviato, o file di un job archiviato dell'account con lo
  stesso contenuto) -> nessun upload, nessun byte in piu' sulla quota;
- upload: presigned PUT su `user_archive/<account_id>/<item_id>.<ext>`, la
  quota si prenota alla creazione e il libro e' `ready` solo dopo `finalize`
  (dimensione verificata su R2). L'app cancella la copia locale solo dopo.

Dopo la revoca dell'abbonamento i libri restano scaricabili per
accounts.archive_grace_days(), poi `sweep` li cancella da R2 e dal DB.

Modulo di servizio: dipende da `db`, `accounts`, `storage_backend`,
`storage_tiering` e dalla stdlib. Le route stanno in `routes_account`.
"""
import hashlib
import os
import re
import secrets
import sqlite3
import time

import accounts
import db
import storage_backend
import storage_tiering
from env_utils import env_int

ROOT = "user_archive"
ALLOWED_EXT = (".m4b", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".flac", ".wav")
LINK_KINDS = ("m4b", "download")
FP_CHUNK = 64 * 1024
PENDING_TTL_SEC = 24 * 3600
SWEEP_INTERVAL_SEC = 3600

_FP_RE = re.compile(r"^[0-9a-f]{64}$")
_sweep_state = {"at": 0.0}


def max_item_bytes():
    """Tetto per singolo libro caricato (un PUT presigned su R2 regge 5 GB)."""
    return max(1, env_int("ABM_ARCHIVE_ITEM_MAX_BYTES", 4 * accounts.GIB))


def upload_ttl_sec():
    return max(300, env_int("ABM_ARCHIVE_UPLOAD_TTL_SEC", 21600))


def _now(now):
    return int(now if now is not None else time.time())


# ---------------------------------------------------------------- fingerprint

def fingerprint_parts(size, head, tail=b""):
    """Stesso algoritmo di `shareFingerprint` dell'app: SHA-256 di
    "<size>:" + intero file (<= 128 KB) o primi + ultimi 64 KB."""
    h = hashlib.sha256(f"{int(size)}:".encode("utf-8"))
    h.update(head)
    if size > 2 * FP_CHUNK:
        h.update(tail)
    return h.hexdigest()


def fingerprint_local(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size <= 2 * FP_CHUNK:
            return fingerprint_parts(size, f.read(size)), size
        head = f.read(FP_CHUNK)
        f.seek(size - FP_CHUNK)
        return fingerprint_parts(size, head, f.read(FP_CHUNK)), size


def fingerprint_cold(key):
    """(fingerprint, size) dell'oggetto su R2 con due Range GET, o (None, None)."""
    size = storage_backend.object_size(key)
    if not size:
        return None, None
    if size <= 2 * FP_CHUNK:
        data = storage_backend.get_range(key, 0, size - 1)
        return (fingerprint_parts(size, data), size) if len(data) == size else (None, None)
    head = storage_backend.get_range(key, 0, FP_CHUNK - 1)
    tail = storage_backend.get_range(key, size - FP_CHUNK, size - 1)
    if len(head) != FP_CHUNK or len(tail) != FP_CHUNK:
        return None, None
    return fingerprint_parts(size, head, tail), size


def fingerprint_of(path):
    """Fingerprint di un output di job, dal disco o dalla copia cold."""
    try:
        if os.path.exists(path):
            return fingerprint_local(path)
        if storage_backend.is_enabled():
            key = storage_tiering.key_for_path(path)
            if key:
                return fingerprint_cold(key)
    except Exception as e:  # noqa: BLE001  file illeggibile: niente collegamento, si carica
        print(f"[user_archive] fingerprint non calcolabile per {path}: {e}", flush=True)
    return None, None


# ---------------------------------------------------------------- righe

def public(row):
    """Forma esposta all'app."""
    return {
        "id": row["id"], "state": row["state"], "fingerprint": row["fingerprint"],
        "filename": row["filename"], "title": row["title"], "author": row["author"],
        "duration_ms": int(row["duration_ms"] or 0), "size_bytes": int(row["size_bytes"] or 0),
        "source": "job" if row["job_id"] else "upload", "created_at": int(row["created_at"]),
    }


def list_items(account_id):
    with db.tx() as c:
        rows = c.execute("SELECT * FROM archive_items WHERE account_id=? AND state='ready' "
                         "ORDER BY created_at DESC, id", (account_id,)).fetchall()
    return [dict(r) for r in rows]


def get_item(account_id, item_id):
    with db.tx() as c:
        r = c.execute("SELECT * FROM archive_items WHERE id=? AND account_id=?",
                      (str(item_id), account_id)).fetchone()
    return dict(r) if r is not None else None


def _by_fingerprint(account_id, fingerprint):
    with db.tx() as c:
        r = c.execute("SELECT * FROM archive_items WHERE account_id=? AND fingerprint=?",
                      (account_id, fingerprint)).fetchone()
    return dict(r) if r is not None else None


def _insert(account_id, fields, now):
    item_id = secrets.token_urlsafe(12)
    row = {"id": item_id, "account_id": account_id, "created_at": now, "updated_at": now, **fields}
    cols = ",".join(row)
    with db.tx() as c:
        c.execute(f"INSERT INTO archive_items({cols}) VALUES ({','.join('?' * len(row))})",
                  tuple(row.values()))
    return get_item(account_id, item_id)


def _delete_row(item_id):
    with db.tx() as c:
        c.execute("DELETE FROM archive_items WHERE id=?", (str(item_id),))
    accounts._archive_cache_clear()


def _ext(filename):
    ext = os.path.splitext(filename or "")[1].lower()
    return ext if ext in ALLOWED_EXT else ""


def _clean(s, n):
    return re.sub(r"[\x00-\x1f\x7f]", "", str(s or "")).strip()[:n]


# ---------------------------------------------------------------- flusso

def create(account, *, fingerprint, size, filename, title="", author="", duration_ms=0,
           job_candidates=(), now=None):
    """Archivia un libro dell'app. Ritorna (esito, dati):

    - ("linked", item): gia' nell'archivio, nessun upload;
    - ("upload", {"item", "upload_url"}): caricare il file, poi `finalize`;
    - ("quota", {"quota_bytes", "used_bytes", "needed_bytes"}): non ci sta;
    - ("inactive" | "bad_request" | "too_large" | "unavailable", None).

    `job_candidates`: [(path, link_kind, download_token)] dei file dei job
    dell'account con cui il libro puo' coincidere (vedi routes_account).
    """
    now = _now(now)
    if accounts.archive_state(account, now) != "active":
        return "inactive", None
    fingerprint = str(fingerprint or "").strip().lower()
    try:
        size = int(size)
    except (TypeError, ValueError):
        size = 0
    filename = _clean(os.path.basename(str(filename or "").replace("\\", "/")), 200)
    if not _FP_RE.match(fingerprint) or size <= 0 or not _ext(filename):
        return "bad_request", None
    aid = account["id"]
    meta = {"filename": filename, "title": _clean(title, 300), "author": _clean(author, 200),
            "duration_ms": max(0, int(duration_ms or 0)), "size_bytes": size,
            "fingerprint": fingerprint}

    existing = _by_fingerprint(aid, fingerprint)
    if existing and existing["state"] == "ready":
        return "linked", existing

    if not existing:
        archived = accounts.archived_job_ids(now)
        for path, kind, token in job_candidates or ():
            job_id = _job_of_token_path(path)
            if kind not in LINK_KINDS or not job_id or job_id not in archived:
                continue
            if accounts.job_owner(job_id) != aid:
                continue
            fp, _sz = fingerprint_of(path)
            if fp != fingerprint:
                continue
            try:
                item = _insert(aid, {**meta, "state": "ready", "job_id": job_id,
                                     "link_token": token, "link_kind": kind}, now)
            except sqlite3.IntegrityError:
                item = _by_fingerprint(aid, fingerprint)
            accounts._archive_cache_clear()
            return "linked", item

    if size > max_item_bytes():
        return "too_large", None
    if not storage_backend.is_enabled():
        return "unavailable", None
    used, _n = accounts.archive_usage(aid)
    if existing:  # upload rimasto a meta': la sua prenotazione e' gia' in `used`
        used -= int(existing["size_bytes"] or 0)
    quota = accounts.archive_quota_bytes(account.get("plan"))
    if used + size > quota:
        return "quota", {"quota_bytes": quota, "used_bytes": used, "needed_bytes": size}

    if existing:
        with db.tx() as c:
            c.execute("UPDATE archive_items SET size_bytes=?, filename=?, title=?, author=?, "
                      "duration_ms=?, updated_at=? WHERE id=?",
                      (size, meta["filename"], meta["title"], meta["author"],
                       meta["duration_ms"], now, existing["id"]))
        item = get_item(aid, existing["id"])
    else:
        try:
            item = _insert(aid, {**meta, "state": "pending", "r2_key": ""}, now)
        except sqlite3.IntegrityError:
            return create(account, fingerprint=fingerprint, size=size, filename=filename,
                          title=title, author=author, duration_ms=duration_ms, now=now)
        key = f"{ROOT}/{aid}/{item['id']}{_ext(filename)}"
        with db.tx() as c:
            c.execute("UPDATE archive_items SET r2_key=? WHERE id=?", (key, item["id"]))
        item["r2_key"] = key
    try:
        url = storage_backend.presigned_put_url(item["r2_key"], ttl=upload_ttl_sec())
    except Exception as e:  # noqa: BLE001
        print(f"[user_archive] presign put fallito per {item['id']}: {e}", flush=True)
        return "unavailable", None
    return "upload", {"item": item, "upload_url": url}


def _job_of_token_path(path):
    """job_id dal path di un output (`<data>/<job_id>/output_*/file`)."""
    key = storage_tiering.key_for_path(path) if path else None
    if not key or "/" not in key:
        return ""
    return key.split("/", 1)[0]


def finalize(account, item_id, now=None):
    """Chiude l'upload di un libro. Esiti: ("ready", item), ("not_found",),
    ("not_uploaded",), ("size_mismatch",), ("storage_error",)."""
    item = get_item(account["id"], item_id)
    if item is None:
        return "not_found", None
    if item["state"] == "ready":
        return "ready", item
    try:
        size = storage_backend.object_size(item["r2_key"])
    except Exception as e:  # noqa: BLE001
        print(f"[user_archive] object_size fallito per {item['id']}: {e}", flush=True)
        return "storage_error", None
    if size is None:
        return "not_uploaded", None
    if size != int(item["size_bytes"]):
        # File diverso da quello dichiarato (e prenotato in quota): via tutto,
        # l'app ricomincia da create.
        try:
            storage_backend.delete_object(item["r2_key"])
        except Exception as e:  # noqa: BLE001
            print(f"[user_archive] delete {item['r2_key']} fallita: {e}", flush=True)
            return "storage_error", None
        _delete_row(item["id"])
        return "size_mismatch", None
    with db.tx() as c:
        c.execute("UPDATE archive_items SET state='ready', updated_at=? WHERE id=?",
                  (_now(now), item["id"]))
    return "ready", get_item(account["id"], item["id"])


def delete(account, item_id):
    """Toglie un libro dall'archivio (e il file da R2 se caricato dall'app).
    Esiti: "ok", "not_found", "storage_error" (riga intatta, si riprova)."""
    item = get_item(account["id"], item_id)
    if item is None:
        return "not_found"
    return "ok" if _purge(item) else "storage_error"


def _purge(item):
    """Copia R2 (se nostra) e poi la riga: se il delete su R2 fallisce la riga
    resta, cosi' il file non diventa un orfano invisibile."""
    if item.get("r2_key"):
        try:
            storage_backend.delete_object(item["r2_key"])
        except Exception as e:  # noqa: BLE001
            print(f"[user_archive] delete {item['r2_key']} fallita: {e}", flush=True)
            return False
    _delete_row(item["id"])
    return True


def download_name(item):
    return item.get("filename") or f"{item['id']}{_ext(item.get('r2_key') or '') or '.m4b'}"


# ---------------------------------------------------------------- sweep

def sweep(now=None, force=False):
    """Pulizia periodica (dal loop di cleanup, al piu' ogni SWEEP_INTERVAL_SEC):
    upload mai chiusi oltre PENDING_TTL_SEC e archivi di account cancellati o
    con l'abbonamento revocato da oltre archive_grace_days(). Ritorna
    {"pending": n, "expired": n, "errors": n}."""
    t = _now(now)
    out = {"pending": 0, "expired": 0, "errors": 0}
    if not force and t - _sweep_state["at"] < SWEEP_INTERVAL_SEC:
        return out
    _sweep_state["at"] = t
    if not accounts.enabled():
        return out
    grace_cut = t - accounts.archive_grace_days() * 86400
    plans = tuple(accounts.ARCHIVE_PLANS)
    with db.tx() as c:
        stale = [dict(r) for r in c.execute(
            "SELECT * FROM archive_items WHERE state='pending' AND updated_at<?",
            (t - PENDING_TTL_SEC,)).fetchall()]
        expired = [dict(r) for r in c.execute(
            "SELECT i.* FROM archive_items i JOIN accounts a ON a.id=i.account_id "
            "WHERE a.deleted_at IS NOT NULL OR (a.plan NOT IN (" + ",".join("?" * len(plans)) + ") "
            "AND (a.plan_until IS NULL OR a.plan_until<=?))",
            plans + (grace_cut,)).fetchall()]
    seen = set()
    for kind, rows in (("pending", stale), ("expired", expired)):
        for item in rows:
            if item["id"] in seen:
                continue
            seen.add(item["id"])
            if _purge(item):
                out[kind] += 1
            else:
                out["errors"] += 1
    if out["pending"] or out["expired"] or out["errors"]:
        print(f"[user_archive] sweep: {out}", flush=True)
    return out
