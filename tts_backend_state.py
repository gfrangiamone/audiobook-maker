"""Stato persistito del backend TTS: circuit breaker a senso unico.

Modulo foglia. Nessun import di `audiobook_app` o `gemini_tts`: lo stato e'
un dato, non una decisione. Chi decide di far scattare il breaker e' il
chiamante, che confronta `record_failure` con ABM_CF_TRIP_FAILURES.

Il rientro su Cloudflare avviene solo per azione manuale dell'admin
(`reset`), mai automaticamente: un backend che e' andato giu' per credito
esaurito tornerebbe a cadere subito, e ogni caduta costa un job.

File di stato: <data_dir>/_tts_backend_state.json
"""
import json
import os
import threading
from datetime import datetime, timezone

_STATE_PATH = None
_LOCK = threading.RLock()
_CACHE = {}

_FILENAME = "_tts_backend_state.json"


def init(data_dir):
    """Fissa la directory dello stato e ricarica dal disco."""
    global _STATE_PATH, _CACHE
    with _LOCK:
        _STATE_PATH = os.path.join(data_dir, _FILENAME)
        _CACHE = _load()


def _load():
    if not _STATE_PATH or not os.path.isfile(_STATE_PATH):
        return {}
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as e:
        # Uno stato illeggibile non deve impedire la sintesi: si riparte
        # puliti. Il caso peggiore e' un'email di trip in piu'.
        print(f"[tts-backend-state] stato illeggibile, riparto vuoto: {e}")
        return {}


def _save():
    if not _STATE_PATH:
        return
    tmp = _STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_CACHE, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _STATE_PATH)
    except OSError as e:
        print(f"[tts-backend-state] scrittura fallita: {e}")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state(model_key):
    with _LOCK:
        return dict(_CACHE.get(model_key) or {})


def is_tripped(model_key):
    return bool(state(model_key).get("tripped_at"))


def trip(model_key, *, reason, detail, job_id):
    """Fa scattare il breaker. True solo al PRIMO chiamante.

    Con piu' job in corso, N thread scoprono l'avaria nello stesso istante:
    il ritorno booleano sotto lock e' cio' che permette di mandare una sola
    email all'admin senza un secondo meccanismo di deduplica.
    """
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        if entry.get("tripped_at"):
            return False
        entry.update({
            "active": "vertex",
            "tripped_at": _now(),
            "trip_reason": reason,
            "trip_detail": str(detail)[:300],
            "trip_job_id": job_id,
            "notified": False,
        })
        _save()
        print(f"[tts-backend-state] TRIP {model_key}: {reason} ({detail})")
        return True


def mark_notified(model_key):
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        entry["notified"] = True
        _save()


def reset(model_key):
    """Rientro manuale su Cloudflare. True se c'era davvero un trip."""
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        had_trip = bool(entry.get("tripped_at"))
        entry.update({
            "active": "cloudflare",
            "tripped_at": None,
            "trip_reason": None,
            "trip_detail": None,
            "trip_job_id": None,
            "consecutive_failures": 0,
            "notified": False,
        })
        _save()
        print(f"[tts-backend-state] RESET {model_key} (aveva trip: {had_trip})")
        return had_trip


def record_failure(model_key):
    """Incrementa e ritorna i fallimenti consecutivi. Non fa scattare nulla."""
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
        _save()
        return entry["consecutive_failures"]


def record_success(model_key):
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        if entry.get("consecutive_failures"):
            entry["consecutive_failures"] = 0
            _save()
