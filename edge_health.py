"""edge_health — salute di edge-tts su finestra scorrevole e allerta admin (modulo foglia).

Nato dall'incidente del 10/10/2026: l'endpoint storico di edge-tts rispondeva
403 a una richiesta su quattro e decine di migliaia di chunk al giorno
finivano in silenzio, scoperto per caso leggendo i log. Il fix stava in un
aggiornamento della libreria; nessun segnale lo diceva all'admin.

`edge_engine` registra qui ogni tentativo (`record_attempt`, con la firma
dell'errore) e l'esito finale di ogni chiamata (`record_call`: False = il
chunk e' diventato silenzio). Su una finestra di `ABM_EDGE_ALERT_WINDOW_SEC`,
con almeno `ABM_EDGE_ALERT_MIN_CALLS` chiamate, l'allerta scatta se:

- le chiamate finite in silenzio superano `ABM_EDGE_ALERT_FAIL_PCT` %, oppure
- i tentativi falliti (poi magari recuperati dal retry) superano
  `ABM_EDGE_ALERT_RETRY_PCT` %: il degrado si vede prima che arrivi ai libri.

L'allerta chiama il notifier registrato con `set_notifier(fn)` (lo fa
`audiobook_app`, che lo collega all'email admin) in un thread daemon: l'SMTP
non deve fermare il loop asyncio del job. Al massimo un'allerta ogni
`ABM_EDGE_ALERT_COOLDOWN_SEC`; `ABM_EDGE_ALERT=0` la spegne. Stato solo in
memoria (processo singolo): un riavvio azzera finestra e cooldown.

Importa solo stdlib e foglie.
"""
import importlib.metadata
import json
import threading
import time
import urllib.request
from collections import Counter

from env_utils import env_bool, env_float, env_int

_BUCKET_SEC = 60
_TOP_ERRORS = 5

_lock = threading.Lock()
# minuto (epoch // 60) -> {"calls", "failed", "attempts", "attempt_errors", "errors": Counter}
_buckets = {}
_last_alert = 0.0
_notifier = None


def window_sec():
    return env_int("ABM_EDGE_ALERT_WINDOW_SEC", 900, floor=_BUCKET_SEC)


def _thresholds():
    return (env_int("ABM_EDGE_ALERT_MIN_CALLS", 40, floor=1),
            env_float("ABM_EDGE_ALERT_FAIL_PCT", 2.0, floor=0.0),
            env_float("ABM_EDGE_ALERT_RETRY_PCT", 20.0, floor=0.0),
            env_int("ABM_EDGE_ALERT_COOLDOWN_SEC", 21600, floor=0))


def set_notifier(fn):
    """`fn(snapshot)` viene chiamata (in un thread) quando scatta l'allerta."""
    global _notifier
    _notifier = fn


def reset():
    """Azzera finestra e cooldown (test, reset da console)."""
    global _last_alert
    with _lock:
        _buckets.clear()
        _last_alert = 0.0


def error_signature(exc):
    """Etichetta breve e stabile di un errore edge-tts, per raggruppare.

    Lo status HTTP dell'handshake websocket (aiohttp `WSServerHandshakeError`)
    viene prima del testo: "HTTP 403" accomuna messaggi che differiscono per
    URL o request id."""
    if exc is None:
        return ""
    status = getattr(exc, "status", None)
    if isinstance(status, int):
        return f"HTTP {status}"
    if isinstance(exc, TimeoutError):
        return "timeout"
    msg = " ".join(str(exc).split())[:80]
    name = type(exc).__name__
    return f"{name}: {msg}" if msg else name


