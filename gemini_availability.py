"""Stato "modello non disponibile" per i modelli Gemini (modulo foglia).

Un errore fatale del canale (chiave revocata, credito esaurito, modello
ritirato) marca il modello non disponibile: sparisce dal catalogo e gli
ingressi HTTP lo rifiutano, cosi' nessuno paga un libro che non puo' partire.
Rientro automatico dopo ABM_GEMINI_UNAVAILABLE_COOLDOWN_SEC dalla marcatura
(anche attraverso un riavvio: lo stato e' su disco) o reset dal pannello admin.

Non importa nulla del progetto.
"""
import json
import os
from fileio import load_json, write_json_safe
import threading
import time
from pathlib import Path

_FILE_NAME = "_gemini_model_availability.json"
_lock = threading.Lock()
_path = None
_state = {}


def cooldown_sec():
    try:
        return max(0, int(os.environ.get("ABM_GEMINI_UNAVAILABLE_COOLDOWN_SEC", "900")))
    except (TypeError, ValueError):
        return 900


def init(data_dir):
    global _path, _state
    with _lock:
        _path = Path(data_dir) / _FILE_NAME
        data = load_json(_path, {}, on_error=lambda e: print(
            f"[gemini-availability] stato illeggibile, ignorato: {e}"))
        _state = {k: v for k, v in data.items() if isinstance(v, dict)}


def _save_locked():
    if _path is None:
        return
    write_json_safe(_path, _state, on_error=lambda e: print(
        f"[gemini-availability] salvataggio fallito: {e}"))


def _active(entry, now):
    return bool(entry) and (now - float(entry.get("since", 0) or 0)) < cooldown_sec()


def mark_unavailable(model_key, reason, now=None):
    """Marca il modello; True se lo stato non era gia' attivo (notificare)."""
    now = time.time() if now is None else float(now)
    with _lock:
        first = not _active(_state.get(model_key), now)
        _state[model_key] = {"since": now, "reason": str(reason or "")[:300]}
        _save_locked()
    return first


def is_unavailable(model_key, now=None):
    now = time.time() if now is None else float(now)
    with _lock:
        return _active(_state.get(model_key), now)


def clear(model_key):
    with _lock:
        existed = _state.pop(model_key, None) is not None
        if existed:
            _save_locked()
    return existed


def snapshot(now=None):
    now = time.time() if now is None else float(now)
    out = {}
    with _lock:
        items = list(_state.items())
    for mk, e in items:
        since = float(e.get("since", 0) or 0)
        active = _active(e, now)
        out[mk] = {"since": since, "reason": e.get("reason", ""),
                   "unavailable": active,
                   "retry_in_sec": int(max(0, since + cooldown_sec() - now)) if active else 0}
    return out
