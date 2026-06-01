"""Persistenza descrittori dei job batch (con email registrata) per il recupero
al riavvio. Riusa community_store.JsonStore (write atomico tmp+rename, lock, .bak).

Un descrittore = tutto il minimo per ricostruire e rilanciare un job dopo il restart.
Scritto quando il job diventa batch; rimosso (finalize) quando la mail finale parte.
"""
from __future__ import annotations

from community_store import JsonStore

_FILENAME = "_pending_jobs.json"
_store: JsonStore | None = None


def init() -> None:
    """Costruisce lo store. Richiede community_store.init() già chiamato."""
    global _store
    _store = JsonStore(_FILENAME)


def _require() -> JsonStore:
    if _store is None:
        raise RuntimeError("pending_jobs.init() must be called first")
    return _store


def register(job_id: str, phase: str, descriptor: dict) -> None:
    """Upsert del descrittore. attempts=0, state='pending'."""
    s = _require()
    rec = dict(descriptor)
    rec["id"] = job_id
    rec["phase"] = phase
    rec["attempts"] = 0
    rec["state"] = "pending"
    if s.get(job_id) is not None:
        s.update(job_id, rec)
    else:
        s.add(rec)


def mark_running_bump(job_id: str) -> int:
    """Incrementa attempts e marca running. Persiste PRIMA del run (crash-safe).
    Ritorna il nuovo valore di attempts."""
    s = _require()
    rec = s.get(job_id)
    n = (rec.get("attempts", 0) if rec else 0) + 1
    s.update(job_id, {"attempts": n, "state": "running"})
    return n


def reset_attempts(job_id: str) -> None:
    s = _require()
    if s.get(job_id) is not None:
        s.update(job_id, {"attempts": 0})


def finalize(job_id: str) -> None:
    """Rimuove il descrittore: job completato e mail inviata."""
    _require().delete(job_id)


def mark_failed(job_id: str) -> None:
    _require().update(job_id, {"state": "failed"})


def orphans() -> list[dict]:
    """Descrittori da recuperare: tutti tranne quelli marcati 'failed'."""
    return [r for r in _require().all(include_archived=True) if r.get("state") != "failed"]
