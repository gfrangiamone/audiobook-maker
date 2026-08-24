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


# ----------------------------------------------------------------------
# LETTURA E AGGREGAZIONE
# ----------------------------------------------------------------------
# Le finestre 24h/7d/28d sono scorrevoli a partire da adesso; "month" parte
# dal primo del mese corrente. Lo step della timeline e' scelto per tenere il
# numero di barre fra 28 e 48: leggibile in un modale senza scroll.
_TIMELINE_STEP = {"24h": 1800, "7d": 14400, "28d": 86400, "month": 86400}
_DEFAULT_WINDOW = "24h"


def _window_bounds(window, now):
    """(from_ts, to_ts) della finestra richiesta."""
    if window == "7d":
        return now - 7 * 86400, now
    if window == "28d":
        return now - 28 * 86400, now
    if window == "month":
        d = datetime.fromtimestamp(now, timezone.utc)
        start = datetime(d.year, d.month, 1, tzinfo=timezone.utc).timestamp()
        return start, now
    return now - 86400, now


def _iter_rows(from_ts, to_ts):
    """Righe dei file mensili che ricadono nella finestra, in ordine di tempo.

    Legge anche i bucket ancora in RAM: senza di essi la finestra 24h
    perderebbe fino a 5 minuti proprio in coda, cioe' la parte che l'admin
    guarda per prima quando sta indagando un problema in corso.
    """
    if _data_dir is None:
        return []
    months = set()
    t = from_ts
    while t <= to_ts:
        months.add(_month_of(t))
        t += 86400
    months.add(_month_of(to_ts))
    rows = []
    for m in sorted(months):
        path = Path(_data_dir) / f"{_FILE_PREFIX}{m}.jsonl"
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue          # riga troncata da un crash: si salta
                    if from_ts <= row.get("t", 0) <= to_ts:
                        rows.append(row)
        except OSError:
            continue
    with _lock:
        live = [_serialize(b) for t0, b in _buckets.items() if from_ts <= t0 <= to_ts]
    rows.extend(live)
    rows.sort(key=lambda r: r["t"])
    return rows


def _first_sample_ts():
    """Epoch del campione piu' vecchio disponibile, o None."""
    if _data_dir is None:
        return None
    try:
        files = sorted(Path(_data_dir).glob(f"{_FILE_PREFIX}*.jsonl"))
    except OSError:
        return None
    for path in files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    try:
                        return int(json.loads(line)["t"])
                    except (ValueError, KeyError):
                        continue
        except OSError:
            continue
    return None


def _peak(rows, name):
    vals = [r["g"][name][1] for r in rows if name in r.get("g", {})]
    return max(vals) if vals else 0


def _low(rows, name):
    vals = [r["g"][name][0] for r in rows if name in r.get("g", {})]
    return min(vals) if vals else 0


def _avg(rows, name):
    num = den = 0.0
    for r in rows:
        acc = r.get("g", {}).get(name)
        if acc:
            num += acc[2] * acc[3]
            den += acc[3]
    return round(num / den, 2) if den else 0.0


def _sum(rows, name):
    return sum(int(r.get("c", {}).get(name, 0)) for r in rows)


def _hist(rows, name):
    total = [0] * _NBINS
    for r in rows:
        arr = r.get("h", {}).get(name)
        if arr:
            for i, v in enumerate(arr[:_NBINS]):
                total[i] += int(v)
    return total


def _percentile(bins, pct):
    """Percentile approssimato per interpolazione lineare dentro il bin.

    Approccio standard degli histogram Prometheus: l'errore e' dell'ordine
    dell'ampiezza del bin, irrilevante per decidere se una coda e' sana, e
    costa un ordine di grandezza in meno rispetto a conservare i campioni.
    Nel bin di overflow non esiste un limite superiore: si ritorna il limite
    inferiore, che il frontend rende come "> 20 min".
    """
    total = sum(bins)
    if total <= 0:
        return 0.0
    target = total * (pct / 100.0)
    cumulative = 0
    for i, count in enumerate(bins):
        if count <= 0:
            continue
        if cumulative + count >= target:
            if i >= len(_BINS):
                return float(_BINS[-1])
            lo = 0.0 if i == 0 else float(_BINS[i - 1])
            hi = float(_BINS[i])
            frac = (target - cumulative) / count
            return round(lo + (hi - lo) * min(1.0, max(0.0, frac)), 1)
        cumulative += count
    return float(_BINS[-1])


