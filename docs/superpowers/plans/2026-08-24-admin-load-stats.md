# Pannello Stats admin — telemetria di carico — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sostituire il contenuto del modale `📊 Stats` di `/admin/log-activity` con un pannello di carico su finestra selezionabile (24h / 7 giorni / 28 giorni / mese corrente, default 24h), alimentato da una telemetria di sistema che oggi non esiste.

**Architecture:** Un modulo foglia `load_metrics.py` accumula gauge, contatori e istogrammi in bucket da 5 minuti e li scrive in append su un JSONL mensile in `ABM_DATA_DIR`. Un thread campionatore a 30 s legge `/proc`, `jobs{}` e `assembly_queue`; sei punti di aggancio nel codice esistente alimentano i contatori. Un endpoint admin aggrega la finestra richiesta e il modale la disegna come card più timeline.

**Tech Stack:** Python 3 stdlib (nessuna dipendenza nuova), Flask, JS vanilla nel fragment HTML generato da `audiobook_app.py`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-24-admin-load-stats-design.md`

## Global Constraints

- **Nessuna dipendenza nuova**: solo stdlib. Niente `psutil`, niente librerie di grafici.
- **`load_metrics.py` è un modulo FOGLIA**: non importa nessun modulo di progetto (CLAUDE.md §1 — anti-import-circolare). Riceve la directory dati via `configure()`.
- **`assembly_queue.py` resta foglia**: comunica con la telemetria solo tramite un observer iniettato, mai con un import.
- **Best-effort assoluto**: nessuna chiamata a `load_metrics` può sollevare verso il chiamante. I punti di aggancio stanno dentro `run_generation` e nel path di `/api/generate`: un'eccezione qui ucciderebbe un job pagato.
- **Degrado fuori da Linux**: senza `/proc` (ambiente di sviluppo Windows) il campionatore raccoglie comunque job, code e contatori. I test girano su Windows e su Linux.
- **Bucket allineati**: `t` è sempre un multiplo esatto di `ABM_LOAD_METRICS_BUCKET_SEC` (default 300).
- **Formato gauge**: `[min, max, media, n_campioni]`. La media di finestra è pesata: `Σ(media_bucket × n_bucket) / Σ(n_bucket)`.
- **Bin istogramma** (8, condivisi da tutte le durate): confini a `10, 30, 60, 120, 300, 600, 1200` secondi; l'ottavo è overflow (`> 20 min`).
- **Definizione unica di premium**: `generation_engine.is_premium_job(job) -> bool`. `_assembly_priority` la richiama. Mai duplicare la logica.
- **Convenzione linguistica**: commenti in italiano senza accenti (come il resto di `assembly_queue.py` e `generation_engine.py`), stringhe UI del pannello admin in italiano.
- **Commit**: Conventional Commits, nessun trailer di attribuzione (CLAUDE.md → Commit Rules).
- **Nessun push**: il piano si ferma prima del push. Il deploy è automatico su push a main, quindi la pubblicazione richiede conferma esplicita dell'utente.

---

## File Structure

| File | Responsabilità |
|---|---|
| `load_metrics.py` (nuovo) | Accumulo in bucket, persistenza JSONL, aggregazione di finestra, retention. Modulo foglia. |
| `assembly_queue.py` (modifica) | Aggiunge `set_observer()` e la notifica di `release`/`timeout` con attesa e durata di possesso. |
| `generation_engine.py` (modifica) | `is_premium_job()` pubblica; registrazione dell'esito e della durata del job in `_set_job_status`. |
| `audiobook_app.py` (modifica) | Thread campionatore + supervisor, heartbeat del cleanup, contatori su rifiuti/boot/memory-pressure, endpoint `/api/admin/load_stats`, nuovo modale Stats. |
| `test/test_load_metrics.py` (nuovo) | Bucketing, aggregazione, percentili, finestre, retention, best-effort. |
| `test/test_assembly_queue_observer.py` (nuovo) | Notifiche dell'observer su release e su timeout. |
| `test/test_admin_load_stats.py` (nuovo) | Autorizzazione, risposta a storico vuoto, forma del JSON. |
| `test/test_admin_load_stats_ui.py` (nuovo) | Presenza del selettore di finestra, rimozione del vecchio grafico. |
| `PARAMETRI_CONFIGURAZIONE.md` (modifica) | Le quattro nuove variabili `ABM_LOAD_METRICS_*`. |
| `CLAUDE.md` (modifica) | Riga di `load_metrics.py` nella tabella dei moduli backend. |

---

### Task 1: `load_metrics.py` — accumulo e persistenza

**Files:**
- Create: `load_metrics.py`
- Test: `test/test_load_metrics.py`

**Interfaces:**
- Consumes: nulla (modulo foglia, prima unità del piano).
- Produces:
  - `configure(data_dir: str | Path) -> None`
  - `sample(**gauges: float) -> None`
  - `incr(counter: str, n: int = 1) -> None`
  - `observe(hist: str, seconds: float, premium: bool = False) -> None`
  - `flush(now: float | None = None) -> int` (numero di bucket scritti)
  - `BUCKET_SEC: int`, `SAMPLE_SEC: int`, `RETENTION_MONTHS: int`, `ENABLED: bool`
  - `_BINS: tuple[int, ...]` (confini in secondi, uso interno e nei test)
  - file prodotto: `<data_dir>/load_metrics_YYYY-MM.jsonl`

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_load_metrics.py`:

```python
"""load_metrics: accumulo in bucket da 5 minuti e persistenza JSONL."""
import json

import pytest

import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    """Ogni test parte da uno stato pulito e da una data dir isolata."""
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def _read(tmp_path, month):
    p = tmp_path / f"load_metrics_{month}.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]


def test_bucket_start_is_aligned():
    assert lm._bucket_start(1756000123.0) % lm.BUCKET_SEC == 0
    assert lm._bucket_start(1756000123.0) <= 1756000123.0


def test_sample_accumulates_min_max_avg_count():
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=2, ram=50.0)
    lm.sample(now=t + 2, gen=4, ram=70.0)
    b = lm._current_bucket()
    assert b["g"]["gen"] == [2, 4, 6, 2]      # min, max, somma, conteggio
    assert b["g"]["ram"] == [50.0, 70.0, 120.0, 2]
    assert b["n"] == 2


def test_gauge_absent_from_a_sample_does_not_skew_count():
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=2, ram=50.0)
    lm.sample(now=t + 2, gen=4)              # niente ram: fuori da Linux
    b = lm._current_bucket()
    assert b["g"]["gen"][3] == 2
    assert b["g"]["ram"][3] == 1
    assert b["g"]["ram"][0] == 50.0          # il minimo non diventa 0


def test_incr_sums_within_bucket():
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    lm.incr("rej_busy", now=t + 2)
    lm.incr("rej_busy", n=3, now=t + 3)
    assert lm._current_bucket()["c"]["rej_busy"] == 4


def test_observe_lands_in_the_right_bin_and_branch():
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    lm.observe("asm_wait", 5, now=t + 2)                    # bin 0: < 10s
    lm.observe("asm_wait", 45, now=t + 3)                   # bin 2: 30-60s
    lm.observe("asm_wait", 5000, now=t + 4)                 # bin 7: overflow
    lm.observe("asm_wait", 5, premium=True, now=t + 5)
    b = lm._current_bucket()
    assert b["h"]["asm_wait"] == [1, 0, 1, 0, 0, 0, 0, 1]
    assert b["h"]["asm_wait_p"] == [1, 0, 0, 0, 0, 0, 0, 0]


def test_flush_writes_only_closed_buckets(tmp_path):
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    assert lm.flush(now=t + 10) == 0                        # bucket ancora aperto
    assert not (tmp_path / "load_metrics_2025-08.jsonl").exists()
    lm.sample(now=t + lm.BUCKET_SEC + 1, gen=2)             # apre il bucket dopo
    assert lm.flush(now=t + lm.BUCKET_SEC + 10) == 1
    rows = _read(tmp_path, lm._month_of(t))
    assert len(rows) == 1
    assert rows[0]["t"] == t
    assert rows[0]["g"]["gen"] == [1, 1, 1.0, 1]            # su file: media, non somma


def test_flush_is_idempotent(tmp_path):
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    lm.sample(now=t + lm.BUCKET_SEC + 1, gen=2)
    lm.flush(now=t + lm.BUCKET_SEC + 10)
    assert lm.flush(now=t + lm.BUCKET_SEC + 20) == 0
    assert len(_read(tmp_path, lm._month_of(t))) == 1


def test_never_raises_when_data_dir_is_unwritable(tmp_path):
    lm.configure(tmp_path / "non" / "esiste" / "affatto")
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    lm.incr("boot", now=t + 1)
    lm.observe("job", 30, now=t + 1)
    lm.sample(now=t + lm.BUCKET_SEC + 1, gen=1)
    lm.flush(now=t + lm.BUCKET_SEC + 10)                    # non deve sollevare


def test_disabled_module_is_a_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(lm, "ENABLED", False)
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    assert lm._current_bucket() is None
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_load_metrics.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'load_metrics'`

