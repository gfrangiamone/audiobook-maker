# Activity log — fase 1: facciata `activity_log.py` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Portare ogni lettura e scrittura del business log `activity_YYYY-MM.log` dietro un modulo foglia `activity_log.py`, correggendo i difetti di dedup C1–C3, senza cambiare formato ne' posizione dei file.

**Architecture:** `activity_log.py` (sola stdlib) possiede formato, parsing (`split_line` → `Row`), scrittura con dedup e letture per mese o intervallo; la cartella arriva da `configure(log_dir=callable)`. `audiobook_app` lo configura con `lambda: SCRIPT_DIR` e sostituisce i suoi 8 lettori/scrittori un punto alla volta. `user_stats` (foglia) smette di leggere file: riceve iterabili di righe dal chiamante.

**Tech Stack:** Python 3.12, Flask, pytest. Nessuna dipendenza nuova.

**Spec:** `docs/superpowers/specs/2026-09-24-activity-log-db-design.md` (sezione "Fase 1 — Design").

## Global Constraints

- Branch `worktree-activity-db`, worktree `.claude/worktrees/activity-db`. Nessun push, nessun merge su `main` senza conferma esplicita dell'utente.
- Shell di sviluppo: PowerShell, un comando per invocazione, niente `&&`.
- Dopo ogni modifica Python: `python -m py_compile <file>`; poi i test del task.
- Commit: Conventional Commits, `type(scope): summary` minuscolo, senza trailer (`Co-Authored-By:` e simili vietati). `git add` solo di path espliciti, mai `-A`.
- `activity_log.py` e `user_stats.py` sono moduli foglia: nessun import dal progetto (neanche fra loro).
- Mai `import audiobook_app` da un sotto-modulo.
- Formato riga su disco invariato: `<job_id> # <ts> # "<file>" # <op> # <cid> # <ip> # <voice> # <lang> # <platform>`, `ts` = `%Y-%m-%d %H:%M:%S`.
- Posizione invariata: `SCRIPT_DIR` (lo spostamento in `ABM_DATA_DIR` e' fase 2).
- `log()` non solleva mai eccezioni.
- Baseline suite (main 18a67a9): 3908 passati, 25 falliti preesistenti ed estranei (`abuse_judge`, `voice_clone_replica`, `voxcpm_runpod`, `tts_backend_probe_state`, `admin_voice_xss`, `audio_generation_tags`, `free_quota_generate_enforcement`). Il numero di falliti non deve crescere.
- Nessun bump di `version.py` in questo piano (si fa al merge su `main`).

## Review Focus

1. **Titolo con `" # "` su una riga `COMPLETE`/`OPT_COMPLETE`** → il job risulta consegnato per `delivered_ids` e conta nelle statistiche community (oggi lo split secco lo perde e il recovery puo' rimborsare un job consegnato). Test: Task 1 (`delivered_ids`), Task 5.
2. **Righe di sistema a `job_id` vuoto** (`VOUCHER_ATTEMPT`, `ADMIN_*`, `TTS_BACKEND_*`) → non diventano una sessione `""` nel pannello admin ne' un client nei power user. Test: Task 6, Task 7.
3. **Byte non UTF-8 nel file del mese** → il pannello admin e l'export rispondono 200, non 500. Test: Task 1, Task 6.
4. **Cambio di mese a processo acceso** → il set di dedup si azzera e lo stesso `(job_id, op)` si riscrive nel file del nuovo mese. Test: Task 1.
5. **`ym` non valido o con path traversal** passato a `month_rows`/`fingerprint` → iteratore vuoto / `None`, nessun file fuori dalla cartella letto. Test: Task 1.

---

## File coinvolti

| File | Ruolo |
|---|---|
| `activity_log.py` (nuovo) | formato, parsing, scrittura con dedup, letture, cache consegne |
| `test/test_activity_log.py` (nuovo) | test di contratto sull'API pubblica |
| `audiobook_app.py` | `configure`, passaggio `_log_activity` → `log()`, rimozione di dedup/parser/cache locali, lettori sui nuovi iteratori |
| `generation_engine.py` | `_log_m4b_progress(job_id, job, event, **fields)` (C3) |
| `user_stats.py` | funzioni sulle righe invece che sui path; via `split_line`/`_ym_from_name` |
| `test/test_activity_platform.py`, `test/test_cold_download_log.py`, `test/test_voice_clone_generate.py`, `test/test_log_activity_regen_dedup.py`, `test/test_orphan_delivered_no_refund.py`, `test/test_m4b_progress.py`, `test/test_regression_double_module.py`, `test/test_admin_user_stats.py`, `test/test_power_users_digest.py` | adeguamento allo stato e alle firme nuove |
| `test/test_activity_log_readers.py` (nuovo) | statistiche community, sessioni admin, power user dell'app |

---

### Task 1: modulo `activity_log.py` e test di contratto

**Files:**
- Create: `activity_log.py`
- Create: `test/test_activity_log.py`
- Create (scratchpad, non nel repo): `<scratchpad>/equiv_activity_log.py`, `<scratchpad>/equiv_compare.py`

`<scratchpad>` = `C:\Users\gfran\AppData\Local\Temp\claude\C--Users-gfran-NEXT-srl-Progetti---Documenti-AudioBook-Maker\57d051a6-dea8-4cef-b003-ed7584a9d87d\scratchpad` (o lo scratchpad della sessione che esegue).

**Interfaces:**
- Consumes: niente.
- Produces (usati dai task 2–8):
  - `Row(NamedTuple)`: `job_id, ts, filename, op, client_id, ip, voice, lang, platform` (tutti `str`)
  - `configure(log_dir: Callable[[], Path]) -> None`
  - `log(job_id, filename, op, client_id="", ip="", voice="", lang="", platform="", epoch=None) -> None`
  - `init_dedup() -> None`
  - `reset() -> None`
  - `split_line(line: str) -> Row | None`
  - `file_rows(path) -> Iterator[Row]`
  - `months() -> list[str]`
  - `month_rows(ym: str) -> Iterator[Row]`
  - `iter_rows(since: datetime, until: datetime | None = None, ops: set | None = None) -> Iterator[Row]`
  - `fingerprint(ym: str) -> tuple | None`
  - `delivered_ids(months: int = 3) -> {"complete": set, "opt_complete": set}`

- [ ] **Step 1: Baseline di equivalenza (prima di toccare il codice)**

Crea `<scratchpad>/equiv_activity_log.py`:

```python
"""Equivalenza dei lettori dell'activity log prima/dopo la fase 1.

Uso: python equiv_activity_log.py <repo> <cartella_log> <out.json>
Copia i log in una cartella temporanea, importa l'app del <repo> con una
ABM_DATA_DIR temporanea e scrive le uscite di tutti i lettori in JSON.
Riconosce da solo l'API vecchia (user_stats.split_line presente) e la nuova.
"""
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

repo, src, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
tmp = Path(tempfile.mkdtemp(prefix="abm_equiv_"))
logs = tmp / "logs"
logs.mkdir()
for p in src.glob("activity_*.log"):
    shutil.copy2(p, logs / p.name)
os.environ["ABM_DATA_DIR"] = str(tmp / "data")
sys.path.insert(0, str(repo))
os.chdir(repo)

import audiobook_app  # noqa: E402
import user_stats  # noqa: E402

audiobook_app.SCRIPT_DIR = logs
NEW = not hasattr(user_stats, "split_line")
if NEW:
    import activity_log  # noqa: E402
    activity_log.reset()


def norm(o):
    if isinstance(o, dict):
        return {str(k): norm(v) for k, v in o.items()}
    if isinstance(o, (set, frozenset)):
        return sorted(norm(v) for v in o)
    if isinstance(o, (list, tuple)):
        return [norm(v) for v in o]
    if isinstance(o, datetime):
        return o.isoformat()
    return o


def safe(fn):
    try:
        return norm(fn())
    except Exception as e:  # la versione vecchia puo' fallire su byte non UTF-8
        return f"ERROR {type(e).__name__}: {e}"


res = {}
yms = sorted(m.group(1) for p in logs.iterdir()
             if (m := re.match(r"^activity_(\d{4}-\d{2})\.log$", p.name)))
for ym in yms:
    res[f"sessions/{ym}"] = safe(lambda: audiobook_app._parse_log_sessions(ym))
    if NEW:
        an = safe(lambda: user_stats.analyze(activity_log.month_rows(ym), ym=ym))
    else:
        an = safe(lambda: user_stats.analyze(logs / f"activity_{ym}.log"))
    if isinstance(an, dict):
        an.pop("file", None)
    res[f"analyze/{ym}"] = an
    y, m = map(int, ym.split("-"))
    since = datetime(y, m, 20, 12, 0, 0)
    start, nxt = datetime(y, m, 1), datetime(y + (m == 12), m % 12 + 1, 1)
    if NEW:
        pu = lambda: user_stats.power_users(activity_log.iter_rows(start, until=nxt),
                                            since, min_jobs=1, top=100000, month_ym=ym)
    else:
        pu = lambda: user_stats.power_users([logs / f"activity_{ym}.log"],
                                            since, min_jobs=1, top=100000, month_ym=ym)
    res[f"power_users/{ym}"] = safe(pu)

audiobook_app._stats_today_cache["value"] = None
audiobook_app._stats_month_cache["value"] = None
res["stats_today"] = safe(audiobook_app._stats_today_count)
res["stats_month"] = safe(audiobook_app._stats_month_by_lang)
if NEW:
    res["delivered"] = safe(lambda: activity_log.delivered_ids(months=12))
else:
    res["delivered"] = safe(lambda: audiobook_app._delivered_job_ids(months=12))

out.write_text(json.dumps(res, sort_keys=True, indent=1, ensure_ascii=False),
               encoding="utf-8")
print(f"{len(res)} chiavi -> {out}")
os._exit(0)  # niente attesa sui thread di background dell'app
```

Crea `<scratchpad>/equiv_compare.py`:

```python
"""Confronta due uscite di equiv_activity_log.py. Uso: python equiv_compare.py a.json b.json"""
import json
import sys

a = json.load(open(sys.argv[1], encoding="utf-8"))
b = json.load(open(sys.argv[2], encoding="utf-8"))
n = 0
for k in sorted(set(a) | set(b)):
    va, vb = a.get(k), b.get(k)
    if va == vb:
        continue
    n += 1
    if isinstance(va, list) and isinstance(vb, list) and len(va) == len(vb) == 2 \
            and isinstance(va[0], dict) and isinstance(vb[0], dict):
        va, vb = va[0], vb[0]  # _parse_log_sessions -> (sessions, client_count)
    if isinstance(va, dict) and isinstance(vb, dict):
        diff = [x for x in sorted(set(va) | set(vb)) if va.get(x) != vb.get(x)]
        print(f"DIFF {k}: {len(diff)} sottochiavi, es. {diff[:5]}")
    else:
        print(f"DIFF {k}: {str(va)[:200]!r} -> {str(vb)[:200]!r}")
print(f"{n} chiavi diverse su {len(set(a) | set(b))}")
```

Run (dal worktree, codice ancora invariato):

```powershell
python "<scratchpad>\equiv_activity_log.py" "." "C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker" "<scratchpad>\equiv_before.json"
```

Expected: `N chiavi -> ...equiv_before.json`. I log di prova sono le copie di produzione nel checkout principale (`activity_2026-02.log` … `activity_2026-09.log`). Annota eventuali valori `ERROR ...` (difetti del codice vecchio, attesi solo su byte non UTF-8).

- [ ] **Step 2: Scrivi i test di contratto**

Crea `test/test_activity_log.py`:

```python
"""Contratto dell'API pubblica di activity_log (fase 1: backend file di testo).

In fase 2 questi test verranno parametrizzati anche sul backend SQLite: vanno
scritti solo contro le funzioni pubbliche, mai contro il formato del file,
salvo dove il formato e' esso stesso il contratto (andata e ritorno).
"""
from datetime import datetime, timedelta

import pytest

import activity_log
from activity_log import Row


def _ym(d):
    return d.strftime("%Y-%m")


def _prev_ym(d):
    first = d.replace(day=1)
    return _ym(first - timedelta(days=1))


def _write(d, ym, lines, raw=None):
    p = d / f"activity_{ym}.log"
    if raw is not None:
        p.write_bytes(raw)
    else:
        p.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
    return p


def _line(job, ts, op, fn="a.epub", cid="c", ip="1.1.1.1", voice="it-IT-X",
          lang="it", plat="web"):
    return f'{job} # {ts} # "{fn}" # {op} # {cid} # {ip} # {voice} # {lang} # {plat}'


@pytest.fixture
def log_dir(tmp_path):
    prev = activity_log._log_dir
    activity_log.configure(lambda: tmp_path)
    activity_log.reset()
    yield tmp_path
    activity_log.reset()
    activity_log.configure(prev)


def _ops_now():
    return [r.op for r in activity_log.month_rows(_ym(datetime.now()))]


# ---------------------------------------------------------------- scrittura

def test_andata_e_ritorno_con_cancelletto_e_platform_vuota(log_dir):
    activity_log.log("J1", "Saga # 2.epub", "GENERATE", client_id="c1",
                     ip="1.2.3.4", voice="it-IT-X", lang="it")
    rows = list(activity_log.month_rows(_ym(datetime.now())))
    assert len(rows) == 1
    assert rows[0] == Row("J1", rows[0].ts, "Saga # 2.epub", "GENERATE", "c1",
                          "1.2.3.4", "it-IT-X", "it", "")
    datetime.strptime(rows[0].ts, "%Y-%m-%d %H:%M:%S")


def test_stessa_chiave_scritta_una_volta(log_dir):
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    assert _ops_now() == ["DOWNLOAD"]


def test_epoch_diverse_due_righe(log_dir):
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.log("J1", "a.epub", "GENERATE", epoch=2)
    assert _ops_now() == ["GENERATE", "GENERATE"]


def test_c1_job_id_vuoto_mai_deduplicato(log_dir):
    activity_log.log("", "", "VOUCHER_ATTEMPT", ip="1.1.1.1", voice="AB12...", lang="invalid")
    activity_log.log("", "", "VOUCHER_ATTEMPT", ip="1.1.1.1", voice="CD34...", lang="invalid")
    rows = list(activity_log.month_rows(_ym(datetime.now())))
    assert [r.op for r in rows] == ["VOUCHER_ATTEMPT", "VOUCHER_ATTEMPT"]
    assert all(r.job_id == "" for r in rows)


def test_c2_init_dedup_ricostruisce_le_chiavi_giuste(log_dir):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write(log_dir, _ym(now), [
        f' # {ts} # "" # VOUCHER_ATTEMPT #  # 1.1.1.1 # AB12... # ok # ',
        _line("J1", ts, "GENERATE", fn="a # b.epub"),
    ])
    activity_log.init_dedup()
    activity_log.log("J1", "a # b.epub", "GENERATE")          # gia' nel file
    activity_log.log("", "", "VOUCHER_ATTEMPT", ip="1.1.1.1")  # C1: si scrive
    assert _ops_now().count("GENERATE") == 1
    assert _ops_now().count("VOUCHER_ATTEMPT") == 2


def test_cambio_mese_azzera_il_dedup(log_dir):
    activity_log.log("J1", "a.epub", "GENERATE")
    # Simula un processo acceso dal mese precedente: il set appartiene a un
    # altro mese e va buttato alla prima scrittura del mese nuovo.
    activity_log._month = "2000-01"
    activity_log.log("J1", "a.epub", "GENERATE")
    assert _ops_now() == ["GENERATE", "GENERATE"]


def test_log_non_solleva_e_riprova_dopo_un_errore(log_dir, tmp_path):
    missing = tmp_path / "manca"
    activity_log.configure(lambda: missing)
    activity_log.log("J1", "a.epub", "COMPLETE")  # cartella assente: nessuna eccezione
    missing.mkdir()
    activity_log.log("J1", "a.epub", "COMPLETE")  # la chiave non era entrata nel set
    assert [r.op for r in activity_log.month_rows(_ym(datetime.now()))] == ["COMPLETE"]


def test_log_senza_configurazione_non_solleva(log_dir):
    activity_log.configure(None)
    activity_log.log("J1", "a.epub", "COMPLETE")
    assert list(activity_log.month_rows(_ym(datetime.now()))) == []


# ---------------------------------------------------------------- parsing

def test_split_line_tollera_il_cancelletto_nel_nome_file():
    r = activity_log.split_line(_line("j1", "2026-08-01 10:00:00", "COMPLETE",
                                      fn="Riftwar Saga # 2 Empire.epub"))
    assert r.filename == "Riftwar Saga # 2 Empire.epub" and r.op == "COMPLETE"
    assert r.platform == "web"


def test_split_line_riga_corta_completata_a_destra():
    r = activity_log.split_line('job1 # 2026-08-01 10:00:00 # "x.epub" # GENERATE')
    assert r.job_id == "job1" and r.op == "GENERATE"
    assert r.client_id == "" and r.platform == ""


def test_split_line_riga_incompleta_scartata():
    assert activity_log.split_line("solo testo") is None
    assert activity_log.split_line("") is None


def test_split_line_regge_il_campo_finale_vuoto():
    line = ('j1 # 2026-08-01 10:00:00 # "a.epub" # COMPLETE # cid1 # 1.2.3.4'
            ' # en-US-GuyNeural # en # ')
    assert activity_log.split_line(line.strip())[7:] == ("en", "")
    assert activity_log.split_line(line + "\n")[7:] == ("en", "")


def test_split_line_cancelletto_nel_titolo_e_platform_vuota():
    line = ('j1 # 2026-08-01 10:00:00 # "Riftwar # 2.epub" # GENERATE # cid1'
            ' # 1.2.3.4 # gemini:flash31:Despina # de # ')
    r = activity_log.split_line(line.strip())
    assert r.filename == "Riftwar # 2.epub" and r.op == "GENERATE"
    assert r.lang == "de" and r.platform == ""


def test_split_line_riga_di_sistema_a_job_vuoto():
    r = activity_log.split_line(' # 2026-08-01 10:00:00 # "" # ADMIN_TTS_PROBE #  # 9.9.9.9 # k # avviata=True # \n')
    assert r.job_id == "" and r.ts == "2026-08-01 10:00:00"
    assert r.op == "ADMIN_TTS_PROBE" and r.ip == "9.9.9.9"


# ---------------------------------------------------------------- lettura

def test_file_rows_file_assente(tmp_path):
    assert list(activity_log.file_rows(tmp_path / "manca.log")) == []


def test_month_rows_tollera_byte_non_utf8_e_righe_rotte(log_dir):
    raw = (b"\xff\xfe spazzatura\n\n"
           + _line("J1", "2026-08-01 10:00:00", "COMPLETE").encode("utf-8") + b"\n")
    _write(log_dir, "2026-08", None, raw=raw)
    rows = list(activity_log.month_rows("2026-08"))
    assert [r.job_id for r in rows if r.op == "COMPLETE"] == ["J1"]


@pytest.mark.parametrize("ym", ["", "2026-8", "../2026-08", "2026-08/../../x", "agosto"])
def test_ym_non_valido(log_dir, ym):
    _write(log_dir, "2026-08", [_line("J1", "2026-08-01 10:00:00", "COMPLETE")])
    assert list(activity_log.month_rows(ym)) == []
    assert activity_log.fingerprint(ym) is None


def test_iter_rows_attraversa_i_mesi_e_filtra(log_dir):
    _write(log_dir, "2026-07", [
        _line("A", "2026-07-30 10:00:00", "COMPLETE"),   # prima di since
        _line("B", "2026-07-31 13:00:00", "COMPLETE"),
        _line("C", "2026-07-31 14:00:00", "GENERATE"),   # op esclusa
    ])
    _write(log_dir, "2026-08", [
        _line("D", "2026-08-01 09:00:00", "OPT_COMPLETE"),
        _line("E", "2026-08-02 00:00:00", "COMPLETE"),   # == until: escluso
    ])
    got = [r.job_id for r in activity_log.iter_rows(
        datetime(2026, 7, 31, 12), until=datetime(2026, 8, 2),
        ops={"COMPLETE", "OPT_COMPLETE"})]
    assert got == ["B", "D"]


def test_iter_rows_senza_until_arriva_a_oggi(log_dir):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write(log_dir, _ym(now), [_line("N", ts, "COMPLETE")])
    got = [r.job_id for r in activity_log.iter_rows(now.replace(day=1, hour=0, minute=0,
                                                                  second=0, microsecond=0))]
    assert got == ["N"]


def test_months_ordinati_e_solo_nomi_validi(log_dir):
    for name in ("activity_2026-07.log", "activity_2026-08.log", "activity_xx.log",
                 "altro.log", "activity_2026-08.log.bak"):
        (log_dir / name).write_text("", encoding="utf-8")
    assert activity_log.months() == ["2026-08", "2026-07"]


def test_months_senza_configurazione(log_dir):
    activity_log.configure(None)
    assert activity_log.months() == []


def test_fingerprint_cambia_dopo_una_scrittura(log_dir):
    ym = _ym(datetime.now())
    assert activity_log.fingerprint(ym) is None
    activity_log.log("J1", "a.epub", "GENERATE")
    fp1 = activity_log.fingerprint(ym)
    activity_log.log("J2", "a.epub", "GENERATE")
    fp2 = activity_log.fingerprint(ym)
    assert fp1 is not None and fp2 is not None and fp1 != fp2


def test_delivered_ids_su_piu_mesi_con_cache(log_dir):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write(log_dir, _prev_ym(now), [_line("OLD", "2000-01-01 00:00:00", "COMPLETE")])
    _write(log_dir, _ym(now), [
        _line("J1", ts, "COMPLETE"),
        _line("J2", ts, "OPT_COMPLETE", fn="Saga # 2.epub"),  # '#' nel titolo
        _line("J3", ts, "GENERATE"),
    ])
    d = activity_log.delivered_ids(months=2)
    assert d["complete"] == {"OLD", "J1"}
    assert d["opt_complete"] == {"J2"}

    with open(log_dir / f"activity_{_ym(now)}.log", "a", encoding="utf-8") as f:
        f.write(_line("J4", ts, "COMPLETE") + "\n")
    assert "J4" not in activity_log.delivered_ids(months=2)["complete"]  # cache 300 s
    activity_log.reset()
    assert "J4" in activity_log.delivered_ids(months=2)["complete"]


def test_delivered_ids_un_mese_solo(log_dir):
    now = datetime.now()
    _write(log_dir, _prev_ym(now), [_line("OLD", "2000-01-01 00:00:00", "COMPLETE")])
    assert activity_log.delivered_ids(months=1)["complete"] == set()
```

- [ ] **Step 3: Esegui i test, devono fallire**

Run: `python -m pytest test/test_activity_log.py -q -p no:cacheprovider`
Expected: errore di collezione `ModuleNotFoundError: No module named 'activity_log'`.

- [ ] **Step 4: Scrivi `activity_log.py`**

```python
"""Business log mensile delle attivita' (modulo foglia, sola stdlib).

Unico punto di accesso a `activity_YYYY-MM.log`: scrittura con dedup,
parsing, letture per mese o per intervallo. Formato su disco:

    <job_id> # <ts> # "<file>" # <op> # <cid> # <ip> # <voice> # <lang> # <platform>

Fase 1 di docs/superpowers/specs/2026-09-24-activity-log-db-design.md: oggi
file di testo, in fase 2-3 SQLite dietro la stessa API. Nessun import dal
progetto: la cartella arriva con `configure()`.
"""
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

TS_FMT = "%Y-%m-%d %H:%M:%S"
_YM_RE = re.compile(r"^\d{4}-\d{2}$")
_YM_IN_NAME = re.compile(r"^activity_(\d{4}-\d{2})\.log$")
# Il recovery interroga molti descrittori in sequenza: 5 minuti bastano.
_DELIVERED_TTL = 300.0


class Row(NamedTuple):
    job_id: str
    ts: str
    filename: str
    op: str
    client_id: str
    ip: str
    voice: str
    lang: str
    platform: str


_log_dir = None            # callable -> Path, risolta a ogni chiamata
_lock = threading.Lock()   # scrittura + dedup
_month = ""
_keys = set()              # (job_id, op) o (job_id, op, epoch) per gli eventi di ciclo
_delivered_lock = threading.Lock()
_delivered_cache = {"value": None, "expires": 0.0}


def configure(log_dir):
    """`log_dir`: callable senza argomenti che ritorna la cartella dei log.

    Risolta a ogni chiamata: i test che sostituiscono `SCRIPT_DIR` in
    audiobook_app restano validi senza riconfigurare nulla."""
    global _log_dir
    _log_dir = log_dir


def _dir():
    if _log_dir is None:
        raise RuntimeError("activity_log non configurato")
    return Path(_log_dir())


def _path(ym):
    return _dir() / f"activity_{ym}.log"


def reset():
    """Stato come a processo appena avviato (per i test)."""
    global _month
    with _lock:
        _month = ""
        _keys.clear()
    with _delivered_lock:
        _delivered_cache["value"] = None
        _delivered_cache["expires"] = 0.0


# --------------------------------------------------------------- parsing

def split_line(line):
    """Spezza una riga del log nei 9 campi, tollerando '#' nel nome file.

    Il separatore e' ' # ' ma un titolo tipo "Riftwar Saga # 2 Empire.epub"
    lo contiene: uno split secco sfasa i campi. Si ancorano quindi i 2 campi
    di testa e i 6 di coda, lasciando al nome file tutto il resto. Le righe
    storiche corte (senza lang/platform) si completano a destra.

    Ritorna None se la riga non ha nemmeno i campi minimi.
    """
    line = line.rstrip("\r\n")
    if line.endswith(" #"):
        # `platform` vuota: la riga finisce con " # " e chi ha gia' fatto
        # strip() si e' mangiato l'ultimo separatore.
        line += " "
    head = line.split(" # ", 2)
    if len(head) < 3:
        return None
    sid, ts, rest = head
    tail = rest.rsplit(" # ", 6)
    if len(tail) < 7:
        tail = tail + [""] * (7 - len(tail))
    filename, op, client_id, ip, voice, lang, platform = tail[:7]
    return Row(sid.strip(), ts.strip(), filename.strip().strip('"'), op.strip(),
               client_id.strip(), ip.strip(), voice.strip(), lang.strip(),
               platform.strip())


def file_rows(path):
    """Righe valide di un file di log qualsiasi; file assente: nessuna riga."""
    try:
        fh = open(path, "r", encoding="utf-8", errors="replace")
    except OSError:
        return
    with fh:
        for line in fh:
            row = split_line(line)
            if row is not None:
                yield row


# --------------------------------------------------------------- scrittura

def log(job_id, filename, op, client_id="", ip="", voice="", lang="",
        platform="", epoch=None):
    """Scrive una riga nel file del mese corrente. Non solleva mai.

    Dedup per (job_id, op), o (job_id, op, epoch) se `epoch` e' dato: cosi'
    GENERATE/COMPLETE di una ri-generazione dello stesso job non vengono
    soppressi, mentre i download ripetuti (chiamati senza epoch) si'.
    Le righe senza job_id (voucher, admin, backend TTS) non si deduplicano
    mai: ogni evento conta.
    """
    global _month
    now = datetime.now()
    ym = now.strftime("%Y-%m")
    key = None
    if job_id:
        key = (job_id, op) if epoch is None else (job_id, op, epoch)
    line = (f'{job_id} # {now.strftime(TS_FMT)} # "{filename}" # {op} # {client_id}'
            f' # {ip} # {voice} # {lang} # {platform}\n')
    with _lock:
        if ym != _month:
            _month = ym
            _keys.clear()
        if key is not None and key in _keys:
            return
        try:
            with open(_path(ym), "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as e:
            print(f"[activity_log] scrittura {op} fallita: {e}")
            return
        if key is not None:
            _keys.add(key)


def init_dedup():
    """Ricostruisce il set di dedup dal file del mese corrente (all'avvio).

    Solo chiavi (job_id, op): l'epoca non sta sulla riga, quindi dopo un
    riavvio un job ri-eseguito puo' ri-loggare il proprio evento di ciclo."""
    global _month
    ym = datetime.now().strftime("%Y-%m")
    keys = {(r.job_id, r.op) for r in month_rows(ym) if r.job_id}
    with _lock:
        _month = ym
        _keys.clear()
        _keys.update(keys)


# --------------------------------------------------------------- lettura

def months():
    """Mesi YYYY-MM con un file di log, dal piu' recente."""
    try:
        names = [p.name for p in _dir().glob("activity_*.log")]
    except (OSError, RuntimeError):
        return []
    found = {m.group(1) for n in names if (m := _YM_IN_NAME.match(n))}
    return sorted(found, reverse=True)


def month_rows(ym):
    """Righe del mese YYYY-MM; mese non valido o assente: nessuna riga."""
    if not _YM_RE.match(ym or ""):
        return
    try:
        path = _path(ym)
    except RuntimeError:
        return
    yield from file_rows(path)


def _months_between(since, until):
    end = until or datetime.now()
    y, m = since.year, since.month
    while (y, m) <= (end.year, end.month):
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1


def iter_rows(since, until=None, ops=None):
    """Righe con `since <= ts < until` (until assente: fino a oggi), in
    ordine di file; `ops`: insieme di operazioni esatte da tenere."""
    since_s = since.strftime(TS_FMT)
    until_s = until.strftime(TS_FMT) if until else None
    for ym in _months_between(since, until):
        for row in month_rows(ym):
            if row.ts < since_s:
                continue
            if until_s is not None and row.ts >= until_s:
                continue
            if ops is not None and row.op not in ops:
                continue
            yield row


def fingerprint(ym):
    """Firma del mese per invalidare le cache; None se il mese non c'e'."""
    if not _YM_RE.match(ym or ""):
        return None
    try:
        st = _path(ym).stat()
    except (OSError, RuntimeError):
        return None
    return (st.st_mtime_ns, st.st_size)


def delivered_ids(months=3):
    """job_id con COMPLETE / OPT_COMPLETE negli ultimi `months` mesi.

    E' la sola traccia persistente di "consegnato": il dict jobs e' in RAM e
    al boot e' vuoto. Cache di 5 minuti."""
    now = time.time()
    with _delivered_lock:
        cached = _delivered_cache["value"]
        if cached is not None and now < _delivered_cache["expires"]:
            return cached
    complete, opt = set(), set()
    d = datetime.now()
    y, m = d.year, d.month
    for _ in range(max(1, int(months))):
        for row in month_rows(f"{y:04d}-{m:02d}"):
            if row.op == "COMPLETE":
                complete.add(row.job_id)
            elif row.op == "OPT_COMPLETE":
                opt.add(row.job_id)
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    value = {"complete": complete, "opt_complete": opt}
    with _delivered_lock:
        _delivered_cache["value"] = value
        _delivered_cache["expires"] = time.time() + _DELIVERED_TTL
    return value
```

- [ ] **Step 5: Compila ed esegui i test**

Run: `python -m py_compile activity_log.py`
Run: `python -m pytest test/test_activity_log.py -q -p no:cacheprovider`
Expected: tutti PASS.

- [ ] **Step 6: Commit**

```powershell
git add activity_log.py test/test_activity_log.py
git commit -m "feat(activity-log): modulo foglia per il business log mensile"
```

---

### Task 2: `_log_activity` e dedup all'avvio passano da `activity_log` (C1, C2)

**Files:**
- Modify: `audiobook_app.py` (import ~riga 158; blocco `_log_lock`/`_logged_month`/`_logged_sids_ops`/`_init_log_dedup` ~righe 3129–3148; `_log_activity` ~righe 3231–3263; chiamata `_init_log_dedup()` ~riga 21870)
- Modify: `test/test_log_activity_regen_dedup.py`, `test/test_activity_platform.py`, `test/test_cold_download_log.py:22`, `test/test_voice_clone_generate.py:141-142`

**Interfaces:**
- Consumes: `activity_log.configure`, `log`, `init_dedup`, `reset` (Task 1).
- Produces: `audiobook_app._log_activity(session_id, filename, operation, client_id='', client_ip='', voice='', browser_lang='', epoch=None, platform='')` — firma invariata, ora passaggio verso `activity_log.log`. Spariscono `_log_lock`, `_logged_month`, `_logged_sids_ops`, `_init_log_dedup`.

- [ ] **Step 1: Adegua i test allo stato nuovo e aggiungi il test C1 lato app**

In `test/test_log_activity_regen_dedup.py`, sostituisci l'intestazione degli import e `_reset_log` con:

```python
import pathlib
import tempfile
from datetime import datetime

import activity_log
import audiobook_app


def _cur_month():
    return datetime.now().strftime("%Y-%m")


def _read_ops(script_dir, month):
    logf = script_dir / f"activity_{month}.log"
    lines = logf.read_text(encoding="utf-8").splitlines()
    return [l.split(" # ")[3] for l in lines]


def _reset_log(monkeypatch):
    script_dir = pathlib.Path(tempfile.mkdtemp())
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", script_dir)
    activity_log.reset()
    return script_dir
```

e in tutto il file sostituisci ogni `audiobook_app._logged_month` con `_cur_month()`. Aggiungi in fondo:

```python
def test_eventi_senza_job_non_deduplicati(monkeypatch):
    """C1: ogni tentativo voucher e' un evento distinto, anche nello stesso processo."""
    script_dir = _reset_log(monkeypatch)

    audiobook_app._log_activity("", "", "VOUCHER_ATTEMPT", "", "1.1.1.1", "AB12...", "invalid")
    audiobook_app._log_activity("", "", "VOUCHER_ATTEMPT", "", "1.1.1.1", "CD34...", "invalid")

    assert _read_ops(script_dir, _cur_month()).count("VOUCHER_ATTEMPT") == 2
```

In `test/test_activity_platform.py` aggiungi `import activity_log` in cima al file e sostituisci entrambe le righe
`app._logged_sids_ops.clear(); app._logged_month = None` con `activity_log.reset()`.

In `test/test_cold_download_log.py` (fixture `app_env`) sostituisci `audiobook_app._logged_sids_ops.clear()` con:

```python
    import activity_log
    activity_log.reset()
```

In `test/test_voice_clone_generate.py` (test `test_generate_maschera_il_token_nel_log_e_nel_digest`) sostituisci le due righe
`audiobook_app._logged_sids_ops.clear()` / `audiobook_app._logged_month = None` con:

```python
    import activity_log
    activity_log.reset()
```

- [ ] **Step 2: Esegui i test, il test C1 deve fallire**

Run: `python -m pytest test/test_log_activity_regen_dedup.py test/test_activity_platform.py test/test_cold_download_log.py -q -p no:cacheprovider`
Expected: FAIL solo `test_eventi_senza_job_non_deduplicati` (`assert 1 == 2`); gli altri possono gia' passare o fallire perche' il dedup vive ancora in `audiobook_app`.

- [ ] **Step 3: Collega `audiobook_app` ad `activity_log`**

Dopo `import user_stats` (~riga 158) aggiungi:

```python
import activity_log

# Il business log vive in SCRIPT_DIR (fase 1). La callable e' risolta a ogni
# scrittura/lettura: patchare SCRIPT_DIR nei test basta a spostarlo.
activity_log.configure(log_dir=lambda: SCRIPT_DIR)
```

Elimina per intero il blocco (~righe 3129–3148):

```python
#  -  -  Activity log  -  -
_log_lock = threading.Lock()
_logged_month: str = ""
_logged_sids_ops: set[tuple] = set()  # (job_id, op) o (job_id, op, epoch) per eventi di ciclo

def _init_log_dedup():
    ...
                    _logged_sids_ops.add((parts[0], parts[3]))
```

lasciando al suo posto solo la riga di sezione `#  -  -  Activity log  -  -`.

Sostituisci l'intera `_log_activity` con:

```python
def _log_activity(session_id, filename, operation, client_id='', client_ip='', voice='', browser_lang='', epoch=None, platform=''):
    """Scrive una riga nel business log mensile (vedi activity_log.log).

    Dedup per (job_id, operazione); con `epoch` (es. job["gen_epoch"]) la
    chiave include l'epoca, cosi' GENERATE/COMPLETE di una RI-generazione
    dello stesso job_id non vengono soppressi. Gli eventi senza job_id
    (voucher, admin, backend TTS) non si deduplicano mai.
    """
    activity_log.log(session_id, filename, operation, client_id=client_id,
                     ip=client_ip, voice=voice, lang=browser_lang,
                     platform=platform, epoch=epoch)
```

Sostituisci la chiamata d'avvio `_init_log_dedup()` (~riga 21870) con `activity_log.init_dedup()`.

- [ ] **Step 4: Verifica che non restino riferimenti**

Run: `git grep -n "_logged_sids_ops\|_logged_month\|_init_log_dedup\|_log_lock\b" -- "*.py"`
Expected: nessun risultato.

- [ ] **Step 5: Compila ed esegui i test**

Run: `python -m py_compile audiobook_app.py`
Run: `python -m pytest test/test_activity_log.py test/test_log_activity_regen_dedup.py test/test_activity_platform.py test/test_cold_download_log.py test/test_voice_clone_generate.py test/test_admin_logactivity_filters.py -q -p no:cacheprovider`
Expected: PASS, salvo i fallimenti preesistenti di `test_voice_clone_generate.py` gia' presenti in baseline (confronta con `git stash`-free: esegui lo stesso file su `fb0cb94` solo se il conteggio differisce).

- [ ] **Step 6: Commit**

```powershell
git add audiobook_app.py test/test_log_activity_regen_dedup.py test/test_activity_platform.py test/test_cold_download_log.py test/test_voice_clone_generate.py
git commit -m "refactor(activity-log): _log_activity e dedup d'avvio su activity_log, eventi senza job mai deduplicati"
```

---

### Task 3: gli eventi `M4B_*` portano il `job_id` (C3)

**Files:**
- Modify: `generation_engine.py:2744-2776` (`_log_m4b_progress`) e i 6 chiamanti in `run_generation` (~righe 6893, 6930, 6984, 7031, 7320, 7351)
- Modify: `audiobook_app.py` (rimuovi la copia morta `_log_m4b_progress`, ~righe 3304–3333)
- Modify: `test/test_m4b_progress.py:11-61`, `test/test_regression_double_module.py:37-54`

**Interfaces:**
- Consumes: `generation_engine._log_activity` (iniettato via `configure`, firma di `audiobook_app._log_activity`).
- Produces: `generation_engine._log_m4b_progress(job_id: str, job: dict, event: str, **fields) -> None`.

- [ ] **Step 1: Riscrivi i test sulla firma nuova**

In `test/test_m4b_progress.py` sostituisci i tre test del blocco "Task 1 — _log_m4b_progress" (righe 11–61) con:

```python
def test_log_m4b_progress_emits_start_line(monkeypatch):
    """START scrive 1 riga M4B_START col job_id passato, anche se il dict
    del job non ha la chiave "job_id" (come i veri jobs[job_id])."""
    import generation_engine

    captured = []
    monkeypatch.setattr(generation_engine, "_log_activity",
                        lambda *a, **kw: captured.append((a, kw)))
    job = {"client_id": "c1", "ip": "1.2.3.4", "voice": "it-IT-Isola", "lang": "it",
           "original_filename": "libro.epub"}

    generation_engine._log_m4b_progress("J1", job, "START", size_mb=12.3, msg="start")

    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[0] == "J1"
    assert args[1] == "libro.epub"
    assert args[2] == "M4B_START"
    assert kwargs["client_id"] == "c1"


def test_log_m4b_progress_throttles_progress_lines(monkeypatch):
    """Chiamate ravvicinate M4B_PROGRESS: al massimo una riga ogni 10 s."""
    import generation_engine

    captured = []
    monkeypatch.setattr(generation_engine, "_log_activity",
                        lambda *a, **kw: captured.append((a, kw)))
    job = {"_m4b_last_log_ts": 0.0}

    for pct in (10, 20, 30):
        generation_engine._log_m4b_progress("J2", job, "PROGRESS", pct=pct, msg="enc")

    assert len(captured) <= 1


def test_log_m4b_progress_end_no_throttle(monkeypatch):
    """M4B_END non e' soggetto a throttling."""
    import generation_engine

    captured = []
    monkeypatch.setattr(generation_engine, "_log_activity",
                        lambda *a, **kw: captured.append((a, kw)))
    job = {"_m4b_last_log_ts": time.time()}

    generation_engine._log_m4b_progress("J3", job, "END", status="ok", pct=100, size_mb=50.0)

    assert len(captured) == 1
    assert captured[0][0][0] == "J3"
    assert captured[0][0][2] == "M4B_END"


def test_run_generation_passa_job_id_a_ogni_evento_m4b():
    """C3: tutti i chiamanti in run_generation passano job_id come primo argomento."""
    import ast
    import inspect
    import generation_engine

    tree = ast.parse(inspect.getsource(generation_engine.run_generation))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_log_m4b_progress"]
    assert len(calls) == 6
    assert all(isinstance(c.args[0], ast.Name) and c.args[0].id == "job_id" for c in calls)
```

In `test/test_regression_double_module.py`, dentro `test_log_m4b_progress_definito_in_generation_engine`, sostituisci:

```python
        job = {"job_id": "R1", "client_id": "c", "ip": "1.1.1.1", "lang": "it"}
        generation_engine._log_m4b_progress(job, "START", size_mb=0.0)
```

con:

```python
        job = {"client_id": "c", "ip": "1.1.1.1", "lang": "it"}
        generation_engine._log_m4b_progress("R1", job, "START", size_mb=0.0)
```

- [ ] **Step 2: Esegui i test, devono fallire**

Run: `python -m pytest test/test_m4b_progress.py test/test_regression_double_module.py -q -p no:cacheprovider`
Expected: FAIL sui 4 test M4B nuovi e su quello di regressione (argomenti in piu' / primo argomento non `job_id`).

- [ ] **Step 3: Cambia la firma in `generation_engine`**

Sostituisci `_log_m4b_progress` con:

```python
def _log_m4b_progress(job_id: str, job: dict, event: str, **fields) -> None:
    """Scrive riga in activity_YYYY-MM.log per eventi M4B_* con throttling 10s per PROGRESS.

    job_id: chiave del job in `_jobs` (il dict del job non la contiene).
    event: "START" | "PROGRESS" | "END"
    fields: size_mb, pct, msg, status, elapsed_s, duration_s (campi liberi, finiscono nel campo `voice`)
    """
    if event == "PROGRESS":
        now = time.time()
        if now - job.get("_m4b_last_log_ts", 0) < 10:
            return
        job["_m4b_last_log_ts"] = now

    # Componi i fields in un payload sintetico nel campo `voice` (libero).
    payload_parts = [f"{k}={fields[k]}" for k in sorted(fields.keys())]
    payload = " ".join(payload_parts)[:200]  # cap a 200 char

    try:
        _log_activity(
            job_id,
            job.get("original_filename", ""),
            "M4B_" + event,
            client_id=job.get("client_id", ""),
            client_ip=job.get("ip", ""),
            voice=payload,
            browser_lang=job.get("lang", ""),
        )
    except Exception as e:
        # Logging non deve mai crashare il thread di generazione.
        print(f"[_log_m4b_progress] errore scrittura log: {e}")
```

(Conserva il corpo esistente riga per riga dove coincide; cambiano solo firma, docstring e primo argomento di `_log_activity`.)

Nei 6 chiamanti dentro `run_generation` sostituisci il primo argomento `job` con `job_id, job`:
- `_log_m4b_progress(job, "START", size_mb=round(` → `_log_m4b_progress(job_id, job, "START", size_mb=round(` (3 occorrenze)
- `_log_m4b_progress(` seguito a capo da `job, "END",` → `job_id, job, "END",` (3 occorrenze)

- [ ] **Step 4: Rimuovi la copia morta in `audiobook_app`**

Elimina da `audiobook_app.py` l'intera funzione `def _log_m4b_progress(job: dict, event: str, **fields) -> None:` (~righe 3304–3333, fino al `print(f"[_log_m4b_progress] errore scrittura log: {e}")` incluso).

Run: `git grep -n "_log_m4b_progress" -- "*.py"`
Expected: definizione e 6 chiamate in `generation_engine.py`, piu' i test; nessuna occorrenza in `audiobook_app.py`.

- [ ] **Step 5: Compila ed esegui i test**

Run: `python -m py_compile generation_engine.py`
Run: `python -m py_compile audiobook_app.py`
Run: `python -m pytest test/test_m4b_progress.py test/test_regression_double_module.py test/test_m4b_conversion_stall.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add generation_engine.py audiobook_app.py test/test_m4b_progress.py test/test_regression_double_module.py
git commit -m "fix(m4b): eventi M4B_* nel business log col job_id del job"
```

---

### Task 4: prova di consegna del recovery su `delivered_ids`

**Files:**
- Modify: `audiobook_app.py:1931-1972` (rimuovi `_delivered_ids_lock`, `_delivered_ids_cache`, `_delivered_job_ids`) e `~1979` (`_orphan_job_delivered`)
- Modify: `test/test_orphan_delivered_no_refund.py:31-46`

**Interfaces:**
- Consumes: `activity_log.delivered_ids(months=3)`, `activity_log.reset()`.
- Produces: niente di nuovo; `_orphan_job_delivered(job_id, rec)` invariata.

- [ ] **Step 1: Adegua la fixture**

In `test/test_orphan_delivered_no_refund.py` aggiungi `import activity_log` agli import e, nella fixture `recovery_env`, sostituisci entrambe le coppie

```python
    audiobook_app._delivered_ids_cache["value"] = None
    audiobook_app._delivered_ids_cache["expires"] = 0.0
```

con `activity_log.reset()`.

Aggiungi in fondo al file un test sul titolo col cancelletto:

```python
def test_consegna_riconosciuta_con_cancelletto_nel_titolo(recovery_env):
    script_dir, _calls = recovery_env
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    _write_activity(script_dir, [
        f'JHASH # {ts} # "Saga # 2.epub" # COMPLETE # cid # 1.2.3.4 # it-IT-X # it'])
    assert "JHASH" in activity_log.delivered_ids()["complete"]
```

- [ ] **Step 2: Esegui i test, devono fallire**

Run: `python -m pytest test/test_orphan_delivered_no_refund.py -q -p no:cacheprovider`
Expected: il test nuovo PASSA gia' (usa `activity_log` direttamente); FALLISCONO i test che si aspettano la consegna letta dall'app se la cache di `audiobook_app` resta sporca fra un test e l'altro. Se passano tutti, procedi: il passo 3 e' comunque richiesto dal criterio di chiusura.

- [ ] **Step 3: Sostituisci la cache locale**

Elimina da `audiobook_app.py` il blocco da `_delivered_ids_lock = threading.Lock()` fino al `return value` finale di `_delivered_job_ids` compreso. In `_orphan_job_delivered` sostituisci `idx = _delivered_job_ids()` con `idx = activity_log.delivered_ids()`.

Run: `git grep -n "_delivered_job_ids\|_delivered_ids_cache\|_delivered_ids_lock" -- "*.py"`
Expected: nessun risultato.

- [ ] **Step 4: Compila ed esegui i test**

Run: `python -m py_compile audiobook_app.py`
Run: `python -m pytest test/test_orphan_delivered_no_refund.py test/test_activity_log.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add audiobook_app.py test/test_orphan_delivered_no_refund.py
git commit -m "refactor(recovery): prova di consegna da activity_log.delivered_ids"
```

---

### Task 5: statistiche community su `iter_rows`

**Files:**
- Modify: `audiobook_app.py:3352-3424` (rimuovi `_parse_activity_lines`; riscrivi `_stats_today_count`, `_stats_month_by_lang`)
- Create: `test/test_activity_log_readers.py`

**Interfaces:**
- Consumes: `activity_log.iter_rows(since, ops=...)`, `activity_log.reset()`.
- Produces: `_stats_today_count() -> int`, `_stats_month_by_lang() -> {"monthly", "top", "other"}` invariati.

- [ ] **Step 1: Scrivi i test**

Crea `test/test_activity_log_readers.py`:

```python
"""Lettori del business log in audiobook_app dopo il passaggio ad activity_log."""
from datetime import datetime, timedelta

import pytest

import activity_log
import audiobook_app


def _line(job, ts, op, fn="a.epub", cid="c", ip="1.1.1.1", voice="it-IT-X",
          lang="it", plat="web"):
    return f'{job} # {ts} # "{fn}" # {op} # {cid} # {ip} # {voice} # {lang} # {plat}'


def _write_by_month(d, lines_with_ts):
    """lines_with_ts: [(datetime, riga)] -> un file per mese."""
    by_month = {}
    for when, line in lines_with_ts:
        by_month.setdefault(when.strftime("%Y-%m"), []).append(line)
    for ym, lines in by_month.items():
        with open(d / f"activity_{ym}.log", "a", encoding="utf-8") as f:
            f.write("".join(l + "\n" for l in lines))


@pytest.fixture
def logs(tmp_path, monkeypatch):
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    activity_log.reset()
    for c in (audiobook_app._stats_today_cache, audiobook_app._stats_month_cache):
        c["value"] = None
        c["expires"] = 0.0
    yield tmp_path
    activity_log.reset()
    for c in (audiobook_app._stats_today_cache, audiobook_app._stats_month_cache):
        c["value"] = None
        c["expires"] = 0.0


def test_statistiche_community_contano_anche_i_titoli_col_cancelletto(logs):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write_by_month(logs, [
        (now, _line("J1", ts, "COMPLETE", voice="it-IT-DiegoNeural")),
        (now, _line("J2", ts, "OPT_COMPLETE", fn="Saga # 2.epub", voice="en-US-GuyNeural")),
        (now, _line("J3", ts, "GENERATE", voice="it-IT-DiegoNeural")),
        (now, _line("J4", ts, "COMPLETE", voice="")),
    ])
    assert audiobook_app._stats_today_count() == 3
    res = audiobook_app._stats_month_by_lang()
    assert res["monthly"] == 3
    assert {r["lang"]: r["count"] for r in res["top"]} == {"it": 1, "en": 1}
    assert res["other"] == 0


def test_statistiche_community_escludono_ieri_dal_conteggio_di_oggi(logs):
    now = datetime.now()
    ieri = now - timedelta(days=1)
    _write_by_month(logs, [
        (ieri, _line("OLD", ieri.strftime("%Y-%m-%d %H:%M:%S"), "COMPLETE")),
        (now, _line("NEW", now.strftime("%Y-%m-%d %H:%M:%S"), "COMPLETE")),
    ])
    assert audiobook_app._stats_today_count() == 1
```

- [ ] **Step 2: Esegui i test, il primo deve fallire**

Run: `python -m pytest test/test_activity_log_readers.py -q -p no:cacheprovider`
Expected: FAIL `test_statistiche_community_contano_anche_i_titoli_col_cancelletto` (la riga `OPT_COMPLETE` col `#` nel titolo non viene contata: `2 == 3`).

- [ ] **Step 3: Riscrivi i due lettori**

Elimina `_parse_activity_lines`. Sotto le cache (`_stats_month_cache = ...`) aggiungi:

```python
_COMMUNITY_OPS = frozenset({"COMPLETE", "OPT_COMPLETE"})
```

Sostituisci `_stats_today_count` e `_stats_month_by_lang` con:

```python
def _stats_today_count() -> int:
    """Conta COMPLETE e OPT_COMPLETE odierni. Cache 60s."""
    now = time.time()
    with _stats_lock:
        if _stats_today_cache["value"] is not None and now < _stats_today_cache["expires"]:
            return _stats_today_cache["value"]
    midnight = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    count = sum(1 for _ in activity_log.iter_rows(midnight, ops=_COMMUNITY_OPS))
    with _stats_lock:
        _stats_today_cache["value"] = count
        _stats_today_cache["expires"] = now + 60.0
    return count


def _stats_month_by_lang() -> dict:
    """Aggrega COMPLETE e OPT_COMPLETE del mese corrente per lingua TTS.
    Restituisce {monthly: int, top: [{lang, count}], other: int}.
    Cache 5min."""
    now = time.time()
    with _stats_lock:
        if _stats_month_cache["value"] is not None and now < _stats_month_cache["expires"]:
            return _stats_month_cache["value"]
    month_start = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    by_lang: dict[str, int] = defaultdict(int)
    total = 0
    for row in activity_log.iter_rows(month_start, ops=_COMMUNITY_OPS):
        total += 1
        if not row.voice:
            continue
        lang = row.voice.split("-")[0].strip().lower()
        if lang:
            by_lang[lang] += 1
    sorted_langs = sorted(by_lang.items(), key=lambda kv: kv[1], reverse=True)
    top = [{"lang": k, "count": v} for k, v in sorted_langs[:4]]
    other = sum(v for _, v in sorted_langs[4:])
    result = {"monthly": total, "top": top, "other": other}
    with _stats_lock:
        _stats_month_cache["value"] = result
        _stats_month_cache["expires"] = now + 300.0
    return result
```

Aggiorna il commento di sezione "COMMUNITY STATS — derivate dai log activity_YYYY-MM.log esistenti" in "COMMUNITY STATS — derivate dal business log (activity_log)".

- [ ] **Step 4: Compila ed esegui i test**

Run: `python -m py_compile audiobook_app.py`
Run: `python -m pytest test/test_activity_log_readers.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add audiobook_app.py test/test_activity_log_readers.py
git commit -m "refactor(stats): statistiche community su activity_log.iter_rows"
```

---

### Task 6: sessioni del pannello admin su `month_rows`

**Files:**
- Modify: `audiobook_app.py:4332-4421` (`_parse_log_sessions`)
- Modify: `test/test_activity_log_readers.py`

**Interfaces:**
- Consumes: `activity_log.month_rows(ym)`.
- Produces: `_parse_log_sessions(ym) -> (OrderedDict sessions, dict client_session_count)` invariata (resta in `audiobook_app`: `test_admin_voice_xss.py` e `test_m4b_progress.py` la sostituiscono con monkeypatch).

- [ ] **Step 1: Aggiungi i test**

In fondo a `test/test_activity_log_readers.py`:

```python
def test_sessioni_admin_ignorano_le_righe_senza_job_e_reggono_byte_rotti(logs):
    raw = (
        ' # 2026-08-01 09:00:00 # "" # ADMIN_TTS_PROBE #  # 9.9.9.9 # k # avviata=True # \n'
        ' # 2026-08-01 09:01:00 # "" # VOUCHER_ATTEMPT #  # 9.9.9.9 # AB12... # ok # \n'
    ).encode("utf-8") + b"\xff\xfe\n" + (
        _line("J1", "2026-08-01 10:00:00", "GENERATE", fn="Saga # 2.epub", cid="cidA") + "\n"
        + _line("J1", "2026-08-01 10:30:00", "COMPLETE", fn="Saga # 2.epub", cid="cidA") + "\n"
    ).encode("utf-8")
    (logs / "activity_2026-08.log").write_bytes(raw)

    sessions, per_client = audiobook_app._parse_log_sessions("2026-08")

    assert list(sessions) == ["J1"]
    s = sessions["J1"]
    assert s["filename"] == "Saga # 2.epub"
    assert s["events"] == ["GENERATE", "COMPLETE"] and s["last_op"] == "COMPLETE"
    assert per_client == {"cidA": 1}


def test_sessioni_admin_mese_assente(logs):
    assert audiobook_app._parse_log_sessions("2026-01") == ({}, {})


def test_pagina_admin_regge_byte_non_utf8(logs, monkeypatch):
    from unittest.mock import patch
    ym = datetime.now().strftime("%Y-%m")
    (logs / f"activity_{ym}.log").write_bytes(
        b"\xff\xfe\n" + _line("J1", f"{ym}-01 10:00:00", "COMPLETE").encode("utf-8") + b"\n")
    with patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity")
    assert r.status_code == 200
```

- [ ] **Step 2: Esegui i test, devono fallire**

Run: `python -m pytest test/test_activity_log_readers.py -q -p no:cacheprovider`
Expected: FAIL `test_sessioni_admin_ignorano...` e `test_pagina_admin_regge_byte_non_utf8` con `UnicodeDecodeError` (il file e' aperto senza `errors="replace"`) o risposta 500.

- [ ] **Step 3: Riscrivi `_parse_log_sessions`**

```python
def _parse_log_sessions(ym):
    """Sessioni del business log del mese YYYY-MM.

    Ritorna (sessions OrderedDict job_id -> dict, client_session_count dict)."""
    from datetime import datetime
    from collections import OrderedDict

    sessions = OrderedDict()
    for fields in activity_log.month_rows(ym):
        (sid, dt_str, filename, operation, client_id, client_ip,
         voice, browser_lang, platform) = fields
        # Righe di sistema (voucher, admin, backend TTS) senza job: non sono
        # sessioni. Prima uscivano di fatto perche' lo strip() iniziale
        # sfasava i campi e la data non si leggeva piu'.
        if not sid:
            continue
        # Skip voucher audit entries — not conversion activity
        if operation.startswith("VOUCHER_ATTEMPT"):
            continue

        try:
            dt = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        # Avvio reale del libro con voce PREMIUM: GENERATE, oppure
        # OPTIMIZE del wizard combinato (ottimizza + auto-gen), che porta
        # la voce di destinazione gia' in fase di ottimizzazione AI. Si
        # guarda la voce della RIGA, non l'ultima vista sulla sessione:
        # un'anteprima premium seguita da un OPTIMIZE senza voce non conta.
        premium_started = (
            operation in _PREMIUM_START_OPS
            and (_is_gemini_voice(voice) or _is_speechify_voice(voice)
                 or _is_voxcpm_voice(voice))
        )
        if sid not in sessions:
            sessions[sid] = {
                "first_dt": dt, "last_dt": dt,
                "filename": filename, "last_op": operation,
                "events": [operation],
                "client_id": client_id, "client_ip": client_ip,
                "voice": voice, "browser_lang": browser_lang,
                "platform": platform,
                "transferred": operation == "TRANSFER",
                "premium_started": premium_started,
            }
        else:
            s = sessions[sid]
            if premium_started:
                s["premium_started"] = True
            if dt < s["first_dt"]:
                s["first_dt"] = dt
            if dt >= s["last_dt"]:
                s["last_dt"] = dt
                s["last_op"] = operation
            # Solo se valorizzato: gli eventi di servizio (TRANSFER,
            # ADMIN_COPY*) loggano filename vuoto e altrimenti cancellavano
            # il titolo del libro dalla card della sessione.
            if filename:
                s["filename"] = filename
            s["events"].append(operation)
            if client_id:
                s["client_id"] = client_id
            if client_ip:
                s["client_ip"] = client_ip
            if voice:
                s["voice"] = voice
            if browser_lang:
                s["browser_lang"] = browser_lang
            if platform and not s["platform"]:
                s["platform"] = platform
            if operation == "TRANSFER":
                s["transferred"] = True

    client_session_count = {}
    for s in sessions.values():
        cid = s.get("client_id", "")
        if cid:
            client_session_count[cid] = client_session_count.get(cid, 0) + 1

    return sessions, client_session_count
```

Prima di sostituire, confronta il corpo del ciclo con quello attuale: la logica deve restare identica riga per riga, cambiano solo sorgente delle righe, indentazione e il nuovo `if not sid: continue`.

- [ ] **Step 4: Compila ed esegui i test**

Run: `python -m py_compile audiobook_app.py`
Run: `python -m pytest test/test_activity_log_readers.py test/test_admin_logactivity_filters.py test/test_admin_voice_xss.py test/test_m4b_progress.py -q -p no:cacheprovider`
Expected: PASS, salvo il fallimento preesistente di `test_admin_voice_xss.py` in baseline.

- [ ] **Step 5: Commit**

```powershell
git add audiobook_app.py test/test_activity_log_readers.py
git commit -m "refactor(admin): sessioni del pannello log da activity_log.month_rows"
```

---

### Task 7: `user_stats` sulle righe; statistiche utente e power user

**Files:**
- Modify: `user_stats.py` (docstring di modulo, import, `split_line`, `parse_sessions`, `_YM_IN_NAME`, `_ym_from_name`, `analyze`, `power_users`)
- Modify: `audiobook_app.py:4505-4530` (`_power_users_data`), `~12856-12913` (`_USER_STATS_CACHE`, `api_admin_user_stats`)
- Modify: `test/test_admin_user_stats.py`, `test/test_power_users_digest.py`, `test/test_activity_log_readers.py`

**Interfaces:**
- Consumes: `activity_log.month_rows`, `iter_rows`, `fingerprint`, `file_rows`.
- Produces:
  - `user_stats.parse_sessions(rows) -> OrderedDict`
  - `user_stats.analyze(rows, ym="", ip_fallback=True, payments=None) -> dict` (con `"file": ""`)
  - `user_stats.power_users(rows, since, min_jobs=5, quota_table=None, top=10, month_ym=None) -> list`
  - `rows`: iterabile di 9-tuple nell'ordine di `activity_log.Row`.

- [ ] **Step 1: Adegua i test di `user_stats`**

In `test/test_admin_user_stats.py`:
- aggiungi `import activity_log` agli import;
- elimina `test_split_line_tollera_il_cancelletto_nel_nome_file`, `test_split_line_riga_corta_non_esplode`, `test_split_line_riga_incompleta_scartata`, `test_split_line_regge_il_campo_finale_vuoto`, `test_split_line_cancelletto_nel_titolo_e_platform_vuota`, `test_ym_dal_nome_del_file` (coperti da `test/test_activity_log.py`);
- sostituisci ogni `user_stats.analyze(str(logfile)` con `user_stats.analyze(activity_log.file_rows(logfile), ym="2026-08"` (4 occorrenze; resta invariato il resto degli argomenti, es. `, payments=pays)`);
- sostituisci ogni `user_stats.parse_sessions(str(logfile))` con `user_stats.parse_sessions(activity_log.file_rows(logfile))` (2 occorrenze);
- se `logfile_lingue` e' passato a `user_stats.analyze(str(logfile_lingue)...`, applica la stessa sostituzione con `activity_log.file_rows(logfile_lingue), ym="2026-08"`.

Aggiungi:

```python
def test_parse_sessions_accetta_righe_e_scarta_quelle_senza_job():
    rows = [
        activity_log.Row("", "2026-08-01 09:00:00", "", "ADMIN_TTS_PROBE", "", "9.9.9.9", "k", "x", ""),
        activity_log.Row("j1", "2026-08-01 10:00:00", "a.epub", "COMPLETE", "cidA", "1.1.1.1",
                         "it-IT-X", "it", "web"),
    ]
    assert list(user_stats.parse_sessions(rows)) == ["j1"]


def test_user_stats_resta_un_modulo_foglia():
    import ast
    import pathlib
    src = pathlib.Path(user_stats.__file__).read_text(encoding="utf-8")
    mods = set()
    for n in ast.walk(ast.parse(src)):
        if isinstance(n, ast.Import):
            mods.update(a.name.split(".")[0] for a in n.names)
        elif isinstance(n, ast.ImportFrom):
            mods.add((n.module or "").split(".")[0])
    assert mods <= {"json", "collections", "datetime"}
```

In `test/test_power_users_digest.py`:
- aggiungi `import itertools` e `import activity_log`;
- sostituisci ogni `user_stats.power_users([p], ` con `user_stats.power_users(activity_log.file_rows(p), `;
- sostituisci `user_stats.power_users([p, tmp_path / "activity_2026-07.log"], since, min_jobs=3)` con
  `user_stats.power_users(itertools.chain(activity_log.file_rows(p), activity_log.file_rows(tmp_path / "activity_2026-07.log")), since, min_jobs=3)`.

Aggiungi:

```python
def test_power_users_ignora_le_righe_senza_job(tmp_path):
    since = datetime(2026, 8, 30, 12, 0, 0)
    lines = [' # 2026-08-30 13:00:00 # "" # GENERATE #  # 7.7.7.7 # en-US-AriaNeural # en # web']
    lines += [_line(f"g{i}", f"2026-08-30 1{3 + i}:00:00", "b.epub", "GENERATE", "cidX", "1.1.1.1")
              for i in range(2)]
    p = _write_log(tmp_path, lines)
    rows = user_stats.power_users(activity_log.file_rows(p), since, min_jobs=1)
    assert [r["client_id"] for r in rows] == ["cidX"]
```

In fondo a `test/test_activity_log_readers.py`:

```python
def test_power_users_data_legge_il_mese_corrente(logs, monkeypatch):
    monkeypatch.setattr(audiobook_app, "POWER_USER_JOBS_PER_DAY", 3)
    now = datetime.now()
    righe = []
    for i in range(3):
        when = now - timedelta(minutes=10 * (i + 1))
        righe.append((when, _line(f"p{i}", when.strftime("%Y-%m-%d %H:%M:%S"),
                                  "GENERATE", cid="heavy", voice="en-US-AriaNeural")))
    _write_by_month(logs, righe)
    data = audiobook_app._power_users_data()
    assert [r["client_id"] for r in data["rows"]] == ["heavy"]
    assert data["rows"][0]["jobs_24h"] == 3


def test_endpoint_user_stats_invalida_la_cache_quando_il_log_cresce(logs):
    from unittest.mock import patch
    audiobook_app._USER_STATS_CACHE.clear()
    p = logs / "activity_2026-08.log"
    p.write_text(_line("J1", "2026-08-01 10:00:00", "COMPLETE", cid="a") + "\n", encoding="utf-8")
    with patch("audiobook_app._admin_auth_ok", return_value=True):
        c = audiobook_app.app.test_client()
        d1 = c.get("/api/admin/user_stats?ym=2026-08").get_json()
        with open(p, "a", encoding="utf-8") as f:
            f.write(_line("J2", "2026-08-01 11:00:00", "COMPLETE", cid="b") + "\n")
        d2 = c.get("/api/admin/user_stats?ym=2026-08").get_json()
    audiobook_app._USER_STATS_CACHE.clear()
    assert d1["coorti"]["totale"]["generazioni"] == 1
    assert d2["coorti"]["totale"]["generazioni"] == 2
    assert d2["file"] == "activity_2026-08.log"
```

- [ ] **Step 2: Esegui i test, devono fallire**

Run: `python -m pytest test/test_admin_user_stats.py test/test_power_users_digest.py test/test_activity_log_readers.py -q -p no:cacheprovider`
Expected: FAIL diffusi (`TypeError`/`expected str, bytes or os.PathLike` su `open(rows)`, `analyze() got an unexpected keyword argument 'ym'`, `test_user_stats_resta_un_modulo_foglia` per `os`/`re`).

- [ ] **Step 3: Riscrivi le parti di `user_stats` che leggono file**

Docstring di modulo: sostituisci il paragrafo "Sorgente: …" e l'ultimo paragrafo con:

```python
"""...
Sorgente: le righe del business log mensile, gia' spezzate nei 9 campi
`job_id, ts, filename, op, client_id, ip, voice, lang, platform` (vedi
`activity_log.Row`). Il modulo non legge file: le righe le passa il chiamante
(`activity_log.month_rows(ym)` nell'app, `activity_log.file_rows(path)` negli
script), cosi' resta una foglia pura.
...
Solo stdlib, nessun import dal progetto.
"""
```

(mantieni invariati i paragrafi su coorte PREMIUM e pagamenti con buono).

Import: `import os` e `import re` escono; restano `json`, `Counter, OrderedDict`, `datetime`.

Elimina `_YM_IN_NAME` (e il suo commento), `split_line`, `_ym_from_name`.

Sostituisci `parse_sessions` con:

```python
def parse_sessions(rows):
    """Aggrega le righe del log per job_id.

    `rows`: iterabile di 9-tuple (es. `activity_log.Row`). Ritorna OrderedDict
    job_id -> {events:set, voice, lang, client_id, client_ip, platform, day}.
    Come `_parse_log_sessions` in audiobook_app.py: per voice/lang/client_id/ip
    vince l'ultimo valore non vuoto.
    """
    sessions = OrderedDict()
    for fields in rows:
        sid, dt_str, _filename, operation, client_id, client_ip, voice, lang, platform = fields
        if not sid:
            continue  # righe di sistema (voucher, admin) senza job
        if operation.startswith("VOUCHER_ATTEMPT"):
            continue

        s = sessions.get(sid)
        if s is None:
            s = sessions[sid] = {
                "events": set(), "voice": "", "lang": "", "client_id": "",
                "client_ip": "", "platform": "", "day": dt_str[:10],
            }
        s["events"].add(operation)
        if client_id:
            s["client_id"] = client_id
        if client_ip:
            s["client_ip"] = client_ip
        if voice:
            s["voice"] = voice
        if lang:
            s["lang"] = lang
        if platform and not s["platform"]:
            s["platform"] = platform
    return sessions
```

In `analyze`:
- firma e docstring:

```python
def analyze(rows, ym="", ip_fallback=True, payments=None):
    """Analisi completa di un mese di log.

    `rows`: righe del mese (vedi `parse_sessions`). `ym`: mese YYYY-MM degli
    incassi da considerare; "" = nessun filtro (sconsigliato: un mese
    sbagliato azzera in silenzio gli incassi, uno assente li somma tutti).
    `payments`: record di `_payments.json` (order_id -> dict) o loro lista;
    servono per la concentrazione in valore, che il solo log non consente.
    """
    sessions = parse_sessions(rows)
```

- le due occorrenze `ym=_ym_from_name(path)` diventano `ym=ym`;
- `"file": str(path),` diventa `"file": "",` (lo imposta il chiamante).

In `power_users`:
- firma `def power_users(rows, since, min_jobs=5, quota_table=None, top=10, month_ym=None):`;
- nel docstring sostituisci il paragrafo su `paths` con:
  "`rows`: righe del log dall'inizio del mese di `since` a oggi (i contatori mensili leggono tutto il mese)."
- sostituisci l'apertura dei file e il ciclo interno:

```python
    for path in paths:
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                fl = split_line(line.strip())
                if not fl:
                    continue
                sid, ts, fn, op, cid, ip, voice, lang, plat = fl
                key = cid or (f"ip:{ip}" if ip else "")
```

con:

```python
    for fl in rows:
        sid, ts, fn, op, cid, ip, voice, lang, plat = fl
        if not sid:
            # Righe di sistema: nessun job da contare, e l'IP dell'admin non
            # deve finire fra gli IP di un client.
            continue
        key = cid or (f"ip:{ip}" if ip else "")
```

e dedenta di 8 spazi il resto del corpo del ciclo (da `if not key:` a `u["platforms"][plat] += 1`), senza cambiarne la logica.

- [ ] **Step 4: Aggiorna i chiamanti in `audiobook_app`**

`_power_users_data`: sostituisci il blocco da `import user_stats` a `rows = user_stats.power_users(...)` con:

```python
    from datetime import datetime, timedelta
    now = datetime.now()
    since = now - timedelta(hours=24)
    # Dall'inizio del mese di `since`: i contatori mensili (books_month,
    # starts_month) contano tutto il mese, non solo le ultime 24h.
    month_start = since.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    try:
        qt = free_tts_quota.month_table()
    except Exception:
        qt = {}
    rows = user_stats.power_users(activity_log.iter_rows(month_start), since,
                                  min_jobs=POWER_USER_JOBS_PER_DAY,
                                  quota_table=qt, top=10,
                                  month_ym=now.strftime("%Y-%m"))
```

Commento sopra `_USER_STATS_CACHE`:

```python
# Cache dell'analisi utenza: la scansione di un mese pieno costa ~1s e il
# pannello viene aperto e richiuso di continuo. Chiave = (ym, impronta del
# mese in activity_log, impronta dei pagamenti): un log che cresce invalida da solo.
```

In `api_admin_user_stats`, dopo la validazione di `ym`, sostituisci tutto fino a `return jsonify(data)` finale con:

```python
    log_name = f"activity_{ym}.log"
    fp = activity_log.fingerprint(ym)
    if fp is None:
        data = user_stats.empty_result(log_name)
        data["ym"] = ym
        data["log_missing"] = True
        return jsonify(data)

    # Gli incassi arrivano dalla memoria di `payment`, che e' l'unica copia
    # sempre allineata (il file su disco e' solo la sua persistenza).
    pay_records = list(getattr(payment, "_payments", {}).values())
    # Impronta dei pagamenti: un incasso nuovo deve invalidare la cache anche
    # se il log del mese non e' cambiato.
    pay_key = (len(pay_records),
               max((r.get("captured_at") or 0 for r in pay_records), default=0))
    key = (ym, fp, pay_key)
    if key in _USER_STATS_CACHE:
        return jsonify(_USER_STATS_CACHE[key])

    t0 = time.time()
    try:
        data = user_stats.analyze(activity_log.month_rows(ym), ym=ym,
                                  payments=pay_records)
    except Exception as e:
        print(f"[admin] user_stats {ym} failed: {e}", flush=True)
        return jsonify({"error": f"Analysis failed: {e}"}), 500
    data["ym"] = ym
    data["file"] = log_name  # mai il path assoluto del server
    data["elapsed_sec"] = round(time.time() - t0, 2)
    if len(_USER_STATS_CACHE) >= _USER_STATS_CACHE_MAX:
        _USER_STATS_CACHE.pop(next(iter(_USER_STATS_CACHE)), None)
    _USER_STATS_CACHE[key] = data
    return jsonify(data)
```

Run: `git grep -n "user_stats.split_line\|_ym_from_name\|power_users(\[" -- "*.py"`
Expected: nessun risultato.

- [ ] **Step 5: Compila ed esegui i test**

Run: `python -m py_compile user_stats.py`
Run: `python -m py_compile audiobook_app.py`
Run: `python -m pytest test/test_admin_user_stats.py test/test_power_users_digest.py test/test_activity_log_readers.py test/test_activity_log.py -q -p no:cacheprovider`
Expected: PASS.

- [ ] **Step 6: Commit**

```powershell
git add user_stats.py audiobook_app.py test/test_admin_user_stats.py test/test_power_users_digest.py test/test_activity_log_readers.py
git commit -m "refactor(user-stats): analisi e power user sulle righe di activity_log"
```

- [ ] **Step 7: Script locale fuori dal repo**

`scripts/analyze_user_concentration.py` nel checkout principale (non tracciato) chiama `user_stats.analyze(a.logfile, ...)`. Adeguarlo a mano:

```python
import activity_log
...
ym = activity_log._YM_IN_NAME.match(os.path.basename(a.logfile))
res = user_stats.analyze(activity_log.file_rows(a.logfile),
                         ym=ym.group(1) if ym else "", ...)
```

Nessun commit (file ignorato). Segnalare all'utente nel resoconto finale.

---

### Task 8: navigazione mesi, criterio di chiusura, equivalenza e suite completa

**Files:**
- Modify: `audiobook_app.py:5044-5051` (mesi disponibili nel pannello admin)
- Modify (locale, non tracciato): `md_files/ARCHITETTURA.md` (tabella moduli)

**Interfaces:**
- Consumes: `activity_log.months()`.
- Produces: nessuna interfaccia nuova.

- [ ] **Step 1: Mesi del pannello admin da `months()`**

Sostituisci:

```python
    available_months = []
    try:
        for f in sorted(SCRIPT_DIR.glob("activity_*.log"), reverse=True):
            m = re.search(r'activity_(\d{4}-\d{2})\.log', f.name)
            if m:
                available_months.append(m.group(1))
    except Exception:
        pass
```

con:

```python
    available_months = activity_log.months()
```

Run: `python -m py_compile audiobook_app.py`
Run: `python -m pytest test/test_admin_user_stats.py -q -p no:cacheprovider -k modale`
Expected: PASS (`test_modale_utenza_ha_un_bottone_per_ogni_mese_con_log` usa la `SCRIPT_DIR` finta di `conftest.admin_log_page`).

- [ ] **Step 2: Criterio di chiusura**

Run: `git grep -n "activity_" -- audiobook_app.py user_stats.py`
Expected: solo commenti, nomi di operazioni, `log_name = f"activity_{ym}.log"` in `api_admin_user_stats`, nomi degli export (`activity_log_{ym}.xlsx/csv`) e la stampa d'avvio `Activity log:`. Nessun `open(`, `glob(`, `SCRIPT_DIR / f"activity_`.

- [ ] **Step 3: Equivalenza sui log reali**

Run:

```powershell
python "<scratchpad>\equiv_activity_log.py" "." "C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker" "<scratchpad>\equiv_after.json"
```

```powershell
python "<scratchpad>\equiv_compare.py" "<scratchpad>\equiv_before.json" "<scratchpad>\equiv_after.json"
```

Expected: `sessions/*`, `analyze/*`, `power_users/*` identici. Differenze ammesse solo in `delivered`, `stats_today`, `stats_month`, e solo in crescita, per righe `COMPLETE`/`OPT_COMPLETE` con `" # "` nel titolo; e in chiavi che prima valevano `ERROR ...` (byte non UTF-8). Verifica le differenze di `delivered` con:

```powershell
python -c "import json,sys; a=json.load(open(sys.argv[1],encoding='utf-8'))['delivered']; b=json.load(open(sys.argv[2],encoding='utf-8'))['delivered']; print({k: sorted(set(b[k])-set(a[k]))[:10] for k in b}, {k: sorted(set(a[k])-set(b[k]))[:10] for k in a})" "<scratchpad>\equiv_before.json" "<scratchpad>\equiv_after.json"
```

Expected: il secondo dizionario (id persi) vuoto; ogni id del primo ha nel log una riga con `" # "` nel titolo (`Select-String -Path "<checkout>\activity_2026-0*.log" -Pattern "^<id> # .*COMPLETE"`). Qualsiasi altra differenza e' un bug da correggere prima di proseguire.

- [ ] **Step 4: Suite completa**

Run: `python -m pytest -q -p no:cacheprovider`
Expected: falliti = i 25 preesistenti della baseline (stessi file), nessuno nuovo; passati >= 3908 + i test aggiunti.

- [ ] **Step 5: Documentazione locale**

In `md_files/ARCHITETTURA.md` (non tracciato) aggiungi alla tabella dei moduli la riga:

`| activity_log.py | Business log mensile: scrittura con dedup, parsing, letture per mese/intervallo, prova di consegna (foglia) |`

e aggiorna le righe di `user_stats.py` ("analisi sulle righe, non legge file").

- [ ] **Step 6: Commit e pulizia**

```powershell
git add audiobook_app.py
git commit -m "refactor(admin): mesi del pannello log da activity_log.months"
```

Run: `git status --short`
Expected: nessun file transitorio nel worktree (i file `activity_*.log` gia' presenti prima del lavoro restano non tracciati e non vanno aggiunti). Gli script di equivalenza restano nello scratchpad.
