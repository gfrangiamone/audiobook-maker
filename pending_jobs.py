"""Persistenza descrittori dei job batch (con email registrata) per il recupero
al riavvio. Riusa community_store.JsonStore (write atomico tmp+rename, lock, .bak).

Un descrittore = tutto il minimo per ricostruire e rilanciare un job dopo il restart.
Scritto quando il job diventa batch; rimosso (finalize) quando la mail finale parte.
"""
from __future__ import annotations

import os
import signal
import time

from community_store import JsonStore
from fileio import atomic_write_json

_FILENAME = "_pending_jobs.json"
# Lasciato dal processo che si chiude su SIGTERM (systemctl restart/stop del
# deploy, reboot): il boot successivo sa che l'arresto e' stato pulito.
_CLEAN_SHUTDOWN_FILE = "_clean_shutdown.json"
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
    s.upsert(rec)


def patch(job_id: str, fields: dict) -> bool:
    """Aggiunge campi a un descrittore esistente, senza toccare attempts/state.
    False se il job non ha descrittore (non batch): nulla da persistere."""
    s = _require()
    if s.get(job_id) is None:
        return False
    s.update(job_id, dict(fields))
    return True


def mark_running_bump(job_id: str) -> int:
    """Incrementa attempts e marca running. Persiste PRIMA del run (crash-safe).
    Ritorna il nuovo valore di attempts."""
    s = _require()
    out = {"n": 1}

    def _bump(it):
        out["n"] = int(it.get("attempts", 0) or 0) + 1
        it["attempts"] = out["n"]
        it["state"] = "running"

    s.modify(job_id, _bump)
    return out["n"]


def mark_running(job_id: str) -> int:
    """Marca running SENZA contare un tentativo (boot dopo un arresto pulito).
    Ritorna il valore attuale di attempts."""
    s = _require()
    out = {"n": 0}

    def _mark(it):
        out["n"] = int(it.get("attempts", 0) or 0)
        it["state"] = "running"

    s.modify(job_id, _mark)
    return out["n"]


# --- arresto pulito -----------------------------------------------------------
# Il cap del recovery deve contare le morti vere del processo (crash, OOM,
# kill), non i riavvii voluti: con il contatore a ogni boot, due deploy e un
# reboot ravvicinati chiudevano con rimborso job sani che sarebbero ripartiti
# riusando i chunk (reboot kernel del 19/11/2026: 3 job oltre il cap).

def _clean_shutdown_path():
    return _require().path.parent / _CLEAN_SHUTDOWN_FILE


def note_clean_shutdown() -> None:
    """Scrive il segnale di arresto pulito. Mai bloccante."""
    try:
        atomic_write_json(_clean_shutdown_path(), {"at": time.time(), "pid": os.getpid()})
    except Exception as e:  # noqa: BLE001 - lo spegnimento non si ferma qui
        print(f"[recover] segnale di arresto pulito non scritto: {e}", flush=True)


def consume_clean_shutdown() -> bool:
    """True se il processo precedente si e' chiuso in modo pulito. Il segnale
    vale per un solo boot: viene tolto subito, cosi' un crash successivo
    torna a contare."""
    p = _clean_shutdown_path()
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError as e:
        print(f"[recover] segnale di arresto pulito non rimosso: {e}", flush=True)
        return True


def install_clean_shutdown_hook() -> None:
    """Su SIGTERM scrive il segnale di arresto pulito e poi termina come
    prima (handler di default ripristinato e segnale rilanciato). Va chiamata
    dal thread principale."""
    def _on_term(signum, _frame):
        note_clean_shutdown()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    signal.signal(signal.SIGTERM, _on_term)


def reset_attempts(job_id: str) -> None:
    s = _require()
    if s.get(job_id) is not None:
        s.update(job_id, {"attempts": 0})


def finalize(job_id: str) -> None:
    """Rimuove il descrittore: job completato e mail inviata."""
    _require().delete(job_id)


def finalize_phase(job_id: str, phase: str) -> None:
    """Come finalize, ma solo se il descrittore e' della fase indicata: chi
    chiude una fase non deve cancellare il descrittore scritto da un'altra."""
    s = _require()
    rec = s.get(job_id)
    if rec is not None and rec.get("phase") == phase:
        s.delete(job_id)


def mark_failed(job_id: str) -> None:
    _require().update(job_id, {"state": "failed"})


def is_active(job_id: str) -> bool:
    """True se il job ha un descrittore non 'failed': il recovery al riavvio
    lo rilancera', quindi non e' (ancora) perso."""
    rec = _require().get(job_id)
    return rec is not None and rec.get("state") != "failed"


def orphans() -> list[dict]:
    """Descrittori da recuperare: tutti tranne quelli marcati 'failed'."""
    return [r for r in _require().all(include_archived=True) if r.get("state") != "failed"]