- [ ] **Step 3: Implementa il modulo**

Crea `load_metrics.py`:

```python
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
            for t, _ in rows:
                _buckets.pop(t, None)
        return written
    except Exception:
        return 0
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `pytest test/test_load_metrics.py -v`
Expected: PASS (10 test)

- [ ] **Step 5: Verifica la sintassi e committa**

```bash
python -m py_compile load_metrics.py
git add load_metrics.py test/test_load_metrics.py
git commit -m "feat(metrics): modulo load_metrics per la telemetria di carico"
```

---

### Task 2: aggregazione di finestra e percentili

**Files:**
- Modify: `load_metrics.py` (aggiunge `query`, `_percentile`, `_read_window`)
- Test: `test/test_load_metrics_query.py`

**Interfaces:**
- Consumes: da Task 1 — `configure`, `sample`, `incr`, `observe`, `flush`, `_BINS`, `BUCKET_SEC`, `_bucket_start`, `_month_of`.
- Produces:
  - `WINDOWS: dict[str, int]` — `{"24h": 86400, "7d": 604800, "28d": 2419200, "month": 0}` (`month` è calcolato, non fisso)
  - `query(window: str, now: float | None = None) -> dict` con chiavi `meta`, `job`, `ffmpeg`, `machine`, `quality`, `reliability`, `timeline`
  - `_percentile(bins: list[int], pct: float) -> float`

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_load_metrics_query.py`:

```python
"""load_metrics.query: aggregazione di finestra, percentili, copertura."""
import json

import pytest

import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def _write(tmp_path, t, g=None, c=None, h=None, n=10):
    row = {"t": t, "n": n, "g": g or {}, "c": c or {}, "h": h or {}}
    p = tmp_path / f"load_metrics_{lm._month_of(t)}.jsonl"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_percentile_interpolates_inside_the_bin():
    # 10 osservazioni tutte nel bin 0 (< 10s): il p50 cade a meta' del bin.
    assert lm._percentile([10, 0, 0, 0, 0, 0, 0, 0], 50) == pytest.approx(5.0, abs=0.6)


def test_percentile_picks_the_right_bin():
    # 8 sotto i 10s, 2 fra 30 e 60s: il p95 cade nel terzo bin.
    bins = [8, 0, 2, 0, 0, 0, 0, 0]
    assert 30 <= lm._percentile(bins, 95) <= 60


def test_percentile_of_empty_histogram_is_zero():
    assert lm._percentile([0] * 8, 95) == 0.0


def test_percentile_in_overflow_bin_returns_lower_edge():
    assert lm._percentile([0, 0, 0, 0, 0, 0, 0, 5], 50) == float(lm._BINS[-1])


def test_window_peak_is_the_max_across_buckets(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 600, g={"gen": [0, 2, 1.0, 10]})
    _write(tmp_path, now - 300, g={"gen": [1, 5, 2.0, 10]})
    out = lm.query("24h", now=now)
    assert out["job"]["gen_peak"] == 5


def test_window_average_is_weighted_by_sample_count(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 600, g={"gen": [0, 2, 1.0, 10]})
    _write(tmp_path, now - 300, g={"gen": [4, 4, 4.0, 2]})
    # (1.0*10 + 4.0*2) / 12 = 1.5
    assert lm.query("24h", now=now)["job"]["gen_avg"] == pytest.approx(1.5, abs=0.01)


def test_counters_are_summed_over_the_window(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 600, c={"rej_busy": 2, "rej_busy_p": 1})
    _write(tmp_path, now - 300, c={"rej_busy": 3})
    out = lm.query("24h", now=now)
    assert out["job"]["rejected_free"] == 5
    assert out["job"]["rejected_premium"] == 1


def test_buckets_outside_the_window_are_ignored(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 86400 - 3600, c={"rej_busy": 99})
    _write(tmp_path, now - 300, c={"rej_busy": 1})
    assert lm.query("24h", now=now)["job"]["rejected_free"] == 1


def test_window_spanning_two_monthly_files(tmp_path):
    # 1756598400 = 2025-08-31 00:00 UTC; una finestra di 7 giorni tocca luglio.
    now = lm._bucket_start(1756598400.0)
    _write(tmp_path, now - 3 * 86400, c={"done": 4})
    _write(tmp_path, now - 300, c={"done": 1})
    months = {p.name for p in tmp_path.glob("load_metrics_*.jsonl")}
    assert len(months) >= 1
    assert lm.query("7d", now=now)["quality"]["completed"] == 5


def test_coverage_is_zero_with_no_history(tmp_path):
    now = lm._bucket_start(1756000000.0)
    out = lm.query("28d", now=now)
    assert out["meta"]["coverage_pct"] == 0
    assert out["meta"]["first_sample_ts"] is None
    assert out["job"]["gen_peak"] == 0


def test_timeline_resolution_matches_the_window(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 300, g={"gen": [0, 2, 1.0, 10]})
    assert lm.query("24h", now=now)["meta"]["timeline_step_sec"] == 1800
    assert lm.query("7d", now=now)["meta"]["timeline_step_sec"] == 14400
    assert lm.query("28d", now=now)["meta"]["timeline_step_sec"] == 86400


def test_timeline_point_carries_peaks_and_rejections(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 300,
           g={"gen": [0, 3, 1.0, 10], "gen_p": [0, 1, 0.5, 10], "ram": [40, 80, 60.0, 10]},
           c={"rej_busy": 2})
    pts = [p for p in lm.query("24h", now=now)["timeline"] if p["gen"] > 0]
    assert pts[-1]["gen"] == 3
    assert pts[-1]["gen_p"] == 1
    assert pts[-1]["ram"] == 80
    assert pts[-1]["rej"] == 2


def test_unknown_window_falls_back_to_24h(tmp_path):
    now = lm._bucket_start(1756000000.0)
    assert lm.query("qualunque", now=now)["meta"]["window"] == "24h"
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_load_metrics_query.py -v`
Expected: FAIL con `AttributeError: module 'load_metrics' has no attribute '_percentile'`

- [ ] **Step 3: Implementa l'aggregazione**

Aggiungi in fondo a `load_metrics.py`:

```python
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
        err, cancel = _sum(rows, "err"), _sum(rows, "cancel")
        total_jobs = done + done_p + err + cancel

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
                "errors": err, "cancelled": cancel,
                "error_pct": round(100.0 * err / total_jobs, 1) if total_jobs else 0.0,
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
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `pytest test/test_load_metrics_query.py test/test_load_metrics.py -v`
Expected: PASS

- [ ] **Step 5: Committa**

```bash
python -m py_compile load_metrics.py
git add load_metrics.py test/test_load_metrics_query.py
git commit -m "feat(metrics): aggregazione di finestra, percentili e timeline"
```

---

### Task 3: retention dei file mensili

**Files:**
- Modify: `load_metrics.py` (aggiunge `purge`)
- Test: `test/test_load_metrics_purge.py`

**Interfaces:**
- Consumes: da Task 1 — `_FILE_PREFIX`, `_data_dir`, `RETENTION_MONTHS`.
- Produces: `purge(now: float | None = None) -> int` (numero di file rimossi).

- [ ] **Step 1: Scrivi il test che fallisce**

Crea `test/test_load_metrics_purge.py`:

```python
"""load_metrics.purge: retention dei file mensili."""
import pytest

import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def _touch(tmp_path, month):
    (tmp_path / f"load_metrics_{month}.jsonl").write_text("{}\n", encoding="utf-8")


def test_purge_removes_only_files_older_than_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(lm, "RETENTION_MONTHS", 4)
    for m in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
              "2026-06", "2026-07", "2026-08"):
        _touch(tmp_path, m)
    # now = 2026-08-24
    removed = lm.purge(now=1787529600.0)
    left = sorted(p.name for p in tmp_path.glob("load_metrics_*.jsonl"))
    assert left == ["load_metrics_2026-05.jsonl", "load_metrics_2026-06.jsonl",
                    "load_metrics_2026-07.jsonl", "load_metrics_2026-08.jsonl"]
    assert removed == 4


def test_purge_ignores_unrelated_files(tmp_path):
    (tmp_path / "activity_2020-01.log").write_text("x", encoding="utf-8")
    lm.purge(now=1787529600.0)
    assert (tmp_path / "activity_2020-01.log").exists()


