"""free_quota.py — Quota gratuita cumulativa per client sui TTS premium.

Struttura del file: {"YYYY-MM": {"<client_id>": {"eur": 1.37, "jobs": {"<job_id>": 0.29}}}}
Nessun dato personale oltre al client_id (cookie anonimo abm_cid).
Best-effort, thread-safe, scrittura atomica: nessuna eccezione propagata.
"""
import json
import os
import threading
from datetime import datetime
from pathlib import Path

from community_store import atomic_write_json
from voice_utils import is_speechify_voice

_lock = threading.RLock()
_KEEP_MONTHS = 3
_ANON = "_anon"


def _quota_file():
    # Letto a ogni chiamata: ABM_DATA_DIR e' definito all'avvio del processo,
    # ma i test lo cambiano per isolare lo stato.
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")) / "_free_quota.json"


def _month():
    return datetime.now().strftime("%Y-%m")


def _env_float(name, default):
    try:
        return float(str(os.environ.get(name, default)).replace(",", "."))
    except (TypeError, ValueError):
        return float(default)


def limit_eur():
    """Quota gratuita mensile per client. 0 = feature disattivata."""
    return _env_float("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")


def _norm_client(client_id):
    return (client_id or "").strip() or _ANON


def _load():
    try:
        with open(_quota_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def used_eur(client_id):
    """Valore di listino gia' regalato al client nel mese corrente."""
    with _lock:
        d = _load()
    bucket = (d.get(_month()) or {}).get(_norm_client(client_id)) or {}
    try:
        return float(bucket.get("eur", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def consume(client_id, eur, job_id):
    """Somma `eur` al bucket del mese. Idempotente per `job_id`.

    Ritorna il totale del mese dopo l'operazione.
    """
    cid = _norm_client(client_id)
    jid = (job_id or "").strip()
    try:
        amount = max(0.0, float(eur or 0.0))
    except (TypeError, ValueError):
        amount = 0.0
    with _lock:
        d = _load()
        bucket = d.setdefault(_month(), {}).setdefault(cid, {"eur": 0.0, "jobs": {}})
        jobs = bucket.setdefault("jobs", {})
        try:
            current = float(bucket.get("eur", 0.0) or 0.0)
        except (TypeError, ValueError):
            current = 0.0
        if jid and jid in jobs:
            return current
        current = round(current + amount, 4)
        bucket["eur"] = current
        if jid:
            jobs[jid] = round(amount, 4)
        for old in sorted(d.keys())[:-_KEEP_MONTHS]:
            d.pop(old, None)
        try:
            atomic_write_json(_quota_file(), d)
        except Exception:
            pass
        return current


def snapshot(client_id):
    """Stato quota per UI/admin."""
    lim = limit_eur()
    used = used_eur(client_id)
    return {
        "used_eur": round(used, 2),
        "limit_eur": round(lim, 2),
        "remaining_eur": round(max(0.0, lim - used), 2),
        "exhausted": bool(lim > 0 and used >= lim),
    }


def _premium_threshold_eur(voice_id):
    if is_speechify_voice(voice_id):
        return _env_float("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.50")
    return _env_float("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")


def decision(client_id, voice_id, list_total_eur):
    """Prezzo dovuto per un job premium, applicando la quota gratuita.

    `list_total_eur` e' il prezzo di LISTINO (TTS premium + eventuale quota LLM
    combinata), cioe' prima dell'azzeramento sotto soglia. Non consuma nulla:
    il consumo e' esplicito via `consume()` dove il job parte davvero.
    """
    try:
        list_total = round(float(list_total_eur or 0.0), 2)
    except (TypeError, ValueError):
        list_total = 0.0
    threshold = _premium_threshold_eur(voice_id)
    limit = limit_eur()
    used = used_eur(client_id) if limit > 0 else 0.0
    out = {
        "due_eur": list_total,
        "is_free": False,
        "quota_exhausted": False,
        "quota_used_eur": round(used, 2),
        "quota_limit_eur": round(limit, 2),
        "threshold_eur": threshold,
        "list_total_eur": list_total,
    }
    if list_total > threshold:
        # Job gia' a pagamento: la quota non c'entra, percorso invariato.
        return out
    if limit <= 0 or round(used + list_total, 4) <= limit:
        out["due_eur"] = 0.0
        out["is_free"] = True
        return out
    floor = _env_float("ABM_PREMIUM_MIN_COST_EUR", "0.50")
    out["due_eur"] = round(max(list_total, floor), 2)
    out["quota_exhausted"] = True
    return out