def _hist_mean(bins):
    """Media approssimata: ogni bin pesa il proprio punto medio."""
    total = sum(bins)
    if total <= 0:
        return 0.0
    acc = 0.0
    for i, count in enumerate(bins):
        if i == 0:
            mid = _BINS[0] / 2.0
        elif i >= len(_BINS):
            mid = float(_BINS[-1])
        else:
            mid = (_BINS[i - 1] + _BINS[i]) / 2.0
        acc += mid * count
    return round(acc / total, 1)


def _pct_of_buckets(rows, predicate):
    """Percentuale di bucket della finestra che soddisfano il predicato."""
    if not rows:
        return 0.0
    return round(100.0 * sum(1 for r in rows if predicate(r)) / len(rows), 1)


def _timeline(rows, from_ts, to_ts, step):
    """Serie ricampionata: un punto per intervallo, con i picchi dell'intervallo."""
    points = []
    slot_start = int(from_ts // step) * step
    by_slot = {}
    for r in rows:
        s = int(r["t"] // step) * step
        cur = by_slot.setdefault(s, {"gen": 0, "gen_p": 0, "ram": 0, "rej": 0})
        g = r.get("g", {})
        if "gen" in g:
            cur["gen"] = max(cur["gen"], g["gen"][1])
        if "gen_p" in g:
            cur["gen_p"] = max(cur["gen_p"], g["gen_p"][1])
        if "ram" in g:
            cur["ram"] = max(cur["ram"], g["ram"][1])
        c = r.get("c", {})
        cur["rej"] += int(c.get("rej_busy", 0)) + int(c.get("rej_busy_p", 0))
    t = slot_start
    while t <= to_ts:
        p = by_slot.get(t, {"gen": 0, "gen_p": 0, "ram": 0, "rej": 0})
        points.append({"t": t, "gen": round(p["gen"], 1), "gen_p": round(p["gen_p"], 1),
                       "ram": round(p["ram"], 1), "rej": p["rej"]})
        t += step
    return points


def query(window, now=None, global_cap=0, assembly_slots=0):
    """Aggrega la finestra richiesta. Non solleva mai: al peggio ritorna zeri.

    global_cap / assembly_slots servono a calcolare le percentuali di tempo in
    saturazione: sono configurazione dell'app, che questo modulo foglia non
    puo' leggere da solo.
    """
    try:
        now = time.time() if now is None else now
        if window not in _TIMELINE_STEP:
            window = _DEFAULT_WINDOW
        from_ts, to_ts = _window_bounds(window, now)
        rows = _iter_rows(from_ts, to_ts)
        step = _TIMELINE_STEP[window]
        span = max(1.0, to_ts - from_ts)
        coverage = min(100.0, round(100.0 * len(rows) * BUCKET_SEC / span, 1))

        h_wait, h_wait_p = _hist(rows, "asm_wait"), _hist(rows, "asm_wait_p")
        h_enc = _hist(rows, "enc")
        h_job, h_job_p = _hist(rows, "job"), _hist(rows, "job_p")
        done, done_p = _sum(rows, "done"), _sum(rows, "done_p")
        err, err_p = _sum(rows, "err"), _sum(rows, "err_p")
        cancel = _sum(rows, "cancel")
        total_jobs = done + done_p + err + err_p + cancel

        return {
            "meta": {
                "window": window, "from": int(from_ts), "to": int(to_ts),
                "buckets": len(rows), "coverage_pct": coverage,
                "first_sample_ts": _first_sample_ts(),
                "timeline_step_sec": step,
                "bucket_sec": BUCKET_SEC,
            },
            "job": {
                "gen_peak": _peak(rows, "gen"), "gen_avg": _avg(rows, "gen"),
                "gen_premium_peak": _peak(rows, "gen_p"),
                "gen_premium_avg": _avg(rows, "gen_p"),
                "in_ram_peak": _peak(rows, "jobs"), "in_ram_avg": _avg(rows, "jobs"),
                "rejected_free": _sum(rows, "rej_busy"),
                "rejected_premium": _sum(rows, "rej_busy_p"),
                "saturation_pct": _pct_of_buckets(
                    rows, lambda r: global_cap > 0
                    and r.get("g", {}).get("gen", [0, 0])[1] >= global_cap),
            },
            "ffmpeg": {
                "asm_peak": _peak(rows, "asm_h"), "asm_avg": _avg(rows, "asm_h"),
                "queue_peak": _peak(rows, "asm_q"),
                "wait_avg": _hist_mean(h_wait), "wait_p50": _percentile(h_wait, 50),
                "wait_p95": _percentile(h_wait, 95),
                "wait_premium_avg": _hist_mean(h_wait_p),
                "wait_premium_p95": _percentile(h_wait_p, 95),
                "encode_p50": _percentile(h_enc, 50), "encode_p95": _percentile(h_enc, 95),
                "timeouts": _sum(rows, "asm_timeout"),
                "slots_full_pct": _pct_of_buckets(
                    rows, lambda r: assembly_slots > 0
                    and r.get("g", {}).get("asm_h", [0, 0])[1] >= assembly_slots),
            },
            "machine": {
                "ram_peak": _peak(rows, "ram"), "ram_avg": _avg(rows, "ram"),
                "swap_peak": _peak(rows, "swap"),
                "rss_peak": _peak(rows, "rss"), "rss_avg": _avg(rows, "rss"),
                "cpu_peak": _peak(rows, "cpu"), "cpu_avg": _avg(rows, "cpu"),
                "iowait_peak": _peak(rows, "iowait"),
                "load_peak": _peak(rows, "load"),
                "threads_peak": _peak(rows, "threads"),
                "disk_peak": _peak(rows, "disk"),
                "disk_free_gb_min": _low(rows, "disk_free_gb"),
            },
            "quality": {
                "completed": done + done_p, "completed_premium": done_p,
                "errors": err + err_p, "errors_premium": err_p,
                "cancelled": cancel,
                "error_pct": (round(100.0 * (err + err_p) / total_jobs, 1)
                              if total_jobs else 0.0),
                "chunk_failed": _sum(rows, "chunk_fail"),
                "job_p50": _percentile(h_job, 50), "job_p95": _percentile(h_job, 95),
                "job_premium_p50": _percentile(h_job_p, 50),
                "job_premium_p95": _percentile(h_job_p, 95),
            },
            "reliability": {
                "boots": _sum(rows, "boot"),
                "cleanup_restarts": _sum(rows, "cl_restart"),
                "cleanup_hb_max_sec": _peak(rows, "hb"),
                "memory_pressure": _sum(rows, "memp"),
            },
            "timeline": _timeline(rows, from_ts, to_ts, step),
        }
    except Exception:
        return {"meta": {"window": window, "buckets": 0, "coverage_pct": 0,
                         "first_sample_ts": None, "error": "aggregation failed"},
                "job": {}, "ffmpeg": {}, "machine": {}, "quality": {},
                "reliability": {}, "timeline": []}


def purge(now=None):
    """Elimina i file mensili oltre la retention. Ritorna quanti ne ha rimossi.

    RETENTION_MONTHS conta i mesi da conservare incluso quello corrente: con 4
    la finestra a 28 giorni e' sempre coperta, con margine per un mese corto.
    """
    try:
        now = time.time() if now is None else now
        if _data_dir is None:
            return 0
        d = datetime.fromtimestamp(now, timezone.utc)
        keep = set()
        year, month = d.year, d.month
        for _ in range(max(1, RETENTION_MONTHS)):
            keep.add(f"{year:04d}-{month:02d}")
            month -= 1
            if month == 0:
                month, year = 12, year - 1
        removed = 0
        for path in Path(_data_dir).glob(f"{_FILE_PREFIX}*.jsonl"):
            tag = path.stem[len(_FILE_PREFIX):]
            if tag and tag not in keep:
                try:
                    path.unlink()
                    removed += 1
                except OSError:
                    pass
        return removed
    except Exception:
        return 0