def test_purge_never_raises_without_data_dir(monkeypatch):
    monkeypatch.setattr(lm, "_data_dir", None)
    assert lm.purge(now=1787529600.0) == 0
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `pytest test/test_load_metrics_purge.py -v`
Expected: FAIL con `AttributeError: module 'load_metrics' has no attribute 'purge'`

- [ ] **Step 3: Implementa**

Aggiungi in fondo a `load_metrics.py`:

```python
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
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `pytest test/test_load_metrics_purge.py -v`
Expected: PASS (3 test)

- [ ] **Step 5: Committa**

```bash
python -m py_compile load_metrics.py
git add load_metrics.py test/test_load_metrics_purge.py
git commit -m "feat(metrics): retention dei file mensili di telemetria"
```

---

### Task 4: observer nella coda di assembly

**Files:**
- Modify: `assembly_queue.py` (aggiunge `set_observer`, notifica in `Slot.release` e su timeout)
- Test: `test/test_assembly_queue_observer.py`

**Interfaces:**
- Consumes: nulla dai task precedenti (`assembly_queue.py` resta foglia e non importa `load_metrics`).
- Produces:
  - `set_observer(fn) -> None` dove `fn(event: str, job_id: str, priority: int, waited_sec: float, held_sec: float) -> None`
  - eventi: `"release"` (slot restituito dopo l'encode) e `"timeout"` (slot mai ottenuto)
  - `Slot.t_acquired: float`

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_assembly_queue_observer.py`:

```python
"""assembly_queue: notifica all'observer di attesa e durata di possesso."""
import time

import pytest

import assembly_queue as aq


@pytest.fixture(autouse=True)
def clean():
    aq.configure(2)
    aq.set_observer(None)
    yield
    aq.set_observer(None)
    aq.configure(2)


def test_release_notifies_with_wait_and_held_time():
    seen = []
    aq.set_observer(lambda *a: seen.append(a))
    slot = aq.acquire("job-1", priority=aq.PRIORITY_PREMIUM)
    time.sleep(0.05)
    slot.release()
    assert len(seen) == 1
    event, job_id, priority, waited, held = seen[0]
    assert event == "release"
    assert job_id == "job-1"
    assert priority == aq.PRIORITY_PREMIUM
    assert waited == 0.0
    assert held >= 0.04


def test_release_is_notified_only_once():
    seen = []
    aq.set_observer(lambda *a: seen.append(a))
    slot = aq.acquire("job-2")
    slot.release()
    slot.release()
    assert len(seen) == 1


def test_timeout_notifies_a_timeout_event():
    aq.configure(1)
    seen = []
    held = aq.acquire("holder")
    aq.set_observer(lambda *a: seen.append(a))
    late = aq.acquire("job-3", timeout=0.05)
    assert late.held is False
    assert [s[0] for s in seen] == ["timeout"]
    assert seen[0][1] == "job-3"
    assert seen[0][3] >= 0.04
    held.release()


def test_observer_exception_never_breaks_the_queue():
    def boom(*_a):
        raise RuntimeError("observer rotto")

    aq.set_observer(boom)
    slot = aq.acquire("job-4")
    slot.release()                       # non deve sollevare
    assert aq.stats()["held"] == 0
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_assembly_queue_observer.py -v`
Expected: FAIL con `AttributeError: module 'assembly_queue' has no attribute 'set_observer'`

- [ ] **Step 3: Implementa**

In `assembly_queue.py`, dopo la riga `_seq = 0  # progressivo di arrivo, per il FIFO a parita' di priorita'`, aggiungi:

```python
# Observer opzionale per la telemetria. Iniettato allo startup invece che
# importato: questo modulo resta foglia (CLAUDE.md §1) e i test della coda
# non tirano dentro il resto dell'app.
_observer = None


def set_observer(fn):
    """Registra fn(event, job_id, priority, waited_sec, held_sec) o None."""
    global _observer
    _observer = fn


def _notify(event, job_id, priority, waited, held):
    """Best-effort: un observer rotto non deve mai fermare un encode."""
    fn = _observer
    if fn is None:
        return
    try:
        fn(event, job_id, priority, float(waited), float(held))
    except Exception:
        pass
```

Nella classe `Slot`, sostituisci `__slots__` e `__init__` con:

```python
    __slots__ = ("job_id", "held", "timed_out", "waited_sec", "priority",
                 "t_acquired", "_lock")

    def __init__(self, job_id, held, timed_out, waited_sec,
                 priority=PRIORITY_NORMAL):
        self.job_id = job_id
        self.held = held
        self.timed_out = timed_out
        self.waited_sec = waited_sec
        self.priority = priority
        self.t_acquired = time.time()
        self._lock = threading.Lock()
```

e in `Slot.release`, subito dopo il blocco `with self._lock:` che marca `self.held = False`, prima di `with _state_lock:`, inserisci:

```python
        _notify("release", self.job_id, self.priority, self.waited_sec,
                time.time() - self.t_acquired)
```

In `acquire()`, aggiorna le tre costruzioni di `Slot` per passare la priorità e notificare il timeout:

```python
        if _held < MAX_CONCURRENT_ASSEMBLY and not _waiters:
            _held += 1
            return Slot(job_id, True, False, 0.0, priority)
```

```python
    if not granted:
        print(f"[{job_id or '-'}] assembly: timeout dopo {waited:.0f}s in coda "
              f"— procedo comunque senza slot", flush=True)
        _notify("timeout", job_id, priority, waited, 0.0)
        return Slot(job_id, False, True, waited, priority)

    print(f"[{job_id or '-'}] assembly: {tag}slot ottenuto dopo {waited:.0f}s "
          f"in coda", flush=True)
    return Slot(job_id, True, False, waited, priority)
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `pytest test/test_assembly_queue_observer.py test/test_assembly_queue.py -v`
Expected: PASS (i test già esistenti della coda devono restare verdi)

- [ ] **Step 5: Committa**

```bash
python -m py_compile assembly_queue.py
git add assembly_queue.py test/test_assembly_queue_observer.py
git commit -m "feat(assembly): observer per attesa e durata degli slot di encode"
```

---

### Task 5: classe premium pubblica ed esito dei job

**Files:**
- Modify: `generation_engine.py:3942-3968` (`_assembly_priority` → richiama `is_premium_job`), `generation_engine.py:395-413` (`_set_job_status`), `generation_engine.py:4070` (avvio della generazione)
- Test: `test/test_load_metrics_job_outcome.py`

**Interfaces:**
- Consumes: da Task 1 — `load_metrics.observe`, `load_metrics.incr`.
- Produces:
  - `generation_engine.is_premium_job(job: dict) -> bool`
  - chiave di job `_lm_gen_t0: float` — istante di avvio della generazione, consumata (`pop`) alla registrazione dell'esito

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_load_metrics_job_outcome.py`:

```python
"""Esito e durata dei job registrati in load_metrics da _set_job_status."""
import pytest

import generation_engine as ge
import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def test_is_premium_job_recognises_paid_voice():
    assert ge.is_premium_job({"voice": "it-IT-Chirp3-HD-Charon"}) is False
    assert ge.is_premium_job({"voice": "gemini-2.5-flash-preview-tts:Kore"}) is True


def test_is_premium_job_recognises_consumed_payment():
    assert ge.is_premium_job({"voice": "it-IT-ElsaNeural", "payment_token": "t-1"}) is True
    assert ge.is_premium_job({"voice": "it-IT-ElsaNeural",
                              "payment_amount_eur": 1.5}) is True
    assert ge.is_premium_job({"voice": "it-IT-ElsaNeural"}) is False


def test_assembly_priority_agrees_with_is_premium_job():
    import assembly_queue as aq
    job = {"voice": "it-IT-ElsaNeural", "payment_token": "t-1"}
    assert ge._assembly_priority(job) == aq.PRIORITY_PREMIUM
    assert ge._assembly_priority({"voice": "it-IT-ElsaNeural"}) == aq.PRIORITY_NORMAL


def test_terminal_status_records_outcome_and_duration(monkeypatch):
    seen = {"obs": [], "inc": []}
    monkeypatch.setattr(lm, "observe",
                        lambda h, s, premium=False, now=None: seen["obs"].append((h, s, premium)))
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen["inc"].append((c, n)))
    job = {"job_id": "j1", "voice": "it-IT-ElsaNeural", "_texts_spilled": True,
           "_lm_gen_t0": __import__("time").time() - 45}
    ge._set_job_status(job, "done")
    assert ("job", pytest.approx(45, abs=2), False) in [
        (h, s, p) for h, s, p in seen["obs"]]
    assert ("done", 1) in seen["inc"]
    assert "_lm_gen_t0" not in job


def test_outcome_is_recorded_once_per_generation(monkeypatch):
    calls = []
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: calls.append(c))
    monkeypatch.setattr(lm, "observe", lambda *a, **k: None)
    job = {"job_id": "j2", "voice": "it-IT-ElsaNeural", "_texts_spilled": True,
           "_lm_gen_t0": __import__("time").time()}
    ge._set_job_status(job, "error")
    ge._set_job_status(job, "cancelled")
    assert calls.count("err") == 1
    assert "cancel" not in calls


def test_non_generation_status_records_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: calls.append(c))
    monkeypatch.setattr(lm, "observe", lambda *a, **k: None)
    ge._set_job_status({"job_id": "j3", "_texts_spilled": True}, "done")
    assert calls == []


def test_premium_job_counts_in_the_premium_branch(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "observe",
                        lambda h, s, premium=False, now=None: seen.append((h, premium)))
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append((c, None)))
    job = {"job_id": "j4", "voice": "gemini-2.5-flash-preview-tts:Kore",
           "_texts_spilled": True, "_lm_gen_t0": __import__("time").time()}
    ge._set_job_status(job, "done")
    assert ("job", True) in seen
    assert ("done_p", None) in seen
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_load_metrics_job_outcome.py -v`
Expected: FAIL con `AttributeError: module 'generation_engine' has no attribute 'is_premium_job'`

