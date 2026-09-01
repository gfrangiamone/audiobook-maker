"""free_tts_quota.py — Quota mensile di caratteri per client sulle voci STANDARD.

Le voci standard (edge-tts, Google) sono gratuite e illimitate: l'analisi di
agosto 2026 ha mostrato che l'1.4% dei client (>30 libri/mese) produce ~40% del
volume sintetizzato. Questa quota mette un tetto mensile per client ai caratteri
sintetizzati con voce standard; oltre il tetto il job resta possibile ma SOLO in
modalita' batch con email registrata (gate email, vedi /api/generate).

Struttura del file `ABM_DATA_DIR/_free_tts_quota.json`:
    {"YYYY-MM": {"<client_id>": {"chars": 1234, "jobs": {"<job_id>": 1234},
                                 "gated": 2}}}
`gated` conta i job accettati oltre quota (solo osservabilita').
Nessun dato personale oltre al client_id (cookie anonimo abm_cid).
Best-effort, thread-safe, scrittura atomica: nessuna eccezione propagata.
Modulo foglia: solo stdlib + community_store.atomic_write_json.
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from community_store import atomic_write_json

_lock = threading.RLock()
_KEEP_MONTHS = 3
_ANON = "_anon"
DEFAULT_LIMIT_CHARS = 10_000_000


def _quota_file():
    # Letto a ogni chiamata: ABM_DATA_DIR e' definito all'avvio del processo,
    # ma i test lo cambiano per isolare lo stato.
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")) / "_free_tts_quota.json"


def _month():
    return datetime.now().strftime("%Y-%m")


def limit_chars():
    """Tetto mensile di caratteri per client sulle voci standard. 0 = feature off."""
    raw = str(os.environ.get("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", DEFAULT_LIMIT_CHARS))
    try:
        return max(0, int(float(raw.replace("_", "").replace(",", "."))))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT_CHARS


def _norm_client(client_id):
    return (client_id or "").strip() or _ANON


def _load():
    try:
        with open(_quota_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    for old in sorted(d.keys())[:-_KEEP_MONTHS]:
        d.pop(old, None)
    try:
        atomic_write_json(_quota_file(), d)
    except Exception:
        pass


def _bucket(d, cid, create=False):
    """Bucket del client nel mese corrente (schema riparato se corrotto)."""
    month = _month()
    if not isinstance(d.get(month), dict):
        if not create:
            return None
        d[month] = {}
    month_bucket = d[month]
    if not isinstance(month_bucket.get(cid), dict):
        if not create:
            return None
        month_bucket[cid] = {"chars": 0, "jobs": {}}
    b = month_bucket[cid]
    if not isinstance(b.get("jobs"), dict):
        b["jobs"] = {}
    try:
        b["chars"] = max(0, int(b.get("chars", 0) or 0))
    except (TypeError, ValueError):
        b["chars"] = 0
    return b


def used_chars(client_id):
    """Caratteri gia' sintetizzati con voce standard dal client nel mese corrente."""
    with _lock:
        b = _bucket(_load(), _norm_client(client_id))
    return int(b["chars"]) if b else 0


def job_charged(client_id, job_id):
    """True se `job_id` ha gia' consumato quota per questo client nel mese
    (idempotenza al retry della stessa generazione)."""
    jid = (job_id or "").strip()
    if not jid:
        return False
    with _lock:
        b = _bucket(_load(), _norm_client(client_id))
    return bool(b) and jid in b["jobs"]


def consume(client_id, chars, job_id, gated=False):
    """Somma `chars` al bucket del mese. Idempotente per `job_id`.

    `gated=True` marca un job accettato OLTRE quota (gate email superato):
    conta comunque i caratteri, cosi' il totale del mese resta veritiero.
    Ritorna il totale del mese dopo l'operazione.
    """
    cid = _norm_client(client_id)
    jid = (job_id or "").strip()
    try:
        amount = max(0, int(chars or 0))
    except (TypeError, ValueError):
        amount = 0
    with _lock:
        d = _load()
        b = _bucket(d, cid, create=True)
        if jid and jid in b["jobs"]:
            return b["chars"]
        b["chars"] += amount
        if jid:
            b["jobs"][jid] = amount
        if gated:
            b["gated"] = int(b.get("gated", 0) or 0) + 1
        _save(d)
        return b["chars"]


def refund(client_id, job_id):
    """Storna il contributo di `job_id` (errore server: il job non ha prodotto
    nulla). No-op se il job non risulta addebiato. Ritorna i chars stornati."""
    cid = _norm_client(client_id)
    jid = (job_id or "").strip()
    if not jid:
        return 0
    with _lock:
        d = _load()
        b = _bucket(d, cid)
        if not b or jid not in b["jobs"]:
            return 0
        try:
            amount = max(0, int(b["jobs"].pop(jid) or 0))
        except (TypeError, ValueError):
            amount = 0
        b["chars"] = max(0, b["chars"] - amount)
        _save(d)
        return amount


def snapshot(client_id):
    """Stato quota per UI/admin."""
    lim = limit_chars()
    used = used_chars(client_id)
    return {
        "used_chars": used,
        "limit_chars": lim,
        "remaining_chars": max(0, lim - used),
        "exhausted": bool(lim > 0 and used >= lim),
    }


def decision(client_id, chars, job_id=None):
    """Esito della quota per un job a voce standard di `chars` caratteri.

    Non consuma nulla: il consumo e' esplicito via `consume()` dove il job
    parte davvero. `allowed=True` quando la feature e' spenta, quando il job
    ha gia' addebitato quota (retry della stessa generazione) o quando
    `used + chars <= limit`. Altrimenti `allowed=False, exhausted=True`: il
    chiamante decide se accettare comunque il job tramite il gate email.
    """
    try:
        need = max(0, int(chars or 0))
    except (TypeError, ValueError):
        need = 0
    limit = limit_chars()
    used = used_chars(client_id) if limit > 0 else 0
    out = {
        "allowed": True,
        "exhausted": False,
        "used_chars": used,
        "limit_chars": limit,
        "chars": need,
        "remaining_chars": max(0, limit - used) if limit > 0 else 0,
    }
    if limit <= 0:
        return out
    if job_id and job_charged(client_id, job_id):
        return out
    if used + need <= limit:
        return out
    out["allowed"] = False
    out["exhausted"] = True
    return out


def month_table():
    """{client_id: {"chars", "jobs": n, "gated": n}} del mese corrente (digest admin)."""
    with _lock:
        d = _load()
    month_data = d.get(_month())
    if not isinstance(month_data, dict):
        return {}
    out = {}
    for cid, b in month_data.items():
        if not isinstance(b, dict):
            continue
        try:
            chars = max(0, int(b.get("chars", 0) or 0))
        except (TypeError, ValueError):
            chars = 0
        jobs = b.get("jobs") if isinstance(b.get("jobs"), dict) else {}
        out[cid] = {"chars": chars, "jobs": len(jobs),
                    "gated": int(b.get("gated", 0) or 0)}
    return out
