"""load_metrics.py — Telemetria di CARICO del servizio.

Modulo FOGLIA: nessun import di progetto (regola anti-import-circolare,
CLAUDE.md §1). Riceve la directory dati via configure().

Perche' esiste
--------------
Nessuna metrica di carico era persistita: RAM e swap finivano solo su stdout
(_log_memory_stats, ogni 300s), i rifiuti per tetto globale solo in un print,
attese e durate della coda di assembly idem, CPU e disco non erano campionati
affatto. I tre incidenti gravi del servizio — freeze da RAM+swap esauriti,
disco al 100% per il cleanup loop morto, disco al 100% per lo zip runaway —
erano tutti preceduti da un segnale che nessuno registrava.

Modello dei dati
----------------
I campioni non vengono salvati uno per uno: confluiscono in BUCKET da 5 minuti
(min/max/media per i gauge, somma per i contatori, istogramma per le durate).
Un bucket chiuso viene scritto in append su load_metrics_YYYY-MM.jsonl. Il
risultato e' ~5 MB al mese, ispezionabile con tail e grep durante un incidente
(vedi docs/FORENSICS_PLAYBOOK.md), contro i ~50 MB dei campioni grezzi.

Il bucket in corso vive in RAM: un riavvio perde al massimo 5 minuti, e il
riavvio stesso viene registrato dal contatore `boot` del bucket successivo.

Tutto e' best-effort: questo modulo viene chiamato da dentro run_generation e
dal path di /api/generate. Un'eccezione qui ucciderebbe un job pagato, quindi
nessuna funzione pubblica solleva mai.
"""
import json
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ENABLED = (os.environ.get("ABM_LOAD_METRICS_ENABLED", "true").strip().lower()
           not in ("0", "false", "no", "off"))
SAMPLE_SEC = int(os.environ.get("ABM_LOAD_METRICS_SAMPLE_SEC", "30"))
BUCKET_SEC = int(os.environ.get("ABM_LOAD_METRICS_BUCKET_SEC", "300"))
RETENTION_MONTHS = int(os.environ.get("ABM_LOAD_METRICS_RETENTION_MONTHS", "4"))

# Confini dei bin, in secondi. L'ottavo bin e' overflow (> 20 min).
_BINS = (10, 30, 60, 120, 300, 600, 1200)
_NBINS = len(_BINS) + 1

_FILE_PREFIX = "load_metrics_"

_lock = threading.Lock()
_data_dir = None          # Path, iniettata da configure()
_buckets = {}             # {t_start: bucket} — quello corrente piu' eventuali arretrati


def configure(data_dir):
    """Inietta la directory dati. Da chiamare una volta allo startup."""
    global _data_dir
    with _lock:
        _data_dir = Path(data_dir)


def reset_for_tests():
    """Azzera lo stato in memoria. Solo per i test."""
    with _lock:
        _buckets.clear()


def _bucket_start(ts):
    return int(ts // BUCKET_SEC) * BUCKET_SEC


def _month_of(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m")


def _new_bucket(t):
    return {"t": t, "n": 0, "g": {}, "c": {}, "h": {}}


def _bucket_for(now):
    """Bucket in cui ricade `now`. Chiamare con _lock tenuto."""
    t = _bucket_start(now)
    b = _buckets.get(t)
    if b is None:
        b = _buckets[t] = _new_bucket(t)
    return b


def _current_bucket():
    """Ultimo bucket aperto, o None. Uso diagnostico e nei test."""
    with _lock:
        if not _buckets:
            return None
        return _buckets[max(_buckets)]


def sample(now=None, **gauges):
    """Registra i valori istantanei nel bucket corrente.

    I gauge assenti dalla chiamata non entrano nel conteggio: fuori da Linux
    mancano le metriche di macchina e la CPU richiede due letture consecutive
    di /proc/stat, quindi i campioni sono disomogenei per costruzione.
    """
    if not ENABLED:
        return
    try:
        now = time.time() if now is None else now
        with _lock:
            b = _bucket_for(now)
            b["n"] += 1
            g = b["g"]
            for name, value in gauges.items():
                if value is None:
                    continue
                v = float(value)
                acc = g.get(name)
                if acc is None:
                    g[name] = [v, v, v, 1]
                else:
                    if v < acc[0]:
                        acc[0] = v
                    if v > acc[1]:
                        acc[1] = v
                    acc[2] += v
                    acc[3] += 1
    except Exception:
        pass


def incr(counter, n=1, now=None):
    """Incrementa un contatore del bucket corrente."""
    if not ENABLED:
        return
    try:
        now = time.time() if now is None else now
        with _lock:
            c = _bucket_for(now)["c"]
            c[counter] = c.get(counter, 0) + int(n)
    except Exception:
        pass


def _bin_index(seconds):
    for i, edge in enumerate(_BINS):
        if seconds < edge:
            return i
    return _NBINS - 1


def observe(hist, seconds, premium=False, now=None):
    """Inserisce una durata nell'istogramma, ramo free o premium."""
    if not ENABLED:
        return
    try:
        now = time.time() if now is None else now
        key = hist + "_p" if premium else hist
        idx = _bin_index(float(seconds))
        with _lock:
            h = _bucket_for(now)["h"]
            arr = h.get(key)
            if arr is None:
                arr = h[key] = [0] * _NBINS
            arr[idx] += 1
    except Exception:
        pass


def _serialize(b):
    """Bucket interno -> riga di file: i gauge passano da somma a media."""
    return {
        "t": b["t"],
        "n": b["n"],
        "g": {k: [v[0], v[1], round(v[2] / v[3], 2) if v[3] else 0.0, v[3]]
              for k, v in b["g"].items()},
        "c": dict(b["c"]),
        "h": {k: list(v) for k, v in b["h"].items()},
    }


def flush(now=None):
    """Scrive i bucket il cui intervallo e' concluso. Ritorna quanti ne ha scritti."""
    if not ENABLED:
        return 0
    try:
        now = time.time() if now is None else now
        cutoff = _bucket_start(now)
        with _lock:
            if _data_dir is None:
                return 0
            ready = sorted(t for t in _buckets if t < cutoff)
            rows = [(t, _serialize(_buckets[t])) for t in ready]
        written = 0
        for t, row in rows:
            path = Path(_data_dir) / f"{_FILE_PREFIX}{_month_of(t)}.jsonl"
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                with open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, separators=(",", ":")) + "\n")
                written += 1
            except OSError:
                # Disco pieno o path non scrivibile: il bucket viene comunque
                # scartato sotto. Trattenerlo farebbe crescere la RAM proprio
                # nella condizione che questa telemetria deve sorvegliare.
                pass
        with _lock:
            for t, _row in rows:
                _buckets.pop(t, None)
        return written
    except Exception:
        return 0