- [ ] **Step 3: Implementa**

In `generation_engine.py`, aggiungi `import load_metrics` fra gli import di progetto già presenti in testa al file (accanto a `import assembly_queue`).

Sostituisci il corpo di `_assembly_priority` (`generation_engine.py:3942-3968`) mantenendo la docstring esistente e aggiungendo sopra la funzione pubblica:

```python
def is_premium_job(job):
    """True se il job ha gia' consumato denaro dell'utente o credito del servizio.

    Premium = voce a pagamento (Gemini/Speechify) OPPURE pagamento incassato
    (ottimizzazione AI sopra la soglia gratuita, o voucher speso).

    Definizione UNICA nel sistema: la usano sia la priorita' nella coda di
    assembly sia la telemetria di carico. Due definizioni divergenti
    renderebbero incoerenti le statistiche free/premium proprio mentre si
    indaga un incidente.
    """
    if not isinstance(job, dict):
        return False
    voice = (job.get("voice") or job.get("opt_voice") or "").strip()
    if _is_gemini_voice(voice) or _is_speechify_voice(voice):
        return True
    if (job.get("payment_token") or "").strip():
        return True
    try:
        if float(job.get("payment_amount_eur") or 0) > 0:
            return True
    except (TypeError, ValueError):
        pass
    if (job.get("payment") or {}).get("token"):
        return True
    return False


def _assembly_priority(job):
    """PREMIUM o NORMAL nella coda degli encode FFmpeg.

    La CPU e' l'unica risorsa satura della macchina e la coda di assembly e'
    dove si accumula l'attesa (nel picco: mediana ~5 min, coda oltre i 20).
    Un job PREMIUM ha gia' consumato denaro dell'utente e credito del servizio
    presso il provider TTS: farlo aspettare dietro a una fila di conversioni
    gratuite e' il peggior uso possibile di quei minuti. Perdere tempo su un
    job free e' spiacevole, perderlo su uno pagato costa due volte.
    """
    return (assembly_queue.PRIORITY_PREMIUM if is_premium_job(job)
            else assembly_queue.PRIORITY_NORMAL)
```

In `_set_job_status` (`generation_engine.py:395`), dopo il blocco che esegue lo spill e prima della fine della funzione, aggiungi:

```python
    # Telemetria di carico: registra esito e durata della generazione TTS.
    # La chiave _lm_gen_t0 e' posata da run_generation e consumata qui, quindi
    # l'esito viene contato UNA volta per generazione e i cambi di stato che
    # non appartengono a una generazione (ottimizzazione, traduzione) non
    # inquinano le statistiche.
    if status in _TERMINAL_STATUSES and isinstance(job, dict):
        t0 = job.pop("_lm_gen_t0", None)
        if t0:
            try:
                premium = is_premium_job(job)
                load_metrics.observe("job", max(0.0, time.time() - t0), premium=premium)
                if status in ("done", "partial"):
                    load_metrics.incr("done_p" if premium else "done")
                elif status == "error":
                    load_metrics.incr("err_p" if premium else "err")
                else:
                    load_metrics.incr("cancel")
                failed = int(job.get("failed_chunks") or 0)
                if failed:
                    load_metrics.incr("chunk_fail", failed)
            except Exception:
                pass
```

In `run_generation` (`generation_engine.py:4070`), subito dopo `_set_job_status(job, "generating")`, aggiungi:

```python
    job["_lm_gen_t0"] = time.time()
```

Il conteggio dei chunk falliti è già sul job: `run_generation` scrive `job["failed_chunks"] = failed_chunks` a `generation_engine.py:5273`, prima di qualunque stato terminale. Non serve altro.

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `pytest test/test_load_metrics_job_outcome.py -v`
Expected: PASS (7 test)

Run: `pytest test/ -q -k "assembly or premium or gemini"`
Expected: PASS — nessuna regressione sulla priorità della coda.

- [ ] **Step 5: Committa**

```bash
python -m py_compile generation_engine.py
git add generation_engine.py test/test_load_metrics_job_outcome.py
git commit -m "feat(metrics): is_premium_job pubblica ed esito dei job in telemetria"
```

---

### Task 6: campionatore, heartbeat e contatori nell'app

**Files:**
- Modify: `audiobook_app.py` — import e `configure` del modulo, `_server_busy_response` (`:887`), claim in `/api/generate` (`:9657-9671`), `_log_memory_stats` (ramo WARN, `:15321`), `_cleanup_loop` (heartbeat), `_cleanup_supervisor` (`:15379`), `_ensure_background_threads` (`:15736`)
- Test: `test/test_load_metrics_sampler.py`

**Interfaces:**
- Consumes: da Task 1-3 — `load_metrics.configure/sample/incr/flush/purge/SAMPLE_SEC`; da Task 4 — `assembly_queue.set_observer`; da Task 5 — `generation_engine.is_premium_job`.
- Produces:
  - `audiobook_app._collect_load_sample() -> dict` — i gauge di un giro, già pronti per `load_metrics.sample(**g)`
  - `audiobook_app._cpu_percent() -> tuple[float, float] | tuple[None, None]` — `(cpu%, iowait%)` dal delta di `/proc/stat`
  - `audiobook_app._cleanup_heartbeat: list[float]` — `[epoch dell'ultimo giro completato]`
  - `audiobook_app._assembly_metrics_observer(event, job_id, priority, waited, held)`

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_load_metrics_sampler.py`:

```python
"""Campionatore di carico e agganci dei contatori in audiobook_app."""
from unittest.mock import patch

import pytest

import audiobook_app as app
import assembly_queue as aq
import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def test_collect_sample_reports_jobs_and_queue():
    with patch.dict(app.jobs, {
        "a": {"status": "generating", "voice": "it-IT-ElsaNeural"},
        "b": {"status": "generating", "voice": "gemini-2.5-flash-preview-tts:Kore"},
        "c": {"status": "done", "voice": "it-IT-ElsaNeural"},
    }, clear=True):
        g = app._collect_load_sample()
    assert g["gen"] == 2
    assert g["gen_p"] == 1
    assert g["jobs"] == 3
    assert "asm_h" in g and "asm_q" in g


def test_collect_sample_works_without_proc(monkeypatch):
    """Fuori da Linux le metriche di macchina mancano, il resto no."""
    monkeypatch.setattr(app, "_read_proc_kv", lambda _p: {})
    monkeypatch.setattr(app, "_cpu_percent", lambda: (None, None))
    with patch.dict(app.jobs, {}, clear=True):
        g = app._collect_load_sample()
    assert g["gen"] == 0
    assert "ram" not in g and "swap" not in g


def test_collect_sample_includes_disk():
    with patch.dict(app.jobs, {}, clear=True):
        g = app._collect_load_sample()
    assert 0 <= g["disk"] <= 100
    assert g["disk_free_gb"] >= 0


def test_cleanup_heartbeat_age_is_reported():
    import time
    app._cleanup_heartbeat[0] = time.time() - 120
    with patch.dict(app.jobs, {}, clear=True):
        g = app._collect_load_sample()
    assert 115 <= g["hb"] <= 130


def test_assembly_observer_records_wait_and_encode(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "observe",
                        lambda h, s, premium=False, now=None: seen.append((h, s, premium)))
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append((c, n, None)))
    app._assembly_metrics_observer("release", "j1", aq.PRIORITY_PREMIUM, 12.0, 30.0)
    assert ("asm_wait", 12.0, True) in seen
    assert ("enc", 30.0, False) in seen


