# Activity log — fasi 2+3: `activity.db` dietro `ABM_ACTIVITY_DB` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** affiancare ai file `activity_YYYY-MM.log` un indice SQLite `activity.db` scritto in doppia scrittura (`dual`) e letto dai lettori della facciata (`db`), dietro il flag `ABM_ACTIVITY_DB=off|dual|db`, senza cambiare l'API pubblica di `activity_log`.

**Architecture:** nuovo modulo foglia `activity_db.py` (schema, migrazioni, mappatura riga ↔ colonne, query). `activity_log.py` resta l'unico punto d'accesso: decide il modo a ogni chiamata, scrive file e/o DB sotto il lock esistente e, nel modo `db`, legge dal DB con ripiego sul file. **Fino alla fase 4 il file resta il registro completo e il DB un indice ricostruibile**: ogni mese del DB si rifà dal suo file (`sync_month`), all'avvio un thread allinea tutto (`sync_all`). Lo spostamento dei file in `ABM_DATA_DIR` passa da `ABM_ACTIVITY_LOG_DIR` (default invariato `SCRIPT_DIR`).

**Tech Stack:** Python 3.12, sqlite3 (stdlib, SQLite ≥ 3.35: indici parziali e su espressione), pytest, bash per gli script di backup.

**Spec:** `docs/superpowers/specs/2026-09-24-activity-log-db-design.md` (sezioni "Fase 2" e "Fase 3", più l'addendum scritto nel Task 1).

## Global Constraints

- Branch `worktree-activity-db`, worktree `.claude/worktrees/activity-db`. Nessun push, nessun merge su `main` senza conferma esplicita dell'utente.
- Shell di sviluppo: PowerShell, un comando per invocazione, niente `&&`.
- Dopo ogni modifica Python: `python -m py_compile <file>`; poi i test del task.
- Commit: Conventional Commits, `type(scope): summary` minuscolo, **senza trailer** (`Co-Authored-By:` e simili vietati). `git add` solo di path espliciti, mai `-A`. I `.md` sono in `.gitignore` (`*.md`): vanno aggiunti con `git add -f <path>`; **mai** `git add -f CLAUDE.md`.
- `activity_db.py` importa solo la stdlib. `activity_log.py` importa solo la stdlib e `activity_db`. Nessuno dei due importa altro del progetto.
- Mai `import audiobook_app` da un sotto-modulo.
- Formato riga su disco invariato: `<job_id> # <ts> # "<file>" # <op> # <cid> # <ip> # <voice> # <lang> # <platform>`, `ts` = `%Y-%m-%d %H:%M:%S`.
- API pubblica di `activity_log` invariata nelle firme: `configure`, `log`, `init_dedup`, `reset`, `split_line`, `file_rows`, `months`, `month_rows`, `iter_rows`, `fingerprint`, `delivered_ids`, `Row`. Si aggiungono `mode`, `sync_month`, `sync_all`, `parity`, `db_stats`.
- `log()` non solleva mai eccezioni, in nessun modo.
- Modo `off` (default, variabile assente o valore sconosciuto) = comportamento di oggi byte per byte: nessun `activity.db` creato.
- Posizione di default dei file invariata (`SCRIPT_DIR`); `ABM_ACTIVITY_LOG_DIR` la sposta. `activity.db` sta nella stessa cartella dei file.
- Retention (fase 4, fuori da questo piano): 12 mesi. Pseudonimizzazione di IP ed email: rinviata.
- Baseline suite (main 5721576, v3.70.0): 3953 passati, 24 falliti preesistenti ed estranei (`abuse_judge`, `admin_voice_xss`, `audio_generation_tags`, `free_quota_generate_enforcement`, `voice_clone_replica`, `voxcpm_runpod`), 21 skipped; `test_voice_clone_generate` ha un test SMTP instabile. Il numero di falliti non deve crescere.
- Nessun bump di `version.py` (si fa al merge su `main`).

## Review Focus

1. **DB illeggibile, corrotto o bloccato nel modo `db`** → i lettori ripiegano sul file e `delivered_ids` non torna mai vuoto per colpa del DB (un vuoto fa rimborsare dal recovery job gia' consegnati). Test: Task 3 (`test_modo_db_db_illeggibile_ripiega_sul_file`).
2. **Avvio nel modo `db` prima che `sync_all` abbia finito** → si legge dal file, mai da un DB a meta'. Test: Task 3 (`test_modo_db_senza_sync_legge_il_file`).
3. **Chiavi ripetute nei file storici** (riavvii che hanno perso l'epoca, righe pre-dedup) → la ricostruzione tiene ogni riga, i conteggi file/DB coincidono e l'avvio successivo non ricostruisce di nuovo. Test: Task 1 (`test_rebuild_tiene_i_duplicati_del_file`), Task 2 (`test_sync_month_ricostruisce_e_poi_salta`).
4. **Righe delle famiglie sovraccariche e titoli con `" # "`** (`M4B_*`, `ADMIN_VOUCHER_*:{kind}`, `VOUCHER_ATTEMPT*`, `PAYMENT_*`, `VOICE_CLONE_*`, `ACCOUNT_*`) → rilette dal DB sono identiche a quelle del file; pannello admin e statistiche non cambiano. Test: Task 1 (andata e ritorno), Task 3 (`test_famiglie_sovraccariche_andata_e_ritorno`), Task 4 (lettori dell'app parametrizzati).
5. **Stesso `(job_id, op)` in due mesi diversi nel modo `db`** → scritto in entrambi i mesi, come fa oggi il reset mensile del set in RAM. Test: Task 1 (`test_insert_new_dedup_per_mese`).

---

## File coinvolti

| File | Ruolo |
|---|---|
| `activity_db.py` (nuovo) | schema e migrazioni di `activity.db`, mappatura riga ↔ colonne, insert/select/rebuild, conteggi |
| `test/test_activity_db.py` (nuovo) | contratto di `activity_db` |
| `activity_log.py` | modi, doppia scrittura, dedup sul DB, `sync_month`/`sync_all`/`parity`, lettori sul DB con ripiego |
| `test/test_activity_log_db.py` (nuovo) | lato scrittura e allineamento |
| `test/test_activity_log.py` | contratto parametrizzato su `off` e `db` + test dei lettori sul DB |
| `audiobook_app.py` | `ABM_ACTIVITY_LOG_DIR` in `configure`, thread `sync_all` all'avvio |
| `test/test_activity_log_readers.py` | lettori dell'app parametrizzati su `off` e `db` |
| `test/test_activity_log_app_config.py` (nuovo) | cartella da env, avvio del thread di sync |
| `.gitignore` | `activity.db*` |
| `scripts/activity_db.py` (nuovo) | CLI `parity` / `sync` / `bench` |
| `test/test_activity_db_cli.py` (nuovo) | test della CLI |
| `scripts/backup_ABM.sh`, `scripts/restore_ABM.sh`, `scripts/server_setup.sh` | nuova posizione dei log, backup coerente di `activity.db` |
| `scripts/migration/migration_recover_prep.py` + `test/test_migration_recover_prep.py` (nuovo) | legge i log da entrambe le cartelle |
| `docs/FORENSICS_PLAYBOOK.md`, `md_files/PARAMETRI_CONFIGURAZIONE.md` | percorsi e flag |
| `docs/superpowers/specs/2026-09-24-activity-log-db-design.md` | addendum fasi 2–3 |

---

### Task 1: modulo `activity_db.py` e addendum alla spec

**Files:**
- Create: `activity_db.py`
- Create: `test/test_activity_db.py`
- Modify: `docs/superpowers/specs/2026-09-24-activity-log-db-design.md` (append in coda)

**Interfaces:**
- Consumes: nulla (modulo foglia).
- Produces (usate dai Task 2–5):
  - `DB_FILENAME = "activity.db"`, `FIELDS` (9 nomi nell'ordine di `activity_log.Row`), `DETAIL_FIELD`
  - `connect(path) -> sqlite3.Connection` (scrittura; crea il file, applica le migrazioni; autocommit)
  - `reader(path) -> sqlite3.Connection` (mai crea il file; `sqlite3.OperationalError` se manca)
  - `to_columns(row: tuple[9 str]) -> dict`, `from_columns(rec: Mapping) -> tuple[9 str]`
  - `insert_new(conn, ym, row, epoch=None) -> bool` (True = scritta, False = chiave gia' presente)
  - `insert_mirror(conn, ym, row, epoch=None) -> True` (sempre scritta, `seq` = prossimo libero)
  - `rebuild_month(conn, ym, rows: Iterable[tuple], size: int) -> int` (righe scritte)
  - `select_rows(conn, ym_from, ym_to, since_ts=None, until_ts=None, ops=None) -> Iterator[tuple[9 str]]`
  - `count(conn, ym) -> int`, `op_counts(conn, ym) -> dict[str, int]`, `fingerprint(conn, ym) -> tuple | None`
  - `synced_size(conn, ym) -> int | None`, `mark_synced(conn, ym, size, rows) -> None`

- [ ] **Step 1: scrivere i test che falliscono**

`test/test_activity_db.py`:

```python
"""Contratto di activity_db: schema, mappatura riga <-> colonne, dedup, query."""
import sqlite3

import pytest

import activity_db


def _r(job="J1", ts="2026-08-01 10:00:00", fn="a.epub", op="GENERATE", cid="c",
       ip="1.1.1.1", voice="it-IT-X", lang="it", plat="web"):
    return (job, ts, fn, op, cid, ip, voice, lang, plat)


@pytest.fixture
def conn(tmp_path):
    c = activity_db.connect(tmp_path / activity_db.DB_FILENAME)
    yield c
    c.close()


def _all(conn, ym_from="0000-00", ym_to="9999-99", **kw):
    return list(activity_db.select_rows(conn, ym_from, ym_to, **kw))


# ---------------------------------------------------------------- schema

def test_connect_due_volte_migrazioni_idempotenti(tmp_path):
    p = tmp_path / activity_db.DB_FILENAME
    activity_db.connect(p).close()
    c = activity_db.connect(p)
    try:
        names = [r[0] for r in c.execute("SELECT name FROM schema_migrations")]
        assert names == ["001_events"]
        assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        c.close()


def test_reader_non_crea_il_file(tmp_path):
    p = tmp_path / "manca.db"
    with pytest.raises(sqlite3.OperationalError):
        activity_db.reader(p)
    assert not p.exists()


def test_reader_non_scrive(conn, tmp_path):
    r = activity_db.reader(tmp_path / activity_db.DB_FILENAME)
    try:
        with pytest.raises(sqlite3.OperationalError):
            r.execute("DELETE FROM events")
    finally:
        r.close()


# ---------------------------------------------------------------- mappatura

ROUND_TRIP = [
    _r(),
    _r(fn="Saga # 2.epub"),
    _r(job="J2", op="M4B_PROGRESS", voice="size_mb=12.5 pct=40"),
    _r(job="", fn="", op="ADMIN_VOUCHER_CREATE:gift", cid="", voice="AB12...", lang="a@b.it", plat=""),
    _r(job="", fn="", op="ADMIN_VOUCHER_REVOKE", voice="AB12...", lang="doppione"),
    _r(job="", fn="", op="VOUCHER_ATTEMPT", voice="CD34...", lang="invalid"),
    _r(job="", fn="", op="VOUCHER_ATTEMPT_BLOCKED:rate", voice="", lang=""),
    _r(job="J3", op="PAYMENT_AMOUNT_MISMATCH", voice="", lang="atteso 5.00"),
    _r(job="vc1", fn="speed=1.1", op="VOICE_CLONE_SPEED", voice="", lang=""),
    _r(job="acct-1234abcd", fn="device=iPhone", op="ACCOUNT_LOGIN", voice="", lang=""),
    _r(job="", fn="", op="STRANA:", voice="", lang=""),        # ':' senza argomento
    _r(job="", fn="", op="TTS_BACKEND_SWITCH", voice="gemini", lang="cf"),
]


@pytest.mark.parametrize("row", ROUND_TRIP)
def test_andata_e_ritorno_identica(row):
    assert activity_db.from_columns(activity_db.to_columns(row)) == row


def test_payload_m4b_va_in_detail():
    rec = activity_db.to_columns(_r(op="M4B_END", voice="size_mb=1"))
    assert rec["voice"] == "" and rec["detail"] == "size_mb=1"


def test_suffisso_e_email_del_voucher_separati():
    rec = activity_db.to_columns(_r(job="", op="ADMIN_VOUCHER_CREATE:gift", lang="a@b.it"))
    assert (rec["op"], rec["op_arg"]) == ("ADMIN_VOUCHER_CREATE", "gift")
    assert rec["lang"] == "" and rec["detail"] == "a@b.it"


def test_op_senza_due_punti_ha_op_arg_null():
    rec = activity_db.to_columns(_r(op="COMPLETE"))
    assert rec["op_arg"] is None and rec["detail"] == ""


# ---------------------------------------------------------------- scrittura

def test_insert_new_dedup_per_chiave_ed_epoca(conn):
    assert activity_db.insert_new(conn, "2026-08", _r(op="DOWNLOAD")) is True
    assert activity_db.insert_new(conn, "2026-08", _r(op="DOWNLOAD")) is False
    assert activity_db.insert_new(conn, "2026-08", _r(), epoch=1) is True
    assert activity_db.insert_new(conn, "2026-08", _r(), epoch=1) is False
    assert activity_db.insert_new(conn, "2026-08", _r(), epoch=2) is True
    assert activity_db.count(conn, "2026-08") == 3


def test_insert_new_job_vuoto_mai_deduplicato(conn):
    row = _r(job="", op="VOUCHER_ATTEMPT", lang="invalid")
    assert activity_db.insert_new(conn, "2026-08", row) is True
    assert activity_db.insert_new(conn, "2026-08", row) is True
    assert activity_db.count(conn, "2026-08") == 2


def test_insert_new_dedup_per_mese(conn):
    assert activity_db.insert_new(conn, "2026-08", _r(op="DOWNLOAD")) is True
    assert activity_db.insert_new(conn, "2026-09", _r(op="DOWNLOAD")) is True


def test_insert_new_suffissi_diversi_non_collidono(conn):
    assert activity_db.insert_new(conn, "2026-08", _r(op="X:a")) is True
    assert activity_db.insert_new(conn, "2026-08", _r(op="X:b")) is True


def test_insert_mirror_entra_sempre_con_seq_crescente(conn):
    for _ in range(3):
        assert activity_db.insert_mirror(conn, "2026-08", _r(), epoch=1) is True
    seqs = [r[0] for r in conn.execute("SELECT seq FROM events ORDER BY id")]
    assert seqs == [0, 1, 2]
    # la chiave seq=0 e' occupata: il dedup del modo db la vede
    assert activity_db.insert_new(conn, "2026-08", _r(), epoch=1) is False


def test_rebuild_tiene_i_duplicati_del_file(conn):
    rows = [_r(ts="2026-08-01 10:00:00"), _r(ts="2026-08-01 11:00:00"),
            _r(job="", op="VOUCHER_ATTEMPT"), _r(job="J2", op="COMPLETE")]
    assert activity_db.rebuild_month(conn, "2026-08", rows, size=123) == 4
    assert _all(conn) == rows
    assert activity_db.synced_size(conn, "2026-08") == 123
    # di nuovo: sostituisce, non accoda
    assert activity_db.rebuild_month(conn, "2026-08", rows[:2], size=50) == 2
    assert _all(conn) == rows[:2]
    assert activity_db.synced_size(conn, "2026-08") == 50


def test_rebuild_non_tocca_gli_altri_mesi(conn):
    activity_db.insert_new(conn, "2026-07", _r(ts="2026-07-01 10:00:00"))
    activity_db.rebuild_month(conn, "2026-08", [_r()], size=1)
    assert activity_db.count(conn, "2026-07") == 1


# ---------------------------------------------------------------- lettura

def test_select_rows_ordine_mese_poi_scrittura_e_filtri(conn):
    activity_db.insert_new(conn, "2026-08", _r(job="D", ts="2026-08-01 09:00:00", op="OPT_COMPLETE"))
    activity_db.insert_new(conn, "2026-07", _r(job="A", ts="2026-07-30 10:00:00", op="COMPLETE"))
    activity_db.insert_new(conn, "2026-07", _r(job="B", ts="2026-07-31 13:00:00", op="COMPLETE"))
    activity_db.insert_new(conn, "2026-07", _r(job="C", ts="2026-07-31 14:00:00", op="GENERATE"))
    activity_db.insert_new(conn, "2026-08", _r(job="E", ts="2026-08-02 00:00:00", op="COMPLETE"))
    assert [r[0] for r in _all(conn)] == ["A", "B", "C", "D", "E"]
    got = _all(conn, "2026-07", "2026-08", since_ts="2026-07-31 12:00:00",
               until_ts="2026-08-02 00:00:00", ops={"COMPLETE", "OPT_COMPLETE"})
    assert [r[0] for r in got] == ["B", "D"]


def test_select_rows_filtra_le_op_col_suffisso(conn):
    activity_db.insert_new(conn, "2026-08", _r(job="", op="ADMIN_VOUCHER_CREATE:gift", lang="a@b.it"))
    activity_db.insert_new(conn, "2026-08", _r(job="", op="ADMIN_VOUCHER_CREATE:promo", lang="c@d.it"))
    got = _all(conn, ops={"ADMIN_VOUCHER_CREATE:gift"})
    assert [(r[3], r[7]) for r in got] == [("ADMIN_VOUCHER_CREATE:gift", "a@b.it")]


def test_select_rows_ops_vuoto_nessuna_riga(conn):
    activity_db.insert_new(conn, "2026-08", _r())
    assert _all(conn, ops=set()) == []


def test_select_rows_molte_righe_a_blocchi(conn):
    rows = [_r(job=f"J{i}") for i in range(4500)]
    activity_db.rebuild_month(conn, "2026-08", rows, size=1)
    assert _all(conn) == rows


def test_op_counts_con_op_completa(conn):
    activity_db.insert_new(conn, "2026-08", _r(job="", op="VOUCHER_ATTEMPT_BLOCKED:rate"))
    activity_db.insert_new(conn, "2026-08", _r(job="", op="VOUCHER_ATTEMPT_BLOCKED:rate"))
    activity_db.insert_new(conn, "2026-08", _r(op="COMPLETE"))
    assert activity_db.op_counts(conn, "2026-08") == {
        "VOUCHER_ATTEMPT_BLOCKED:rate": 2, "COMPLETE": 1}


def test_fingerprint_none_se_vuoto_e_cambia_dopo_una_scrittura(conn):
    assert activity_db.fingerprint(conn, "2026-08") is None
    activity_db.insert_new(conn, "2026-08", _r(job="J1"))
    fp1 = activity_db.fingerprint(conn, "2026-08")
    activity_db.insert_new(conn, "2026-08", _r(job="J2"))
    assert fp1 is not None and activity_db.fingerprint(conn, "2026-08") != fp1


def test_mark_synced_sovrascrive(conn):
    assert activity_db.synced_size(conn, "2026-08") is None
    activity_db.mark_synced(conn, "2026-08", 10, 1)
    activity_db.mark_synced(conn, "2026-08", 20, 2)
    assert activity_db.synced_size(conn, "2026-08") == 20
```

- [ ] **Step 2: eseguire i test e verificare che falliscono**

Run: `python -m pytest test/test_activity_db.py -q`
Expected: FAIL / ERROR con `ModuleNotFoundError: No module named 'activity_db'`.

- [ ] **Step 3: scrivere `activity_db.py`**

```python
"""Indice SQLite dell'activity log (modulo foglia, sola stdlib).

`activity.db` affianca i file `activity_YYYY-MM.log` (fasi 2-3 di
docs/superpowers/specs/2026-09-24-activity-log-db-design.md). Fino alla
fase 4 il file resta il registro completo: ogni mese del DB si puo' rifare
da capo dal suo file. Qui stanno schema, mappatura riga <-> colonne e
query; modi, lock e dedup stanno in activity_log.

Le righe entrano ed escono come tuple di 9 stringhe nell'ordine di
activity_log.Row (FIELDS): questo modulo non importa activity_log.
"""
import sqlite3
import time
from pathlib import Path

DB_FILENAME = "activity.db"
FIELDS = ("job_id", "ts", "filename", "op", "client_id", "ip", "voice",
          "lang", "platform")

# Famiglie di op che scrivono un payload in una colonna nata per altro: nel
# DB il valore passa in `detail` e la colonna resta vuota. Vince il primo
# prefisso che combacia con l'op senza suffisso. La mappatura e' invertibile:
# la riga riletta e' identica a quella del file.
DETAIL_FIELD = (
    ("M4B_", "voice"),             # size_mb=... pct=... (generation_engine)
    ("ADMIN_VOUCHER_", "lang"),    # email del destinatario o motivo della revoca
    ("VOUCHER_ATTEMPT", "lang"),   # esito del tentativo
    ("PAYMENT_", "lang"),          # errore della capture
    ("VOICE_CLONE_", "filename"),  # extra di _vc_log
    ("ACCOUNT_", "filename"),      # extra di _acct_log
)

# L'op come sta nel file: base piu' eventuale ':' + argomento.
_FULL_OP = "op || IFNULL(':' || op_arg, '')"
_COLS = ("ym", "ts", "job_id", "op", "op_arg", "filename", "client_id", "ip",
         "voice", "detail", "lang", "platform", "epoch", "seq")
_INSERT = ("INSERT {} INTO events (" + ", ".join(_COLS) + ") VALUES ("
           + ", ".join("?" * len(_COLS)) + ")")
_SEL = ("job_id", "ts", "filename", "op", "op_arg", "client_id", "ip",
        "voice", "detail", "lang", "platform")

_MIGRATIONS = (
    ("001_events", (
        """CREATE TABLE events (
            id INTEGER PRIMARY KEY,
            ym TEXT NOT NULL,
            ts TEXT NOT NULL,
            job_id TEXT NOT NULL,
            op TEXT NOT NULL,
            op_arg TEXT,
            filename TEXT NOT NULL,
            client_id TEXT NOT NULL,
            ip TEXT NOT NULL,
            voice TEXT NOT NULL,
            detail TEXT NOT NULL,
            lang TEXT NOT NULL,
            platform TEXT NOT NULL,
            epoch REAL,
            seq INTEGER NOT NULL DEFAULT 0
        )""",
        "CREATE INDEX events_ym ON events (ym, id)",
        "CREATE INDEX events_ts ON events (ts)",
        "CREATE INDEX events_job ON events (job_id)",
        "CREATE INDEX events_op_ts ON events (op, ts)",
        "CREATE INDEX events_client_ts ON events (client_id, ts)",
        # Regola C1 (job vuoto mai deduplicato) + reset mensile (ym) + le
        # ripetizioni storiche del file (seq): vedi l'addendum della spec.
        "CREATE UNIQUE INDEX events_dedup ON events (ym, job_id, op, "
        "IFNULL(op_arg, ''), IFNULL(epoch, -1), seq) WHERE job_id <> ''",
        "CREATE TABLE sync_state (ym TEXT PRIMARY KEY, size INTEGER NOT NULL, "
        "rows INTEGER NOT NULL)",
    )),
)


# --------------------------------------------------------------- connessioni

def _migrate(conn, name, statements):
    conn.execute("BEGIN IMMEDIATE")
    try:
        done = conn.execute("SELECT 1 FROM schema_migrations WHERE name = ?",
                            (name,)).fetchone()
        if done is None:
            for s in statements:
                conn.execute(s)
            conn.execute("INSERT INTO schema_migrations (name, applied_at) "
                         "VALUES (?, ?)", (name, int(time.time())))
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def connect(path):
    """Connessione di scrittura (autocommit): crea il file se manca e
    applica le migrazioni. Chi la condivide fra thread la serializza."""
    conn = sqlite3.connect(str(path), check_same_thread=False,
                           isolation_level=None, timeout=2.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)")
        for name, statements in _MIGRATIONS:
            _migrate(conn, name, statements)
    except BaseException:
        conn.close()
        raise
    return conn


def reader(path):
    """Connessione di sola lettura su un DB esistente: se il file manca
    solleva sqlite3.OperationalError invece di crearlo vuoto."""
    uri = Path(path).resolve().as_uri() + "?mode=rw"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=2.0)
    conn.execute("PRAGMA query_only=1")
    return conn


# --------------------------------------------------------------- mappatura

def _detail_field(op):
    for prefix, field in DETAIL_FIELD:
        if op.startswith(prefix):
            return field
    return None


def to_columns(row):
    """Tupla di 9 campi (ordine FIELDS) -> colonne di `events` senza
    ym/epoch/seq."""
    rec = dict(zip(FIELDS, row))
    base, sep, arg = rec["op"].partition(":")
    rec["op"], rec["op_arg"] = base, (arg if sep else None)
    rec["detail"] = ""
    field = _detail_field(base)
    if field is not None:
        rec["detail"], rec[field] = rec[field], ""
    return rec


def from_columns(rec):
    """Inversa di to_columns: dalle colonne (mapping) alla tupla del file."""
    out = {f: rec[f] for f in FIELDS}
    field = _detail_field(rec["op"])
    if field is not None:
        out[field] = rec["detail"]
    if rec["op_arg"] is not None:
        out["op"] = f'{rec["op"]}:{rec["op_arg"]}'
    return tuple(out[f] for f in FIELDS)


def _values(ym, rec, epoch, seq):
    return (ym, rec["ts"], rec["job_id"], rec["op"], rec["op_arg"],
            rec["filename"], rec["client_id"], rec["ip"], rec["voice"],
            rec["detail"], rec["lang"], rec["platform"], epoch, seq)


# --------------------------------------------------------------- scrittura

def insert_new(conn, ym, row, epoch=None):
    """Dedup del modo db: True se la riga e' entrata, False se la chiave
    (ym, job_id, op, op_arg, epoch) c'era gia'. Job vuoto: entra sempre."""
    cur = conn.execute(_INSERT.format("OR IGNORE"),
                       _values(ym, to_columns(row), epoch, 0))
    return cur.rowcount == 1


def insert_mirror(conn, ym, row, epoch=None):
    """Copia fedele del modo dual: la riga e' gia' nel file ed entra sempre,
    con `seq` = prossimo libero della sua chiave. Il chiamante serializza."""
    rec = to_columns(row)
    seq = 0
    if rec["job_id"]:
        seq = conn.execute(
            "SELECT IFNULL(MAX(seq) + 1, 0) FROM events WHERE job_id <> '' "
            "AND ym = ? AND job_id = ? AND op = ? AND IFNULL(op_arg, '') = ? "
            "AND IFNULL(epoch, -1) = ?",
            (ym, rec["job_id"], rec["op"], rec["op_arg"] or "",
             -1 if epoch is None else epoch)).fetchone()[0]
    conn.execute(_INSERT.format(""), _values(ym, rec, epoch, seq))
    return True


def rebuild_month(conn, ym, rows, size):
    """Rifa da capo il mese `ym` con `rows` (righe del file, in ordine) in
    una transazione. Le chiavi ripetute nel file prendono seq crescente,
    cosi' entrano tutte; l'epoca non sta nel file e resta NULL. Registra
    la dimensione del file allineato. Ritorna le righe scritte."""
    seen = {}
    n = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute("DELETE FROM events WHERE ym = ?", (ym,))
        for row in rows:
            rec = to_columns(row)
            seq = 0
            if rec["job_id"]:
                k = (rec["job_id"], rec["op"], rec["op_arg"] or "")
                seq = seen.get(k, 0)
                seen[k] = seq + 1
            conn.execute(_INSERT.format(""), _values(ym, rec, None, seq))
            n += 1
        mark_synced(conn, ym, size, n)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return n


def mark_synced(conn, ym, size, rows):
    conn.execute("INSERT OR REPLACE INTO sync_state (ym, size, rows) "
                 "VALUES (?, ?, ?)", (ym, size, rows))


# --------------------------------------------------------------- lettura

def synced_size(conn, ym):
    r = conn.execute("SELECT size FROM sync_state WHERE ym = ?", (ym,)).fetchone()
    return r[0] if r else None


def count(conn, ym):
    return conn.execute("SELECT COUNT(*) FROM events WHERE ym = ?",
                        (ym,)).fetchone()[0]


def op_counts(conn, ym):
    """{op completa: righe} del mese."""
    return dict(conn.execute(
        f"SELECT {_FULL_OP}, COUNT(*) FROM events WHERE ym = ? GROUP BY 1",
        (ym,)).fetchall())


def fingerprint(conn, ym):
    """Firma del mese per invalidare le cache; None se il mese e' vuoto."""
    n, last = conn.execute("SELECT COUNT(*), MAX(id) FROM events WHERE ym = ?",
                           (ym,)).fetchone()
    return (last, n) if n else None


def select_rows(conn, ym_from, ym_to, since_ts=None, until_ts=None, ops=None,
                batch=2000):
    """Righe (tuple di 9) dei mesi ym_from..ym_to inclusi, in ordine di mese
    e di scrittura. since_ts/until_ts: stringhe nel formato del file, since
    incluso, until escluso. ops: op complete (con suffisso) da tenere."""
    sql = ["SELECT", ", ".join(_SEL), "FROM events WHERE ym >= ? AND ym <= ?"]
    args = [ym_from, ym_to]
    if since_ts is not None:
        sql.append("AND ts >= ?")
        args.append(since_ts)
    if until_ts is not None:
        sql.append("AND ts < ?")
        args.append(until_ts)
    if ops is not None:
        ops = sorted(ops)
        if not ops:
            return
        sql.append(f"AND {_FULL_OP} IN ({', '.join('?' * len(ops))})")
        args.extend(ops)
    sql.append("ORDER BY ym, id")
    cur = conn.execute(" ".join(sql), args)
    while True:
        chunk = cur.fetchmany(batch)
        if not chunk:
            return
        for r in chunk:
            yield from_columns(dict(zip(_SEL, r)))
```

- [ ] **Step 4: eseguire i test e verificare che passano**

Run: `python -m py_compile activity_db.py`
Run: `python -m pytest test/test_activity_db.py -q`
Expected: tutti PASS.

- [ ] **Step 5: addendum alla spec**

Aggiungere in coda a `docs/superpowers/specs/2026-09-24-activity-log-db-design.md`:

```markdown
## Addendum fasi 2–3 (24/09/2026)

Piano: `docs/superpowers/plans/2026-09-24-activity-log-sqlite.md`. Decisioni prese scrivendo il
piano, dove la direzione sopra era incompleta o va corretta:

1. **`ts TEXT`** nel formato del file (`%Y-%m-%d %H:%M:%S`, ora locale), non `INTEGER`: i lettori
   confrontano stringhe e l'ora locale nel passaggio all'epoca e' ambigua al cambio d'ora. Colonna
   **`ym`** = mese del file che contiene la riga: `month_rows` filtra per `ym`, come oggi per file,
   anche se il `ts` di una riga e' storto.
2. **Chiave di dedup** `UNIQUE (ym, job_id, op, IFNULL(op_arg,''), IFNULL(epoch,-1), seq) WHERE
   job_id <> ''`. `ym` conserva il reset mensile del set in RAM; `seq` fa entrare le chiavi
   ripetute dei file storici (riavvii che hanno perso l'epoca), senza le quali i conteggi file/DB
   non tornerebbero mai. Le scritture nuove del modo `db` usano `seq = 0`.
3. **`op_arg`** e' NULL senza `':'`. **`detail`** raccoglie i payload di sei famiglie, non solo
   `M4B_*`: `M4B_*` (da `voice`), `ADMIN_VOUCHER_*` e `VOUCHER_ATTEMPT*` e `PAYMENT_*` (da `lang`),
   `VOICE_CLONE_*` e `ACCOUNT_*` (da `filename`). La mappatura e' invertibile: i lettori vedono
   le stesse `Row` del file.
4. **Il file resta il registro completo fino alla fase 4, il DB e' un indice ricostruibile.**
   `dual`: file poi DB (copia fedele). `db`: prima il DB decide il dedup, poi il file riceve solo
   le righe nuove; se il DB non risponde la riga va comunque nel file. All'avvio un thread
   (`sync_all`) confronta i conteggi e ricostruisce dal file i mesi che non tornano; finche' non
   ha finito, e ogni volta che il DB non si legge, il modo `db` legge dal file. Rollback da `db`
   a `dual`/`off` senza perdite. Per questo il rollout passa sempre da `dual`: al primo avvio in
   `db` il DB ha gia' le chiavi del mese e il dedup non riscrive righe gia' presenti nel file
   (se il DB fosse vuoto, le chiavi di prima del riavvio non ci sarebbero fino alla fine di
   `sync_all`).
5. **`months()` resta sui file** (elenco economico, include i mesi appena creati).
6. **Spostamento dei file via `ABM_ACTIVITY_LOG_DIR`** (default invariato `SCRIPT_DIR`), non
   cambiando il default nel codice: col deploy automatico su push un cambio di default
   spezzerebbe il mese corrente fra due cartelle. `activity.db` sta accanto ai file.
7. **Scrittura sincrona** sotto il lock di `log()`, senza coda. Misura: `scripts/activity_db.py
   bench` (percentili di `log()` in `off` e `dual`) e un avviso in log per ogni scrittura DB oltre
   50 ms. Coda in memoria solo se in prod il p99 di `dual` supera 5 ms.
8. **Fase 4:** `docs/STORAGE_TIERING.md` non esiste; il copy-before-delete di riferimento e'
   `generation_engine._offload_to_cloud`. Retention decisa: 12 mesi. Pseudonimizzazione di IP ed
   email: rinviata.

### Rollout in prod

1. Deploy con `ABM_ACTIVITY_DB` assente (= `off`): nessun cambiamento.
2. Spostamento dei file, a servizio fermo: `systemctl stop audiobook-maker`;
   `mv /opt/audiobook-maker/activity_*.log /opt/audiobook-maker/data/`; in `override.conf`
   `Environment="ABM_ACTIVITY_LOG_DIR=/opt/audiobook-maker/data"`; `systemctl daemon-reload`;
   `systemctl start audiobook-maker`. Verifica: una riga nuova in `data/activity_<mese>.log`.
3. Misura: `python3 scripts/activity_db.py bench --dir /opt/audiobook-maker/data -n 2000`.
4. `Environment="ABM_ACTIVITY_DB=dual"`, restart. In syslog `[activity_log] sync: N mesi
   ricostruiti, 0 falliti`. Dopo un giorno `python3 scripts/activity_db.py parity --dir
   /opt/audiobook-maker/data` deve uscire con 0; nessun `scrittura DB lenta` ricorrente.
5. `ABM_ACTIVITY_DB=db`, restart. Controllo del pannello `/admin/log-activity`, delle statistiche
   community e del digest power user. Rollback: `dual` o `off` + restart.

Le ABM_* dell'unit non sono nella shell ssh: agli script si passa `--dir` esplicito.
```

- [ ] **Step 6: commit**

```bash
git add activity_db.py test/test_activity_db.py
git add -f docs/superpowers/specs/2026-09-24-activity-log-db-design.md
git commit -m "feat(activity-db): sqlite index module for the activity log"
```

---

### Task 2: `activity_log` — modi, doppia scrittura, allineamento dal file

**Files:**
- Modify: `activity_log.py`
- Create: `test/test_activity_log_db.py`

**Interfaces:**
- Consumes (Task 1): `activity_db.DB_FILENAME`, `connect`, `reader`, `insert_new`, `insert_mirror`, `rebuild_month`, `count`, `op_counts`, `synced_size`, `mark_synced`, `select_rows`.
- Produces (usate dai Task 3–5):
  - `mode() -> "off" | "dual" | "db"` (letta a ogni chiamata da `ABM_ACTIVITY_DB`)
  - `sync_month(ym: str, force: bool = False) -> bool` (True = ricostruito)
  - `sync_all() -> int` (mesi ricostruiti; in `off` ritorna 0 senza fare nulla; a fine corsa senza errori imposta `_db_ready`)
  - `parity(ym: str) -> dict[str, tuple[int, int]]` (solo le op con conteggi diversi; `ValueError` se `ym` non valido)
  - `db_stats() -> {"writes": int, "avg_ms": float, "max_ms": float}`
  - interni usati dal Task 3: `_db_ready` (`threading.Event`), `_db_path()`, `_close_writer()` (da chiamare con `_lock` preso)

- [ ] **Step 1: scrivere i test che falliscono**

`test/test_activity_log_db.py`:

```python
"""activity_log con activity.db: modi, doppia scrittura, dedup sul DB, sync."""
from datetime import datetime

import pytest

import activity_db
import activity_log


@pytest.fixture
def ddir(tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_ACTIVITY_DB", raising=False)
    prev = activity_log._log_dir
    activity_log.configure(lambda: tmp_path)
    activity_log.reset()
    yield tmp_path
    activity_log.reset()
    activity_log.configure(prev)


def _ym():
    return datetime.now().strftime("%Y-%m")


def _file(d, ym):
    return [tuple(r) for r in activity_log.file_rows(d / f"activity_{ym}.log")]


def _db(d, ym):
    c = activity_db.connect(d / activity_db.DB_FILENAME)
    try:
        return list(activity_db.select_rows(c, ym, ym))
    finally:
        c.close()


def _line(job, ts, op, fn="a.epub", voice="it-IT-X", lang="it"):
    return f'{job} # {ts} # "{fn}" # {op} # c # 1.1.1.1 # {voice} # {lang} # web'


def test_mode_letto_a_ogni_chiamata(ddir, monkeypatch):
    assert activity_log.mode() == "off"
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    assert activity_log.mode() == "dual"
    monkeypatch.setenv("ABM_ACTIVITY_DB", " DB ")
    assert activity_log.mode() == "db"
    monkeypatch.setenv("ABM_ACTIVITY_DB", "boh")
    assert activity_log.mode() == "off"


def test_off_non_crea_il_db(ddir):
    activity_log.log("J1", "a.epub", "GENERATE")
    assert not (ddir / activity_db.DB_FILENAME).exists()
    assert activity_log.sync_all() == 0


def test_dual_file_e_db_identici(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    activity_log.log("J1", "Saga # 2.epub", "GENERATE", client_id="c1", ip="1.2.3.4",
                     voice="it-IT-X", lang="it", epoch=1)
    activity_log.log("J1", "Saga # 2.epub", "M4B_PROGRESS", voice="size_mb=3 pct=50")
    activity_log.log("", "", "ADMIN_VOUCHER_CREATE:gift", ip="9.9.9.9",
                     voice="AB12...", lang="a@b.it")
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    activity_log.log("J1", "a.epub", "DOWNLOAD")                     # dedup
    ym = _ym()
    assert len(_file(ddir, ym)) == 4
    assert _db(ddir, ym) == _file(ddir, ym)
    assert activity_log.parity(ym) == {}


def test_dual_ripetizione_dopo_riavvio_entra_anche_nel_db(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.reset()          # riavvio: il set in RAM riparte dal file,
    activity_log.init_dedup()     # senza epoca -> la riga si riscrive
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    ym = _ym()
    assert [r[3] for r in _file(ddir, ym)] == ["GENERATE", "GENERATE"]
    assert _db(ddir, ym) == _file(ddir, ym)


def test_dual_db_rotto_non_ferma_il_file(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    (ddir / activity_db.DB_FILENAME).mkdir()     # connect fallisce
    activity_log.log("J1", "a.epub", "COMPLETE")
    assert [r[3] for r in _file(ddir, _ym())] == ["COMPLETE"]
    assert activity_log.db_stats()["writes"] == 0


def test_db_dedup_sul_db_e_file_solo_per_le_righe_nuove(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "db")
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    activity_log.log("J1", "a.epub", "DOWNLOAD")
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.log("J1", "a.epub", "GENERATE", epoch=2)
    activity_log.log("", "", "VOUCHER_ATTEMPT", lang="invalid")
    activity_log.log("", "", "VOUCHER_ATTEMPT", lang="invalid")
    ym = _ym()
    expected = ["DOWNLOAD", "GENERATE", "GENERATE", "VOUCHER_ATTEMPT", "VOUCHER_ATTEMPT"]
    assert [r[3] for r in _file(ddir, ym)] == expected
    assert _db(ddir, ym) == _file(ddir, ym)


def test_db_ricorda_l_epoca_dopo_il_riavvio(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "db")
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    activity_log.reset()
    activity_log.init_dedup()
    activity_log.log("J1", "a.epub", "GENERATE", epoch=1)
    assert [r[3] for r in _file(ddir, _ym())] == ["GENERATE"]


def test_db_irraggiungibile_scrive_comunque_il_file(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "db")
    (ddir / activity_db.DB_FILENAME).mkdir()
    activity_log.log("J1", "a.epub", "COMPLETE")
    activity_log.log("J1", "a.epub", "COMPLETE")   # senza DB nessun dedup
    assert [r[3] for r in _file(ddir, _ym())] == ["COMPLETE", "COMPLETE"]


def test_sync_month_ricostruisce_e_poi_salta(ddir):
    p = ddir / "activity_2026-07.log"
    lines = [_line("J1", "2026-07-01 10:00:00", "GENERATE"),
             _line("J1", "2026-07-01 11:00:00", "GENERATE"),     # ripetizione storica
             _line("J2", "2026-07-02 10:00:00", "M4B_END", voice="size_mb=1"),
             _line("", "2026-07-03 10:00:00", "VOUCHER_ATTEMPT", fn="", lang="ok")]
    p.write_text("".join(l + "\n" for l in lines), encoding="utf-8")
    assert activity_log.sync_month("2026-07") is True
    assert _db(ddir, "2026-07") == _file(ddir, "2026-07")
    assert activity_log.sync_month("2026-07") is False           # stessa dimensione
    with open(p, "a", encoding="utf-8") as f:
        f.write(_line("J3", "2026-07-04 10:00:00", "COMPLETE") + "\n")
    assert activity_log.sync_month("2026-07") is True
    assert activity_log.parity("2026-07") == {}


def test_sync_month_conteggi_uguali_non_ricostruisce(ddir):
    p = ddir / "activity_2026-07.log"
    p.write_text(_line("J1", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    assert activity_log.sync_month("2026-07") is True
    c = activity_db.connect(ddir / activity_db.DB_FILENAME)
    try:
        c.execute("DELETE FROM sync_state")          # dimensione dimenticata
        first_id = c.execute("SELECT id FROM events").fetchone()[0]
    finally:
        c.close()
    assert activity_log.sync_month("2026-07") is False   # conta e ritrova 1 = 1
    c = activity_db.connect(ddir / activity_db.DB_FILENAME)
    try:
        assert c.execute("SELECT id FROM events").fetchone()[0] == first_id
    finally:
        c.close()


def test_sync_month_forzato_e_mese_non_valido(ddir):
    p = ddir / "activity_2026-07.log"
    p.write_text(_line("J1", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    activity_log.sync_month("2026-07")
    assert activity_log.sync_month("2026-07", force=True) is True
    assert activity_log.sync_month("../2026-07") is False
    assert activity_log.sync_month("2026-06") is False            # file assente


def test_sync_all_dal_vecchio_al_corrente_e_pronto(ddir, monkeypatch):
    (ddir / "activity_2026-06.log").write_text(
        _line("A", "2026-06-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (ddir / f"activity_{_ym()}.log").write_text(
        _line("B", ts, "COMPLETE") + "\n", encoding="utf-8")
    assert activity_log.sync_all() == 0 and not activity_log._db_ready.is_set()  # off
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    assert activity_log.sync_all() == 2
    assert activity_log._db_ready.is_set()
    assert activity_log.sync_all() == 0


def test_parity_segnala_le_differenze(ddir, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    activity_log.log("J1", "a.epub", "GENERATE")
    ym = _ym()
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(ddir / f"activity_{ym}.log", "a", encoding="utf-8") as f:
        f.write(_line("J2", ts, "COMPLETE") + "\n")
    assert activity_log.parity(ym) == {"COMPLETE": (1, 0)}
    with pytest.raises(ValueError):
        activity_log.parity("2026-8")


def test_parity_senza_db(ddir):
    (ddir / "activity_2026-07.log").write_text(
        _line("J1", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    assert activity_log.parity("2026-07") == {"COMPLETE": (1, 0)}
    assert not (ddir / activity_db.DB_FILENAME).exists()


def test_scrittura_lenta_segnalata(ddir, monkeypatch, capsys):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    monkeypatch.setattr(activity_log, "_SLOW_DB_MS", -1.0)
    activity_log.log("J1", "a.epub", "GENERATE")
    assert "scrittura DB lenta: GENERATE" in capsys.readouterr().out
    st = activity_log.db_stats()
    assert st["writes"] == 1 and st["max_ms"] >= st["avg_ms"] >= 0.0
```

- [ ] **Step 2: eseguire i test e verificare che falliscono**

Run: `python -m pytest test/test_activity_log_db.py -q`
Expected: FAIL con `AttributeError: module 'activity_log' has no attribute 'mode'` (e simili).

- [ ] **Step 3: modificare `activity_log.py`**

3a. Docstring del modulo: sostituire il secondo e terzo paragrafo (da `Fase 1 di docs/...` a `la cartella arriva con \`configure()\`.`) con:

```python
Fasi 1-3 di docs/superpowers/specs/2026-09-24-activity-log-db-design.md.
Il modo arriva a ogni chiamata da ABM_ACTIVITY_DB: `off` (default) solo
file; `dual` file piu' copia in activity.db, letture dal file; `db` dedup e
letture sul DB, file sempre scritto. Fino alla fase 4 il file e' il
registro completo e il DB un indice ricostruibile (`sync_month`). Nessun
import dal progetto oltre ad activity_db: la cartella arriva con
`configure()`.
```

3b. Import (in testa, al posto degli import attuali):

```python
import contextlib
import os
import re
import sqlite3
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import NamedTuple

import activity_db
```

3c. Costanti, dopo `_DELIVERED_TTL = 300.0`:

```python
MODES = ("off", "dual", "db")
# Oltre questa soglia una scrittura sul DB finisce nel log di servizio: e'
# la misura che decide fra scrittura sincrona e coda (spec, addendum 7).
_SLOW_DB_MS = 50.0
```

3d. Stato, dopo `_delivered_cache = {"value": None, "expires": 0.0}`:

```python
_wconn = None              # connessione di scrittura su activity.db, sotto _lock
_wpath = None
_db_ready = threading.Event()   # sync_all finito senza errori: il modo db legge dal DB
_db_stats = {"writes": 0, "total_ms": 0.0, "max_ms": 0.0}
```

3e. Dopo `_path(ym)` aggiungere:

```python
def mode():
    """Modo del backend, letto a ogni chiamata; valore ignoto = off."""
    m = os.environ.get("ABM_ACTIVITY_DB", "off").strip().lower()
    return m if m in MODES else "off"


def _db_path():
    return _dir() / activity_db.DB_FILENAME


def _writer():
    """Connessione di scrittura, da usare sotto `_lock`; riaperta se la
    cartella cambia (i test la spostano)."""
    global _wconn, _wpath
    path = _db_path()
    if _wconn is None or _wpath != path:
        _close_writer()
        _wconn = activity_db.connect(path)
        _wpath = path
    return _wconn


def _close_writer():
    """Chiude la connessione di scrittura. Con `_lock` preso."""
    global _wconn, _wpath
    if _wconn is not None:
        try:
            _wconn.close()
        except Exception:
            pass
    _wconn, _wpath = None, None


def _db_write(fn, ym, row, epoch):
    """`fn(conn, ym, row, epoch)` sul DB, con `_lock` gia' preso. Mai
    un'eccezione: None se il DB non risponde."""
    try:
        conn = _writer()
        t0 = time.perf_counter()
        res = fn(conn, ym, row, epoch)
    except Exception as e:
        _close_writer()
        print(f"[activity_log] scrittura DB {row[3]} fallita: {e}")
        return None
    ms = (time.perf_counter() - t0) * 1000.0
    _db_stats["writes"] += 1
    _db_stats["total_ms"] += ms
    _db_stats["max_ms"] = max(_db_stats["max_ms"], ms)
    if ms > _SLOW_DB_MS:
        print(f"[activity_log] scrittura DB lenta: {row[3]} {ms:.0f} ms")
    return res


def db_stats():
    """Scritture sul DB di questo processo e loro latenza in ms."""
    w = _db_stats["writes"]
    return {"writes": w,
            "avg_ms": (_db_stats["total_ms"] / w) if w else 0.0,
            "max_ms": _db_stats["max_ms"]}
```

3f. `reset()` diventa:

```python
def reset():
    """Stato come a processo appena avviato (per i test)."""
    global _month
    with _lock:
        _month = ""
        _keys.clear()
        _close_writer()
    _db_ready.clear()
    _db_stats.update(writes=0, total_ms=0.0, max_ms=0.0)
    with _delivered_lock:
        _delivered_cache["value"] = None
        _delivered_cache["expires"] = 0.0
```

3g. `log()` diventa:

```python
def log(job_id, filename, op, client_id="", ip="", voice="", lang="",
        platform="", epoch=None):
    """Scrive una riga nel mese corrente. Non solleva mai.

    Dedup per (job_id, op), o (job_id, op, epoch) se `epoch` e' dato: cosi'
    GENERATE/COMPLETE di una ri-generazione dello stesso job non vengono
    soppressi, mentre i download ripetuti (chiamati senza epoch) si'.
    Le righe senza job_id (voucher, admin, backend TTS) non si deduplicano
    mai: ogni evento conta.

    `off`: file, dedup sul set in RAM. `dual`: come off, poi la stessa riga
    entra tale e quale nel DB. `db`: decide il DB (chiave del mese, epoca
    compresa, anche dopo un riavvio) e il file riceve solo le righe nuove;
    se il DB non risponde la riga va comunque nel file, senza dedup.
    """
    global _month
    now = datetime.now()
    ym = now.strftime("%Y-%m")
    key = None
    if job_id:
        key = (job_id, op) if epoch is None else (job_id, op, epoch)
    line = (f'{job_id} # {now.strftime(TS_FMT)} # "{filename}" # {op} # {client_id}'
            f' # {ip} # {voice} # {lang} # {platform}\n')
    m = mode()
    # La riga del DB e' quella che il file restituira' rileggendola.
    row = tuple(split_line(line)) if m != "off" else None
    with _lock:
        if m == "db":
            if _db_write(activity_db.insert_new, ym, row, epoch) is False:
                return
        else:
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
        if m == "db":
            return
        if key is not None:
            _keys.add(key)
        if m == "dual":
            _db_write(activity_db.insert_mirror, ym, row, epoch)
```

3h. `init_dedup()` diventa:

```python
def init_dedup():
    """Ricostruisce il set di dedup dal file del mese corrente (all'avvio).

    Solo chiavi (job_id, op): l'epoca non sta sulla riga, quindi dopo un
    riavvio un job ri-eseguito puo' ri-loggare il proprio evento di ciclo.
    Nel modo db non serve: il dedup lo fa il DB."""
    global _month
    ym = datetime.now().strftime("%Y-%m")
    if mode() == "db":
        with _lock:
            _month = ym
            _keys.clear()
        return
    keys = {(r.job_id, r.op) for r in month_rows(ym) if r.job_id}
    with _lock:
        _month = ym
        _keys.clear()
        _keys.update(keys)
```

3i. Nuova sezione prima di `# --------------------------------------------------------------- lettura`:

```python
# --------------------------------------------------------------- allineamento

def sync_month(ym, force=False):
    """Allinea il mese `ym` del DB al suo file; True se l'ha ricostruito.

    Mese chiuso con la dimensione dell'ultimo allineamento: saltato senza
    leggerlo. Altrimenti si contano le righe valide del file e, se non
    tornano con il DB (o con `force`), il mese si rifa' da capo. Il mese
    corrente si tratta sotto `_lock`: nessuna riga nuova entra nel file fra
    la lettura e la riscrittura."""
    if not _YM_RE.match(ym or ""):
        return False
    try:
        path = _path(ym)
        path.stat()
    except (OSError, RuntimeError):
        return False
    current = ym == datetime.now().strftime("%Y-%m")
    with (_lock if current else contextlib.nullcontext()):
        size = path.stat().st_size
        conn = activity_db.connect(_db_path())
        try:
            if not force:
                if not current and activity_db.synced_size(conn, ym) == size:
                    return False
                n = sum(1 for _ in file_rows(path))
                if activity_db.count(conn, ym) == n:
                    activity_db.mark_synced(conn, ym, size, n)
                    return False
            activity_db.rebuild_month(conn, ym, file_rows(path), size)
            return True
        finally:
            conn.close()


def sync_all():
    """Allinea il DB ai file, dal mese piu' vecchio al corrente (all'avvio,
    in un thread). Senza errori i lettori del modo db passano al DB; finche'
    non succede leggono dal file. Mai un'eccezione. Modo off: nulla."""
    if mode() == "off":
        return 0
    rebuilt = failed = 0
    for ym in sorted(months()):
        try:
            if sync_month(ym):
                rebuilt += 1
        except Exception as e:
            failed += 1
            print(f"[activity_log] sync {ym} fallito: {e}")
    if not failed:
        _db_ready.set()
    print(f"[activity_log] sync: {rebuilt} mesi ricostruiti, {failed} falliti")
    return rebuilt


def parity(ym):
    """Op del mese con conteggi diversi fra file e DB: {op: (file, db)}."""
    if not _YM_RE.match(ym or ""):
        raise ValueError(f"mese non valido: {ym!r}")
    in_file = Counter(r.op for r in file_rows(_path(ym)))
    try:
        conn = activity_db.reader(_db_path())
    except sqlite3.OperationalError:
        in_db = {}
    else:
        try:
            in_db = activity_db.op_counts(conn, ym)
        finally:
            conn.close()
    return {op: (in_file.get(op, 0), in_db.get(op, 0))
            for op in set(in_file) | set(in_db)
            if in_file.get(op, 0) != in_db.get(op, 0)}
```

- [ ] **Step 4: eseguire i test e verificare che passano**

Run: `python -m py_compile activity_log.py`
Run: `python -m pytest test/test_activity_log_db.py test/test_activity_log.py test/test_activity_db.py -q`
Expected: tutti PASS (il contratto della fase 1 gira ancora solo in `off`).

- [ ] **Step 5: commit**

```bash
git add activity_log.py test/test_activity_log_db.py
git commit -m "feat(activity-log): dual write and db dedup behind ABM_ACTIVITY_DB"
```

---

### Task 3: lettori sul DB nel modo `db`, contratto parametrizzato

**Files:**
- Modify: `activity_log.py` (sezione lettura)
- Modify: `test/test_activity_log.py`

**Interfaces:**
- Consumes (Task 1): `activity_db.reader`, `select_rows`, `fingerprint`. (Task 2): `mode()`, `sync_all()`, `_db_ready`, `_db_path()`, `_close_writer()`, `_lock`.
- Produces: `month_rows`, `iter_rows`, `fingerprint`, `delivered_ids` con le stesse firme; nel modo `db` e con `_db_ready` impostato leggono dal DB, altrimenti dal file. `months()` resta sui file. Fingerprint del DB: `("db", max_id, count)`.

- [ ] **Step 1: parametrizzare il contratto e aggiungere i test del DB**

In `test/test_activity_log.py`:

1a. Sostituire la fixture `log_dir` con:

```python
@pytest.fixture(params=["off", "db"])
def log_dir(request, tmp_path, monkeypatch):
    """Ogni test di contratto gira sul backend file (`off`) e sul DB (`db`)."""
    monkeypatch.setenv("ABM_ACTIVITY_DB", request.param)
    prev = activity_log._log_dir
    activity_log.configure(lambda: tmp_path)
    activity_log.reset()
    activity_log.sync_all()
    yield tmp_path
    activity_log.reset()
    activity_log.configure(prev)


def _sync():
    """Dopo una scrittura diretta del file, il DB la riprende come all'avvio."""
    if activity_log.mode() != "off":
        activity_log.sync_all()
```

1b. In `_write(...)`, prima di `return p`, aggiungere la chiamata `_sync()`.

1c. `test_cambio_mese_azzera_il_dedup` simula l'interno del set in RAM, che il modo `db` non usa: restringerlo al file mettendo sopra la funzione

```python
@pytest.mark.parametrize("log_dir", ["off"], indirect=True)
```

e aggiungere in coda al file:

```python
# ---------------------------------------------------------------- backend db

def _db_only(fn):
    return pytest.mark.parametrize("log_dir", ["db"], indirect=True)(fn)


@_db_only
def test_modo_db_legge_dal_db_non_dal_file(log_dir):
    activity_log.log("J1", "a.epub", "COMPLETE")
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(log_dir / f"activity_{_ym(datetime.now())}.log", "a", encoding="utf-8") as f:
        f.write(_line("J2", ts, "COMPLETE") + "\n")        # nel file ma non nel DB
    assert [r.job_id for r in activity_log.month_rows(_ym(datetime.now()))] == ["J1"]


@_db_only
def test_modo_db_senza_sync_legge_il_file(log_dir):
    activity_log.reset()                                   # _db_ready spento
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    (log_dir / f"activity_{_ym(datetime.now())}.log").write_text(
        _line("J9", ts, "COMPLETE") + "\n", encoding="utf-8")
    assert [r.job_id for r in activity_log.month_rows(_ym(datetime.now()))] == ["J9"]
    assert activity_log.delivered_ids(months=1)["complete"] == {"J9"}


@_db_only
def test_modo_db_db_illeggibile_ripiega_sul_file(log_dir):
    now = datetime.now()
    ts = now.strftime("%Y-%m-%d %H:%M:%S")
    _write(log_dir, _ym(now), [_line("J1", ts, "COMPLETE")])
    with activity_log._lock:
        activity_log._close_writer()
    for suffix in ("-wal", "-shm"):
        (log_dir / (activity_db.DB_FILENAME + suffix)).unlink(missing_ok=True)
    (log_dir / activity_db.DB_FILENAME).write_bytes(b"non sono un database" * 300)
    assert [r.job_id for r in activity_log.month_rows(_ym(now))] == ["J1"]
    assert activity_log.delivered_ids(months=1)["complete"] == {"J1"}
    assert activity_log.fingerprint(_ym(now)) is not None


@_db_only
def test_fingerprint_del_db_distinto_da_quello_del_file(log_dir):
    activity_log.log("J1", "a.epub", "GENERATE")
    fp = activity_log.fingerprint(_ym(datetime.now()))
    assert fp[0] == "db"


def test_famiglie_sovraccariche_andata_e_ritorno(log_dir):
    activity_log.log("J1", "Saga # 2.epub", "M4B_PROGRESS", voice="size_mb=1.0 pct=50")
    activity_log.log("", "", "ADMIN_VOUCHER_CREATE:gift", ip="9.9.9.9",
                     voice="AB12...", lang="a@b.it")
    activity_log.log("", "", "VOUCHER_ATTEMPT_BLOCKED:rate", ip="9.9.9.9")
    activity_log.log("J2", "b.epub", "PAYMENT_AMOUNT_MISMATCH", lang="atteso 5.00")
    activity_log.log("vc1", "speed=1.1", "VOICE_CLONE_SPEED", client_id="c1")
    activity_log.log("acct-1234abcd", "", "ACCOUNT_LOGIN", client_id="c1")
    got = [r[:1] + r[2:] for r in activity_log.month_rows(_ym(datetime.now()))]
    assert got == [
        ("J1", "Saga # 2.epub", "M4B_PROGRESS", "", "", "size_mb=1.0 pct=50", "", ""),
        ("", "", "ADMIN_VOUCHER_CREATE:gift", "", "9.9.9.9", "AB12...", "a@b.it", ""),
        ("", "", "VOUCHER_ATTEMPT_BLOCKED:rate", "", "9.9.9.9", "", "", ""),
        ("J2", "b.epub", "PAYMENT_AMOUNT_MISMATCH", "", "", "", "atteso 5.00", ""),
        ("vc1", "speed=1.1", "VOICE_CLONE_SPEED", "c1", "", "", "", ""),
        ("acct-1234abcd", "", "ACCOUNT_LOGIN", "c1", "", "", "", ""),
    ]
```

e aggiungere `import activity_db` fra gli import in testa.

- [ ] **Step 2: eseguire i test e verificare che falliscono**

Run: `python -m pytest test/test_activity_log.py -q`
Expected: i casi `[off]` PASS; falliscono almeno `test_modo_db_legge_dal_db_non_dal_file` (legge ancora il file, trova J1 e J2) e `test_fingerprint_del_db_distinto_da_quello_del_file`.

- [ ] **Step 3: lettori con ripiego nel modo `db`**

In `activity_log.py`, sezione lettura. `months()` resta com'e'. Sostituire `month_rows`, `iter_rows`, `fingerprint` con le versioni seguenti, rinominando le implementazioni attuali in `_file_month_rows`, `_file_iter_rows`, `_file_fingerprint` (corpo invariato; `_file_iter_rows` chiama `_file_month_rows`):

```python
def _use_db():
    return mode() == "db" and _db_ready.is_set()


def _db_rows(fallback, ym_from, ym_to, since_ts=None, until_ts=None, ops=None):
    """Righe dal DB; se il DB non si apre o la query fallisce prima della
    prima riga, quelle di `fallback()` (il file, registro completo)."""
    conn = None
    try:
        conn = activity_db.reader(_db_path())
        it = activity_db.select_rows(conn, ym_from, ym_to, since_ts, until_ts, ops)
        first = next(it, None)
    except (sqlite3.Error, OSError, RuntimeError) as e:
        if conn is not None:
            conn.close()
        print(f"[activity_log] lettura DB fallita, uso il file: {e}")
        yield from fallback()
        return
    try:
        if first is not None:
            yield Row(*first)
            for t in it:
                yield Row(*t)
    finally:
        conn.close()


def month_rows(ym):
    """Righe del mese YYYY-MM; mese non valido o assente: nessuna riga."""
    if not _YM_RE.match(ym or ""):
        return
    if _use_db():
        yield from _db_rows(lambda: _file_month_rows(ym), ym, ym)
        return
    yield from _file_month_rows(ym)


def iter_rows(since, until=None, ops=None):
    """Righe con `since <= ts < until` (until assente: fino a oggi), in
    ordine di mese e di scrittura; `ops`: insieme di operazioni esatte."""
    if _use_db():
        end = until or datetime.now()
        yield from _db_rows(lambda: _file_iter_rows(since, until, ops),
                            since.strftime("%Y-%m"), end.strftime("%Y-%m"),
                            since.strftime(TS_FMT),
                            until.strftime(TS_FMT) if until else None, ops)
        return
    yield from _file_iter_rows(since, until, ops)


def fingerprint(ym):
    """Firma del mese per invalidare le cache; None se il mese non c'e'."""
    if not _YM_RE.match(ym or ""):
        return None
    if _use_db():
        try:
            conn = activity_db.reader(_db_path())
            try:
                fp = activity_db.fingerprint(conn, ym)
            finally:
                conn.close()
            return None if fp is None else ("db",) + fp
        except (sqlite3.Error, OSError, RuntimeError):
            pass
    return _file_fingerprint(ym)
```

`_file_month_rows(ym)` non ripete il controllo di `_YM_RE` (lo fa gia' `month_rows`), ma lo tiene se il corpo attuale lo contiene: nessun danno. `delivered_ids` resta invariata (passa da `month_rows`).

- [ ] **Step 4: eseguire i test e verificare che passano**

Run: `python -m py_compile activity_log.py`
Run: `python -m pytest test/test_activity_log.py test/test_activity_log_db.py test/test_activity_db.py -q`
Expected: tutti PASS, su entrambi i parametri. Se un test di contratto fallisce solo in `[db]` e non ispeziona il file direttamente, il difetto e' in `activity_log`/`activity_db`: correggere li', non il test.

- [ ] **Step 5: commit**

```bash
git add activity_log.py test/test_activity_log.py
git commit -m "feat(activity-log): read months from activity.db in db mode with file fallback"
```

---

### Task 4: integrazione in `audiobook_app`

**Files:**
- Modify: `audiobook_app.py:160-163` (configure) e `audiobook_app.py:21602-21614` (`_ensure_background_threads`)
- Modify: `test/test_activity_log_readers.py`
- Create: `test/test_activity_log_app_config.py`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: `activity_log.mode()`, `activity_log.sync_all()` (Task 2); lettori (Task 3).
- Produces: `audiobook_app._start_activity_sync() -> threading.Thread | None`; env `ABM_ACTIVITY_LOG_DIR` letta a ogni chiamata.

- [ ] **Step 1: scrivere i test che falliscono**

`test/test_activity_log_app_config.py`:

```python
"""Cartella del business log da env e thread di allineamento all'avvio."""
from datetime import datetime

import activity_log
import audiobook_app


def test_cartella_da_abm_activity_log_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_ACTIVITY_DB", raising=False)
    monkeypatch.setenv("ABM_ACTIVITY_LOG_DIR", str(tmp_path))
    activity_log.reset()
    try:
        audiobook_app._log_activity("J1", "a.epub", "ANALYZE")
        ym = datetime.now().strftime("%Y-%m")
        assert [r.op for r in activity_log.file_rows(tmp_path / f"activity_{ym}.log")] == ["ANALYZE"]
    finally:
        activity_log.reset()


def test_senza_env_resta_script_dir(tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_ACTIVITY_LOG_DIR", raising=False)
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    assert activity_log._dir() == tmp_path


def test_sync_parte_solo_con_db_acceso(monkeypatch):
    calls = []
    monkeypatch.setattr(activity_log, "sync_all", lambda: calls.append(1))
    monkeypatch.setenv("ABM_ACTIVITY_DB", "off")
    assert audiobook_app._start_activity_sync() is None
    monkeypatch.setenv("ABM_ACTIVITY_DB", "dual")
    t = audiobook_app._start_activity_sync()
    t.join(5)
    assert calls == [1]
```

In `test/test_activity_log_readers.py`:

- sostituire la fixture `logs` con:

```python
@pytest.fixture(params=["off", "db"])
def logs(request, tmp_path, monkeypatch):
    """I lettori dell'app devono dare lo stesso risultato sul file e sul DB."""
    monkeypatch.setenv("ABM_ACTIVITY_DB", request.param)
    monkeypatch.delenv("ABM_ACTIVITY_LOG_DIR", raising=False)
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    activity_log.reset()
    activity_log.sync_all()
    for c in (audiobook_app._stats_today_cache, audiobook_app._stats_month_cache):
        c["value"] = None
        c["expires"] = 0.0
    yield tmp_path
    activity_log.reset()
    for c in (audiobook_app._stats_today_cache, audiobook_app._stats_month_cache):
        c["value"] = None
        c["expires"] = 0.0
```

- in fondo a `_write_by_month(...)` aggiungere:

```python
    if activity_log.mode() != "off":
        activity_log.sync_all()
```

- [ ] **Step 2: eseguire i test e verificare che falliscono**

Run: `python -m pytest test/test_activity_log_app_config.py test/test_activity_log_readers.py -q`
Expected: FAIL su `test_cartella_da_abm_activity_log_dir` (file non creato in tmp) e `AttributeError: ... '_start_activity_sync'`. I test dei lettori possono gia' passare in `[db]` (e' atteso: la facciata e' pronta dal Task 3).

- [ ] **Step 3: implementazione**

3a. `audiobook_app.py`, sostituire il commento e la chiamata a `activity_log.configure` (righe 160-163) con:

```python
# Il business log vive in ABM_ACTIVITY_LOG_DIR se impostata (in prod la data
# dir, dopo lo spostamento della fase 2), altrimenti in SCRIPT_DIR. La
# callable e' risolta a ogni scrittura/lettura: patchare SCRIPT_DIR nei test
# basta a spostarlo. activity.db (ABM_ACTIVITY_DB=dual|db) sta accanto ai file.
activity_log.configure(
    log_dir=lambda: Path(os.environ.get("ABM_ACTIVITY_LOG_DIR") or SCRIPT_DIR))
```

3b. Subito prima di `def _ensure_background_threads():` aggiungere:

```python
def _start_activity_sync():
    """Allinea activity.db ai file in un thread, solo con ABM_ACTIVITY_DB
    dual|db. Finche' non ha finito il modo db legge dal file."""
    if activity_log.mode() == "off":
        return None
    t = threading.Thread(target=activity_log.sync_all, daemon=True,
                         name="activity-sync")
    t.start()
    return t
```

e dentro `_ensure_background_threads()`, subito dopo `threading.Thread(target=_cleanup_supervisor, daemon=True).start()`:

```python
    _start_activity_sync()
```

3c. `.gitignore`: aggiungere in coda

```
# activity log su SQLite (ABM_ACTIVITY_DB), accanto ai file in dev
activity.db*
```

- [ ] **Step 4: eseguire i test e verificare che passano**

Run: `python -m py_compile audiobook_app.py`
Run: `python -m pytest test/test_activity_log_app_config.py test/test_activity_log_readers.py test/test_activity_platform.py test/test_admin_logactivity_filters.py test/test_admin_user_stats.py test/test_log_activity_regen_dedup.py test/test_orphan_delivered_no_refund.py test/test_cold_download_log.py test/test_m4b_progress.py -q`
Expected: tutti PASS. Un test dei lettori che fallisce solo in `[db]` e ispeziona il file sul disco si restringe con `@pytest.mark.parametrize("logs", ["off"], indirect=True)` e un commento del perche'; ogni altro fallimento in `[db]` e' un difetto da correggere nella facciata.

- [ ] **Step 5: commit**

```bash
git add audiobook_app.py test/test_activity_log_readers.py test/test_activity_log_app_config.py .gitignore
git commit -m "feat(activity-log): ABM_ACTIVITY_LOG_DIR and startup sync of activity.db"
```

---

### Task 5: CLI `scripts/activity_db.py` (parita', sync, misura di latenza)

**Files:**
- Create: `scripts/activity_db.py`
- Create: `test/test_activity_db_cli.py`

**Interfaces:**
- Consumes: `activity_log.configure`, `months`, `parity`, `sync_month`, `log`, `reset`, `_YM_RE` (Task 2).
- Produces: `main(argv=None) -> int` (exit code), comandi `parity`, `sync`, `bench`.

- [ ] **Step 1: scrivere i test che falliscono**

`test/test_activity_db_cli.py`:

```python
"""CLI scripts/activity_db.py: parity, sync dei mesi chiusi, bench."""
import importlib.util
import os
from datetime import datetime
from pathlib import Path

import pytest

import activity_log

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "activity_db.py"
_spec = importlib.util.spec_from_file_location("activity_db_cli", _SCRIPT)
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


def _line(job, ts, op):
    return f'{job} # {ts} # "a.epub" # {op} # c # 1.1.1.1 # v # it # web'


@pytest.fixture
def d(tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_ACTIVITY_DB", raising=False)
    prev = activity_log._log_dir
    activity_log.reset()
    yield tmp_path
    activity_log.reset()
    activity_log.configure(prev)


def test_sync_salta_il_mese_corrente_e_parity(d, capsys):
    (d / "activity_2026-07.log").write_text(
        _line("J1", "2026-07-01 10:00:00", "COMPLETE") + "\n", encoding="utf-8")
    cur = datetime.now().strftime("%Y-%m")
    (d / f"activity_{cur}.log").write_text(
        _line("J2", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "COMPLETE") + "\n",
        encoding="utf-8")
    assert cli.main(["sync", "--dir", str(d)]) == 0
    out = capsys.readouterr().out
    assert "2026-07 ricostruito" in out and f"{cur} saltato" in out
    assert cli.main(["parity", "--dir", str(d), "--month", "2026-07"]) == 0
    assert cli.main(["parity", "--dir", str(d), "--month", cur]) == 1
    assert f"{cur} COMPLETE: file=1 db=0" in capsys.readouterr().out


def test_parity_mese_non_valido(d):
    with pytest.raises(SystemExit):
        cli.main(["parity", "--dir", str(d), "--month", "2026-7"])


def test_bench_stampa_i_due_modi_e_ripristina_env(d, capsys, monkeypatch):
    monkeypatch.setenv("ABM_ACTIVITY_DB", "db")
    assert cli.main(["bench", "--dir", str(d), "-n", "5"]) == 0
    out = capsys.readouterr().out
    assert "off: n=5" in out and "dual: n=5" in out
    assert os.environ["ABM_ACTIVITY_DB"] == "db"
    assert [p.name for p in d.iterdir()] == []        # cartella di lavoro rimossa
```

- [ ] **Step 2: eseguire i test e verificare che falliscono**

Run: `python -m pytest test/test_activity_db_cli.py -q`
Expected: ERROR in collection (`FileNotFoundError` sullo script).

- [ ] **Step 3: scrivere `scripts/activity_db.py`**

```python
#!/usr/bin/env python3
"""Attrezzi per activity.db (fasi 2-3 del business log su SQLite).

    python3 scripts/activity_db.py parity [--dir DIR] [--month YYYY-MM ...]
    python3 scripts/activity_db.py sync   [--dir DIR] [--force]
    python3 scripts/activity_db.py bench  [--dir DIR] [-n N]

--dir: cartella di activity_*.log e activity.db. Default: ABM_ACTIVITY_LOG_DIR,
poi /opt/audiobook-maker/data. Nella shell ssh di prod le ABM_* dell'unit
systemd non ci sono: passare --dir esplicito.

parity  conteggi per op e mese fra file e DB; exit 1 se qualcosa differisce.
sync    ricostruisce dal file i mesi CHIUSI che non tornano. Il mese corrente
        lo allinea l'app all'avvio, sotto il suo lock di scrittura.
bench   latenza di activity_log.log() nei modi off e dual, su una cartella
        temporanea dentro --dir (stesso disco dei log), poi rimossa.
"""
import argparse
import os
import shutil
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import activity_log  # noqa: E402

DEFAULT_DIR = "/opt/audiobook-maker/data"


def _ym_arg(value):
    if not activity_log._YM_RE.match(value):
        raise argparse.ArgumentTypeError(f"mese non valido: {value!r} (YYYY-MM)")
    return value


def _parity(args):
    bad = 0
    for ym in sorted(args.month or activity_log.months()):
        diff = activity_log.parity(ym)
        if not diff:
            print(f"{ym} ok")
            continue
        bad += 1
        for op, (in_file, in_db) in sorted(diff.items()):
            print(f"{ym} {op}: file={in_file} db={in_db}")
    return 1 if bad else 0


def _sync(args):
    current = datetime.now().strftime("%Y-%m")
    for ym in sorted(activity_log.months()):
        if ym == current:
            print(f"{ym} saltato: mese corrente, lo allinea l'app all'avvio")
            continue
        done = activity_log.sync_month(ym, force=args.force)
        print(f"{ym} {'ricostruito' if done else 'gia allineato'}")
    return 0


def _pct(values, p):
    s = sorted(values)
    return s[min(len(s) - 1, int(round(p / 100.0 * (len(s) - 1))))]


def _bench(args):
    prev_mode = os.environ.get("ABM_ACTIVITY_DB")
    work = Path(tempfile.mkdtemp(prefix="activity_bench_", dir=args.dir))
    try:
        for m in ("off", "dual"):
            os.environ["ABM_ACTIVITY_DB"] = m
            d = work / m
            d.mkdir()
            activity_log.configure(lambda d=d: d)
            activity_log.reset()
            times = []
            for i in range(args.n):
                t0 = time.perf_counter()
                activity_log.log(f"J{i}", "bench.epub", "GENERATE", client_id="c",
                                 ip="127.0.0.1", voice="v", lang="it", platform="web")
                times.append((time.perf_counter() - t0) * 1000.0)
            print(f"{m}: n={args.n} p50={_pct(times, 50):.2f} p95={_pct(times, 95):.2f}"
                  f" p99={_pct(times, 99):.2f} max={max(times):.2f} ms")
            activity_log.reset()      # chiude activity.db prima di rimuovere la cartella
    finally:
        if prev_mode is None:
            os.environ.pop("ABM_ACTIVITY_DB", None)
        else:
            os.environ["ABM_ACTIVITY_DB"] = prev_mode
        shutil.rmtree(work, ignore_errors=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=("parity", "sync", "bench"))
    ap.add_argument("--dir", default=os.environ.get("ABM_ACTIVITY_LOG_DIR") or DEFAULT_DIR)
    ap.add_argument("--month", action="append", type=_ym_arg)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("-n", type=int, default=2000)
    args = ap.parse_args(argv)
    log_dir = Path(args.dir)
    activity_log.configure(lambda: log_dir)
    return {"parity": _parity, "sync": _sync, "bench": _bench}[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: eseguire i test e verificare che passano**

Run: `python -m py_compile scripts/activity_db.py`
Run: `python -m pytest test/test_activity_db_cli.py -q`
Expected: tutti PASS.

- [ ] **Step 5: commit**

```bash
git add scripts/activity_db.py test/test_activity_db_cli.py
git commit -m "feat(scripts): activity_db cli for parity, closed-month sync and latency bench"
```

---

### Task 6: backup, restore, setup, script di migrazione e documentazione

**Files:**
- Modify: `scripts/backup_ABM.sh:68-89`
- Modify: `scripts/restore_ABM.sh:124-133`
- Modify: `scripts/server_setup.sh:138`
- Modify: `scripts/migration/migration_recover_prep.py:61-99,123-148`
- Create: `test/test_migration_recover_prep.py`
- Modify: `docs/FORENSICS_PLAYBOOK.md:19,35`
- Modify: `md_files/PARAMETRI_CONFIGURAZIONE.md` (append)

**Interfaces:**
- Consumes: la posizione `ABM_ACTIVITY_LOG_DIR` e il file `activity.db` (Task 4).
- Produces: `migration_recover_prep.delivered_job_ids(*log_dirs) -> set[str]`; opzione `--log-dir` (default `/opt/audiobook-maker/data`).

- [ ] **Step 1: test dello script di migrazione (fallisce)**

`test/test_migration_recover_prep.py`:

```python
"""migration_recover_prep: consegne lette dai log in SCRIPT_DIR e nella data dir."""
import importlib.util
from pathlib import Path

_SCRIPT = (Path(__file__).resolve().parent.parent / "scripts" / "migration"
           / "migration_recover_prep.py")
_spec = importlib.util.spec_from_file_location("migration_recover_prep", _SCRIPT)
mrp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mrp)


def _line(job, op):
    return f'{job} # 2026-08-01 10:00:00 # "a # b.epub" # {op} # c # 1.1.1.1 # v # it # web\n'


def test_unione_delle_due_cartelle(tmp_path):
    old, new = tmp_path / "app", tmp_path / "data"
    old.mkdir()
    new.mkdir()
    (old / "activity_2026-07.log").write_text(_line("J1", "EMAIL_SENT"), encoding="utf-8")
    (new / "activity_2026-08.log").write_text(
        _line("J2", "TR_EMAIL_SENT") + _line("J3", "GENERATE"), encoding="utf-8")
    assert mrp.delivered_job_ids(str(new), str(old)) == {"J1", "J2"}


def test_una_cartella_assente_non_avvisa(tmp_path, capsys):
    new = tmp_path / "data"
    new.mkdir()
    (new / "activity_2026-08.log").write_text(_line("J2", "EMAIL_SENT"), encoding="utf-8")
    assert mrp.delivered_job_ids(str(new), str(tmp_path / "manca")) == {"J2"}
    assert "ATTENZIONE" not in capsys.readouterr().err


def test_tutte_assenti_avvisa(tmp_path, capsys):
    assert mrp.delivered_job_ids(str(tmp_path / "a"), str(tmp_path / "b")) == set()
    assert "ATTENZIONE" in capsys.readouterr().err
```

Run: `python -m pytest test/test_migration_recover_prep.py -q`
Expected: FAIL su `test_unione_delle_due_cartelle` (la funzione accetta una sola cartella: `TypeError`).

- [ ] **Step 2: `migration_recover_prep.py`**

Sostituire `delivered_job_ids(script_dir)` (righe 61-99) con:

```python
def delivered_job_ids(*log_dirs):
    """job_id che hanno un evento di consegna negli activity log di `log_dirs`.

    Gli activity log stavano in SCRIPT_DIR; dallo spostamento della fase 2
    (ABM_ACTIVITY_LOG_DIR) stanno nella data dir: si leggono tutte le
    cartelle date, una assente si salta. Un file per mese
    `activity_YYYY-MM.log`, formato di riga scritto da activity_log.log():

        {job_id} # {ts} # "{filename}" # {operation} # {client_id} # {client_ip}
                 # {voice} # {browser_lang} # {platform}

    Il job_id e' il campo 0; l'operazione e' normalmente il campo 3, ma un
    filename contenente ' # ' farebbe slittare le colonne. Si confronta quindi
    ogni campo dal terzo in poi con l'elenco degli eventi, per uguaglianza
    esatta: un match parziale marcherebbe come 'gia' consegnato' un job che
    invece va ripreso, cioe' lo perderebbe."""
    ids = set()
    readable = 0
    for log_dir in log_dirs:
        try:
            names = [n for n in os.listdir(log_dir)
                     if n.startswith("activity_") and n.endswith(".log")]
        except OSError:
            continue
        readable += 1
        for name in sorted(names):
            path = os.path.join(log_dir, name)
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    for line in f:
                        fields = [p.strip() for p in line.rstrip("\n").split(" # ")]
                        if len(fields) < 4:
                            continue
                        if any(fld in DELIVERED_EVENTS for fld in fields[3:]):
                            ids.add(fields[0])
            except OSError:
                continue
    if not readable:
        print("ATTENZIONE: activity log non leggibili in %s: il controllo "
              "'gia' consegnato' viene saltato." % ", ".join(log_dirs),
              file=sys.stderr)
    return ids
```

In `main()`: dopo l'argomento `--script-dir` aggiungere

```python
    ap.add_argument("--log-dir", default="/opt/audiobook-maker/data",
                    help="ABM_ACTIVITY_LOG_DIR: dove stanno gli activity_*.log dopo "
                         "lo spostamento (default: /opt/audiobook-maker/data); "
                         "--script-dir resta letta per i mesi rimasti li'")
```

e sostituire `delivered = delivered_job_ids(args.script_dir)` con

```python
    delivered = delivered_job_ids(args.log_dir, args.script_dir)
```

Aggiornare nella docstring del modulo la riga d'uso (riga 34) in:
`    python3 migration_recover_prep.py [--data-dir DIR] [--log-dir DIR] [--script-dir DIR]`

Run: `python -m py_compile scripts/migration/migration_recover_prep.py`
Run: `python -m pytest test/test_migration_recover_prep.py -q`
Expected: PASS.

- [ ] **Step 3: `backup_ABM.sh`**

Sostituire il blocco `# Database SQLite degli account (abm.db)...` fino al suo `fi` di chiusura (righe 68-83) con:

```bash
# Database SQLite (abm.db, activity.db): copia coerente via API di backup
# (sicura anche con l'app in scrittura e il WAL attivo); fallback a cp se
# manca sqlite3 o se il backup a caldo fallisce. Mai fatale: un intoppo su un
# DB non deve far saltare il resto del backup giornaliero.
backup_sqlite() {
    local name="$1"
    [ -f "$DATA_DIR/$name" ] || return 0
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$DATA_DIR/$name" ".backup '$BACKUP_DIR/data/$name'" && return 0
        echo "  ATTENZIONE: backup sqlite di $name fallito, uso cp a freddo"
    fi
    cp "$DATA_DIR/$name" "$BACKUP_DIR/data/$name" 2>/dev/null || true
    [ -f "$DATA_DIR/$name-wal" ] && cp "$DATA_DIR/$name-wal" "$BACKUP_DIR/data/" 2>/dev/null || true
    return 0
}
backup_sqlite abm.db
# Indice del business log (ABM_ACTIVITY_DB): ricostruibile dai file, ma
# copiarlo evita di rifarlo al primo avvio dopo un restore.
backup_sqlite activity.db
```

Nel blocco `# ── 6. Log attivita' ──` sostituire la riga `cp /opt/audiobook-maker/activity_*.log ...` con:

```bash
# Posizione storica (SCRIPT_DIR) e, dallo spostamento, ABM_ACTIVITY_LOG_DIR
# = data dir: si copiano entrambe, una delle due e' vuota.
cp /opt/audiobook-maker/activity_*.log "$BACKUP_DIR/logs/" 2>/dev/null || true
cp "$DATA_DIR"/activity_*.log "$BACKUP_DIR/logs/" 2>/dev/null || true
```

Run: `bash -n scripts/backup_ABM.sh`
Expected: nessun output (sintassi valida).

- [ ] **Step 4: `restore_ABM.sh`**

Nel blocco `# ── 7. Ripristina dati applicazione ──`, dopo la riga `cp "$BACKUP_DIR/data/abm.db" ...` aggiungere:

```bash
    cp "$BACKUP_DIR/data/activity.db" /opt/audiobook-maker/data/ 2>/dev/null || true
```

e sostituire il blocco `if [ -d "$BACKUP_DIR/logs" ]; then ... fi` dei log con:

```bash
if [ -d "$BACKUP_DIR/logs" ]; then
    # I log vanno dove li cerca l'app: ABM_ACTIVITY_LOG_DIR dell'override
    # appena ripristinato, altrimenti la cartella dell'app (SCRIPT_DIR).
    ACT_DIR=$(grep 'ABM_ACTIVITY_LOG_DIR' /etc/systemd/system/audiobook-maker.service.d/override.conf 2>/dev/null | sed 's/.*ABM_ACTIVITY_LOG_DIR=//' | sed 's/"//g')
    ACT_DIR=${ACT_DIR:-/opt/audiobook-maker}
    mkdir -p "$ACT_DIR"
    cp "$BACKUP_DIR/logs/activity_"*.log "$ACT_DIR/" 2>/dev/null || true
    cp "$BACKUP_DIR/logs/voucher_admin.log" /opt/audiobook-maker/data/ 2>/dev/null || true
    echo "  Log attivita' ripristinati in $ACT_DIR."
fi
```

Run: `bash -n scripts/restore_ABM.sh`
Expected: nessun output.

- [ ] **Step 5: `server_setup.sh`**

Dopo la riga `Environment="ABM_DATA_DIR=/opt/audiobook-maker/data"` (riga 138) aggiungere:

```
Environment="ABM_ACTIVITY_LOG_DIR=/opt/audiobook-maker/data"
```

Run: `bash -n scripts/server_setup.sh`
Expected: nessun output.

- [ ] **Step 6: `docs/FORENSICS_PLAYBOOK.md`**

Sostituire l'inizio della voce 1 di "Log sources" (riga 19), da `1. **\`activity_YYYY-MM.log\` in the APP dir**` fino a `**NOT** the data dir).`, con:

```markdown
1. **`activity_YYYY-MM.log` in `ABM_ACTIVITY_LOG_DIR`** — the data dir `/opt/audiobook-maker/data/` after the phase-2 move; before it (and whenever the variable is unset) the APP dir `/opt/audiobook-maker/` (= `SCRIPT_DIR`). Check `/proc/<pid>/environ` for `ABM_ACTIVITY_LOG_DIR`; old months may still sit in the app dir. With `ABM_ACTIVITY_DB=dual|db` the same rows are in `activity.db` next to the files: `sqlite3 -readonly /opt/audiobook-maker/data/activity.db "SELECT ts, op, op_arg, filename, client_id, ip, voice, detail, lang FROM events WHERE job_id='<jid>' ORDER BY id"` (`op_arg` = the `:suffix`, `detail` = payload of `M4B_*`/`ADMIN_VOUCHER_*`/`VOUCHER_ATTEMPT*`/`PAYMENT_*`/`VOICE_CLONE_*`/`ACCOUNT_*`). The files stay the complete record until phase 4.
```

(il resto della riga, da ` Persistent per-month business log` in poi, resta invariato). Nella "Fast diagnostic sequence" sostituire il passo 1 con:

```markdown
1. `grep -h <jid> /opt/audiobook-maker/data/activity_*.log /opt/audiobook-maker/activity_*.log 2>/dev/null` → lifecycle + whether ever downloaded.
```

- [ ] **Step 7: `md_files/PARAMETRI_CONFIGURAZIONE.md`**

Aggiungere in coda:

```markdown
## Activity log su SQLite (`ABM_ACTIVITY_DB`, `ABM_ACTIVITY_LOG_DIR`)

| Variabile | Default | Effetto |
|---|---|---|
| `ABM_ACTIVITY_LOG_DIR` | `SCRIPT_DIR` | Cartella di `activity_YYYY-MM.log` e di `activity.db`. In prod `/opt/audiobook-maker/data` dopo lo spostamento (a servizio fermo, vedi l'addendum della spec `docs/superpowers/specs/2026-09-24-activity-log-db-design.md`). |
| `ABM_ACTIVITY_DB` | `off` | `off`: solo file. `dual`: file piu' copia in `activity.db`, letture dal file. `db`: dedup e letture su `activity.db`, file sempre scritto. Valore ignoto = `off`. Letta a ogni scrittura; il cambio passa dall'unit systemd e da un restart. |

Il file resta il registro completo fino alla fase 4: all'avvio, con `dual` o `db`, un thread
(`activity_log.sync_all`) ricostruisce dal file i mesi del DB che non tornano; finche' non ha
finito, e se il DB non si legge, il modo `db` legge dal file. Ogni scrittura sul DB oltre 50 ms
lascia `[activity_log] scrittura DB lenta` nel log di servizio. Attrezzi:
`python3 scripts/activity_db.py parity|sync|bench --dir <cartella>` (in ssh le ABM_* dell'unit
non ci sono: `--dir` esplicito).
```

- [ ] **Step 8: commit**

```bash
git add scripts/backup_ABM.sh scripts/restore_ABM.sh scripts/server_setup.sh scripts/migration/migration_recover_prep.py test/test_migration_recover_prep.py
git add -f docs/FORENSICS_PLAYBOOK.md md_files/PARAMETRI_CONFIGURAZIONE.md
git commit -m "chore(ops): activity log dir and activity.db in backup, restore, setup and docs"
```

---

### Task 7: verifica d'insieme

**Files:**
- Create (scratchpad, non nel repo): `<scratchpad>/equiv_activity_db.py`

`<scratchpad>` = lo scratchpad della sessione che esegue. `<cartella_log>` = una cartella con copie dei log reali (`activity_*.log`), la stessa usata per l'equivalenza della fase 1 (es. `.worktrees/ABM_DB` nel checkout principale): **copiarli**, mai leggerli o scriverli sul posto.

**Interfaces:**
- Consumes: tutto il piano.
- Produces: nessuna API; solo evidenze nel report.

- [ ] **Step 1: suite completa**

Run: `python -m pytest test -q -p no:cacheprovider`
Expected: 24 falliti (o meno) tutti nei file della baseline (`abuse_judge`, `admin_voice_xss`, `audio_generation_tags`, `free_quota_generate_enforcement`, `voice_clone_replica`, `voxcpm_runpod`; `test_voice_clone_generate` solo se il suo test SMTP instabile). Qualunque altro fallimento: fermarsi e correggere.

- [ ] **Step 2: equivalenza dei lettori `off` vs `db` sui log reali**

Scrivere `<scratchpad>/equiv_activity_db.py`:

```python
"""Uscite dei lettori dell'app sui log reali, backend file o DB.

Uso: python equiv_activity_db.py <repo> <cartella_log> <off|db> <out.json>
"""
import json
import os
import re
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

repo, src, mode, out = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
tmp = Path(tempfile.mkdtemp(prefix="abm_equiv_db_"))
logs = tmp / "logs"
logs.mkdir()
for p in src.glob("activity_*.log"):
    shutil.copy2(p, logs / p.name)
os.environ["ABM_DATA_DIR"] = str(tmp / "data")
os.environ["ABM_ACTIVITY_DB"] = mode
os.environ.pop("ABM_ACTIVITY_LOG_DIR", None)
sys.path.insert(0, str(repo))
os.chdir(repo)

import audiobook_app  # noqa: E402
import activity_log  # noqa: E402
import user_stats  # noqa: E402

audiobook_app.SCRIPT_DIR = logs
activity_log.reset()
print("sync:", activity_log.sync_all())


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


res = {}
yms = sorted(m.group(1) for p in logs.iterdir()
             if (m := re.match(r"^activity_(\d{4}-\d{2})\.log$", p.name)))
for ym in yms:
    res[f"parity/{ym}"] = norm(activity_log.parity(ym)) if mode != "off" else {}
    res[f"sessions/{ym}"] = norm(audiobook_app._parse_log_sessions(ym))
    an = norm(user_stats.analyze(activity_log.month_rows(ym), ym=ym))
    an.pop("file", None)
    res[f"analyze/{ym}"] = an
    y, m = map(int, ym.split("-"))
    start, nxt = datetime(y, m, 1), datetime(y + (m == 12), m % 12 + 1, 1)
    res[f"power_users/{ym}"] = norm(user_stats.power_users(
        activity_log.iter_rows(start, until=nxt), datetime(y, m, 20, 12),
        min_jobs=1, top=100000, month_ym=ym))
audiobook_app._stats_today_cache["value"] = None
audiobook_app._stats_month_cache["value"] = None
res["stats_today"] = norm(audiobook_app._stats_today_count())
res["stats_month"] = norm(audiobook_app._stats_month_by_lang())
res["delivered"] = norm(activity_log.delivered_ids(months=12))
out.write_text(json.dumps(res, sort_keys=True, indent=1, ensure_ascii=False), encoding="utf-8")
print(f"{len(res)} chiavi -> {out}")
sys.stdout.flush()
os._exit(0)
```

Run: `python <scratchpad>/equiv_activity_db.py . <cartella_log> off <scratchpad>/equiv_off.json`
Run: `python <scratchpad>/equiv_activity_db.py . <cartella_log> db <scratchpad>/equiv_db.json`
Run: `python -c "import json,sys; a=json.load(open(sys.argv[1],encoding='utf-8')); b=json.load(open(sys.argv[2],encoding='utf-8')); d=[k for k in sorted(set(a)|set(b)) if not k.startswith('parity/') and a.get(k)!=b.get(k)]; p=[k for k in b if k.startswith('parity/') and b[k]]; print('diff:', d); print('parity ko:', p)" <scratchpad>/equiv_off.json <scratchpad>/equiv_db.json`
Expected: `diff: []` e `parity ko: []`. Se `stats_today` differisce solo perche' il giorno e' cambiato fra le due esecuzioni, rilanciare entrambe.

- [ ] **Step 3: misura della latenza in locale**

Run: `python scripts/activity_db.py bench --dir <scratchpad> -n 2000`
Expected: due righe `off:` e `dual:` con i percentili. Riportarle nel report: sono l'indicazione locale; la decisione (sincrona vs coda, soglia p99 5 ms) si prende sulla misura di prod del rollout, passo 3.

- [ ] **Step 4: pulizia**

Rimuovere `<scratchpad>/equiv_off.json`, `<scratchpad>/equiv_db.json` e le cartelle `abm_equiv_db_*` rimaste nella temp di sistema. Verificare `git status --short`: solo `.claude/settings.local.json` (preesistente) fuori dai commit. Nessun commit in questo task.
