"""metrics_store.py — Contatori aggregati anonimi per il funnel app->web.
Struttura: {"YYYY-MM-DD": {"app_open": {"android": N, ...}, "web_visit_from_app": {...}}}
Nessun dato personale. Best-effort, thread-safe, scrittura atomica.
"""
from datetime import datetime, timedelta
from pathlib import Path

from monthly_ledger import JsonDoc, prune_keys_before

_SCRIPT_DIR = Path(__file__).resolve().parent
_METRICS_FILE = _SCRIPT_DIR / "_metrics.json"
_VALID_EVENTS = ("app_open", "web_visit_from_app", "payment_from_app")
# Retention: i giorni piu' vecchi di cosi' vengono potati a ogni incremento
# (prima il file cresceva per sempre). Il funnel admin legge al massimo
# l'ultimo anno.
_KEEP_DAYS = 400


def _norm_platform(p):
    p = (p or "").strip().lower()
    return p if p in ("android", "ios") else "unknown"


def _prune(d, today=None):
    """Rimuove in place le chiavi giorno piu' vecchie di _KEEP_DAYS. Le chiavi
    sono 'YYYY-MM-DD', quindi il confronto lessicale coincide con quello
    cronologico; chiavi di altra forma restano intatte."""
    today = today or datetime.now()
    cutoff = (today - timedelta(days=_KEEP_DAYS)).strftime("%Y-%m-%d")
    prune_keys_before(d, cutoff, key_len=10)


# Lock, lettura con default, potatura e scrittura atomica best-effort: JsonDoc.
_DOC = JsonDoc(lambda: _METRICS_FILE, prune=lambda d: _prune(d))
_lock = _DOC.lock


def _load():
    return _DOC.load()


def _save(d):
    _DOC.save(d)


def incr(event, platform, day=None):
    if event not in _VALID_EVENTS:
        return
    plat = _norm_platform(platform)
    day = day or datetime.now().strftime("%Y-%m-%d")
    with _DOC.mutate() as d:
        bucket = d.setdefault(day, {}).setdefault(event, {})
        bucket[plat] = int(bucket.get(plat, 0)) + 1


def read_range(days):
    d = _DOC.read()
    out = {e: {p: 0 for p in ("android", "ios", "unknown")} for e in _VALID_EVENTS}
    for day in days:
        for e in _VALID_EVENTS:
            for p, n in (d.get(day, {}).get(e, {}) or {}).items():
                out.setdefault(e, {}).setdefault(p, 0)
                out[e][p] += int(n)
    return out