def _bucket_locked(now):
    key = int(now // _BUCKET_SEC)
    b = _buckets.get(key)
    if b is None:
        b = _buckets[key] = {"calls": 0, "failed": 0, "attempts": 0,
                             "attempt_errors": 0, "errors": Counter()}
        cutoff = key - window_sec() // _BUCKET_SEC
        for k in [k for k in _buckets if k < cutoff]:
            del _buckets[k]
    return b


def record_attempt(error=None, now=None):
    """Un tentativo edge-tts: `error` e' la firma (vuota = riuscito)."""
    now = time.time() if now is None else float(now)
    with _lock:
        b = _bucket_locked(now)
        b["attempts"] += 1
        if error:
            b["attempt_errors"] += 1
            b["errors"][str(error)[:120]] += 1


def _snapshot_locked(now):
    first = int((now - window_sec()) // _BUCKET_SEC) + 1
    tot = {"calls": 0, "failed": 0, "attempts": 0, "attempt_errors": 0}
    errors = Counter()
    for k, b in _buckets.items():
        if k < first:
            continue
        for f in tot:
            tot[f] += b[f]
        errors.update(b["errors"])
    tot["fail_pct"] = round(100.0 * tot["failed"] / tot["calls"], 2) if tot["calls"] else 0.0
    tot["retry_pct"] = (round(100.0 * tot["attempt_errors"] / tot["attempts"], 2)
                        if tot["attempts"] else 0.0)
    tot["top_errors"] = errors.most_common(_TOP_ERRORS)
    tot["window_sec"] = window_sec()
    return tot


def snapshot(now=None):
    now = time.time() if now is None else float(now)
    with _lock:
        snap = _snapshot_locked(now)
    snap["library_version"] = library_version()
    return snap


def _breach(snap, min_calls, fail_pct, retry_pct):
    """Motivo dell'allerta ("" = sotto soglia)."""
    if snap["calls"] < min_calls:
        return ""
    if snap["fail_pct"] > fail_pct:
        return "silence"
    if snap["retry_pct"] > retry_pct:
        return "retries"
    return ""


def record_call(ok, now=None):
    """Esito finale di una chiamata (False = chunk sostituito da silenzio).
    Ritorna True se questa chiamata ha fatto partire l'allerta."""
    global _last_alert
    now = time.time() if now is None else float(now)
    min_calls, fail_pct, retry_pct, cooldown = _thresholds()
    with _lock:
        b = _bucket_locked(now)
        b["calls"] += 1
        if not ok:
            b["failed"] += 1
        if not env_bool("ABM_EDGE_ALERT", True) or _notifier is None:
            return False
        if _last_alert and now - _last_alert < cooldown:
            return False
        snap = _snapshot_locked(now)
        reason = _breach(snap, min_calls, fail_pct, retry_pct)
        if not reason:
            return False
        _last_alert = now
        notifier = _notifier
    snap.update(reason=reason, fail_threshold_pct=fail_pct,
                retry_threshold_pct=retry_pct, cooldown_sec=cooldown,
                library_version=library_version())
    print(f"[edge-health] ALLERTA {reason}: {snap['failed']}/{snap['calls']} chiamate "
          f"in silenzio ({snap['fail_pct']}%), {snap['attempt_errors']}/{snap['attempts']} "
          f"tentativi falliti ({snap['retry_pct']}%), top: {snap['top_errors'][:3]}", flush=True)
    threading.Thread(target=_notify, args=(notifier, snap),
                     name="edge-health-alert", daemon=True).start()
    return True


def _notify(notifier, snap):
    try:
        notifier(snap)
    except Exception as e:  # noqa: BLE001 - l'allerta non deve mai far cadere nulla
        print(f"[edge-health] notifica fallita: {e}", flush=True)


def library_version():
    """Versione installata di edge-tts ("" se non leggibile)."""
    try:
        return importlib.metadata.version("edge-tts")
    except importlib.metadata.PackageNotFoundError:
        return ""


def latest_release(timeout=5.0):
    """Ultima versione di edge-tts su PyPI ("" se non raggiungibile).
    Chiamata solo dal thread dell'allerta, mai dal percorso di sintesi."""
    try:
        with urllib.request.urlopen("https://pypi.org/pypi/edge-tts/json", timeout=timeout) as r:
            return str(json.load(r).get("info", {}).get("version") or "")
    except (OSError, ValueError) as e:
        print(f"[edge-health] versione PyPI non leggibile: {e}", flush=True)
        return ""