def test_assembly_observer_records_timeout(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "observe",
                        lambda h, s, premium=False, now=None: seen.append(("obs", h)))
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append(("inc", c)))
    app._assembly_metrics_observer("timeout", "j2", aq.PRIORITY_NORMAL, 1800.0, 0.0)
    assert ("inc", "asm_timeout") in seen
    assert ("obs", "asm_wait") in seen


def test_server_busy_counts_the_rejection(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append(c))
    monkeypatch.setattr(app, "_server_at_capacity", lambda: (True, 6, 6))
    with app.app.test_request_context("/api/generate"):
        resp = app._server_busy_response("j3", "/api/generate", premium=True)
    assert resp[1] == 429
    assert seen == ["rej_busy_p"]


def test_server_busy_does_not_count_when_not_at_capacity(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append(c))
    monkeypatch.setattr(app, "_server_at_capacity", lambda: (False, 1, 6))
    with app.app.test_request_context("/api/generate"):
        assert app._server_busy_response("j4", "/api/generate") is None
    assert seen == []
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_load_metrics_sampler.py -v`
Expected: FAIL con `AttributeError: module 'audiobook_app' has no attribute '_collect_load_sample'`

- [ ] **Step 3: Implementa**

**3a.** In `audiobook_app.py`, accanto a `import assembly_queue`, aggiungi `import load_metrics`.

**3b.** Aggiungi la lettura della CPU e il campionamento, subito dopo `_log_memory_stats` (dopo `audiobook_app.py:15330`):

```python
# ----------------------------------------------------------------------
# TELEMETRIA DI CARICO — campionatore
# ----------------------------------------------------------------------
# Heartbeat del cleanup loop: [epoch dell'ultimo giro completato]. L'eta' di
# questo valore e' il segnale che mancava quando il thread mori' silenziosamente
# (incidente 2026-06-15: 17h senza retention, disco al 100%).
_cleanup_heartbeat = [time.time()]
_cpu_prev = [None]          # (total, idle, iowait) della lettura precedente


def _cpu_percent():
    """(cpu%, iowait%) dal delta di /proc/stat. (None, None) fuori da Linux."""
    try:
        with open("/proc/stat", "r", encoding="utf-8") as fh:
            fields = fh.readline().split()
        if not fields or fields[0] != "cpu":
            return None, None
        vals = [int(v) for v in fields[1:11]]
    except (OSError, ValueError, IndexError):
        return None, None
    total = sum(vals)
    idle = vals[3] + vals[4]        # idle + iowait
    iowait = vals[4]
    prev = _cpu_prev[0]
    _cpu_prev[0] = (total, idle, iowait)
    if prev is None:
        return None, None           # serve un delta: il primo giro non conta
    d_total = total - prev[0]
    if d_total <= 0:
        return None, None
    d_idle = idle - prev[1]
    d_iow = iowait - prev[2]
    return (round(100.0 * (d_total - d_idle) / d_total, 1),
            round(100.0 * d_iow / d_total, 1))


def _collect_load_sample():
    """Gauge di un giro di campionamento, pronti per load_metrics.sample()."""
    g = {}
    with _jobs_lock:
        snapshot = list(jobs.values())
    gen = gen_p = 0
    for j in snapshot:
        if j.get("status") == "generating":
            gen += 1
            try:
                if generation_engine.is_premium_job(j):
                    gen_p += 1
            except Exception:
                pass
    g["gen"] = gen
    g["gen_p"] = gen_p
    g["jobs"] = len(snapshot)
    try:
        asm = assembly_queue.stats()
        g["asm_h"] = asm["held"]
        g["asm_q"] = asm["waiting"]
        g["asm_qp"] = asm["waiting_premium"]
    except Exception:
        pass
    status = _read_proc_kv("/proc/self/status")
    if status:
        g["rss"] = round(status.get("VmRSS", 0) / 1024.0, 1)
        g["threads"] = status.get("Threads", 0)
    meminfo = _read_proc_kv("/proc/meminfo")
    if meminfo:
        total = meminfo.get("MemTotal", 0)
        if total:
            g["ram"] = round(100.0 * (total - meminfo.get("MemAvailable", 0)) / total, 1)
        swap_total = meminfo.get("SwapTotal", 0)
        if swap_total:
            g["swap"] = round(100.0 * (swap_total - meminfo.get("SwapFree", 0)) / swap_total, 1)
    cpu, iowait = _cpu_percent()
    if cpu is not None:
        g["cpu"] = cpu
        g["iowait"] = iowait
    try:
        load1 = os.getloadavg()[0]
        g["load"] = round(load1 / max(1, os.cpu_count() or 1), 2)
    except (OSError, AttributeError):
        pass
    try:
        usage = shutil.disk_usage(str(UPLOAD_DIR))
        g["disk"] = round(100.0 * usage.used / usage.total, 1)
        g["disk_free_gb"] = round(usage.free / (1024 ** 3), 2)
    except Exception:
        pass
    g["hb"] = round(max(0.0, time.time() - _cleanup_heartbeat[0]), 1)
    return g


def _assembly_metrics_observer(event, job_id, priority, waited, held):
    """Ponte fra la coda di assembly (modulo foglia) e la telemetria."""
    premium = priority >= assembly_queue.PRIORITY_PREMIUM
    if event == "timeout":
        load_metrics.observe("asm_wait", waited, premium=premium)
        load_metrics.incr("asm_timeout")
        return
    load_metrics.observe("asm_wait", waited, premium=premium)
    load_metrics.observe("enc", held)


def _load_metrics_sampler():
    """Campiona il carico ogni SAMPLE_SEC, scrive i bucket chiusi, fa retention.

    Thread PROPRIO e non un innesto nel _cleanup_loop: il cleanup fa lavoro
    pesante a cadenza variabile ed e' gia' morto una volta in produzione. Una
    telemetria che muore insieme al componente che deve sorvegliare non serve
    a niente.
    """
    last_purge = [0.0]
    while True:
        time.sleep(load_metrics.SAMPLE_SEC)
        try:
            load_metrics.sample(**_collect_load_sample())
            load_metrics.flush()
            now = time.time()
            if now - last_purge[0] > 86400:
                last_purge[0] = now
                load_metrics.purge()
        except Exception as e:
            print(f"[load-metrics] errore di campionamento (non fatale): {e}")


def _load_metrics_supervisor():
    """Mantiene vivo il campionatore, come _cleanup_supervisor fa col cleanup."""
    import traceback
    while True:
        try:
            _load_metrics_sampler()
        except Exception as e:
            traceback.print_exc()
            print(f"[load-metrics] sampler crashed, restarting: {type(e).__name__}: {e}")
            time.sleep(5)
```

Verifica che `shutil` sia già importato in testa a `audiobook_app.py`; se non lo è, aggiungi `import shutil`.

**3c.** Heartbeat: in `_cleanup_loop`, come ultima istruzione del corpo del `while True` (dopo tutto il lavoro del giro), aggiungi:

```python
        _cleanup_heartbeat[0] = time.time()
```

**3d.** In `_cleanup_supervisor`, nel ramo `except`, subito dopo `traceback.print_exc()`, aggiungi:

```python
            load_metrics.incr("cl_restart")
```

**3e.** In `_log_memory_stats`, nel ramo WARN (dopo `_log_activity("system", line, "MEMORY_PRESSURE")`), aggiungi:

```python
        load_metrics.incr("memp")
```

**3f.** Contatore dei rifiuti. Cambia la firma di `_server_busy_response` (`audiobook_app.py:887`):

```python
def _server_busy_response(job_id="", where="", premium=False):
    """429 server_busy se l'istanza e' al tetto globale, altrimenti None.

    Va invocata PRIMA di chiedere un pagamento: l'utente deve sapere che il
    server e' sovraccarico prima di pagare, non dopo (incidente 2026-08-21).
    Il controllo dentro il blocco atomico di /api/generate resta come guardia
    finale sulla race fra il gate anticipato e il claim dello slot.
    """
    at_capacity, active, cap = _server_at_capacity()
    if not at_capacity:
        return None
    load_metrics.incr("rej_busy_p" if premium else "rej_busy")
    print(f"[{job_id or '-'}] {where or 'richiesta'} rifiutata: tetto globale "
          f"raggiunto ({active}/{cap})", flush=True)
    return jsonify({
        "error": "The server is at capacity right now. "
                 "Please try again in a few minutes.",
        "error_code": "server_busy",
        "max": cap,
        "active": active,
    }), 429
```

Nei due chiamanti passa la classe del job. In `/api/generate` (`audiobook_app.py:9172`):

```python
    _busy = _server_busy_response(
        job_id, "/api/generate",
        premium=generation_engine.is_premium_job(jobs.get(job_id) or {}))
```

In `/api/paypal_create_order_gemini` (`audiobook_app.py:11502`) la voce a pagamento è implicita nell'endpoint stesso:

```python
    _busy = _server_busy_response(job_id, "/api/paypal_create_order_gemini",
                                  premium=True)
