"""metrics_store.py — Contatori aggregati anonimi per il funnel app->web.
Struttura: {"YYYY-MM-DD": {"app_open": {"android": N, ...}, "web_visit_from_app": {...}}}
Nessun dato personale. Best-effort, thread-safe, scrittura atomica.
"""
import json, os, threading
from datetime import datetime
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_METRICS_FILE = _SCRIPT_DIR / "_metrics.json"
_lock = threading.Lock()
_VALID_EVENTS = ("app_open", "web_visit_from_app", "payment_from_app")


def _norm_platform(p):
    p = (p or "").strip().lower()
    return p if p in ("android", "ios") else "unknown"


def _load():
    try:
        with open(_METRICS_FILE, "r", encoding="utf-8") as f:
            d = json.load(f)
            return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _save(d):
    tmp = _METRICS_FILE.with_suffix(_METRICS_FILE.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
        f.flush()
        try: os.fsync(f.fileno())
        except OSError: pass
    os.replace(str(tmp), str(_METRICS_FILE))


def incr(event, platform, day=None):
    if event not in _VALID_EVENTS:
        return
    plat = _norm_platform(platform)
    day = day or datetime.now().strftime("%Y-%m-%d")
    with _lock:
        d = _load()
        bucket = d.setdefault(day, {}).setdefault(event, {})
        bucket[plat] = int(bucket.get(plat, 0)) + 1
        try: _save(d)
        except Exception: pass


def read_range(days):
    with _lock:
        d = _load()
    out = {e: {p: 0 for p in ("android", "ios", "unknown")} for e in _VALID_EVENTS}
    for day in days:
        for e in _VALID_EVENTS:
            for p, n in (d.get(day, {}).get(e, {}) or {}).items():
                out.setdefault(e, {}).setdefault(p, 0)
                out[e][p] += int(n)
    return out