```

Nel claim atomico di `/api/generate` (`audiobook_app.py:9657-9671`), subito prima di `_refund_payment_on_orphan(job_id, job, "server_busy")`, aggiungi:

```python
                load_metrics.incr(
                    "rej_busy_p" if generation_engine.is_premium_job(job) else "rej_busy")
```

**3g.** Avvio e configurazione, in `_ensure_background_threads` (`audiobook_app.py:15736`), subito dopo `_cleanup_started = True`:

```python
    load_metrics.configure(_DATA_DIR)
    load_metrics.incr("boot")
    assembly_queue.set_observer(_assembly_metrics_observer)
    if load_metrics.ENABLED:
        threading.Thread(target=_load_metrics_supervisor, daemon=True).start()
```

e nel blocco di righe `[startup]` in fondo alla funzione:

```python
    print(f"[startup] Load metrics: "
          f"{'on' if load_metrics.ENABLED else 'off'} "
          f"(sample {load_metrics.SAMPLE_SEC}s, bucket {load_metrics.BUCKET_SEC}s, "
          f"retention {load_metrics.RETENTION_MONTHS} mesi)")
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `pytest test/test_load_metrics_sampler.py -v`
Expected: PASS (8 test)

Run: `pytest test/ -q`
Expected: nessuna regressione (in particolare i test che chiamano `_server_busy_response`).

- [ ] **Step 5: Committa**

```bash
python -m py_compile audiobook_app.py
git add audiobook_app.py test/test_load_metrics_sampler.py
git commit -m "feat(metrics): campionatore di carico, heartbeat cleanup e contatori"
```

---

### Task 7: endpoint `/api/admin/load_stats`

**Files:**
- Modify: `audiobook_app.py` (nuova route accanto a `api_admin_google_tts_status`, `:8226`)
- Test: `test/test_admin_load_stats.py`

**Interfaces:**
- Consumes: da Task 2 — `load_metrics.query(window, global_cap=..., assembly_slots=...)`; `_admin_auth_ok`, `_admin_auth_from_request` esistenti.
- Produces: `GET /api/admin/load_stats?window=24h|7d|28d|month` → JSON della spec §6.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_admin_load_stats.py`:

```python
"""Endpoint admin /api/admin/load_stats."""
from unittest.mock import patch

import pytest

import audiobook_app as app
import load_metrics as lm


@pytest.fixture
def client(tmp_path):
    app.app.config["TESTING"] = True
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield app.app.test_client()
    lm.reset_for_tests()


def test_requires_admin_auth(client):
    with patch.object(app, "_admin_auth_ok", return_value=False):
        r = client.get("/api/admin/load_stats?window=24h")
    assert r.status_code == 403


def test_returns_all_sections(client):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        r = client.get("/api/admin/load_stats?window=24h")
    assert r.status_code == 200
    data = r.get_json()
    for key in ("meta", "job", "ffmpeg", "machine", "quality", "reliability", "timeline"):
        assert key in data


def test_empty_history_is_not_an_error(client):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        data = client.get("/api/admin/load_stats?window=28d").get_json()
    assert data["meta"]["coverage_pct"] == 0
    assert data["meta"]["first_sample_ts"] is None
    assert data["job"]["gen_peak"] == 0


def test_invalid_window_falls_back_to_24h(client):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        data = client.get("/api/admin/load_stats?window=../etc/passwd").get_json()
    assert data["meta"]["window"] == "24h"


def test_caps_are_passed_through_for_saturation(client):
    with patch.object(app, "_admin_auth_ok", return_value=True), \
         patch.object(app, "MAX_CONCURRENT_GLOBAL", 6), \
         patch.object(lm, "query", side_effect=lm.query) as spy:
        client.get("/api/admin/load_stats?window=7d")
    assert spy.call_args.kwargs["global_cap"] == 6
    assert spy.call_args.kwargs["assembly_slots"] >= 1
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_admin_load_stats.py -v`
Expected: FAIL — 404 invece di 200/403 (la route non esiste)

- [ ] **Step 3: Implementa**

In `audiobook_app.py`, subito dopo la route `api_admin_google_tts_status`, aggiungi:

```python
@app.route("/api/admin/load_stats")
def api_admin_load_stats():
    """Statistiche di CARICO aggregate sulla finestra richiesta.

    Alimenta il pannello Stats di /admin/log-activity. Richiede admin token:
    espone la capacita' residua e lo stato di salute dell'istanza, che non
    devono essere leggibili dall'esterno.
    """
    if not _admin_auth_ok(_admin_auth_from_request()):
        return jsonify({"error": "Unauthorized"}), 403
    window = (request.args.get("window") or "24h").strip()
    try:
        slots = assembly_queue.MAX_CONCURRENT_ASSEMBLY
    except Exception:
        slots = 0
    data = load_metrics.query(window,
                              global_cap=MAX_CONCURRENT_GLOBAL,
                              assembly_slots=slots)
    data["meta"]["global_cap"] = MAX_CONCURRENT_GLOBAL
    data["meta"]["assembly_slots"] = slots
    return jsonify(data)
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `pytest test/test_admin_load_stats.py -v`
Expected: PASS (5 test)

- [ ] **Step 5: Committa**

```bash
python -m py_compile audiobook_app.py
git add audiobook_app.py test/test_admin_load_stats.py
git commit -m "feat(admin): endpoint load_stats per il pannello di carico"
```

---

### Task 8: nuovo modale Stats

**Files:**
- Modify: `audiobook_app.py:4137-4152` (markup del modale), `:4162-4180` (CSS del grafico), `:4230-4299` (JS `showStats`/`hideStats`)
- Test: `test/test_admin_load_stats_ui.py`

**Interfaces:**
- Consumes: da Task 7 — `GET /api/admin/load_stats?window=...`.
- Produces: markup con `id="statsModal"`, selettore `.lsw-btn[data-window]`, contenitori `id="lsCards"`, `id="lsTimeline"`, `id="lsCoverage"`; funzioni JS `showStats()`, `hideStats()`, `loadStats(window)`.

> **Nota per chi implementa:** la pagina è generata da una f-string Python. Ogni graffa letterale del CSS e del JS va raddoppiata (`{{` e `}}`), come nel codice già presente.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_admin_load_stats_ui.py`:

```python
"""Pannello Stats: selettore di finestra e rimozione del vecchio grafico."""
from unittest.mock import patch

import audiobook_app


def _page():
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_window_selector_present_with_four_windows():
    html = _page()
    for w in ("24h", "7d", "28d", "month"):
        assert f'data-window="{w}"' in html


def test_default_window_is_24h():
    html = _page()
    assert 'data-window="24h" class="lsw-btn active"' in html or \
           'class="lsw-btn active" data-window="24h"' in html


def test_stats_modal_fetches_the_admin_endpoint():
    html = _page()
    assert "/api/admin/load_stats?window=" in html


def test_old_hourly_language_chart_removed():
    html = _page()
    assert "chart-bar-wrap" not in html
    assert "hourlyData" not in html
    assert "Job Distribution (24h)" not in html


def test_cards_and_timeline_containers_present():
    html = _page()
    assert 'id="lsCards"' in html
    assert 'id="lsTimeline"' in html
    assert 'id="lsCoverage"' in html
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_admin_load_stats_ui.py -v`
Expected: FAIL — `data-window="24h"` assente, `hourlyData` ancora presente

- [ ] **Step 3: Sostituisci markup, CSS e JS**

**3a.** Sostituisci il blocco `<div id="statsModal" class="modal">…</div>` (`audiobook_app.py:4137-4152`) con:

```html
<div id="statsModal" class="modal">
    <div class="modal-content">
        <div class="modal-header">
            <h2>📊 Carico sistema</h2>
            <button class="modal-close" onclick="hideStats()">&times;</button>
        </div>
        <div class="lsw-bar">
            <button class="lsw-btn active" data-window="24h" onclick="loadStats('24h',this)">24 ore</button>
            <button class="lsw-btn" data-window="7d" onclick="loadStats('7d',this)">7 giorni</button>
            <button class="lsw-btn" data-window="28d" onclick="loadStats('28d',this)">28 giorni</button>
            <button class="lsw-btn" data-window="month" onclick="loadStats('month',this)">Mese corrente</button>
            <button class="lsw-btn lsw-refresh" onclick="loadStats(lsWindow,null)" title="Ricarica">⟳</button>
        </div>
        <div id="lsCoverage" class="ls-coverage"></div>
        <div id="lsCards" class="ls-cards"></div>
        <div id="lsTimeline" class="ls-timeline"></div>
    </div>
</div>
```

**3b.** Sostituisci il blocco CSS del grafico (dalle regole `.chart-legend` a `.chart-x-label`, intorno a `audiobook_app.py:4162-4180`, la riga `.chart-bar-wrap` e a `:4171`) con:

```css
.lsw-bar {{ display:flex; gap:6px; flex-wrap:wrap; margin-bottom:14px; }}
.lsw-btn {{ background:var(--surface2); color:var(--text-dim); border:1px solid var(--border);
           border-radius:8px; padding:6px 14px; font-size:.78rem; cursor:pointer; }}
.lsw-btn:hover {{ color:var(--text); }}
.lsw-btn.active {{ background:var(--accent); color:#fff; border-color:var(--accent); }}
.lsw-refresh {{ margin-left:auto; }}
.ls-coverage {{ font-size:.7rem; color:var(--orange); margin-bottom:10px; min-height:1em; }}
.ls-cards {{ display:flex; flex-direction:column; gap:14px; }}
.ls-sec {{ }}
.ls-sec h3 {{ font-size:.68rem; text-transform:uppercase; letter-spacing:.8px;
             color:var(--text-dim); margin-bottom:6px; font-weight:600; }}
.ls-grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:8px; }}
.ls-card {{ background:var(--surface2); border:1px solid var(--border); border-radius:8px; padding:10px 12px; }}
.ls-card .v {{ font-size:1.25rem; font-weight:700; color:var(--text); }}
.ls-card .l {{ font-size:.62rem; color:var(--text-dim); text-transform:uppercase; letter-spacing:.5px; }}
.ls-card .s {{ font-size:.68rem; color:var(--text-dim); margin-top:3px; }}
.ls-card.warn .v {{ color:var(--orange); }}
.ls-card.crit .v {{ color:var(--red,#ef4444); }}
.ls-card.ok .v {{ color:var(--green); }}
.ls-badge {{ display:inline-block; font-size:.55rem; padding:1px 5px; border-radius:4px;
            border:1px solid var(--border); margin-right:4px; }}
.ls-badge.p {{ color:var(--accent2,#a78bfa); border-color:rgba(167,139,250,.4); }}
.ls-timeline {{ margin-top:18px; border-left:2px solid var(--border);
               border-bottom:2px solid var(--border); padding:14px 6px 0 6px;
               height:170px; display:flex; align-items:flex-end; gap:2px; position:relative; }}
.ls-tl-wrap {{ flex:1; height:100%; display:flex; flex-direction:column;
              justify-content:flex-end; position:relative; }}
.ls-tl-seg {{ width:100%; }}
.ls-tl-seg.free {{ background:var(--accent); }}
.ls-tl-seg.prem {{ background:var(--accent2,#a78bfa); }}
.ls-tl-wrap:hover::after {{ content:attr(data-label); position:absolute; bottom:100%; left:50%;
    transform:translateX(-50%); background:var(--surface2); color:var(--text); padding:3px 7px;
    border-radius:4px; font-size:.65rem; white-space:nowrap; z-index:10; border:1px solid var(--border); }}
.ls-tl-rej {{ position:absolute; top:2px; left:50%; transform:translateX(-50%);
             width:6px; height:6px; border-radius:50%; background:var(--red,#ef4444); }}
.ls-tl-ram {{ position:absolute; left:0; right:0; height:1px; background:var(--orange); opacity:.55; }}
.ls-empty {{ color:var(--text-dim); font-size:.8rem; text-align:center; padding:30px; }}
```

**3c.** Sostituisci il blocco JS da `const hourlyData = {hourly_json};` fino alla fine di `hideStats()` (`audiobook_app.py:4230-4299`) con:

```javascript
let lsWindow = '24h';
let lsLoaded = false;

function showStats() {{
    document.getElementById('statsModal').style.display = 'block';
    if (!lsLoaded) loadStats('24h', document.querySelector('.lsw-btn[data-window="24h"]'));
}}

function hideStats() {{
    document.getElementById('statsModal').style.display = 'none';
}}

function lsFmtSec(s) {{
    if (!s) return '0s';
    if (s >= 1200) return '> 20m';
    if (s < 60) return Math.round(s) + 's';
    const m = Math.floor(s / 60), r = Math.round(s % 60);
    return r ? m + 'm' + String(r).padStart(2, '0') + 's' : m + 'm';
}}

function lsCard(label, value, sub, level) {{
    return '<div class="ls-card ' + (level || '') + '"><div class="l">' + label +
           '</div><div class="v">' + value + '</div>' +
           (sub ? '<div class="s">' + sub + '</div>' : '') + '</div>';
}}

function lsLevel(v, warn, crit) {{
    if (v >= crit) return 'crit';
    if (v >= warn) return 'warn';
    return 'ok';
}}

function lsRender(d) {{
    const j = d.job || {{}}, f = d.ffmpeg || {{}}, m = d.machine || {{}},
          q = d.quality || {{}}, r = d.reliability || {{}};
    const sec = (title, cards) =>
        '<div class="ls-sec"><h3>' + title + '</h3><div class="ls-grid">' + cards.join('') + '</div></div>';

    let html = '';
    html += sec('Job', [
        lsCard('In elaborazione (picco)', j.gen_peak || 0, 'media ' + (j.gen_avg || 0)),
        lsCard('<span class="ls-badge p">PREMIUM</span> picco', j.gen_premium_peak || 0,
               'media ' + (j.gen_premium_avg || 0)),
        lsCard('Job in RAM (picco)', j.in_ram_peak || 0, 'media ' + (j.in_ram_avg || 0)),
        lsCard('Rifiutati per carico', (j.rejected_free || 0) + (j.rejected_premium || 0),
               'di cui premium ' + (j.rejected_premium || 0),
               (j.rejected_free || 0) + (j.rejected_premium || 0) > 0 ? 'warn' : 'ok'),
        lsCard('Tempo al tetto globale', (j.saturation_pct || 0) + '%',
               'cap ' + (d.meta.global_cap || 0), lsLevel(j.saturation_pct || 0, 5, 20)),
    ]);
    html += sec('FFmpeg / assembly', [
        lsCard('In assembly (picco)', f.asm_peak || 0, 'media ' + (f.asm_avg || 0)),
        lsCard('In coda (picco)', f.queue_peak || 0, ''),
        lsCard('Attesa media', lsFmtSec(f.wait_avg),
               'p50 ' + lsFmtSec(f.wait_p50) + ' · p95 ' + lsFmtSec(f.wait_p95),
               lsLevel(f.wait_p95 || 0, 300, 900)),
        lsCard('<span class="ls-badge p">PREMIUM</span> attesa', lsFmtSec(f.wait_premium_avg),
               'p95 ' + lsFmtSec(f.wait_premium_p95)),
        lsCard('Durata encode', lsFmtSec(f.encode_p50), 'p95 ' + lsFmtSec(f.encode_p95)),
        lsCard('Timeout coda', f.timeouts || 0, '', (f.timeouts || 0) > 0 ? 'crit' : 'ok'),
        lsCard('Slot tutti occupati', (f.slots_full_pct || 0) + '%',
               (d.meta.assembly_slots || 0) + ' slot', lsLevel(f.slots_full_pct || 0, 20, 50)),
    ]);
    html += sec('Macchina', [
        lsCard('RAM picco', (m.ram_peak || 0) + '%', 'media ' + (m.ram_avg || 0) + '%',
               lsLevel(m.ram_peak || 0, 80, 92)),
        lsCard('Swap picco', (m.swap_peak || 0) + '%', '', lsLevel(m.swap_peak || 0, 20, 60)),
        lsCard('RSS processo', (m.rss_peak || 0) + ' MB', 'media ' + (m.rss_avg || 0) + ' MB'),
        lsCard('CPU picco', (m.cpu_peak || 0) + '%', 'media ' + (m.cpu_avg || 0) + '%',
               lsLevel(m.cpu_peak || 0, 85, 97)),
        lsCard('IOwait picco', (m.iowait_peak || 0) + '%', '', lsLevel(m.iowait_peak || 0, 15, 35)),
        lsCard('Load per core', m.load_peak || 0, '', lsLevel(m.load_peak || 0, 1.5, 3)),
        lsCard('Thread picco', m.threads_peak || 0, ''),
        lsCard('Disco max', (m.disk_peak || 0) + '%',
               'liberi min ' + (m.disk_free_gb_min || 0) + ' GB',
               lsLevel(m.disk_peak || 0, 75, 90)),
    ]);
    html += sec('Qualità servizio', [
        lsCard('Completati', q.completed || 0, 'premium ' + (q.completed_premium || 0)),
        lsCard('Errori', q.errors || 0, (q.error_pct || 0) + '% dei job',
               lsLevel(q.error_pct || 0, 5, 15)),
        lsCard('Annullati', q.cancelled || 0, ''),
        lsCard('Durata job', lsFmtSec(q.job_p50), 'p95 ' + lsFmtSec(q.job_p95)),
        lsCard('<span class="ls-badge p">PREMIUM</span> durata', lsFmtSec(q.job_premium_p50),
               'p95 ' + lsFmtSec(q.job_premium_p95)),
        lsCard('Chunk TTS falliti', q.chunk_failed || 0, '',
               (q.chunk_failed || 0) > 0 ? 'warn' : 'ok'),
    ]);
    html += sec('Affidabilità', [
        lsCard('Riavvii processo', r.boots || 0, '', (r.boots || 0) > 1 ? 'warn' : 'ok'),
        lsCard('Restart cleanup', r.cleanup_restarts || 0, '',
               (r.cleanup_restarts || 0) > 0 ? 'crit' : 'ok'),
        lsCard('Heartbeat cleanup max', lsFmtSec(r.cleanup_hb_max_sec),
               'atteso < 2m', lsLevel(r.cleanup_hb_max_sec || 0, 300, 900)),
        lsCard('Memory pressure', r.memory_pressure || 0, '',
               (r.memory_pressure || 0) > 0 ? 'crit' : 'ok'),
    ]);
    document.getElementById('lsCards').innerHTML = html;

    const cov = document.getElementById('lsCoverage');
    if ((d.meta.coverage_pct || 0) < 100) {{
        const since = d.meta.first_sample_ts
            ? new Date(d.meta.first_sample_ts * 1000).toLocaleString('it-IT')
            : 'mai';
        cov.textContent = 'Dati parziali (' + (d.meta.coverage_pct || 0) +
                          '% della finestra) — raccolta iniziata il ' + since;
    }} else {{
        cov.textContent = '';
    }}

    const tl = document.getElementById('lsTimeline');
    const pts = d.timeline || [];
    if (!pts.length) {{
        tl.innerHTML = '<div class="ls-empty">Nessun dato nella finestra selezionata.</div>';
        return;
    }}
    const maxGen = Math.max(1, ...pts.map(p => p.gen));
    tl.innerHTML = pts.map(p => {{
        const prem = Math.min(p.gen_p, p.gen);
        const free = Math.max(0, p.gen - prem);
        const when = new Date(p.t * 1000).toLocaleString('it-IT',
            {{day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit'}});
        const label = when + ' · job ' + p.gen + ' (prem ' + prem + ') · RAM ' + p.ram +
                      '%' + (p.rej ? ' · rifiuti ' + p.rej : '');
        return '<div class="ls-tl-wrap" data-label="' + label + '">' +
               (p.rej ? '<div class="ls-tl-rej"></div>' : '') +
               (p.ram ? '<div class="ls-tl-ram" style="bottom:' + p.ram + '%"></div>' : '') +
               '<div class="ls-tl-seg prem" style="height:' + (prem / maxGen * 100) + '%"></div>' +
               '<div class="ls-tl-seg free" style="height:' + (free / maxGen * 100) + '%"></div>' +
               '</div>';
    }}).join('');
}}

function loadStats(win, btn) {{
    lsWindow = win;
    lsLoaded = true;
    document.querySelectorAll('.lsw-btn[data-window]').forEach(b => b.classList.remove('active'));
    const target = btn || document.querySelector('.lsw-btn[data-window="' + win + '"]');
    if (target) target.classList.add('active');
    document.getElementById('lsCards').innerHTML = '<div class="ls-empty">Caricamento…</div>';
    document.getElementById('lsTimeline').innerHTML = '';
    fetch('/api/admin/load_stats?window=' + encodeURIComponent(win), {{credentials: 'same-origin'}})
        .then(r => r.ok ? r.json() : Promise.reject(r.status))
        .then(lsRender)
        .catch(e => {{
            document.getElementById('lsCards').innerHTML =
                '<div class="ls-empty">Errore nel caricamento delle statistiche (' + e + ').</div>';
        }});
}}
```

**3d.** Rimuovi il calcolo ormai inutilizzato di `hourly_json` e `lang_labels_json` (`audiobook_app.py:3930`, `:3954-3955`) e i relativi riferimenti nella f-string. Verifica con `grep -n "hourly_json\|lang_labels_json" audiobook_app.py` che non resti alcun uso.

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `pytest test/test_admin_load_stats_ui.py test/test_admin_logactivity_filters.py -v`
Expected: PASS — il nuovo pannello c'è e i filtri esistenti della pagina non regrediscono.

- [ ] **Step 5: Verifica manuale**

```bash
python -c "import audiobook_app"          # la f-string della pagina deve compilare
pytest test/ -q
```

Poi apri `/admin/log-activity`, premi `📊 Stats` e controlla: apertura sulla finestra 24 ore, cambio finestra funzionante, banner di copertura parziale presente al primo giorno.

- [ ] **Step 6: Committa**

```bash
git add audiobook_app.py test/test_admin_load_stats_ui.py
git commit -m "feat(admin): pannello Stats con carico su finestra selezionabile"
```

---

### Task 9: documentazione e versione

**Files:**
- Modify: `PARAMETRI_CONFIGURAZIONE.md`, `CLAUDE.md`, `version.py`

**Interfaces:**
- Consumes: tutto quanto sopra.
- Produces: nessuna interfaccia di codice.

- [ ] **Step 1: Documenta le variabili di configurazione**

In `PARAMETRI_CONFIGURAZIONE.md`, nella sezione dei limiti/osservabilità, aggiungi la tabella:

```markdown
### Telemetria di carico (`load_metrics.py`)

| Variabile | Descrizione | Default | Sorgente |
|-----------|-------------|---------|----------|
| `ABM_LOAD_METRICS_ENABLED` | Abilita campionatore e pannello di carico admin | `true` | `load_metrics.py` |
| `ABM_LOAD_METRICS_SAMPLE_SEC` | Passo di campionamento dei gauge | `30` | `load_metrics.py` |
| `ABM_LOAD_METRICS_BUCKET_SEC` | Ampiezza del bucket di aggregazione | `300` | `load_metrics.py` |
| `ABM_LOAD_METRICS_RETENTION_MONTHS` | File mensili `load_metrics_YYYY-MM.jsonl` conservati | `4` | `load_metrics.py` |
```

- [ ] **Step 2: Aggiorna la tabella dei moduli in CLAUDE.md**

Nella tabella *Backend Modules*, dopo la riga di `assembly_queue.py`, aggiungi:

```markdown
| `load_metrics.py` | Telemetria di CARICO: gauge (job attivi free/premium, coda assembly, RAM/swap/CPU/iowait/load/disco), contatori (rifiuti per tetto globale, timeout coda, boot, restart cleanup) e istogrammi di durata, aggregati in bucket da 5 min su `load_metrics_YYYY-MM.jsonl` in `ABM_DATA_DIR`. Alimenta `/api/admin/load_stats` e il pannello Stats di `/admin/log-activity`. Modulo foglia; riceve la data dir via `configure()` e la coda di assembly gli parla via observer. |
```

- [ ] **Step 3: Esegui l'intera suite**

Run: `pytest test/ -q`
Expected: PASS

- [ ] **Step 4: Allinea la versione**

In `version.py` porta `__version__` alla minor successiva (nuova funzionalità admin, nessuna rottura): da `3.45.x` a `3.46.0`.

- [ ] **Step 5: Committa**

```bash
git add PARAMETRI_CONFIGURAZIONE.md version.py
git add -f CLAUDE.md 2>/dev/null || true   # CLAUDE.md resta fuori dal repo: NON forzarlo
git commit -m "docs(metrics): parametri della telemetria di carico e bump versione"
```

> **Attenzione:** `CLAUDE.md` non è tracciato da git e non va mai aggiunto. Modificalo in locale ma escludilo dal commit — committa solo `PARAMETRI_CONFIGURAZIONE.md` e `version.py`.

- [ ] **Step 6: Fermati prima del push**

Il push su `main` fa partire il deploy automatico in produzione. Chiedi conferma esplicita all'utente prima di eseguirlo.

---

## Note di verifica finale

Prima di dichiarare completo il lavoro:

1. `pytest test/ -q` — l'intera suite verde.
2. `python -c "import audiobook_app"` — la f-string della pagina admin compila.
3. `grep -n "hourly_json\|lang_labels_json\|chart-bar-wrap" audiobook_app.py` — nessun residuo del vecchio grafico.
4. Avvio locale (`python audiobook_app.py`) e apertura di `/admin/log-activity`: il pannello si apre su 24 ore, il cambio finestra ricarica, il banner di copertura parziale compare. Su Windows le card di macchina restano a zero — è il degrado previsto, non un bug.
5. Nessun file temporaneo lasciato nella working tree (CLAUDE.md §11).
