# Account Magic Link (Blocco 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Account opzionale con login passwordless (magic link + codice a 6 cifre), storico dei job con download dei file ancora disponibili, introducendo SQLite come persistenza.

**Architecture:** Due moduli foglia nuovi (`db.py` per SQLite via stdlib `sqlite3`, `accounts.py` per codici/sessioni/storico) più `account_page.py` per le pagine server-side. `audiobook_app.py` aggiunge le route `/api/auth/*`, `/auth/<token>`, `/account`, `/api/account/*` e aggancia i job ai tre endpoint di avvio (`/api/generate`, `/api/optimize`, `/api/translate`). `generation_engine.py` notifica stato terminale e token di download tramite le funzioni iniettate da `configure()`. L'autorizzazione al download resta quella dei token `/dl/<token>/*`: lo storico li elenca soltanto.

**Tech Stack:** Python 3 / Flask, `sqlite3` stdlib (WAL), vanilla JS SPA (`static/js/app.js`, `templates/_fragments/`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-19-account-magic-link-design.md`

## Global Constraints

- Branch di lavoro: `gestione-utenti`, worktree `.worktrees/gestione-utenti`. Solo commit locali: **nessun `git push`** senza conferma esplicita dell'utente nel turno corrente.
- Commit in stile Conventional Commits `type(scope): summary`, **senza trailer** di attribuzione (`Co-Authored-By`, `Generated with`, `Claude-Session` ecc.): CLAUDE.md prevale sull'harness.
- `*.md` è in `.gitignore`: i file `.md` di `docs/`, `i18n/*.json` no. Non serve `-f` per `.py`/`.js`/`.json`; serve `git add -f` solo per file `.md`.
- Shell di sviluppo: PowerShell, un comando per riga, mai `&&`. Validare sempre la sintassi (`python -m py_compile <file>`) prima di consegnare codice. Test: `pytest test/<file>.py -v --tb=short`.
- `git add` solo con path espliciti (sessioni parallele sullo stesso checkout): mai `git add -A`, mai reset/stash globali.
- Mai import di `audiobook_app` dai sotto-moduli: stato condiviso via `configure()`.
- Nessuna eccezione dei nuovi hook deve raggiungere i thread di generazione: ogni chiamata da `generation_engine` e dai path di avvio job va in `try/except` con `print` di WARNING.
- Email in chiaro mai nel business log: sid `acct-<email_hash[:8]>`. Il token admin mai in query string.
- Stringhe UI non localizzate in inglese; mai nominare provider AI/TTS nella UI utente.
- Variabili d'ambiente nuove (default): `ABM_ACCOUNT_ENABLE=1`, `ABM_ACCOUNT_SESSION_DAYS=90`, `ABM_ACCOUNT_CODE_TTL_MIN=10`, `ABM_ACCOUNT_CODE_MAX_ATTEMPTS=5`, `ABM_ACCOUNT_HISTORY_MONTHS=24`, `ABM_ACCOUNT_GRACE_DAYS=90`.
- Codice: TTL 10 min, 5 tentativi (bloccato al 6°), consumato una sola volta, `GET /auth/<token>` **non consuma mai**. Sessione: token opaco `secrets.token_urlsafe(32)`, in DB solo `sha256(token)`, cookie `abm_session` HttpOnly/SameSite=Lax/max-age 90 giorni, rinnovo rolling solo se `now - last_seen_at > 3600`. `Authorization: Bearer` ha precedenza sul cookie.
- Risposte neutre su `/api/auth/request` (`{ok:true}` sempre, nessuna enumerazione); 429 solo dal rate limit per IP.
- Ogni file nuovo con docstring di modulo; commenti misti IT/EN come nel resto del repo.

---

### Task 1: `db.py` — accesso SQLite condiviso

**Files:**
- Create: `db.py`
- Test: `test/test_db.py`

**Interfaces:**
- Consumes: nulla (modulo foglia, sola stdlib).
- Produces: `db.DB_FILENAME = "abm.db"`; `db.init(data_dir) -> sqlite3.Connection`; `db.is_ready() -> bool`; `db.conn() -> sqlite3.Connection`; `db.tx()` context manager (yield connessione; commit all'uscita del livello più esterno, rollback su eccezione); `db.migrate(name: str, statements: list[str]) -> bool` (True se applicata, False se già presente in `schema_migrations`); `db.backup_to(path) -> str`; `db.close()`.

- [ ] **Step 1: Scrivere i test**

```python
# test/test_db.py
"""db.py: connessione unica, tx annidate, migrazioni idempotenti, backup."""
import sqlite3
import threading

import pytest

import db


@pytest.fixture
def dbenv(tmp_path):
    db.init(tmp_path)
    yield tmp_path
    db.close()


def test_init_creates_file_and_wal(dbenv):
    assert (dbenv / db.DB_FILENAME).exists()
    assert db.is_ready()
    mode = db.conn().execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"
    fk = db.conn().execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1


def test_conn_before_init_raises():
    db.close()
    assert not db.is_ready()
    with pytest.raises(RuntimeError):
        db.conn()


def test_migrate_is_idempotent(dbenv):
    stmts = ["CREATE TABLE t1 (id INTEGER PRIMARY KEY, v TEXT)"]
    assert db.migrate("t1_v1", stmts) is True
    assert db.migrate("t1_v1", stmts) is False
    names = [r[0] for r in db.conn().execute("SELECT name FROM schema_migrations")]
    assert names == ["t1_v1"]


def test_migrate_rolls_back_on_error(dbenv):
    with pytest.raises(sqlite3.OperationalError):
        db.migrate("bad", ["CREATE TABLE ok1 (id INTEGER)", "THIS IS NOT SQL"])
    tables = [r[0] for r in db.conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='ok1'")]
    assert tables == []
    assert db.conn().execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_tx_commit_and_rollback(dbenv):
    db.migrate("t2", ["CREATE TABLE t2 (v TEXT)"])
    with db.tx() as c:
        c.execute("INSERT INTO t2 VALUES ('a')")
    with pytest.raises(ValueError):
        with db.tx() as c:
            c.execute("INSERT INTO t2 VALUES ('b')")
            raise ValueError("boom")
    rows = [r[0] for r in db.conn().execute("SELECT v FROM t2 ORDER BY v")]
    assert rows == ["a"]


def test_tx_nested_commits_once_at_outer_level(dbenv):
    db.migrate("t3", ["CREATE TABLE t3 (v TEXT)"])
    with pytest.raises(ValueError):
        with db.tx() as c:
            c.execute("INSERT INTO t3 VALUES ('outer')")
            with db.tx() as c2:
                c2.execute("INSERT INTO t3 VALUES ('inner')")
            raise ValueError("after inner")
    assert db.conn().execute("SELECT COUNT(*) FROM t3").fetchone()[0] == 0
    with db.tx() as c:
        c.execute("INSERT INTO t3 VALUES ('x')")
        with db.tx() as c2:
            c2.execute("INSERT INTO t3 VALUES ('y')")
    assert db.conn().execute("SELECT COUNT(*) FROM t3").fetchone()[0] == 2


def test_tx_serializes_threads(dbenv):
    db.migrate("t4", ["CREATE TABLE t4 (n INTEGER)", "INSERT INTO t4 VALUES (0)"])

    def worker():
        for _ in range(100):
            with db.tx() as c:
                n = c.execute("SELECT n FROM t4").fetchone()[0]
                c.execute("UPDATE t4 SET n=?", (n + 1,))

    ts = [threading.Thread(target=worker) for _ in range(4)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert db.conn().execute("SELECT n FROM t4").fetchone()[0] == 400


def test_backup_to_produces_openable_copy(dbenv, tmp_path):
    db.migrate("t5", ["CREATE TABLE t5 (v TEXT)", "INSERT INTO t5 VALUES ('k')"])
    dest = tmp_path / "copy.db"
    out = db.backup_to(dest)
    assert out == str(dest)
    other = sqlite3.connect(str(dest))
    try:
        assert other.execute("SELECT v FROM t5").fetchone()[0] == "k"
    finally:
        other.close()
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_db.py -v --tb=short`
Expected: FAIL con `ModuleNotFoundError: No module named 'db'`

- [ ] **Step 3: Implementare `db.py`**

```python
# db.py
"""Accesso SQLite condiviso dell'app (modulo foglia, sola stdlib).

Un solo file `abm.db` in ABM_DATA_DIR, una sola connessione condivisa fra i
thread (check_same_thread=False) serializzata da un RLock di processo.
`tx()` e' annidabile: solo il livello piu' esterno apre BEGIN IMMEDIATE e
chiude con COMMIT/ROLLBACK. Le migrazioni sono per nome (tabella
`schema_migrations`), cosi' un secondo modulo puo' aggiungere le sue senza
toccare un contatore globale.
"""
import contextlib
import os
import sqlite3
import threading
import time

DB_FILENAME = "abm.db"

_conn = None
_path = None
_lock = threading.RLock()
_depth = 0


def init(data_dir):
    """Apre (o crea) il DB in data_dir e prepara la tabella delle migrazioni."""
    global _conn, _path
    os.makedirs(str(data_dir), exist_ok=True)
    _path = os.path.join(str(data_dir), DB_FILENAME)
    c = sqlite3.connect(_path, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations "
        "(name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)"
    )
    _conn = c
    return c


def is_ready():
    return _conn is not None


def conn():
    if _conn is None:
        raise RuntimeError("db.init() non chiamata")
    return _conn


def path():
    return _path


@contextlib.contextmanager
def tx():
    """Transazione annidabile: commit/rollback solo al livello esterno."""
    global _depth
    with _lock:
        c = conn()
        outer = _depth == 0
        if outer:
            c.execute("BEGIN IMMEDIATE")
        _depth += 1
        try:
            yield c
        except BaseException:
            _depth -= 1
            if outer:
                c.execute("ROLLBACK")
            raise
        else:
            _depth -= 1
            if outer:
                c.execute("COMMIT")


def migrate(name, statements):
    """Applica `statements` una sola volta, sotto il nome `name`.

    Ritorna True se applicata ora, False se gia' registrata.
    """
    with tx() as c:
        row = c.execute(
            "SELECT 1 FROM schema_migrations WHERE name=?", (name,)
        ).fetchone()
        if row is not None:
            return False
        for s in statements:
            c.execute(s)
        c.execute(
            "INSERT INTO schema_migrations(name, applied_at) VALUES (?, ?)",
            (name, int(time.time())),
        )
        return True


def backup_to(dest_path):
    """Copia consistente del DB in dest_path (API Connection.backup)."""
    with _lock:
        dest = sqlite3.connect(str(dest_path))
        try:
            conn().backup(dest)
        finally:
            dest.close()
    return str(dest_path)


def close():
    global _conn, _depth
    with _lock:
        if _conn is not None:
            try:
                _conn.close()
            except Exception:
                pass
        _conn = None
        _depth = 0
```

- [ ] **Step 4: Compilare ed eseguire i test**

Run: `python -m py_compile db.py`
Run: `pytest test/test_db.py -v --tb=short`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add db.py test/test_db.py
git commit -m "feat(db): modulo SQLite condiviso con tx annidabili e migrazioni per nome"
```

---

### Task 2: `accounts.py` — codici di accesso e sessioni

**Files:**
- Create: `accounts.py`
- Test: `test/test_accounts.py`

**Interfaces:**
- Consumes: `db.tx()`, `db.migrate()`, `db.is_ready()` (Task 1).
- Produces (usati da Task 3, 5, 6, 7):
  - costanti `ENABLE, SESSION_DAYS, CODE_TTL_MIN, CODE_MAX_ATTEMPTS, HISTORY_MONTHS, GRACE_DAYS`, `PURPOSES = ("login", "delete")`
  - `configure(*, payments_path=None, voice_clone_ids_for_email_fn=None, link_voice_fn=None, log_fn=None)`
  - `enabled() -> bool`; `init_schema() -> None`; `email_hash(email) -> str`
  - `request_code(email, purpose="login", lang="en", ip_hash="", ua="", now=None) -> tuple[str, str] | None` (token, code) — `None` se rate limit per-email (3 in 10 min)
  - `verify(token=None, email=None, code=None, purpose="login", now=None) -> tuple[str, dict | None]` con stato in `("ok", "wrong", "expired", "locked", "none")`
  - `open_session(account_id, device_name="", ip_hash="", now=None) -> str` (token in chiaro, mai salvato)
  - `resolve_session(token, now=None) -> dict | None` (account dict + chiave `session_id`)
  - `revoke_session(token) -> bool`; `revoke_all(account_id) -> int`; `sessions_count(account_id, now=None) -> int`
  - `get(account_id) -> dict | None`; `account_for_email(email) -> dict | None`
  - `adopt_history(account) -> tuple[int, int]` (in questo task ritorna `(0, 0)`; corpo reale in Task 3)
  - account dict: chiavi `id, email, email_hash, lang, plan, plan_until, created_at, last_login_at, deleted_at`

- [ ] **Step 1: Scrivere i test**

```python
# test/test_accounts.py
"""accounts.py: codici magic link, verifica, sessioni."""
import pytest

import accounts
import db


@pytest.fixture
def acct_env(tmp_path, monkeypatch):
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    yield tmp_path
    db.close()


T0 = 1_800_000_000


def test_request_code_returns_token_and_six_digits(acct_env):
    out = accounts.request_code("Mario@Example.com", "login", "it", now=T0)
    assert out is not None
    token, code = out
    assert len(token) >= 40
    assert len(code) == 6 and code.isdigit()
    row = db.conn().execute("SELECT * FROM auth_codes").fetchone()
    assert row["email"] == "mario@example.com"
    assert row["purpose"] == "login"
    assert row["lang"] == "it"
    assert row["expires_at"] == T0 + accounts.CODE_TTL_MIN * 60
    assert token not in row["token_hash"]
    assert code not in row["code_hash"]


def test_request_code_per_email_rate_limit(acct_env):
    for i in range(3):
        assert accounts.request_code("a@b.it", now=T0 + i) is not None
    assert accounts.request_code("a@b.it", now=T0 + 3) is None
    assert accounts.request_code("other@b.it", now=T0 + 3) is not None
    assert accounts.request_code("a@b.it", now=T0 + 601) is not None


def test_request_code_rejects_unknown_purpose(acct_env):
    with pytest.raises(ValueError):
        accounts.request_code("a@b.it", purpose="reset")


def test_verify_by_token_creates_account_and_consumes(acct_env):
    token, _ = accounts.request_code("a@b.it", "login", "fr", now=T0)
    status, acct = accounts.verify(token=token, now=T0 + 5)
    assert status == "ok"
    assert acct["email"] == "a@b.it"
    assert acct["lang"] == "fr"
    assert acct["plan"] == "free"
    assert acct["last_login_at"] == T0 + 5
    status2, acct2 = accounts.verify(token=token, now=T0 + 6)
    assert (status2, acct2) == ("none", None)


def test_verify_by_code_ok_and_wrong_then_locked(acct_env):
    _, code = accounts.request_code("a@b.it", now=T0)
    for _ in range(5):
        status, acct = accounts.verify(email="A@B.IT", code="000000" if code != "000000" else "111111", now=T0 + 1)
        assert (status, acct) == ("wrong", None)
    status, acct = accounts.verify(email="a@b.it", code=code, now=T0 + 2)
    assert (status, acct) == ("locked", None)


def test_verify_by_code_success(acct_env):
    _, code = accounts.request_code("a@b.it", now=T0)
    status, acct = accounts.verify(email="a@b.it", code=code, now=T0 + 1)
    assert status == "ok"
    assert acct["email"] == "a@b.it"


def test_verify_expired(acct_env):
    token, code = accounts.request_code("a@b.it", now=T0)
    assert accounts.verify(token=token, now=T0 + accounts.CODE_TTL_MIN * 60 + 1) == ("expired", None)
    assert accounts.verify(email="a@b.it", code=code, now=T0 + accounts.CODE_TTL_MIN * 60 + 1) == ("expired", None)


def test_verify_none_for_unknown(acct_env):
    assert accounts.verify(token="nope") == ("none", None)
    assert accounts.verify(email="x@y.it", code="123456") == ("none", None)


def test_verify_uses_latest_code_for_email(acct_env):
    _, code1 = accounts.request_code("a@b.it", now=T0)
    _, code2 = accounts.request_code("a@b.it", now=T0 + 1)
    assert accounts.verify(email="a@b.it", code=code2, now=T0 + 2)[0] == "ok"
    assert accounts.verify(email="a@b.it", code=code1, now=T0 + 3)[0] in ("none", "wrong")


def test_verify_login_existing_account_updates_lang_and_last_login(acct_env):
    token, _ = accounts.request_code("a@b.it", "login", "it", now=T0)
    _, first = accounts.verify(token=token, now=T0 + 1)
    token2, _ = accounts.request_code("a@b.it", "login", "de", now=T0 + 10)
    status, again = accounts.verify(token=token2, now=T0 + 11)
    assert status == "ok"
    assert again["id"] == first["id"]
    assert again["lang"] == "de"
    assert again["last_login_at"] == T0 + 11
    assert db.conn().execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_verify_delete_purpose_requires_account(acct_env):
    token, _ = accounts.request_code("ghost@b.it", "delete", now=T0)
    assert accounts.verify(token=token, purpose="delete", now=T0 + 1) == ("none", None)
    tl, _ = accounts.request_code("a@b.it", "login", now=T0)
    accounts.verify(token=tl, now=T0 + 1)
    td, _ = accounts.request_code("a@b.it", "delete", now=T0 + 2)
    status, acct = accounts.verify(token=td, purpose="delete", now=T0 + 3)
    assert status == "ok" and acct["email"] == "a@b.it"


def test_verify_purpose_must_match_token(acct_env):
    tl, _ = accounts.request_code("a@b.it", "login", now=T0)
    assert accounts.verify(token=tl, purpose="delete", now=T0 + 1) == ("none", None)


def _login(email, now=T0):
    token, _ = accounts.request_code(email, "login", now=now)
    return accounts.verify(token=token, now=now + 1)[1]


def test_session_open_resolve_revoke(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], device_name="Chrome", ip_hash="abcd", now=T0)
    assert len(tok) >= 40
    stored = db.conn().execute("SELECT id, device_name FROM sessions").fetchone()
    assert stored["id"] != tok and stored["device_name"] == "Chrome"
    res = accounts.resolve_session(tok, now=T0 + 10)
    assert res["email"] == "a@b.it" and res["session_id"] == stored["id"]
    assert accounts.sessions_count(acct["id"], now=T0 + 10) == 1
    assert accounts.revoke_session(tok) is True
    assert accounts.resolve_session(tok, now=T0 + 11) is None
    assert accounts.revoke_session(tok) is False
    assert accounts.resolve_session("", now=T0) is None
    assert accounts.resolve_session("garbage", now=T0) is None


def test_session_expires_after_session_days(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], now=T0)
    assert accounts.resolve_session(tok, now=T0 + accounts.SESSION_DAYS * 86400 - 1) is not None
    assert accounts.resolve_session(tok, now=T0 + accounts.SESSION_DAYS * 86400 + 1) is None


def test_session_rolling_renewal_only_after_one_hour(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], now=T0)
    accounts.resolve_session(tok, now=T0 + 100)
    row = db.conn().execute("SELECT last_seen_at, expires_at FROM sessions").fetchone()
    assert row["last_seen_at"] == T0
    accounts.resolve_session(tok, now=T0 + 3601)
    row = db.conn().execute("SELECT last_seen_at, expires_at FROM sessions").fetchone()
    assert row["last_seen_at"] == T0 + 3601
    assert row["expires_at"] == T0 + 3601 + accounts.SESSION_DAYS * 86400


def test_revoke_all(acct_env):
    acct = _login("a@b.it")
    t1 = accounts.open_session(acct["id"], now=T0)
    t2 = accounts.open_session(acct["id"], now=T0)
    assert accounts.sessions_count(acct["id"], now=T0) == 2
    assert accounts.revoke_all(acct["id"]) == 2
    assert accounts.resolve_session(t1, now=T0) is None
    assert accounts.resolve_session(t2, now=T0) is None
    assert accounts.sessions_count(acct["id"], now=T0) == 0


def test_get_and_account_for_email(acct_env):
    acct = _login("a@b.it")
    assert accounts.get(acct["id"])["email"] == "a@b.it"
    assert accounts.account_for_email("A@B.it")["id"] == acct["id"]
    assert accounts.get("missing") is None
    assert accounts.account_for_email("no@b.it") is None


def test_enabled_requires_flag_and_db(acct_env, monkeypatch):
    assert accounts.enabled() is True
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert accounts.enabled() is False
    monkeypatch.setattr(accounts, "ENABLE", True)
    db.close()
    assert accounts.enabled() is False


def test_email_hash_normalizes(acct_env):
    assert accounts.email_hash(" A@B.it ") == accounts.email_hash("a@b.it")
    assert len(accounts.email_hash("a@b.it")) == 64
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_accounts.py -v --tb=short`
Expected: FAIL con `ModuleNotFoundError: No module named 'accounts'`

- [ ] **Step 3: Implementare `accounts.py` (codici + sessioni)**

```python
# accounts.py
"""Account opzionali: magic link + codice a 6 cifre, sessioni, storico job.

Modulo foglia: dipende solo da `db` e dalla stdlib. Lo stato dell'app
(percorso di `_payments.json`, funzioni di voice_clone, logger) arriva via
`configure()`. Nessuna email in chiaro nei log: usare `email_hash()`.
"""
import hashlib
import hmac
import json
import os
import secrets
import time

import db


def _env_int(name, default):
    try:
        return int(os.environ.get(name, "") or default)
    except ValueError:
        return default


ENABLE = os.environ.get("ABM_ACCOUNT_ENABLE", "1").strip().lower() not in ("0", "false", "no", "off")
SESSION_DAYS = _env_int("ABM_ACCOUNT_SESSION_DAYS", 90)
CODE_TTL_MIN = _env_int("ABM_ACCOUNT_CODE_TTL_MIN", 10)
CODE_MAX_ATTEMPTS = _env_int("ABM_ACCOUNT_CODE_MAX_ATTEMPTS", 5)
HISTORY_MONTHS = _env_int("ABM_ACCOUNT_HISTORY_MONTHS", 24)
GRACE_DAYS = _env_int("ABM_ACCOUNT_GRACE_DAYS", 90)

PURPOSES = ("login", "delete")
EMAIL_RATE_MAX = 3            # richieste di codice per email ...
EMAIL_RATE_WINDOW_SEC = 600   # ... in questa finestra
SESSION_TOUCH_SEC = 3600      # rinnovo rolling solo oltre quest'inattivita'
JOB_STATUSES = ("running", "done", "error", "cancelled")

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS accounts (
        id TEXT PRIMARY KEY,
        email TEXT NOT NULL UNIQUE,
        email_hash TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT 'en',
        plan TEXT NOT NULL DEFAULT 'free',
        plan_until INTEGER,
        created_at INTEGER NOT NULL,
        last_login_at INTEGER,
        deleted_at INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES accounts(id),
        created_at INTEGER NOT NULL,
        last_seen_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        revoked_at INTEGER,
        device_name TEXT NOT NULL DEFAULT '',
        ip_hash TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS ix_sessions_account ON sessions(account_id)",
    """CREATE TABLE IF NOT EXISTS auth_codes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        purpose TEXT NOT NULL,
        token_hash TEXT NOT NULL UNIQUE,
        code_hash TEXT NOT NULL,
        lang TEXT NOT NULL DEFAULT 'en',
        created_at INTEGER NOT NULL,
        expires_at INTEGER NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        consumed_at INTEGER,
        ip_hash TEXT NOT NULL DEFAULT '',
        ua TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX IF NOT EXISTS ix_auth_codes_email ON auth_codes(email, created_at)",
    """CREATE TABLE IF NOT EXISTS account_jobs (
        job_id TEXT PRIMARY KEY,
        account_id TEXT NOT NULL REFERENCES accounts(id),
        created_at INTEGER NOT NULL,
        kind TEXT NOT NULL,
        book_title TEXT NOT NULL DEFAULT '',
        output_format TEXT NOT NULL DEFAULT '',
        voice TEXT NOT NULL DEFAULT '',
        lang TEXT NOT NULL DEFAULT '',
        paid_eur REAL NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'running',
        source TEXT NOT NULL DEFAULT 'forced',
        download_token TEXT NOT NULL DEFAULT '',
        updated_at INTEGER NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS ix_account_jobs_account ON account_jobs(account_id, created_at DESC)",
]

_payments_path = None
_voice_ids_for_email = None
_link_voice = None
_log = print


def configure(*, payments_path=None, voice_clone_ids_for_email_fn=None,
              link_voice_fn=None, log_fn=None):
    global _payments_path, _voice_ids_for_email, _link_voice, _log
    if payments_path is not None:
        _payments_path = str(payments_path)
    if voice_clone_ids_for_email_fn is not None:
        _voice_ids_for_email = voice_clone_ids_for_email_fn
    if link_voice_fn is not None:
        _link_voice = link_voice_fn
    if log_fn is not None:
        _log = log_fn


def enabled():
    return bool(ENABLE) and db.is_ready()


def init_schema():
    db.migrate("accounts_v1", SCHEMA)


# ---------------------------------------------------------------- helpers

def _sha(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _norm(email):
    return (email or "").strip().lower()


def email_hash(email):
    return _sha(_norm(email))


def _now(now):
    return int(now if now is not None else time.time())


def _row(r):
    return dict(r) if r is not None else None


# ---------------------------------------------------------------- codes

def request_code(email, purpose="login", lang="en", ip_hash="", ua="", now=None):
    """Genera token (magic link) e codice a 6 cifre per `email`.

    Ritorna (token, code) oppure None se l'email ha gia' chiesto
    EMAIL_RATE_MAX codici nella finestra (risposta neutra a monte).
    """
    if purpose not in PURPOSES:
        raise ValueError("purpose non valido: %r" % (purpose,))
    email = _norm(email)
    now = _now(now)
    with db.tx() as c:
        n = c.execute(
            "SELECT COUNT(*) FROM auth_codes WHERE email=? AND created_at>?",
            (email, now - EMAIL_RATE_WINDOW_SEC),
        ).fetchone()[0]
        if n >= EMAIL_RATE_MAX:
            return None
        token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(10**6):06d}"
        c.execute(
            "INSERT INTO auth_codes(email, purpose, token_hash, code_hash, lang, "
            "created_at, expires_at, attempts, ip_hash, ua) "
            "VALUES (?,?,?,?,?,?,?,0,?,?)",
            (email, purpose, _sha(token), _sha(email + ":" + code),
             (lang or "en")[:8], now, now + CODE_TTL_MIN * 60,
             ip_hash or "", (ua or "")[:200]),
        )
    return token, code


def _login_or_get(c, email, lang, purpose, now):
    row = c.execute("SELECT * FROM accounts WHERE email=?", (email,)).fetchone()
    if purpose == "delete":
        if row is None or row["deleted_at"] is not None:
            return None
        return _row(row)
    created = False
    if row is None:
        aid = "ac_" + secrets.token_hex(8)
        c.execute(
            "INSERT INTO accounts(id, email, email_hash, lang, plan, created_at, last_login_at) "
            "VALUES (?,?,?,?,'free',?,?)",
            (aid, email, _sha(email), lang or "en", now, now),
        )
        created = True
    else:
        aid = row["id"]
        c.execute(
            "UPDATE accounts SET lang=?, last_login_at=? WHERE id=?",
            (lang or row["lang"] or "en", now, aid),
        )
    acct = _row(c.execute("SELECT * FROM accounts WHERE id=?", (aid,)).fetchone())
    if created:
        try:
            adopt_history(acct)
        except Exception as e:  # mai bloccare il login per l'adozione
            _log(f"WARNING accounts.adopt_history: {e}")
    return acct


def verify(token=None, email=None, code=None, purpose="login", now=None):
    """Verifica magic link (token) o coppia email+codice.

    Ritorna (stato, account): stato in ok|wrong|expired|locked|none.
    Il codice e' consumato solo su `ok`. Un token consumato vale `none`.
    """
    now = _now(now)
    with db.tx() as c:
        if token:
            row = c.execute(
                "SELECT * FROM auth_codes WHERE token_hash=? AND purpose=?",
                (_sha(token), purpose),
            ).fetchone()
        else:
            row = c.execute(
                "SELECT * FROM auth_codes WHERE email=? AND purpose=? AND consumed_at IS NULL "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (_norm(email), purpose),
            ).fetchone()
        if row is None or row["consumed_at"] is not None:
            return "none", None
        if row["expires_at"] <= now:
            return "expired", None
        if row["attempts"] >= CODE_MAX_ATTEMPTS:
            return "locked", None
        if not token:
            got = _sha(row["email"] + ":" + str(code or "").strip())
            if not hmac.compare_digest(row["code_hash"], got):
                c.execute("UPDATE auth_codes SET attempts=attempts+1 WHERE id=?", (row["id"],))
                return "wrong", None
        acct = _login_or_get(c, row["email"], row["lang"], purpose, now)
        if acct is None:
            return "none", None
        c.execute("UPDATE auth_codes SET consumed_at=? WHERE id=?", (now, row["id"]))
        return "ok", acct


# ---------------------------------------------------------------- sessions

def open_session(account_id, device_name="", ip_hash="", now=None):
    now = _now(now)
    token = secrets.token_urlsafe(32)
    with db.tx() as c:
        c.execute(
            "INSERT INTO sessions(id, account_id, created_at, last_seen_at, expires_at, "
            "device_name, ip_hash) VALUES (?,?,?,?,?,?,?)",
            (_sha(token), account_id, now, now, now + SESSION_DAYS * 86400,
             (device_name or "")[:80], ip_hash or ""),
        )
    return token


def resolve_session(token, now=None):
    """Account della sessione (con `session_id`) o None. Rinnovo rolling."""
    if not token:
        return None
    now = _now(now)
    with db.tx() as c:
        row = c.execute(
            "SELECT s.id AS session_id, s.last_seen_at AS s_last_seen, "
            "s.expires_at AS s_expires, s.revoked_at AS s_revoked, a.* "
            "FROM sessions s JOIN accounts a ON a.id = s.account_id WHERE s.id=?",
            (_sha(token),),
        ).fetchone()
        if row is None or row["s_revoked"] is not None or row["s_expires"] <= now \
                or row["deleted_at"] is not None:
            return None
        if now - row["s_last_seen"] > SESSION_TOUCH_SEC:
            c.execute(
                "UPDATE sessions SET last_seen_at=?, expires_at=? WHERE id=?",
                (now, now + SESSION_DAYS * 86400, row["session_id"]),
            )
        d = dict(row)
        for k in ("s_last_seen", "s_expires", "s_revoked"):
            d.pop(k, None)
        return d


def revoke_session(token):
    if not token:
        return False
    with db.tx() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (int(time.time()), _sha(token)),
        )
        return cur.rowcount > 0


def revoke_all(account_id):
    with db.tx() as c:
        cur = c.execute(
            "UPDATE sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL",
            (int(time.time()), account_id),
        )
        return cur.rowcount


def sessions_count(account_id, now=None):
    now = _now(now)
    with db.tx() as c:
        return c.execute(
            "SELECT COUNT(*) FROM sessions WHERE account_id=? AND revoked_at IS NULL AND expires_at>?",
            (account_id, now),
        ).fetchone()[0]


# ---------------------------------------------------------------- accounts

def get(account_id):
    with db.tx() as c:
        return _row(c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone())


def account_for_email(email):
    with db.tx() as c:
        return _row(c.execute(
            "SELECT * FROM accounts WHERE email=? AND deleted_at IS NULL", (_norm(email),)
        ).fetchone())


# ---------------------------------------------------------------- history (Task 3)

def adopt_history(account):
    """Adozione retroattiva: completata nel Task 3. Qui non fa nulla."""
    return 0, 0
```

- [ ] **Step 4: Compilare ed eseguire i test**

Run: `python -m py_compile accounts.py`
Run: `pytest test/test_accounts.py -v --tb=short`
Expected: 19 PASS

- [ ] **Step 5: Commit**

```bash
git add accounts.py test/test_accounts.py
git commit -m "feat(account): codici magic link e sessioni su SQLite"
```

---

### Task 3: `accounts.py` — storico job, adozione retroattiva, purge, cancellazione

**Files:**
- Modify: `accounts.py` (sostituire lo stub `adopt_history`, aggiungere la sezione history)
- Modify: `voice_clone.py` (dopo `email_has_active_voice`, ~:1145)
- Test: `test/test_accounts.py` (aggiungere), `test/test_voice_clone_account_link.py` (nuovo)

**Interfaces:**
- Consumes: `voice_clone.store()`, `voice_clone._all()`, `voice_clone.email_hash()`.
- Produces:
  - `accounts.record_job(account_id, job_id, *, kind, book_title="", output_format="", voice="", lang="", paid_eur=0.0, source="forced", status="running", created_at=None) -> None` (upsert su `job_id`)
  - `accounts.update_status(job_id, status, download_token="") -> bool` (`canceled` normalizzato in `cancelled`; stati ammessi `running|done|error|cancelled`)
  - `accounts.set_download_token(job_id, token) -> bool`
  - `accounts.attach_if_known(job_id, email, **fields) -> bool` (True solo se esiste un account per `email`; fields = stesse kwargs di `record_job`)
  - `accounts.list_jobs(account_id, page=1, per_page=50) -> tuple[list[dict], int]` (ordinati per `created_at DESC`)
  - `accounts.adopt_history(account) -> tuple[int, int]` (job adottati, voci collegate)
  - `accounts.delete_account(account_id, now=None) -> bool`
  - `accounts.purge_expired(now=None) -> dict` con chiavi `jobs, codes, sessions`
  - `accounts.MONTH_SEC = 2629800`
  - `voice_clone.ids_for_email(email) -> list[str]`; `voice_clone.link_account(clone_id, account_id) -> bool` (True se il record è cambiato)

- [ ] **Step 1: Aggiungere i test in `test/test_accounts.py`**

```python
# --- appendere in fondo a test/test_accounts.py ---
import json


def test_record_job_upsert_and_list(acct_env):
    acct = _login("a@b.it")
    accounts.record_job(acct["id"], "j1", kind="generate", book_title="Libro", output_format="m4b",
                        voice="it-IT-ElsaNeural", lang="it", created_at=T0)
    accounts.record_job(acct["id"], "j2", kind="translate", book_title="Book", created_at=T0 + 10)
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 2
    assert [r["job_id"] for r in rows] == ["j2", "j1"]
    assert rows[1]["status"] == "running" and rows[1]["source"] == "forced"
    accounts.record_job(acct["id"], "j1", kind="generate", book_title="Libro 2", paid_eur=1.5,
                        status="running", created_at=T0)
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 2
    j1 = [r for r in rows if r["job_id"] == "j1"][0]
    assert j1["book_title"] == "Libro 2" and j1["paid_eur"] == 1.5
    assert j1["voice"] == "it-IT-ElsaNeural"  # campo vuoto non sovrascrive


def test_list_jobs_pagination(acct_env):
    acct = _login("a@b.it")
    for i in range(7):
        accounts.record_job(acct["id"], f"j{i}", kind="generate", created_at=T0 + i)
    rows, total = accounts.list_jobs(acct["id"], page=2, per_page=3)
    assert total == 7
    assert [r["job_id"] for r in rows] == ["j3", "j2", "j1"]
    rows, _ = accounts.list_jobs(acct["id"], page=99, per_page=3)
    assert rows == []


def test_update_status_and_token(acct_env):
    acct = _login("a@b.it")
    accounts.record_job(acct["id"], "j1", kind="generate", created_at=T0)
    assert accounts.update_status("j1", "canceled") is True
    assert accounts.list_jobs(acct["id"])[0][0]["status"] == "cancelled"
    assert accounts.update_status("j1", "done", download_token="tok123") is True
    row = accounts.list_jobs(acct["id"])[0][0]
    assert row["status"] == "done" and row["download_token"] == "tok123"
    assert accounts.update_status("j1", "weird") is False
    assert accounts.update_status("missing", "done") is False
    assert accounts.set_download_token("j1", "tok456") is True
    assert accounts.list_jobs(acct["id"])[0][0]["download_token"] == "tok456"
    assert accounts.set_download_token("missing", "x") is False


def test_attach_if_known(acct_env):
    assert accounts.attach_if_known("j1", "nobody@b.it", kind="generate") is False
    acct = _login("a@b.it")
    assert accounts.attach_if_known("j1", "A@B.it", kind="generate", book_title="T", paid_eur=2.0,
                                    created_at=T0) is True
    row = accounts.list_jobs(acct["id"])[0][0]
    assert row["source"] == "payments" and row["paid_eur"] == 2.0 and row["status"] == "running"
    accounts.record_job(acct["id"], "j2", kind="generate", book_title="X", created_at=T0)
    accounts.update_status("j2", "done")
    assert accounts.attach_if_known("j2", "a@b.it", kind="generate", paid_eur=3.0) is True
    j2 = [r for r in accounts.list_jobs(acct["id"])[0] if r["job_id"] == "j2"][0]
    assert j2["paid_eur"] == 3.0 and j2["status"] == "done" and j2["source"] == "forced"
    assert j2["book_title"] == "X"


def test_adopt_history_from_payments_and_voices(acct_env, tmp_path, monkeypatch):
    pays = {
        "O1": {"amount_eur": 2.5, "email": "a@b.it", "job_id": "old1", "captured_at": T0 - 100, "used": True},
        "O2": {"amount_eur": 1.0, "email": "A@B.IT", "job_id": "old2", "captured_at": T0 - 50, "used": False},
        "O3": {"amount_eur": 9.0, "email": "other@b.it", "job_id": "x", "captured_at": T0 - 10},
        "O4": {"amount_eur": 1.0, "email": "a@b.it", "job_id": "", "captured_at": T0 - 5},
        "O5": {"amount_eur": 1.0, "email": "a@b.it", "job_id": "nocap", "captured_at": 0},
    }
    p = tmp_path / "_payments.json"
    p.write_text(json.dumps(pays), encoding="utf-8")
    linked = []
    accounts.configure(
        payments_path=p,
        voice_clone_ids_for_email_fn=lambda email: ["vc_1", "vc_2"] if email == "a@b.it" else [],
        link_voice_fn=lambda cid, aid: linked.append((cid, aid)) or True,
    )
    acct = _login("a@b.it")
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 2
    assert [r["job_id"] for r in rows] == ["old2", "old1"]
    assert rows[0]["source"] == "payments" and rows[0]["status"] == "done"
    assert rows[0]["created_at"] == T0 - 50 and rows[1]["paid_eur"] == 2.5
    assert linked == [("vc_1", acct["id"]), ("vc_2", acct["id"])]
    # idempotente
    assert accounts.adopt_history(acct) == (0, 2)
    assert accounts.list_jobs(acct["id"])[1] == 2


def test_adopt_history_survives_missing_or_broken_payments(acct_env, tmp_path):
    accounts.configure(payments_path=tmp_path / "missing.json")
    acct = _login("a@b.it")
    assert accounts.adopt_history(acct) == (0, 0)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    accounts.configure(payments_path=bad)
    assert accounts.adopt_history(acct) == (0, 0)


def test_delete_account(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], now=T0)
    accounts.record_job(acct["id"], "j1", kind="generate", created_at=T0)
    accounts.request_code("a@b.it", "delete", now=T0 + 1)
    assert accounts.delete_account(acct["id"], now=T0 + 2) is True
    assert accounts.resolve_session(tok, now=T0 + 3) is None
    assert accounts.account_for_email("a@b.it") is None
    assert accounts.list_jobs(acct["id"]) == ([], 0)
    assert db.conn().execute("SELECT COUNT(*) FROM auth_codes WHERE email='a@b.it'").fetchone()[0] == 0
    gone = accounts.get(acct["id"])
    assert gone["deleted_at"] == T0 + 2 and gone["email"].startswith("deleted:")
    assert accounts.delete_account(acct["id"]) is False
    # la stessa email puo' registrarsi di nuovo e cancellarsi di nuovo
    again = _login("a@b.it", now=T0 + 100)
    assert again["id"] != acct["id"]
    assert accounts.delete_account(again["id"], now=T0 + 200) is True


def test_purge_expired(acct_env):
    free = _login("free@b.it")
    paid = _login("paid@b.it")
    lapsed = _login("lapsed@b.it")
    db.conn().execute("UPDATE accounts SET plan='paid', plan_until=NULL WHERE id=?", (paid["id"],))
    db.conn().execute("UPDATE accounts SET plan='paid', plan_until=? WHERE id=?",
                      (T0 - (accounts.GRACE_DAYS + 1) * 86400, lapsed["id"]))
    old = T0 - accounts.HISTORY_MONTHS * accounts.MONTH_SEC - 10
    for a in (free, paid, lapsed):
        accounts.record_job(a["id"], "old_" + a["id"], kind="generate", created_at=old)
        accounts.record_job(a["id"], "new_" + a["id"], kind="generate", created_at=T0 - 10)
    accounts.request_code("free@b.it", now=T0 - 2 * 86400)   # scaduto da >24h
    accounts.request_code("free@b.it", now=T0 - 60)           # ancora vivo
    tok_old = accounts.open_session(free["id"], now=T0 - 200 * 86400)   # scaduta da >30 giorni
    tok_live = accounts.open_session(free["id"], now=T0)
    out = accounts.purge_expired(now=T0)
    assert out == {"jobs": 2, "codes": 1, "sessions": 1}
    assert accounts.list_jobs(free["id"])[1] == 1
    assert accounts.list_jobs(lapsed["id"])[1] == 1
    assert accounts.list_jobs(paid["id"])[1] == 2
    assert accounts.resolve_session(tok_live, now=T0) is not None
    assert db.conn().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert tok_old  # solo per chiarezza: la riga e' stata eliminata
```

- [ ] **Step 2: Scrivere `test/test_voice_clone_account_link.py`**

```python
# test/test_voice_clone_account_link.py
"""voice_clone: collegamento delle voci campionate a un account."""
import pytest

import community_store
import storage_backend
import voice_clone as vc


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    yield


def _voice(vid, email, state="ready"):
    rec = {"id": vid, "state": state, "owner_email": email,
           "owner_email_hash": vc.email_hash(email) if email else None}
    vc.store().add(rec)
    return rec


def test_ids_for_email_matches_hash_case_insensitive():
    _voice("vc_a", "A@B.it")
    _voice("vc_b", "a@b.it", state="deleted")
    _voice("vc_c", "other@b.it")
    _voice("vc_d", None)
    assert sorted(vc.ids_for_email("a@b.it")) == ["vc_a", "vc_b"]
    assert vc.ids_for_email("nobody@b.it") == []


def test_link_account_is_idempotent_and_persists():
    _voice("vc_a", "a@b.it")
    assert vc.link_account("vc_a", "ac_1") is True
    assert vc.store().get("vc_a")["account_id"] == "ac_1"
    assert vc.link_account("vc_a", "ac_1") is False
    assert vc.link_account("vc_missing", "ac_1") is False
```

- [ ] **Step 3: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_accounts.py test/test_voice_clone_account_link.py -v --tb=short`
Expected: i nuovi test FAIL con `AttributeError: module 'accounts' has no attribute 'record_job'` / `'voice_clone' has no attribute 'ids_for_email'`

- [ ] **Step 4: Implementare in `accounts.py` (sostituire la sezione "history (Task 3)")**

```python
# ---------------------------------------------------------------- history

MONTH_SEC = 2629800  # 30.44 giorni


def _load_payments_file():
    if not _payments_path or not os.path.exists(_payments_path):
        return {}
    try:
        with open(_payments_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:  # noqa: BLE001
        _log(f"WARNING accounts: _payments.json non leggibile: {e}")
        return {}
    return data if isinstance(data, dict) else {}


def record_job(account_id, job_id, *, kind, book_title="", output_format="", voice="",
               lang="", paid_eur=0.0, source="forced", status="running", created_at=None):
    """Registra (o aggiorna) un job nello storico dell'account.

    Upsert su job_id: i campi testuali vuoti non sovrascrivono valori gia'
    presenti; paid_eur tiene il massimo; status e source seguono l'ultima
    chiamata (chi registra l'avvio conosce la verita').
    """
    now = int(time.time())
    created = int(created_at if created_at is not None else now)
    with db.tx() as c:
        c.execute(
            "INSERT INTO account_jobs(job_id, account_id, created_at, kind, book_title, "
            "output_format, voice, lang, paid_eur, status, source, download_token, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,'',?) "
            "ON CONFLICT(job_id) DO UPDATE SET "
            "account_id=excluded.account_id, kind=excluded.kind, "
            "book_title=CASE WHEN excluded.book_title<>'' THEN excluded.book_title ELSE account_jobs.book_title END, "
            "output_format=CASE WHEN excluded.output_format<>'' THEN excluded.output_format ELSE account_jobs.output_format END, "
            "voice=CASE WHEN excluded.voice<>'' THEN excluded.voice ELSE account_jobs.voice END, "
            "lang=CASE WHEN excluded.lang<>'' THEN excluded.lang ELSE account_jobs.lang END, "
            "paid_eur=MAX(account_jobs.paid_eur, excluded.paid_eur), "
            "status=excluded.status, source=excluded.source, updated_at=excluded.updated_at",
            (str(job_id), account_id, created, kind or "generate", (book_title or "")[:200],
             output_format or "", voice or "", (lang or "")[:8], float(paid_eur or 0),
             status or "running", source or "forced", now),
        )


def update_status(job_id, status, download_token=""):
    if not enabled():
        return False
    status = "cancelled" if status == "canceled" else status
    if status not in JOB_STATUSES:
        return False
    with db.tx() as c:
        if download_token:
            cur = c.execute(
                "UPDATE account_jobs SET status=?, download_token=?, updated_at=? WHERE job_id=?",
                (status, download_token, int(time.time()), str(job_id)),
            )
        else:
            cur = c.execute(
                "UPDATE account_jobs SET status=?, updated_at=? WHERE job_id=?",
                (status, int(time.time()), str(job_id)),
            )
        return cur.rowcount > 0


def set_download_token(job_id, token):
    if not enabled() or not token:
        return False
    with db.tx() as c:
        cur = c.execute(
            "UPDATE account_jobs SET download_token=?, updated_at=? WHERE job_id=?",
            (token, int(time.time()), str(job_id)),
        )
        return cur.rowcount > 0


def attach_if_known(job_id, email, **fields):
    """Aggancia un job a un account SOLO se l'email ha gia' un account.

    Usato dai pagamenti: un job pagato da un utente non loggato finisce nel
    suo storico se l'account esiste. Se il job e' gia' registrato (forced),
    aggiorna solo importo e campi vuoti, senza toccare status/source.
    """
    if not enabled():
        return False
    acct = account_for_email(email)
    if acct is None:
        return False
    with db.tx() as c:
        row = c.execute("SELECT job_id FROM account_jobs WHERE job_id=?", (str(job_id),)).fetchone()
        if row is None:
            fields.setdefault("source", "payments")
            fields.setdefault("kind", "generate")
            record_job(acct["id"], job_id, **fields)
            return True
        c.execute(
            "UPDATE account_jobs SET paid_eur=MAX(paid_eur, ?), "
            "book_title=CASE WHEN book_title='' THEN ? ELSE book_title END, "
            "output_format=CASE WHEN output_format='' THEN ? ELSE output_format END, "
            "voice=CASE WHEN voice='' THEN ? ELSE voice END, "
            "lang=CASE WHEN lang='' THEN ? ELSE lang END, updated_at=? WHERE job_id=?",
            (float(fields.get("paid_eur") or 0), (fields.get("book_title") or "")[:200],
             fields.get("output_format") or "", fields.get("voice") or "",
             (fields.get("lang") or "")[:8], int(time.time()), str(job_id)),
        )
        return True


def list_jobs(account_id, page=1, per_page=50):
    page = max(1, int(page or 1))
    per_page = max(1, min(200, int(per_page or 50)))
    with db.tx() as c:
        total = c.execute(
            "SELECT COUNT(*) FROM account_jobs WHERE account_id=?", (account_id,)
        ).fetchone()[0]
        rows = c.execute(
            "SELECT * FROM account_jobs WHERE account_id=? ORDER BY created_at DESC, job_id DESC "
            "LIMIT ? OFFSET ?",
            (account_id, per_page, (page - 1) * per_page),
        ).fetchall()
    return [dict(r) for r in rows], total


def adopt_history(account):
    """Adozione retroattiva: job pagati (_payments.json, email+job_id) e voci
    campionate con owner_email uguale. Idempotente: INSERT OR IGNORE sui job,
    link_voice ritorna False se gia' collegata."""
    email = _norm(account.get("email"))
    aid = account["id"]
    n_jobs = 0
    pays = _load_payments_file()
    now = int(time.time())
    with db.tx() as c:
        for p in pays.values():
            if not isinstance(p, dict) or _norm(p.get("email")) != email:
                continue
            jid = str(p.get("job_id") or "").strip()
            cap = p.get("captured_at") or 0
            if not jid or not cap:
                continue
            cur = c.execute(
                "INSERT OR IGNORE INTO account_jobs(job_id, account_id, created_at, kind, "
                "book_title, output_format, voice, lang, paid_eur, status, source, "
                "download_token, updated_at) VALUES (?,?,?,'generate','','','','',?,'done',"
                "'payments','',?)",
                (jid, aid, int(float(cap)), float(p.get("amount_eur") or 0), now),
            )
            n_jobs += cur.rowcount
    n_voices = 0
    if _voice_ids_for_email is not None and _link_voice is not None:
        try:
            for cid in _voice_ids_for_email(email):
                if _link_voice(cid, aid):
                    n_voices += 1
        except Exception as e:  # noqa: BLE001
            _log(f"WARNING accounts: collegamento voci fallito: {e}")
    return n_jobs, n_voices


def delete_account(account_id, now=None):
    """Cancellazione self-service: email sostituita da un segnaposto,
    sessioni revocate, storico e codici eliminati. `_payments.json` e le
    voci campionate restano (obblighi fiscali / flusso proprio)."""
    now = _now(now)
    with db.tx() as c:
        row = c.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        if row is None or row["deleted_at"] is not None:
            return False
        c.execute("DELETE FROM account_jobs WHERE account_id=?", (account_id,))
        c.execute("DELETE FROM auth_codes WHERE email=?", (row["email"],))
        c.execute(
            "UPDATE sessions SET revoked_at=? WHERE account_id=? AND revoked_at IS NULL",
            (now, account_id),
        )
        c.execute(
            "UPDATE accounts SET email=?, deleted_at=? WHERE id=?",
            (f"deleted:{row['email_hash'][:16]}:{account_id}", now, account_id),
        )
        return True


def purge_expired(now=None):
    """Retention: storico oltre HISTORY_MONTHS per account free (o con piano
    scaduto da piu' di GRACE_DAYS), codici scaduti da >24h, sessioni
    scadute/revocate da >30 giorni. Ritorna i conteggi."""
    now = _now(now)
    job_cut = now - HISTORY_MONTHS * MONTH_SEC
    grace_cut = now - GRACE_DAYS * 86400
    with db.tx() as c:
        jobs = c.execute(
            "DELETE FROM account_jobs WHERE created_at<? AND account_id IN ("
            "SELECT id FROM accounts WHERE plan='free' "
            "OR (plan_until IS NOT NULL AND plan_until<?))",
            (job_cut, grace_cut),
        ).rowcount
        codes = c.execute(
            "DELETE FROM auth_codes WHERE expires_at<?", (now - 86400,)
        ).rowcount
        sessions = c.execute(
            "DELETE FROM sessions WHERE expires_at<? OR (revoked_at IS NOT NULL AND revoked_at<?)",
            (now - 30 * 86400, now - 30 * 86400),
        ).rowcount
    return {"jobs": jobs, "codes": codes, "sessions": sessions}
```

- [ ] **Step 5: Aggiungere in `voice_clone.py` dopo `email_has_active_voice`**

```python
def ids_for_email(email):
    """Id di tutte le voci (anche terminali) con quell'owner_email: serve
    all'adozione retroattiva dell'account."""
    h = email_hash(email)
    return [rec["id"] for rec in _all()
            if rec.get("id") and rec.get("owner_email_hash") == h]


def link_account(clone_id, account_id):
    """Annota l'account proprietario sul record della voce. True se cambiato."""
    rec = store().get(clone_id)
    if rec is None or rec.get("account_id") == account_id:
        return False
    store().update(clone_id, {"account_id": account_id})
    return True
```

- [ ] **Step 6: Compilare ed eseguire i test**

Run: `python -m py_compile accounts.py`
Run: `python -m py_compile voice_clone.py`
Run: `pytest test/test_accounts.py test/test_voice_clone_account_link.py test/test_voice_clone.py -v --tb=short`
Expected: tutti PASS (27 in test_accounts, 2 nel nuovo file, nessuna regressione in test_voice_clone)

- [ ] **Step 7: Commit**

```bash
git add accounts.py voice_clone.py test/test_accounts.py test/test_voice_clone_account_link.py
git commit -m "feat(account): storico job, adozione retroattiva, purge e cancellazione"
```

---

### Task 4: Email di accesso e di cancellazione

**Files:**
- Create: `i18n/account_emails.json`
- Modify: `email_service.py` (dopo `send_voice_clone_expiring`, ~:880)
- Test: `test/test_account_emails.py`

**Interfaces:**
- Consumes: `email_service._send_email(to_addr, subject, html_body)`, pattern `_vc_send`.
- Produces: `email_service.send_account_code(email, lang, *, code, link_url, purpose, minutes) -> bool` (`purpose` in `login|delete`); `email_service.send_account_deleted(email, lang) -> bool`.

- [ ] **Step 1: Scrivere i test**

```python
# test/test_account_emails.py
"""Email account: codice/magic link e conferma cancellazione, 7 lingue."""
import json
from pathlib import Path

import pytest

import email_service

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
KEYS = ["brand", "login_subject", "login_body", "delete_subject", "delete_body",
        "deleted_subject", "deleted_body", "footer"]


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subject, body, **kw: box.append((to, subject, body)) or True)
    return box


def test_i18n_file_complete():
    data = json.loads((Path("i18n") / "account_emails.json").read_text(encoding="utf-8"))
    assert sorted(data) == sorted(LANGS)
    for lang in LANGS:
        assert sorted(data[lang]) == sorted(KEYS), lang
        assert "{code}" in data[lang]["login_body"] and "{link_url}" in data[lang]["login_body"]
        assert "{minutes}" in data[lang]["login_body"]
        assert "{code}" in data[lang]["delete_body"] and "{link_url}" in data[lang]["delete_body"]


@pytest.mark.parametrize("lang", LANGS + ["xx"])
def test_send_account_code_login(sent, lang):
    ok = email_service.send_account_code("a@b.it", lang, code="123456",
                                         link_url="https://x.test/auth/T0K", purpose="login",
                                         minutes=10)
    assert ok is True
    to, subject, body = sent[0]
    assert to == "a@b.it"
    assert "123456" in body and "https://x.test/auth/T0K" in body and "10" in body


def test_send_account_code_delete_uses_delete_texts(sent):
    email_service.send_account_code("a@b.it", "it", code="654321", link_url="https://x/auth/D",
                                    purpose="delete", minutes=10)
    _, subject, body = sent[0]
    data = json.loads((Path("i18n") / "account_emails.json").read_text(encoding="utf-8"))
    assert subject == data["it"]["delete_subject"]
    assert "654321" in body


def test_send_account_code_escapes_values(sent):
    email_service.send_account_code("a@b.it", "en", code="<b>1</b>", link_url="https://x/auth/T",
                                    purpose="login", minutes=10)
    assert "<b>1</b>" not in sent[0][2] and "&lt;b&gt;" in sent[0][2]


def test_send_account_code_rejects_bad_purpose(sent):
    assert email_service.send_account_code("a@b.it", "en", code="1", link_url="u",
                                           purpose="reset", minutes=10) is False
    assert sent == []


def test_send_account_deleted(sent):
    assert email_service.send_account_deleted("a@b.it", "de") is True
    assert sent[0][0] == "a@b.it"


def test_send_returns_false_on_smtp_error(monkeypatch):
    monkeypatch.setattr(email_service, "_send_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp")))
    assert email_service.send_account_code("a@b.it", "en", code="1", link_url="u",
                                           purpose="login", minutes=10) is False
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_account_emails.py -v --tb=short`
Expected: FAIL (`FileNotFoundError` per il JSON, `AttributeError` per `send_account_code`)

- [ ] **Step 3: Creare `i18n/account_emails.json`**

Sette lingue con le stesse 8 chiavi. Placeholder: `{code}`, `{link_url}`, `{minutes}` in `login_body`/`delete_body`. Nessun nome di provider. Contenuto:

```json
{
  "it": {
    "brand": "Audiobook Maker",
    "login_subject": "Il tuo codice di accesso: {code}",
    "login_body": "<p>Per accedere al tuo account Audiobook Maker inserisci questo codice:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>oppure apri il link: <a href=\"{link_url}\">{link_url}</a></p><p>Il codice vale {minutes} minuti e si usa una volta sola. Se non hai chiesto tu l'accesso, ignora questa email.</p>",
    "delete_subject": "Conferma la cancellazione del tuo account: {code}",
    "delete_body": "<p>Hai chiesto di cancellare il tuo account Audiobook Maker. Per confermare inserisci questo codice:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>oppure apri il link: <a href=\"{link_url}\">{link_url}</a></p><p>Il codice vale {minutes} minuti. Lo storico dei job e le sessioni verranno eliminati; i file gia' consegnati restano scaricabili dai link ricevuti via email fino alla loro scadenza.</p><p>Se non sei stato tu, ignora questa email: non succede nulla.</p>",
    "deleted_subject": "Account cancellato",
    "deleted_body": "<p>Il tuo account Audiobook Maker e' stato cancellato. Puoi continuare a usare il servizio senza account, o crearne uno nuovo in qualunque momento con la stessa email.</p>",
    "footer": "<p style=\"color:#888;font-size:.9em\">Audiobook Maker</p>"
  },
  "en": {
    "brand": "Audiobook Maker",
    "login_subject": "Your sign-in code: {code}",
    "login_body": "<p>To sign in to your Audiobook Maker account enter this code:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>or open the link: <a href=\"{link_url}\">{link_url}</a></p><p>The code is valid for {minutes} minutes and works once. If you did not request it, ignore this email.</p>",
    "delete_subject": "Confirm your account deletion: {code}",
    "delete_body": "<p>You asked to delete your Audiobook Maker account. To confirm, enter this code:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>or open the link: <a href=\"{link_url}\">{link_url}</a></p><p>The code is valid for {minutes} minutes. Your job history and sessions will be removed; files already delivered stay downloadable from the links you received by email until they expire.</p><p>If this was not you, ignore this email: nothing happens.</p>",
    "deleted_subject": "Account deleted",
    "deleted_body": "<p>Your Audiobook Maker account has been deleted. You can keep using the service without an account, or create a new one at any time with the same email.</p>",
    "footer": "<p style=\"color:#888;font-size:.9em\">Audiobook Maker</p>"
  },
  "fr": {
    "brand": "Audiobook Maker",
    "login_subject": "Votre code de connexion : {code}",
    "login_body": "<p>Pour vous connecter à votre compte Audiobook Maker, saisissez ce code :</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>ou ouvrez le lien : <a href=\"{link_url}\">{link_url}</a></p><p>Le code est valable {minutes} minutes et ne sert qu'une fois. Si vous n'avez rien demandé, ignorez cet e-mail.</p>",
    "delete_subject": "Confirmez la suppression de votre compte : {code}",
    "delete_body": "<p>Vous avez demandé la suppression de votre compte Audiobook Maker. Pour confirmer, saisissez ce code :</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>ou ouvrez le lien : <a href=\"{link_url}\">{link_url}</a></p><p>Le code est valable {minutes} minutes. L'historique des travaux et les sessions seront supprimés ; les fichiers déjà livrés restent téléchargeables depuis les liens reçus par e-mail jusqu'à leur expiration.</p><p>Si ce n'était pas vous, ignorez cet e-mail : rien ne se passe.</p>",
    "deleted_subject": "Compte supprimé",
    "deleted_body": "<p>Votre compte Audiobook Maker a été supprimé. Vous pouvez continuer à utiliser le service sans compte, ou en créer un nouveau à tout moment avec la même adresse.</p>",
    "footer": "<p style=\"color:#888;font-size:.9em\">Audiobook Maker</p>"
  },
  "es": {
    "brand": "Audiobook Maker",
    "login_subject": "Tu código de acceso: {code}",
    "login_body": "<p>Para acceder a tu cuenta de Audiobook Maker introduce este código:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>o abre el enlace: <a href=\"{link_url}\">{link_url}</a></p><p>El código vale {minutes} minutos y se usa una sola vez. Si no lo has pedido tú, ignora este correo.</p>",
    "delete_subject": "Confirma la eliminación de tu cuenta: {code}",
    "delete_body": "<p>Has pedido eliminar tu cuenta de Audiobook Maker. Para confirmar, introduce este código:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>o abre el enlace: <a href=\"{link_url}\">{link_url}</a></p><p>El código vale {minutes} minutos. El historial de trabajos y las sesiones se eliminarán; los archivos ya entregados siguen descargables desde los enlaces recibidos por correo hasta su caducidad.</p><p>Si no has sido tú, ignora este correo: no pasa nada.</p>",
    "deleted_subject": "Cuenta eliminada",
    "deleted_body": "<p>Tu cuenta de Audiobook Maker ha sido eliminada. Puedes seguir usando el servicio sin cuenta o crear una nueva en cualquier momento con el mismo correo.</p>",
    "footer": "<p style=\"color:#888;font-size:.9em\">Audiobook Maker</p>"
  },
  "de": {
    "brand": "Audiobook Maker",
    "login_subject": "Dein Anmeldecode: {code}",
    "login_body": "<p>Gib diesen Code ein, um dich bei deinem Audiobook-Maker-Konto anzumelden:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>oder öffne den Link: <a href=\"{link_url}\">{link_url}</a></p><p>Der Code gilt {minutes} Minuten und nur einmal. Falls du ihn nicht angefordert hast, ignoriere diese E-Mail.</p>",
    "delete_subject": "Bestätige die Löschung deines Kontos: {code}",
    "delete_body": "<p>Du hast die Löschung deines Audiobook-Maker-Kontos angefordert. Gib zur Bestätigung diesen Code ein:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>oder öffne den Link: <a href=\"{link_url}\">{link_url}</a></p><p>Der Code gilt {minutes} Minuten. Auftragsverlauf und Sitzungen werden gelöscht; bereits gelieferte Dateien bleiben über die per E-Mail erhaltenen Links bis zu deren Ablauf herunterladbar.</p><p>Falls das nicht du warst, ignoriere diese E-Mail: es passiert nichts.</p>",
    "deleted_subject": "Konto gelöscht",
    "deleted_body": "<p>Dein Audiobook-Maker-Konto wurde gelöscht. Du kannst den Dienst ohne Konto weiter nutzen oder jederzeit mit derselben E-Mail ein neues anlegen.</p>",
    "footer": "<p style=\"color:#888;font-size:.9em\">Audiobook Maker</p>"
  },
  "zh": {
    "brand": "Audiobook Maker",
    "login_subject": "您的登录验证码：{code}",
    "login_body": "<p>请输入以下验证码登录您的 Audiobook Maker 账户：</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>或打开链接：<a href=\"{link_url}\">{link_url}</a></p><p>验证码 {minutes} 分钟内有效，仅可使用一次。如果不是您本人操作，请忽略此邮件。</p>",
    "delete_subject": "确认删除您的账户：{code}",
    "delete_body": "<p>您申请删除 Audiobook Maker 账户。请输入以下验证码确认：</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>或打开链接：<a href=\"{link_url}\">{link_url}</a></p><p>验证码 {minutes} 分钟内有效。任务历史和会话将被删除；已交付的文件在过期前仍可通过邮件中的链接下载。</p><p>如果不是您本人操作，请忽略此邮件，不会有任何变化。</p>",
    "deleted_subject": "账户已删除",
    "deleted_body": "<p>您的 Audiobook Maker 账户已删除。您可以继续无账户使用服务，也可以随时用同一邮箱重新创建账户。</p>",
    "footer": "<p style=\"color:#888;font-size:.9em\">Audiobook Maker</p>"
  },
  "hi": {
    "brand": "Audiobook Maker",
    "login_subject": "आपका साइन-इन कोड: {code}",
    "login_body": "<p>अपने Audiobook Maker खाते में साइन इन करने के लिए यह कोड दर्ज करें:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>या यह लिंक खोलें: <a href=\"{link_url}\">{link_url}</a></p><p>कोड {minutes} मिनट तक मान्य है और केवल एक बार काम करता है। यदि आपने इसका अनुरोध नहीं किया, तो इस ईमेल को अनदेखा करें।</p>",
    "delete_subject": "अपने खाते को हटाने की पुष्टि करें: {code}",
    "delete_body": "<p>आपने अपना Audiobook Maker खाता हटाने का अनुरोध किया है। पुष्टि के लिए यह कोड दर्ज करें:</p><p style=\"font-size:1.6em;letter-spacing:.2em\"><strong>{code}</strong></p><p>या यह लिंक खोलें: <a href=\"{link_url}\">{link_url}</a></p><p>कोड {minutes} मिनट तक मान्य है। कार्य इतिहास और सत्र हटा दिए जाएँगे; पहले से डिलीवर की गई फ़ाइलें ईमेल में मिले लिंक से उनकी समाप्ति तक डाउनलोड की जा सकती हैं।</p><p>यदि यह आप नहीं थे, तो इस ईमेल को अनदेखा करें: कुछ नहीं होगा।</p>",
    "deleted_subject": "खाता हटा दिया गया",
    "deleted_body": "<p>आपका Audiobook Maker खाता हटा दिया गया है। आप बिना खाते के सेवा का उपयोग जारी रख सकते हैं, या उसी ईमेल से कभी भी नया खाता बना सकते हैं।</p>",
    "footer": "<p style=\"color:#888;font-size:.9em\">Audiobook Maker</p>"
  }
}
```

- [ ] **Step 4: Aggiungere in `email_service.py` (dopo `send_voice_clone_expiring`)**

```python
# ---------------------------------------------------------------------------
# Account: codice di accesso / cancellazione (i18n/account_emails.json)
# ---------------------------------------------------------------------------

_ACCT_I18N = {}
try:
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "i18n",
                           "account_emails.json"), encoding="utf-8") as _f:
        _ACCT_I18N = json.load(_f)
except Exception as _e:      # noqa: BLE001
    print(f"WARNING: i18n/account_emails.json non caricato: {_e}", flush=True)


def _acct_t(lang):
    return _ACCT_I18N.get((lang or "").split("-")[0].lower()) or _ACCT_I18N.get("en") or {}


def _acct_send(email, lang, subject_key, body_key, **values):
    t = _acct_t(lang)
    if not t or not email:
        return False
    safe = {k: (v if k.endswith("_url") else html.escape(str(v))) for k, v in values.items()}
    try:
        subject = t[subject_key].format(**safe)
        body = t[body_key].format(**safe) + t.get("footer", "")
        return bool(_send_email(email, subject, body))
    except Exception as e:      # noqa: BLE001
        print(f"[email] account {subject_key} non inviata: {type(e).__name__}: {e}", flush=True)
        return False


def send_account_code(email, lang, *, code, link_url, purpose, minutes):
    """Codice a 6 cifre + magic link. `purpose`: login | delete."""
    if purpose not in ("login", "delete"):
        return False
    return _acct_send(email, lang, f"{purpose}_subject", f"{purpose}_body",
                      code=code, link_url=link_url, minutes=int(minutes))


def send_account_deleted(email, lang):
    return _acct_send(email, lang, "deleted_subject", "deleted_body")
```

- [ ] **Step 5: Compilare ed eseguire i test**

Run: `python -m py_compile email_service.py`
Run: `python -c "import json; json.load(open('i18n/account_emails.json', encoding='utf-8'))"`
Run: `pytest test/test_account_emails.py -v --tb=short`
Expected: 14 PASS

- [ ] **Step 6: Commit**

```bash
git add i18n/account_emails.json email_service.py test/test_account_emails.py
git commit -m "feat(account): email di accesso e di cancellazione in sette lingue"
```

---

### Task 5: Wiring di avvio, helper di sessione e route di autenticazione

**Files:**
- Create: `account_page.py` (solo le due pagine di conferma: login e cancellazione; la pagina storico arriva nel Task 6)
- Create: `i18n/account_pages.json`
- Modify: `audiobook_app.py` — import (dopo `import pending_jobs` :149), init all'avvio (dopo `voice_clone_audio.init(_DATA_DIR)` :393), nuova sezione helper + route (inserire subito dopo `_hash_ip` :~10736)
- Test: `test/test_account_routes.py`

**Interfaces:**
- Consumes: `accounts.*` (Task 2-3), `email_service.send_account_code` (Task 4), `voice_clone.ids_for_email` / `link_account` (Task 3), esistenti `_ip_rl_check`, `_client_ip`, `_hash_ip`, `_get_browser_lang`, `_smtp_available`, `BASE_URL`, `_log_activity`, `_get_client_id`, `_apply_no_cache`, `_VC_LOGO_SVG`.
- Produces (usati da Task 6, 7):
  - `_ACCOUNT_SESSION_COOKIE = "abm_session"`
  - `_acct_gate() -> Response|None` (None se attivo; altrimenti 404 `account_disabled`)
  - `_acct_err(code, msg, status) -> (Response, int)`
  - `_acct_session_token() -> str` (Bearer prima del cookie)
  - `_current_account() -> dict|None` (cache per-request in `flask.g`)
  - `_acct_set_cookie(resp, token)`, `_acct_clear_cookie(resp)`
  - `_acct_log(op, email, extra="")`
  - `_acct_page_lang() -> str`, `_acct_txt(lang) -> dict`
  - `account_page.render_confirm(t, *, lang, purpose, action_url) -> str` (HTML completo)
  - `account_page.render_error(t, *, lang, status_key) -> str` (`status_key` in `expired|locked|none|wrong`)
  - `account_page.render_deleted(t, *, lang) -> str`
  - `account_page.page_html(t, lang, title, body_html) -> str` (scheletro con CSS, riusato dal Task 6)
  - Route: `POST /api/auth/request`, `GET|POST /auth/<token>`, `POST /api/auth/verify`, `POST /api/auth/logout`, `POST /api/auth/logout_all`, `GET /api/auth/me`

- [ ] **Step 1: Scrivere `test/test_account_routes.py`**

```python
# test/test_account_routes.py
"""Route di autenticazione account: request/verify/logout/me e /auth/<token>."""
import pytest

import accounts
import audiobook_app
import db
import email_service

T0 = 1_800_000_000


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    audiobook_app._ip_rl_buckets.pop("auth_request", None)
    box = []
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: box.append((email, lang, kw)) or True)
    audiobook_app.app.config["TESTING"] = True
    yield box
    db.close()


@pytest.fixture
def client(env):
    return audiobook_app.app.test_client()


def _cookie(resp, name="abm_session"):
    for h in resp.headers.getlist("Set-Cookie"):
        if h.startswith(name + "="):
            return h
    return None


def test_request_sends_code_and_link(client, env):
    r = client.post("/api/auth/request", json={"email": "A@B.it", "lang": "it"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    email, lang, kw = env[0]
    assert email == "a@b.it" and lang == "it" and kw["purpose"] == "login"
    assert kw["link_url"].startswith("https://abm.test/auth/")
    assert kw["minutes"] == accounts.CODE_TTL_MIN and len(kw["code"]) == 6


def test_request_is_neutral_on_bad_email_and_rate_limit(client, env):
    r = client.post("/api/auth/request", json={"email": "not-an-email"})
    assert r.status_code == 400 and r.get_json()["error_code"] == "invalid_email"
    for _ in range(3):
        assert client.post("/api/auth/request", json={"email": "a@b.it"}).status_code == 200
    r = client.post("/api/auth/request", json={"email": "a@b.it"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert len(env) == 3  # la 4a non manda nulla ma risponde uguale


def test_request_ip_rate_limit_429(client, env):
    for i in range(5):
        assert client.post("/api/auth/request", json={"email": f"u{i}@b.it"}).status_code == 200
    r = client.post("/api/auth/request", json={"email": "u9@b.it"})
    assert r.status_code == 429 and r.get_json()["error_code"] == "rate_limited"


def test_disabled_returns_404_and_me_reports_it(client, monkeypatch):
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert client.post("/api/auth/request", json={"email": "a@b.it"}).status_code == 404
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and r.get_json() == {"logged_in": False, "enabled": False}


def test_no_smtp_returns_404(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: False)
    assert client.post("/api/auth/request", json={"email": "a@b.it"}).status_code == 404


def test_verify_by_code_sets_cookie_and_me(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it", "lang": "fr"})
    code = env[0][2]["code"]
    r = client.post("/api/auth/verify", json={"email": "a@b.it", "code": code, "device_name": "Pixel"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["email"] == "a@b.it" and d["lang"] == "fr" and d["plan"] == "free"
    assert "session_token" not in d
    ck = _cookie(r)
    assert ck and "HttpOnly" in ck and "SameSite=Lax" in ck and "Secure" in ck and "Path=/" in ck
    me = client.get("/api/auth/me").get_json()
    assert me["logged_in"] is True and me["email"] == "a@b.it" and me["sessions_count"] == 1


def test_verify_wrong_code_401_with_error_code(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    bad = "000000" if env[0][2]["code"] != "000000" else "111111"
    r = client.post("/api/auth/verify", json={"email": "a@b.it", "code": bad})
    assert r.status_code == 401 and r.get_json()["error_code"] == "wrong"
    r = client.post("/api/auth/verify", json={"email": "zz@b.it", "code": "123456"})
    assert r.status_code == 401 and r.get_json()["error_code"] == "none"


def test_verify_with_mobile_header_returns_session_token(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    code = env[0][2]["code"]
    r = client.post("/api/auth/verify", json={"email": "a@b.it", "code": code},
                    headers={"X-ABM-Cid": "mobile-cid-000001"})
    d = r.get_json()
    assert d["ok"] and d["session_token"]
    me = audiobook_app.app.test_client().get(
        "/api/auth/me", headers={"Authorization": "Bearer " + d["session_token"]}).get_json()
    assert me["logged_in"] is True and me["email"] == "a@b.it"


def test_bearer_has_precedence_over_cookie(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    client.post("/api/auth/verify", json={"email": "a@b.it", "code": env[0][2]["code"]})
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.get_json()["logged_in"] is False


def test_magic_link_get_does_not_consume_post_does(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    link = env[0][2]["link_url"]
    path = link[len("https://abm.test"):]
    r = client.get(path)
    assert r.status_code == 200 and b"<form" in r.data and b"method=\"post\"" in r.data
    assert accounts.account_for_email("a@b.it") is None
    r = client.post(path)
    assert r.status_code == 302 and r.headers["Location"].endswith("/account")
    assert _cookie(r) is not None
    assert accounts.account_for_email("a@b.it") is not None
    r = client.post(path)
    assert r.status_code == 410


def test_magic_link_unknown_token_410_page(client, env):
    r = client.get("/auth/doesnotexist")
    assert r.status_code == 410 and b"<html" in r.data


def test_verify_by_token_json(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    token = env[0][2]["link_url"].rsplit("/", 1)[1]
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200 and r.get_json()["email"] == "a@b.it"


def test_logout_and_logout_all(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    code = env[0][2]["code"]
    client.post("/api/auth/verify", json={"email": "a@b.it", "code": code})
    acct = accounts.account_for_email("a@b.it")
    other = accounts.open_session(acct["id"])
    r = client.post("/api/auth/logout")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert "abm_session=;" in _cookie(r) or "Max-Age=0" in _cookie(r)
    assert client.get("/api/auth/me").get_json()["logged_in"] is False
    assert accounts.resolve_session(other) is not None
    r = audiobook_app.app.test_client().post(
        "/api/auth/logout_all", headers={"Authorization": "Bearer " + other})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "revoked": 1}
    assert accounts.resolve_session(other) is None
    assert client.post("/api/auth/logout_all").status_code == 401


def test_login_logs_activity_with_hashed_sid(client, env, monkeypatch):
    rows = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda sid, fn, op, **kw: rows.append((sid, fn, op)))
    client.post("/api/auth/request", json={"email": "a@b.it"})
    client.post("/api/auth/verify", json={"email": "a@b.it", "code": env[0][2]["code"]})
    assert rows and rows[-1][2] == "ACCOUNT_LOGIN"
    assert rows[-1][0] == "acct-" + accounts.email_hash("a@b.it")[:8]
    assert "a@b.it" not in rows[-1][0] + rows[-1][1]
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_account_routes.py -v --tb=short`
Expected: FAIL (404 sulle route inesistenti / `AttributeError` su `_ip_rl_buckets` esiste già, `send_account_code` esiste dal Task 4; il primo errore sarà lo status 404 di `/api/auth/request`)

- [ ] **Step 3: Creare `i18n/account_pages.json`**

Sette lingue (`en, it, fr, es, de, zh, hi`), stesse chiavi. Le chiavi `history_*` sono usate dal Task 6 e vanno inserite già ora. Contenuto completo (nessuna chiave lasciata in inglese nelle altre lingue):

```json
{
  "en": {
    "brand": "Audiobook Maker",
    "confirm_login_title": "Sign in",
    "confirm_login_p": "Press the button to sign in to your account on this device.",
    "confirm_login_btn": "Sign in",
    "confirm_delete_title": "Delete your account",
    "confirm_delete_p": "Press the button to permanently delete your account. Your job history and sessions will be removed; files already delivered stay downloadable from the links you received by email until they expire.",
    "confirm_delete_btn": "Delete my account",
    "err_expired_title": "Link expired",
    "err_expired_p": "This link is no longer valid. Request a new code from the site.",
    "err_locked_title": "Too many attempts",
    "err_locked_p": "This code has been locked after too many wrong attempts. Request a new one from the site.",
    "err_none_title": "Link not valid",
    "err_none_p": "This link has already been used or does not exist. Request a new code from the site.",
    "err_wrong_title": "Wrong code",
    "err_wrong_p": "The code does not match. Check the email and try again.",
    "deleted_title": "Account deleted",
    "deleted_p": "Your account has been deleted. You can keep using Audiobook Maker without an account.",
    "home": "Back to Audiobook Maker",
    "history_title": "Your audiobooks",
    "history_signed_in_as": "Signed in as",
    "history_empty": "No jobs yet. Everything you generate while signed in will appear here.",
    "history_col_date": "Date",
    "history_col_book": "Book",
    "history_col_kind": "Type",
    "history_col_status": "Status",
    "history_col_downloads": "Downloads",
    "kind_generate": "Audiobook",
    "kind_optimize": "Text optimization",
    "kind_translate": "Translation",
    "status_running": "In progress",
    "status_done": "Done",
    "status_error": "Failed",
    "status_cancelled": "Cancelled",
    "dl_page": "Download page",
    "dl_m4b": "M4B",
    "dl_abm": "ABM",
    "dl_translated": "Translated book",
    "dl_expired": "expired",
    "dl_expires_in": "expires in {hours} h",
    "dl_expires_soon": "expires in {minutes} min",
    "voices_linked": "{n} voice samples linked to this account",
    "page_prev": "Newer",
    "page_next": "Older",
    "logout": "Sign out",
    "logout_all": "Sign out everywhere",
    "delete_account": "Delete account",
    "delete_account_p": "We will send you a confirmation code by email.",
    "delete_sent": "Check your email: open the link or enter the code on the site to confirm."
  },
  "it": {
    "brand": "Audiobook Maker",
    "confirm_login_title": "Accedi",
    "confirm_login_p": "Premi il pulsante per accedere al tuo account su questo dispositivo.",
    "confirm_login_btn": "Accedi",
    "confirm_delete_title": "Cancella il tuo account",
    "confirm_delete_p": "Premi il pulsante per cancellare definitivamente il tuo account. Lo storico dei job e le sessioni verranno eliminati; i file già consegnati restano scaricabili dai link ricevuti via email fino alla loro scadenza.",
    "confirm_delete_btn": "Cancella il mio account",
    "err_expired_title": "Link scaduto",
    "err_expired_p": "Questo link non è più valido. Richiedi un nuovo codice dal sito.",
    "err_locked_title": "Troppi tentativi",
    "err_locked_p": "Questo codice è stato bloccato dopo troppi tentativi errati. Richiedine uno nuovo dal sito.",
    "err_none_title": "Link non valido",
    "err_none_p": "Questo link è già stato usato o non esiste. Richiedi un nuovo codice dal sito.",
    "err_wrong_title": "Codice errato",
    "err_wrong_p": "Il codice non corrisponde. Controlla l'email e riprova.",
    "deleted_title": "Account cancellato",
    "deleted_p": "Il tuo account è stato cancellato. Puoi continuare a usare Audiobook Maker senza account.",
    "home": "Torna ad Audiobook Maker",
    "history_title": "I tuoi audiolibri",
    "history_signed_in_as": "Connesso come",
    "history_empty": "Nessun job ancora. Tutto ciò che generi da connesso comparirà qui.",
    "history_col_date": "Data",
    "history_col_book": "Libro",
    "history_col_kind": "Tipo",
    "history_col_status": "Stato",
    "history_col_downloads": "Download",
    "kind_generate": "Audiolibro",
    "kind_optimize": "Ottimizzazione testo",
    "kind_translate": "Traduzione",
    "status_running": "In corso",
    "status_done": "Completato",
    "status_error": "Fallito",
    "status_cancelled": "Annullato",
    "dl_page": "Pagina di download",
    "dl_m4b": "M4B",
    "dl_abm": "ABM",
    "dl_translated": "Libro tradotto",
    "dl_expired": "scaduto",
    "dl_expires_in": "scade fra {hours} h",
    "dl_expires_soon": "scade fra {minutes} min",
    "voices_linked": "{n} voci campionate collegate a questo account",
    "page_prev": "Più recenti",
    "page_next": "Più vecchi",
    "logout": "Esci",
    "logout_all": "Esci da tutti i dispositivi",
    "delete_account": "Cancella account",
    "delete_account_p": "Ti invieremo un codice di conferma via email.",
    "delete_sent": "Controlla la posta: apri il link o inserisci il codice sul sito per confermare."
  },
  "fr": {
    "brand": "Audiobook Maker",
    "confirm_login_title": "Connexion",
    "confirm_login_p": "Appuyez sur le bouton pour vous connecter à votre compte sur cet appareil.",
    "confirm_login_btn": "Se connecter",
    "confirm_delete_title": "Supprimer votre compte",
    "confirm_delete_p": "Appuyez sur le bouton pour supprimer définitivement votre compte. Votre historique et vos sessions seront effacés ; les fichiers déjà livrés restent téléchargeables depuis les liens reçus par e-mail jusqu'à leur expiration.",
    "confirm_delete_btn": "Supprimer mon compte",
    "err_expired_title": "Lien expiré",
    "err_expired_p": "Ce lien n'est plus valide. Demandez un nouveau code depuis le site.",
    "err_locked_title": "Trop de tentatives",
    "err_locked_p": "Ce code a été bloqué après trop de tentatives erronées. Demandez-en un nouveau depuis le site.",
    "err_none_title": "Lien non valide",
    "err_none_p": "Ce lien a déjà été utilisé ou n'existe pas. Demandez un nouveau code depuis le site.",
    "err_wrong_title": "Code erroné",
    "err_wrong_p": "Le code ne correspond pas. Vérifiez l'e-mail et réessayez.",
    "deleted_title": "Compte supprimé",
    "deleted_p": "Votre compte a été supprimé. Vous pouvez continuer à utiliser Audiobook Maker sans compte.",
    "home": "Retour à Audiobook Maker",
    "history_title": "Vos livres audio",
    "history_signed_in_as": "Connecté en tant que",
    "history_empty": "Aucun travail pour l'instant. Tout ce que vous générez en étant connecté apparaîtra ici.",
    "history_col_date": "Date",
    "history_col_book": "Livre",
    "history_col_kind": "Type",
    "history_col_status": "État",
    "history_col_downloads": "Téléchargements",
    "kind_generate": "Livre audio",
    "kind_optimize": "Optimisation du texte",
    "kind_translate": "Traduction",
    "status_running": "En cours",
    "status_done": "Terminé",
    "status_error": "Échec",
    "status_cancelled": "Annulé",
    "dl_page": "Page de téléchargement",
    "dl_m4b": "M4B",
    "dl_abm": "ABM",
    "dl_translated": "Livre traduit",
    "dl_expired": "expiré",
    "dl_expires_in": "expire dans {hours} h",
    "dl_expires_soon": "expire dans {minutes} min",
    "voices_linked": "{n} voix échantillonnées liées à ce compte",
    "page_prev": "Plus récents",
    "page_next": "Plus anciens",
    "logout": "Se déconnecter",
    "logout_all": "Se déconnecter partout",
    "delete_account": "Supprimer le compte",
    "delete_account_p": "Nous vous enverrons un code de confirmation par e-mail.",
    "delete_sent": "Consultez votre messagerie : ouvrez le lien ou saisissez le code sur le site pour confirmer."
  },
  "es": {
    "brand": "Audiobook Maker",
    "confirm_login_title": "Iniciar sesión",
    "confirm_login_p": "Pulsa el botón para iniciar sesión en tu cuenta en este dispositivo.",
    "confirm_login_btn": "Iniciar sesión",
    "confirm_delete_title": "Eliminar tu cuenta",
    "confirm_delete_p": "Pulsa el botón para eliminar definitivamente tu cuenta. Se borrarán tu historial y tus sesiones; los archivos ya entregados seguirán descargables desde los enlaces recibidos por correo hasta su caducidad.",
    "confirm_delete_btn": "Eliminar mi cuenta",
    "err_expired_title": "Enlace caducado",
    "err_expired_p": "Este enlace ya no es válido. Solicita un nuevo código desde el sitio.",
    "err_locked_title": "Demasiados intentos",
    "err_locked_p": "Este código se ha bloqueado tras demasiados intentos erróneos. Solicita uno nuevo desde el sitio.",
    "err_none_title": "Enlace no válido",
    "err_none_p": "Este enlace ya se ha usado o no existe. Solicita un nuevo código desde el sitio.",
    "err_wrong_title": "Código incorrecto",
    "err_wrong_p": "El código no coincide. Revisa el correo e inténtalo de nuevo.",
    "deleted_title": "Cuenta eliminada",
    "deleted_p": "Tu cuenta se ha eliminado. Puedes seguir usando Audiobook Maker sin cuenta.",
    "home": "Volver a Audiobook Maker",
    "history_title": "Tus audiolibros",
    "history_signed_in_as": "Sesión iniciada como",
    "history_empty": "Todavía no hay trabajos. Todo lo que generes con la sesión iniciada aparecerá aquí.",
    "history_col_date": "Fecha",
    "history_col_book": "Libro",
    "history_col_kind": "Tipo",
    "history_col_status": "Estado",
    "history_col_downloads": "Descargas",
    "kind_generate": "Audiolibro",
    "kind_optimize": "Optimización del texto",
    "kind_translate": "Traducción",
    "status_running": "En curso",
    "status_done": "Completado",
    "status_error": "Fallido",
    "status_cancelled": "Cancelado",
    "dl_page": "Página de descarga",
    "dl_m4b": "M4B",
    "dl_abm": "ABM",
    "dl_translated": "Libro traducido",
    "dl_expired": "caducado",
    "dl_expires_in": "caduca en {hours} h",
    "dl_expires_soon": "caduca en {minutes} min",
    "voices_linked": "{n} voces muestreadas vinculadas a esta cuenta",
    "page_prev": "Más recientes",
    "page_next": "Más antiguos",
    "logout": "Cerrar sesión",
    "logout_all": "Cerrar sesión en todos los dispositivos",
    "delete_account": "Eliminar cuenta",
    "delete_account_p": "Te enviaremos un código de confirmación por correo.",
    "delete_sent": "Revisa tu correo: abre el enlace o introduce el código en el sitio para confirmar."
  },
  "de": {
    "brand": "Audiobook Maker",
    "confirm_login_title": "Anmelden",
    "confirm_login_p": "Drücken Sie die Schaltfläche, um sich auf diesem Gerät bei Ihrem Konto anzumelden.",
    "confirm_login_btn": "Anmelden",
    "confirm_delete_title": "Konto löschen",
    "confirm_delete_p": "Drücken Sie die Schaltfläche, um Ihr Konto endgültig zu löschen. Ihr Verlauf und Ihre Sitzungen werden entfernt; bereits gelieferte Dateien bleiben über die per E-Mail erhaltenen Links bis zu deren Ablauf herunterladbar.",
    "confirm_delete_btn": "Mein Konto löschen",
    "err_expired_title": "Link abgelaufen",
    "err_expired_p": "Dieser Link ist nicht mehr gültig. Fordern Sie auf der Website einen neuen Code an.",
    "err_locked_title": "Zu viele Versuche",
    "err_locked_p": "Dieser Code wurde nach zu vielen Fehlversuchen gesperrt. Fordern Sie auf der Website einen neuen an.",
    "err_none_title": "Link ungültig",
    "err_none_p": "Dieser Link wurde bereits verwendet oder existiert nicht. Fordern Sie auf der Website einen neuen Code an.",
    "err_wrong_title": "Falscher Code",
    "err_wrong_p": "Der Code stimmt nicht überein. Prüfen Sie die E-Mail und versuchen Sie es erneut.",
    "deleted_title": "Konto gelöscht",
    "deleted_p": "Ihr Konto wurde gelöscht. Sie können Audiobook Maker weiterhin ohne Konto nutzen.",
    "home": "Zurück zu Audiobook Maker",
    "history_title": "Ihre Hörbücher",
    "history_signed_in_as": "Angemeldet als",
    "history_empty": "Noch keine Aufträge. Alles, was Sie angemeldet erzeugen, erscheint hier.",
    "history_col_date": "Datum",
    "history_col_book": "Buch",
    "history_col_kind": "Art",
    "history_col_status": "Status",
    "history_col_downloads": "Downloads",
    "kind_generate": "Hörbuch",
    "kind_optimize": "Textoptimierung",
    "kind_translate": "Übersetzung",
    "status_running": "In Bearbeitung",
    "status_done": "Fertig",
    "status_error": "Fehlgeschlagen",
    "status_cancelled": "Abgebrochen",
    "dl_page": "Download-Seite",
    "dl_m4b": "M4B",
    "dl_abm": "ABM",
    "dl_translated": "Übersetztes Buch",
    "dl_expired": "abgelaufen",
    "dl_expires_in": "läuft in {hours} Std. ab",
    "dl_expires_soon": "läuft in {minutes} Min. ab",
    "voices_linked": "{n} Stimmproben mit diesem Konto verknüpft",
    "page_prev": "Neuere",
    "page_next": "Ältere",
    "logout": "Abmelden",
    "logout_all": "Überall abmelden",
    "delete_account": "Konto löschen",
    "delete_account_p": "Wir senden Ihnen einen Bestätigungscode per E-Mail.",
    "delete_sent": "Prüfen Sie Ihr Postfach: öffnen Sie den Link oder geben Sie den Code auf der Website ein, um zu bestätigen."
  },
  "zh": {
    "brand": "Audiobook Maker",
    "confirm_login_title": "登录",
    "confirm_login_p": "点击按钮，在此设备上登录您的账户。",
    "confirm_login_btn": "登录",
    "confirm_delete_title": "删除您的账户",
    "confirm_delete_p": "点击按钮将永久删除您的账户。您的任务记录和登录会话将被清除；已交付的文件在过期前仍可通过邮件中的链接下载。",
    "confirm_delete_btn": "删除我的账户",
    "err_expired_title": "链接已过期",
    "err_expired_p": "此链接已失效。请在网站上重新申请验证码。",
    "err_locked_title": "尝试次数过多",
    "err_locked_p": "错误尝试过多，此验证码已被锁定。请在网站上重新申请。",
    "err_none_title": "链接无效",
    "err_none_p": "此链接已被使用或不存在。请在网站上重新申请验证码。",
    "err_wrong_title": "验证码错误",
    "err_wrong_p": "验证码不匹配。请检查邮件后重试。",
    "deleted_title": "账户已删除",
    "deleted_p": "您的账户已删除。您仍可在无账户的情况下继续使用 Audiobook Maker。",
    "home": "返回 Audiobook Maker",
    "history_title": "您的有声书",
    "history_signed_in_as": "当前登录：",
    "history_empty": "暂无任务。登录状态下生成的所有内容都会显示在这里。",
    "history_col_date": "日期",
    "history_col_book": "书籍",
    "history_col_kind": "类型",
    "history_col_status": "状态",
    "history_col_downloads": "下载",
    "kind_generate": "有声书",
    "kind_optimize": "文本优化",
    "kind_translate": "翻译",
    "status_running": "进行中",
    "status_done": "已完成",
    "status_error": "失败",
    "status_cancelled": "已取消",
    "dl_page": "下载页面",
    "dl_m4b": "M4B",
    "dl_abm": "ABM",
    "dl_translated": "翻译后的书籍",
    "dl_expired": "已过期",
    "dl_expires_in": "{hours} 小时后过期",
    "dl_expires_soon": "{minutes} 分钟后过期",
    "voices_linked": "已关联到此账户的采样声音：{n} 个",
    "page_prev": "较新",
    "page_next": "较早",
    "logout": "退出登录",
    "logout_all": "退出所有设备",
    "delete_account": "删除账户",
    "delete_account_p": "我们将通过邮件向您发送确认码。",
    "delete_sent": "请查收邮件：打开链接或在网站上输入验证码以确认。"
  },
  "hi": {
    "brand": "Audiobook Maker",
    "confirm_login_title": "साइन इन करें",
    "confirm_login_p": "इस डिवाइस पर अपने खाते में साइन इन करने के लिए बटन दबाएँ।",
    "confirm_login_btn": "साइन इन करें",
    "confirm_delete_title": "अपना खाता हटाएँ",
    "confirm_delete_p": "अपना खाता स्थायी रूप से हटाने के लिए बटन दबाएँ। आपका इतिहास और सत्र हटा दिए जाएँगे; पहले से डिलीवर की गई फ़ाइलें ईमेल में मिले लिंक से समाप्ति तक डाउनलोड की जा सकेंगी।",
    "confirm_delete_btn": "मेरा खाता हटाएँ",
    "err_expired_title": "लिंक की अवधि समाप्त",
    "err_expired_p": "यह लिंक अब मान्य नहीं है। साइट से नया कोड माँगें।",
    "err_locked_title": "बहुत अधिक प्रयास",
    "err_locked_p": "बहुत अधिक गलत प्रयासों के बाद यह कोड लॉक कर दिया गया है। साइट से नया कोड माँगें।",
    "err_none_title": "लिंक अमान्य",
    "err_none_p": "यह लिंक पहले ही उपयोग हो चुका है या मौजूद नहीं है। साइट से नया कोड माँगें।",
    "err_wrong_title": "गलत कोड",
    "err_wrong_p": "कोड मेल नहीं खाता। ईमेल जाँचें और फिर से कोशिश करें।",
    "deleted_title": "खाता हटा दिया गया",
    "deleted_p": "आपका खाता हटा दिया गया है। आप बिना खाते के भी Audiobook Maker का उपयोग जारी रख सकते हैं।",
    "home": "Audiobook Maker पर वापस जाएँ",
    "history_title": "आपकी ऑडियोबुक",
    "history_signed_in_as": "साइन इन:",
    "history_empty": "अभी कोई कार्य नहीं। साइन इन रहते हुए आप जो भी बनाएँगे वह यहाँ दिखेगा।",
    "history_col_date": "तारीख़",
    "history_col_book": "पुस्तक",
    "history_col_kind": "प्रकार",
    "history_col_status": "स्थिति",
    "history_col_downloads": "डाउनलोड",
    "kind_generate": "ऑडियोबुक",
    "kind_optimize": "टेक्स्ट अनुकूलन",
    "kind_translate": "अनुवाद",
    "status_running": "प्रगति में",
    "status_done": "पूर्ण",
    "status_error": "विफल",
    "status_cancelled": "रद्द",
    "dl_page": "डाउनलोड पेज",
    "dl_m4b": "M4B",
    "dl_abm": "ABM",
    "dl_translated": "अनूदित पुस्तक",
    "dl_expired": "समाप्त",
    "dl_expires_in": "{hours} घंटे में समाप्त",
    "dl_expires_soon": "{minutes} मिनट में समाप्त",
    "voices_linked": "इस खाते से जुड़े {n} आवाज़ नमूने",
    "page_prev": "नए",
    "page_next": "पुराने",
    "logout": "साइन आउट",
    "logout_all": "सभी डिवाइस से साइन आउट",
    "delete_account": "खाता हटाएँ",
    "delete_account_p": "हम आपको ईमेल से एक पुष्टि कोड भेजेंगे।",
    "delete_sent": "अपना ईमेल देखें: पुष्टि के लिए लिंक खोलें या साइट पर कोड दर्ज करें।"
  }
}
```

Il test `test_account_page_i18n_complete` del Task 6 verifica che tutte le lingue abbiano esattamente le chiavi di `en`.

- [ ] **Step 4: Creare `account_page.py`**

```python
# account_page.py
"""Pagine server-side dell'account (modulo foglia): conferma magic link,
errori, account cancellato e, dal Task 6, lo storico. Solo stdlib: i testi
arrivano gia' scelti per lingua (dict `t`), l'escaping e' fatto qui.
"""
import html

_CSS = (
    ":root{--acc:#c29a6c;--acc-d:#a67d50;--bd:#dcd6cd;--mut:#666}"
    "body{font-family:system-ui,sans-serif;max-width:760px;margin:3em auto;padding:0 1em;"
    "color:#222;background:#fff;line-height:1.5}"
    "button,a.btn{font:inherit;padding:.5em 1.1em;border:1px solid var(--bd);border-radius:8px;"
    "background:#f6f3ee;color:#222;cursor:pointer;text-decoration:none;display:inline-block}"
    "button:hover,a.btn:hover{background:#ece7df}"
    "button.primary{background:var(--acc);border-color:var(--acc);color:#fff}"
    "button.primary:hover{background:var(--acc-d);border-color:var(--acc-d)}"
    "button.danger{background:#fff;color:#b3261e;border-color:#e8bdb9}"
    "button.danger:hover{background:#fdecea}"
    ".meta{color:var(--mut);font-size:.9em}.actions{display:flex;gap:.6em;flex-wrap:wrap;margin-top:1.5em}"
    "table{width:100%;border-collapse:collapse;margin-top:1em;font-size:.95em}"
    "th,td{text-align:left;padding:.5em .4em;border-top:1px solid var(--bd);vertical-align:top}"
    "th{color:var(--mut);font-weight:600;border-top:none}"
    ".badge{font-size:.8em;border-radius:1em;padding:.1em .6em;background:#eee;color:#444;white-space:nowrap}"
    ".badge.done{background:#e6f4ea;color:#1e6b34}.badge.error{background:#fdecea;color:#b3261e}"
    ".badge.running{background:#eef3ff;color:#2c4a8a}.badge.expired{background:#f3f0ea;color:#8a7a62}"
    ".dl a{margin-right:.6em;white-space:nowrap}"
    ".brand{display:flex;align-items:center;gap:.6em;margin-bottom:1.8em;color:inherit;text-decoration:none}"
    ".brand span{font-size:1.1em;font-weight:600}"
    "@media(max-width:600px){table,thead,tbody,tr,td,th{display:block}thead{display:none}"
    "td{border-top:none;padding:.15em 0}tr{border-top:1px solid var(--bd);padding:.6em 0}}"
)


def _e(s):
    return html.escape(str(s if s is not None else ""))


def page_html(t, lang, title, body_html):
    """Scheletro HTML completo. `body_html` e' gia' escapato dal chiamante."""
    brand = _e(t.get("brand", "Audiobook Maker"))
    return (
        f"<!doctype html><html lang=\"{_e(lang)}\"><head><meta charset=\"utf-8\">"
        f"<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<meta name=\"robots\" content=\"noindex,nofollow\">"
        f"<title>{brand} - {_e(title)}</title><style>{_CSS}</style></head>"
        f"<body><a class=\"brand\" href=\"/\"><span>{brand}</span></a>"
        f"<h1>{_e(title)}</h1>{body_html}</body></html>"
    )


def render_confirm(t, *, lang, purpose, action_url):
    """Pagina GET /auth/<token>: un form POST, cosi' il GET non consuma mai."""
    key = "confirm_delete" if purpose == "delete" else "confirm_login"
    cls = "danger" if purpose == "delete" else "primary"
    body = (
        f"<p>{_e(t[key + '_p'])}</p>"
        f"<form method=\"post\" action=\"{_e(action_url)}\" class=\"actions\">"
        f"<button type=\"submit\" class=\"{cls}\">{_e(t[key + '_btn'])}</button></form>"
    )
    return page_html(t, lang, t[key + "_title"], body)


def render_error(t, *, lang, status_key):
    key = status_key if status_key in ("expired", "locked", "none", "wrong") else "none"
    body = (f"<p>{_e(t['err_' + key + '_p'])}</p>"
            f"<p class=\"actions\"><a class=\"btn\" href=\"/\">{_e(t['home'])}</a></p>")
    return page_html(t, lang, t["err_" + key + "_title"], body)


def render_deleted(t, *, lang):
    body = (f"<p>{_e(t['deleted_p'])}</p>"
            f"<p class=\"actions\"><a class=\"btn\" href=\"/\">{_e(t['home'])}</a></p>")
    return page_html(t, lang, t["deleted_title"], body)
```

- [ ] **Step 5: Modificare `audiobook_app.py` — import e init**

Dopo `import pending_jobs` (:149):

```python
import db
import accounts
import account_page
```

Dopo `voice_clone_audio.init(_DATA_DIR)` (:393):

```python
# Account opzionali (SQLite): il DB apre sempre, l'interruttore e' ABM_ACCOUNT_ENABLE.
try:
    db.init(_DATA_DIR)
    accounts.init_schema()
    accounts.configure(
        payments_path=Path(_DATA_DIR) / "_payments.json",
        voice_clone_ids_for_email_fn=voice_clone.ids_for_email,
        link_voice_fn=voice_clone.link_account,
        log_fn=lambda m: print(m, flush=True),
    )
    print(f"[startup] accounts: {'enabled' if accounts.enabled() else 'disabled'} ({db.DB_FILENAME})")
except Exception as e:
    print(f"[startup] accounts init failed (feature disabled): {e}", flush=True)
```

Accanto a `_VC_PAGES_I18N` (:164) aggiungere il loader gemello:

```python
_ACCT_PAGES_I18N = {}
try:
    with open(SCRIPT_DIR / "i18n" / "account_pages.json", encoding="utf-8") as _f:
        _ACCT_PAGES_I18N = json.load(_f)
except Exception as _e:
    print(f"WARNING: Could not load i18n/account_pages.json: {_e}", file=sys.stderr)
```

- [ ] **Step 6: Aggiungere helper e route in `audiobook_app.py` (dopo `_hash_ip`)**

```python
# ===========================================================================
# Account: sessione, gate, pagine e route di autenticazione
# ===========================================================================

_ACCOUNT_SESSION_COOKIE = "abm_session"
_ACCT_EMAIL_RE = re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")


def _acct_err(code, msg, status, **extra):
    return jsonify({"error": msg, "error_code": code, **extra}), status


def _acct_gate():
    """None se la feature e' usabile, altrimenti la risposta 404 da ritornare."""
    if not accounts.enabled() or not _smtp_available():
        return _acct_err("account_disabled", "Accounts are not available", 404)
    return None


def _acct_session_token():
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(_ACCOUNT_SESSION_COOKIE, "")


def _current_account():
    """Account della richiesta corrente o None. Cache in flask.g."""
    if hasattr(g, "_acct"):
        return g._acct
    acct = None
    try:
        if accounts.enabled():
            acct = accounts.resolve_session(_acct_session_token())
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _current_account: {e}", flush=True)
    g._acct = acct
    return acct


def _acct_cookie_secure():
    if (BASE_URL or "").startswith("https"):
        return True
    return (request.headers.get("X-Forwarded-Proto") or "").lower() == "https"


def _acct_set_cookie(resp, token):
    resp.set_cookie(_ACCOUNT_SESSION_COOKIE, token, max_age=accounts.SESSION_DAYS * 86400,
                    httponly=True, samesite="Lax", secure=_acct_cookie_secure(), path="/")


def _acct_clear_cookie(resp):
    resp.set_cookie(_ACCOUNT_SESSION_COOKIE, "", max_age=0, expires=0, httponly=True,
                    samesite="Lax", secure=_acct_cookie_secure(), path="/")


def _acct_log(op, email, extra=""):
    """Business log senza email in chiaro: sid = acct-<hash8>."""
    try:
        sid = "acct-" + accounts.email_hash(email)[:8]
        _log_activity(sid, extra, op, client_id=_get_client_id(), client_ip=_client_ip())
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _acct_log: {e}", flush=True)


def _acct_page_lang():
    lang = _get_browser_lang()
    return lang if lang in _ACCT_PAGES_I18N else "en"


def _acct_txt(lang):
    t = dict(_ACCT_PAGES_I18N.get("en") or {})
    t.update(_ACCT_PAGES_I18N.get(lang) or {})
    return t


def _acct_html(html_doc, status=200):
    resp = _apply_no_cache(Response(html_doc, status=status, mimetype="text/html"))
    resp.headers["Vary"] = "Accept-Language, Cookie"
    return resp


def _acct_send_code(email, purpose, lang):
    """Genera e spedisce il codice. Sempre silenzioso: risposta neutra a monte."""
    try:
        out = accounts.request_code(email, purpose, lang, ip_hash=_hash_ip(_client_ip()),
                                    ua=request.headers.get("User-Agent", ""))
        if out is None:
            return
        token, code = out
        link = f"{BASE_URL}/auth/{token}" + ("?p=delete" if purpose == "delete" else "")
        email_service.send_account_code(
            email, lang, code=code, link_url=link,
            purpose=purpose, minutes=accounts.CODE_TTL_MIN)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING _acct_send_code: {type(e).__name__}: {e}", flush=True)


def _acct_do_delete(acct, lang):
    """Cancellazione confermata: DB, log, email di cortesia (best-effort)."""
    accounts.delete_account(acct["id"])
    _acct_log("ACCOUNT_DELETE", acct["email"])
    try:
        email_service.send_account_deleted(acct["email"], acct.get("lang") or lang)
    except Exception as e:  # noqa: BLE001
        print(f"WARNING send_account_deleted: {e}", flush=True)


def _acct_login_response(acct, payload=None):
    """Apre la sessione, logga, imposta il cookie. `session_token` solo per
    l'app (header X-ABM-Cid), che non usa i cookie."""
    token = accounts.open_session(acct["id"],
                                  device_name=(request.headers.get("User-Agent") or "")[:80],
                                  ip_hash=_hash_ip(_client_ip()))
    _acct_log("ACCOUNT_LOGIN", acct["email"])
    body = {"ok": True, "email": acct["email"], "lang": acct.get("lang") or "en",
            "plan": acct.get("plan") or "free"}
    if payload is not None:
        body.update(payload)
    if (request.headers.get(_MOBILE_CID_HEADER) or "").strip():
        body["session_token"] = token
    resp = jsonify(body)
    _acct_set_cookie(resp, token)
    return resp


@app.route("/api/auth/request", methods=["POST"])
def api_auth_request():
    gate = _acct_gate()
    if gate:
        return gate
    ip = _client_ip()
    allowed, retry = _ip_rl_check("auth_request", ip, 5, 30)
    if not allowed:
        return _acct_err("rate_limited", "Too many requests", 429, retry_after=retry)
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    if not _ACCT_EMAIL_RE.match(email):
        return _acct_err("invalid_email", "Invalid email address", 400)
    lang = (data.get("lang") or _get_browser_lang() or "en")[:8]
    _acct_send_code(email, "login", lang)
    return jsonify({"ok": True})


@app.route("/api/auth/verify", methods=["POST"])
def api_auth_verify():
    gate = _acct_gate()
    if gate:
        return gate
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    email = (data.get("email") or "").strip().lower()
    code = (data.get("code") or "").strip()
    if token:
        status, acct = accounts.verify(token=token, purpose="login")
    elif email and code:
        status, acct = accounts.verify(email=email, code=code, purpose="login")
    else:
        return _acct_err("bad_request", "token or email+code required", 400)
    if status != "ok":
        return _acct_err(status, "Verification failed", 401)
    return _acct_login_response(acct)


@app.route("/auth/<token>", methods=["GET", "POST"])
def auth_magic_link(token):
    lang = _acct_page_lang()
    t = _acct_txt(lang)
    if not accounts.enabled() or not _smtp_available():
        return _acct_html(account_page.render_error(t, lang=lang, status_key="none"), 404)
    purpose = "delete" if request.args.get("p") == "delete" else "login"
    if request.method == "GET":
        # Mai consumare al GET: i client di posta pre-aprono i link.
        return _acct_html(account_page.render_confirm(
            t, lang=lang, purpose=purpose, action_url=request.full_path.rstrip("?")))
    status, acct = accounts.verify(token=token, purpose=purpose)
    if status != "ok":
        return _acct_html(account_page.render_error(t, lang=lang, status_key=status), 410)
    if purpose == "delete":
        _acct_do_delete(acct, lang)
        resp = _acct_html(account_page.render_deleted(t, lang=lang))
        _acct_clear_cookie(resp)
        return resp
    session_token = accounts.open_session(
        acct["id"], device_name=(request.headers.get("User-Agent") or "")[:80],
        ip_hash=_hash_ip(_client_ip()))
    _acct_log("ACCOUNT_LOGIN", acct["email"])
    resp = redirect("/account", code=302)
    _acct_set_cookie(resp, session_token)
    return resp


@app.route("/api/auth/logout", methods=["POST"])
def api_auth_logout():
    token = _acct_session_token()
    acct = _current_account()
    if token:
        try:
            accounts.revoke_session(token)
        except Exception as e:  # noqa: BLE001
            print(f"WARNING logout: {e}", flush=True)
    if acct:
        _acct_log("ACCOUNT_LOGOUT", acct["email"])
    resp = jsonify({"ok": True})
    _acct_clear_cookie(resp)
    return resp


@app.route("/api/auth/logout_all", methods=["POST"])
def api_auth_logout_all():
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    n = accounts.revoke_all(acct["id"])
    _acct_log("ACCOUNT_LOGOUT_ALL", acct["email"], str(n))
    resp = jsonify({"ok": True, "revoked": n})
    _acct_clear_cookie(resp)
    return resp


@app.route("/api/auth/me", methods=["GET"])
def api_auth_me():
    if not accounts.enabled() or not _smtp_available():
        return jsonify({"logged_in": False, "enabled": False})
    acct = _current_account()
    if not acct:
        return jsonify({"logged_in": False, "enabled": True})
    return jsonify({
        "logged_in": True, "enabled": True, "email": acct["email"],
        "lang": acct.get("lang") or "en", "plan": acct.get("plan") or "free",
        "sessions_count": accounts.sessions_count(acct["id"]),
    })
```

`redirect` è già importato da `flask` (riga 42-45); **`g` no**: aggiungerlo alla tupla `from flask import (...)` alla riga 43.

- [ ] **Step 7: Compilare ed eseguire i test**

Run: `python -m py_compile account_page.py`
Run: `python -m py_compile audiobook_app.py`
Run: `python -c "import json; d=json.load(open('i18n/account_pages.json', encoding='utf-8')); assert all(set(d[l])==set(d['en']) for l in d), 'chiavi'"`
Run: `pytest test/test_account_routes.py test/test_accounts.py -v --tb=short`
Expected: tutti PASS (14 nel file route)

- [ ] **Step 8: Commit**

```bash
git add db.py accounts.py account_page.py i18n/account_pages.json audiobook_app.py test/test_account_routes.py
git commit -m "feat(account): route di autenticazione magic link, sessioni e pagine di conferma"
```

---

### Task 6: Pagina `/account`, API storico e cancellazione self-service

**Files:**
- Modify: `account_page.py` (aggiunge `render_history`)
- Modify: `audiobook_app.py` (dopo le route del Task 5: `_account_downloads_for`, `GET /account`, `GET /api/account/jobs`, `POST /api/account/delete_request`, `POST /api/account/delete_confirm`)
- Test: `test/test_account_page.py`

**Interfaces:**
- Consumes: `accounts.list_jobs(account_id, page, per_page) -> (rows, total)`, `accounts.request_code`, `accounts.verify(..., purpose="delete")`, `accounts.delete_account`, `email_service.send_account_deleted`, `voice_clone.ids_for_email(email) -> list[str]`, `_download_tokens` (dict token→info con `job_id`, `created_at`, `download_type` in `audio|optimized_abm|translated`, `output_m4b`), `_effective_retention_for_token_info(info) -> float` (secondi), helper del Task 5.
- Produces:
  - `_account_downloads_for(row, now=None) -> list[dict]` con `{"kind": "page|m4b|abm|translated", "url": str, "expires_at": int}`; lista vuota se nessun token vivo.
  - `account_page.render_history(t, *, lang, account, rows, page, per_page, total, voices_count, now=None) -> str`; ogni `row` è un dict `account_jobs` con in più `downloads` (lista sopra).
  - `GET /account` (HTML; 302 a `/?login=1` senza sessione), `GET /api/account/jobs?p=N` → `{"jobs": [...], "total": int, "page": int, "per_page": int}`.
  - `POST /api/account/delete_request` → `{ok:true}`; `POST /api/account/delete_confirm` con `{token}` o `{code}` → `{ok:true}` + cookie azzerato.

- [ ] **Step 1: Scrivere `test/test_account_page.py`**

```python
# test/test_account_page.py
"""Pagina /account, API storico e cancellazione self-service."""
import json
import time
from pathlib import Path

import pytest

import accounts
import audiobook_app
import db
import email_service
import voice_clone as vc
import community_store

T0 = 1_800_000_000


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_download_tokens", {})
    monkeypatch.setattr(audiobook_app, "_save_tokens", lambda: None)
    audiobook_app._ip_rl_buckets.pop("auth_request", None)
    box = {"codes": [], "deleted": []}
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: box["codes"].append((email, kw)) or True)
    monkeypatch.setattr(email_service, "send_account_deleted",
                        lambda email, lang: box["deleted"].append(email) or True)
    audiobook_app.app.config["TESTING"] = True
    yield box
    db.close()


@pytest.fixture
def logged(env):
    c = audiobook_app.app.test_client()
    c.post("/api/auth/request", json={"email": "a@b.it", "lang": "it"})
    code = env["codes"][-1][1]["code"]
    r = c.post("/api/auth/verify", json={"email": "a@b.it", "code": code})
    assert r.status_code == 200
    acct = accounts.account_for_email("a@b.it")
    return c, acct


def _token(job_id, dl_type="audio", created_at=None, **extra):
    info = {"job_id": job_id, "created_at": created_at if created_at is not None else time.time(),
            "download_type": dl_type, "base_url": "https://abm.test", "book_title": "B"}
    info.update(extra)
    tok = "tok-" + job_id
    audiobook_app._download_tokens[tok] = info
    return tok


def test_i18n_complete():
    d = json.loads((Path(audiobook_app.SCRIPT_DIR) / "i18n" / "account_pages.json").read_text(encoding="utf-8"))
    assert set(d) == {"en", "it", "fr", "es", "de", "zh", "hi"}
    for lang, t in d.items():
        assert set(t) == set(d["en"]), lang
        assert "..." not in t, lang


def test_account_page_redirects_without_session(env):
    c = audiobook_app.app.test_client()
    r = c.get("/account")
    assert r.status_code == 302 and r.headers["Location"].endswith("/?login=1")


def test_account_page_disabled_404(env, monkeypatch):
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert audiobook_app.app.test_client().get("/account").status_code == 404


def test_account_page_lists_jobs_with_downloads(logged, monkeypatch):
    c, acct = logged
    accounts.record_job(acct["id"], "j1", kind="generate", book_title="Il Gattopardo <b>",
                        output_format="m4b", status="done", created_at=T0)
    accounts.record_job(acct["id"], "j2", kind="translate", book_title="Old", status="done",
                        created_at=T0 - 86400 * 400)
    _token("j1", "audio", output_m4b="/x/a.m4b")
    accounts.set_download_token("j1", "tok-j1")
    _token("j2", "translated", created_at=T0 - 86400 * 400)
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 3600.0)
    r = c.get("/account", headers={"Accept-Language": "it"})
    assert r.status_code == 200
    html = r.data.decode()
    assert "Il Gattopardo &lt;b&gt;" in html and "<b>" not in html.split("Gattopardo")[1][:10]
    assert "/dl/tok-j1" in html and "/dl/tok-j1/m4b" in html
    assert "/dl/tok-j2" not in html and "scaduto" in html
    assert "Connesso come" in html and "a@b.it" in html
    assert "no-store" in r.headers.get("Cache-Control", "")


def test_api_jobs_pagination_and_shape(logged, monkeypatch):
    c, acct = logged
    for i in range(3):
        accounts.record_job(acct["id"], f"j{i}", kind="generate", status="done", created_at=T0 + i)
    monkeypatch.setattr(audiobook_app, "_ACCT_PER_PAGE", 2)
    r = c.get("/api/account/jobs?p=2")
    assert r.status_code == 200
    d = r.get_json()
    assert d["page"] == 2 and d["total"] == 3 and d["per_page"] == 2 and len(d["jobs"]) == 1
    j = d["jobs"][0]
    assert set(j) >= {"job_id", "created_at", "kind", "book_title", "output_format", "status",
                      "paid_eur", "downloads"}
    assert j["job_id"] == "j0" and j["downloads"] == []


def test_api_jobs_requires_session(env):
    c = audiobook_app.app.test_client()
    assert c.get("/api/account/jobs").status_code == 401


def test_downloads_for_handles_types_and_expiry(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 100.0)
    now = time.time()
    _token("ja", "audio", created_at=now - 10, output_m4b="")
    _token("jb", "optimized_abm", created_at=now - 10)
    _token("jc", "translated", created_at=now - 10)
    _token("jd", "audio", created_at=now - 500)
    f = audiobook_app._account_downloads_for
    assert [d["kind"] for d in f({"job_id": "ja", "download_token": ""}, now)] == ["page"]
    assert [d["kind"] for d in f({"job_id": "jb", "download_token": "tok-jb"}, now)] == ["page", "abm"]
    kinds = [d["kind"] for d in f({"job_id": "jc", "download_token": ""}, now)]
    assert kinds == ["page", "translated"]
    assert f({"job_id": "jd", "download_token": "tok-jd"}, now) == []
    assert f({"job_id": "nope", "download_token": ""}, now) == []
    d = f({"job_id": "ja", "download_token": ""}, now)[0]
    assert d["url"] == "https://abm.test/dl/tok-ja" and abs(d["expires_at"] - (now + 90)) < 2


def test_delete_flow_by_code(logged, env):
    c, acct = logged
    accounts.record_job(acct["id"], "j1", kind="generate", status="done")
    r = c.post("/api/account/delete_request")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    email, kw = env["codes"][-1]
    assert email == "a@b.it" and kw["purpose"] == "delete" and "?p=delete" in kw["link_url"]
    r = c.post("/api/account/delete_confirm", json={"code": kw["code"]})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert env["deleted"] == ["a@b.it"]
    assert accounts.account_for_email("a@b.it") is None
    assert accounts.list_jobs(acct["id"])[1] == 0
    assert c.get("/api/auth/me").get_json()["logged_in"] is False


def test_delete_flow_by_magic_link(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request")
    link = env["codes"][-1][1]["link_url"]
    path = link[len("https://abm.test"):]
    r = c.get(path)
    assert r.status_code == 200 and b"<form" in r.data
    assert accounts.account_for_email("a@b.it") is not None
    r = c.post(path)
    assert r.status_code == 200 and env["deleted"] == ["a@b.it"]
    assert accounts.account_for_email("a@b.it") is None


def test_delete_confirm_wrong_code_401_and_requires_session(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request")
    r = c.post("/api/account/delete_confirm", json={"code": "000000"})
    assert r.status_code == 401 and r.get_json()["error_code"] in ("wrong", "none")
    assert accounts.account_for_email("a@b.it") is not None
    anon = audiobook_app.app.test_client()
    assert anon.post("/api/account/delete_request").status_code == 401
    assert anon.post("/api/account/delete_confirm", json={"code": "1"}).status_code == 401


def test_delete_request_ignores_body_email(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request", json={"email": "victim@x.it"})
    assert env["codes"][-1][0] == "a@b.it"
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_account_page.py -v --tb=short`
Expected: FAIL — `test_i18n_complete` può già passare se il JSON del Task 5 è completo; gli altri falliscono con 404 su `/account` o `AttributeError: _account_downloads_for`.

- [ ] **Step 3: Aggiungere `render_history` a `account_page.py`**

Appendere in coda al modulo:

```python
def _fmt_date(epoch):
    import datetime as _dt
    try:
        return _dt.datetime.fromtimestamp(int(epoch)).strftime("%Y-%m-%d %H:%M")
    except Exception:  # noqa: BLE001
        return ""


def _expiry_label(t, expires_at, now):
    left = int(expires_at - now)
    if left <= 0:
        return t["dl_expired"]
    if left < 3600:
        return t["dl_expires_soon"].replace("{minutes}", str(max(1, left // 60)))
    return t["dl_expires_in"].replace("{hours}", str(left // 3600))


def render_history(t, *, lang, account, rows, page, per_page, total, voices_count, now=None):
    import time as _time
    now = now if now is not None else _time.time()
    parts = [f"<p class=\"meta\">{_e(t['history_signed_in_as'])} <strong>{_e(account['email'])}</strong>"]
    if voices_count:
        parts.append(" &middot; " + _e(t["voices_linked"].replace("{n}", str(voices_count))))
    parts.append("</p>")
    if not rows:
        parts.append(f"<p>{_e(t['history_empty'])}</p>")
    else:
        parts.append("<table><thead><tr>"
                     f"<th>{_e(t['history_col_date'])}</th><th>{_e(t['history_col_book'])}</th>"
                     f"<th>{_e(t['history_col_kind'])}</th><th>{_e(t['history_col_status'])}</th>"
                     f"<th>{_e(t['history_col_downloads'])}</th></tr></thead><tbody>")
        for r in rows:
            status = r.get("status") or "running"
            kind = r.get("kind") or "generate"
            dls = r.get("downloads") or []
            if dls:
                cell = "".join(
                    f"<a href=\"{_e(d['url'])}\">{_e(t.get('dl_' + d['kind'], d['kind']))}</a>" for d in dls)
                cell += f" <span class=\"badge\">{_e(_expiry_label(t, min(d['expires_at'] for d in dls), now))}</span>"
            elif status == "done":
                cell = f"<span class=\"badge expired\">{_e(t['dl_expired'])}</span>"
            else:
                cell = ""
            paid = float(r.get("paid_eur") or 0)
            book = _e(r.get("book_title") or r.get("job_id") or "")
            if paid > 0:
                book += f" <span class=\"meta\">&euro; {paid:.2f}</span>"
            parts.append(
                f"<tr><td>{_e(_fmt_date(r.get('created_at')))}</td><td>{book}</td>"
                f"<td>{_e(t.get('kind_' + kind, kind))}</td>"
                f"<td><span class=\"badge {_e(status)}\">{_e(t.get('status_' + status, status))}</span></td>"
                f"<td class=\"dl\">{cell}</td></tr>")
        parts.append("</tbody></table>")
        pages = max(1, (int(total) + per_page - 1) // per_page)
        if pages > 1:
            nav = []
            if page > 1:
                nav.append(f"<a class=\"btn\" href=\"/account?p={page - 1}\">{_e(t['page_prev'])}</a>")
            nav.append(f"<span class=\"meta\">{page} / {pages}</span>")
            if page < pages:
                nav.append(f"<a class=\"btn\" href=\"/account?p={page + 1}\">{_e(t['page_next'])}</a>")
            parts.append("<p class=\"actions\">" + " ".join(nav) + "</p>")
    parts.append(
        "<div class=\"actions\">"
        f"<button type=\"button\" id=\"acctLogout\">{_e(t['logout'])}</button>"
        f"<button type=\"button\" id=\"acctLogoutAll\">{_e(t['logout_all'])}</button>"
        f"<button type=\"button\" class=\"danger\" id=\"acctDelete\">{_e(t['delete_account'])}</button>"
        "</div>"
        f"<p class=\"meta\" id=\"acctDeleteHint\">{_e(t['delete_account_p'])}</p>"
        f"<p class=\"meta\" id=\"acctDeleteSent\" hidden>{_e(t['delete_sent'])}</p>"
        "<script>"
        "(function(){"
        "function post(u){return fetch(u,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:'{}'});}"
        "document.getElementById('acctLogout').onclick=function(){post('/api/auth/logout').then(function(){location.href='/';});};"
        "document.getElementById('acctLogoutAll').onclick=function(){post('/api/auth/logout_all').then(function(){location.href='/';});};"
        "document.getElementById('acctDelete').onclick=function(){"
        "var b=this;b.disabled=true;post('/api/account/delete_request').then(function(){"
        "document.getElementById('acctDeleteSent').hidden=false;});};"
        "})();"
        "</script>"
    )
    return page_html(t, lang, t["history_title"], "".join(parts))
```

- [ ] **Step 4: Aggiungere route e helper in `audiobook_app.py`**

Subito dopo `api_auth_me` (Task 5):

```python
_ACCT_PER_PAGE = 50


def _account_downloads_for(row, now=None):
    """Link ancora vivi per una riga dello storico. Il token arriva dalla
    riga (`download_token`) o, per i job adottati dai pagamenti, dalla
    ricerca per job_id in _download_tokens. `expires_at` usa la retention
    effettiva del token (protezione no-download compresa)."""
    now = now if now is not None else time.time()
    job_id = row.get("job_id") or ""
    token = row.get("download_token") or ""
    info = _download_tokens.get(token) if token else None
    if info is None:
        for tok, ti in list(_download_tokens.items()):
            if isinstance(ti, dict) and ti.get("job_id") == job_id:
                token, info = tok, ti
                break
    if not isinstance(info, dict) or not token:
        return []
    try:
        expires_at = float(info.get("created_at") or 0) + float(_effective_retention_for_token_info(info))
    except Exception:  # noqa: BLE001
        return []
    if expires_at <= now:
        return []
    base = (BASE_URL or "").rstrip("/")
    exp = int(expires_at)
    out = [{"kind": "page", "url": f"{base}/dl/{token}", "expires_at": exp}]
    dl_type = info.get("download_type") or "audio"
    if dl_type == "optimized_abm":
        out.append({"kind": "abm", "url": f"{base}/dl/{token}/abm", "expires_at": exp})
    elif dl_type == "translated":
        out.append({"kind": "translated", "url": f"{base}/dl/{token}/translated", "expires_at": exp})
    elif info.get("output_m4b"):
        out.append({"kind": "m4b", "url": f"{base}/dl/{token}/m4b", "expires_at": exp})
    return out


def _account_rows_for(acct, page):
    rows, total = accounts.list_jobs(acct["id"], page=page, per_page=_ACCT_PER_PAGE)
    now = time.time()
    out = []
    for r in rows:
        d = dict(r)
        d["downloads"] = _account_downloads_for(d, now)
        out.append(d)
    return out, total


@app.route("/account", methods=["GET"])
def account_page_view():
    if not accounts.enabled() or not _smtp_available():
        abort(404)
    acct = _current_account()
    if not acct:
        return redirect("/?login=1", code=302)
    try:
        page = max(1, int(request.args.get("p") or 1))
    except ValueError:
        page = 1
    rows, total = _account_rows_for(acct, page)
    try:
        voices_count = len(voice_clone.ids_for_email(acct["email"]))
    except Exception:  # noqa: BLE001
        voices_count = 0
    lang = acct.get("lang") if acct.get("lang") in _ACCT_PAGES_I18N else _acct_page_lang()
    t = _acct_txt(lang)
    return _acct_html(account_page.render_history(
        t, lang=lang, account=acct, rows=rows, page=page, per_page=_ACCT_PER_PAGE,
        total=total, voices_count=voices_count))


@app.route("/api/account/jobs", methods=["GET"])
def api_account_jobs():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    try:
        page = max(1, int(request.args.get("p") or 1))
    except ValueError:
        page = 1
    rows, total = _account_rows_for(acct, page)
    jobs = [{
        "job_id": r["job_id"], "created_at": r.get("created_at"), "kind": r.get("kind"),
        "book_title": r.get("book_title") or "", "output_format": r.get("output_format") or "",
        "status": r.get("status"), "paid_eur": float(r.get("paid_eur") or 0),
        "downloads": r["downloads"],
    } for r in rows]
    return jsonify({"jobs": jobs, "total": total, "page": page, "per_page": _ACCT_PER_PAGE})


@app.route("/api/account/delete_request", methods=["POST"])
def api_account_delete_request():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    ip = _client_ip()
    allowed, retry = _ip_rl_check("auth_request", ip, 5, 30)
    if not allowed:
        return _acct_err("rate_limited", "Too many requests", 429, retry_after=retry)
    # L'email e' quella dell'account: il body viene ignorato (nessuna cancellazione per conto terzi).
    _acct_send_code(acct["email"], "delete", acct.get("lang") or "en")
    return jsonify({"ok": True})


@app.route("/api/account/delete_confirm", methods=["POST"])
def api_account_delete_confirm():
    gate = _acct_gate()
    if gate:
        return gate
    acct = _current_account()
    if not acct:
        return _acct_err("unauthorized", "Sign in required", 401)
    data = request.get_json(silent=True) or {}
    token = (data.get("token") or "").strip()
    code = (data.get("code") or "").strip()
    if token:
        status, target = accounts.verify(token=token, purpose="delete")
    elif code:
        status, target = accounts.verify(email=acct["email"], code=code, purpose="delete")
    else:
        return _acct_err("bad_request", "token or code required", 400)
    if status != "ok" or not target or target["id"] != acct["id"]:
        return _acct_err(status if status != "ok" else "wrong", "Verification failed", 401)
    _acct_do_delete(acct, acct.get("lang") or "en")
    resp = jsonify({"ok": True})
    _acct_clear_cookie(resp)
    return resp
```

`_acct_do_delete` e il suffisso `?p=delete` del link sono già definiti nel Task 5.

Nota su `accounts.verify` con `purpose="delete"`: per come è definito nel Task 2, `_login_or_get` con purpose `delete` richiede un account esistente non cancellato e non ne crea uno: la route confronta comunque `target["id"]` con la sessione corrente, così un codice di cancellazione di un altro account non può essere usato da una sessione diversa.

- [ ] **Step 5: Compilare ed eseguire i test**

Run: `python -m py_compile account_page.py`
Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_account_page.py test/test_account_routes.py -v --tb=short`
Expected: tutti PASS (11 nel file pagina)

- [ ] **Step 6: Commit**

```bash
git add account_page.py audiobook_app.py test/test_account_page.py
git commit -m "feat(account): pagina storico /account, API job e cancellazione self-service"
```

---

### Task 7: Notifica forzata all'email dell'account e registrazione dei job nello storico

**Files:**
- Modify: `audiobook_app.py` — `_register_paid_job_batch` :1362-1428 (fattorizzazione), `/api/generate` :12561 (subito prima del blocco `pending_jobs.register` di partenza, :13395), `/api/register_email` :13819, `/api/optimize` :15429 (validazione batch :15555, blocco notify :16155), `/api/translate` :16340 (validazione :16405, blocco notify :16490)
- Test: `test/test_account_forced_email.py`

**Interfaces:**
- Consumes: `accounts.enabled()`, `accounts.record_job(account_id, job_id, *, kind, book_title, output_format, voice, lang, paid_eur, source, status)`, `accounts.attach_if_known(job_id, email, **fields)`, `_current_account()` (Task 5), `_smtp_available()`, `_write_email_pending_marker`, `pending_jobs.register`, `_build_job_descriptor`, `payment.email_for_token`.
- Produces:
  - `_arm_email_delivery(job, job_id, email, *, lang="en", output_format=None, podcast_base_url="", pending_kind="", engine="") -> bool` — imposta i campi `notify_*`, `email_registered`, `_auto_batch_notify`, marker pending, descrittore di recupero se `pending_kind`; idempotente (False se già `email_registered`).
  - `_job_paid_eur(job) -> float`
  - `_job_book_title(job) -> str`
  - `_acct_forced_batch(batch, email) -> (bool, str)` — con sessione attiva e SMTP disponibile ritorna `(True, email_account)`, altrimenti gli argomenti invariati.
  - `_apply_account_to_job(job, job_id, kind, *, output_format=None, podcast_base_url="", voice="", lang="") -> dict|None` — se c'è una sessione: arma la consegna email (se non già armata) e registra il job nello storico (`source="forced"`, `status="running"`); ritorna l'account o None.
  - `/api/register_email` risponde 409 `{"error_code": "logged_in_email_forced", "email": <email account>}` se c'è una sessione e l'email nel body è diversa.

- [ ] **Step 1: Scrivere `test/test_account_forced_email.py`**

```python
# test/test_account_forced_email.py
"""Con sessione attiva ogni job va in modalita' email sull'indirizzo
dell'account e finisce nello storico; i job pagati agganciano lo storico
per email anche senza sessione."""
import json

import pytest

import accounts
import audiobook_app
import db
import email_service

CID = "cid-forced-000001"
HDR = {"X-ABM-Cid": CID}
T0 = 1_800_000_000


class _Info:
    title = "Il Gattopardo"
    author = "Tomasi"
    language = "it"
    chapters = []


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_write_email_pending_marker", lambda p: None)
    monkeypatch.setattr(audiobook_app.pending_jobs, "register", lambda *a, **k: None)
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: env.codes.append((email, kw)) or True)
    audiobook_app._ip_rl_buckets.pop("auth_request", None)
    audiobook_app.app.config["TESTING"] = True
    env.codes = []
    yield env
    for jid in list(audiobook_app.jobs):
        if jid.startswith("jt-"):
            audiobook_app.jobs.pop(jid, None)
    db.close()


def _login(client):
    client.post("/api/auth/request", json={"email": "a@b.it", "lang": "it"}, headers=HDR)
    code = env.codes[-1][1]["code"]
    r = client.post("/api/auth/verify", json={"email": "a@b.it", "code": code}, headers=HDR)
    assert r.status_code == 200
    return accounts.account_for_email("a@b.it")


def _job(jid, **extra):
    job = {"status": "analyzed", "client_id": CID, "info": _Info(), "original_filename": "g.epub",
           "browser_lang": "it"}
    job.update(extra)
    audiobook_app.jobs[jid] = job
    return job


def test_arm_email_delivery_sets_fields_once(env):
    job = _job("jt-1")
    with audiobook_app.app.test_request_context("/", headers=HDR):
        assert audiobook_app._arm_email_delivery(job, "jt-1", "x@y.it", lang="fr",
                                                 output_format="zip_rss", podcast_base_url="https://p") is True
        assert job["notify_email"] == "x@y.it" and job["notify_lang"] == "fr"
        assert job["notify_download_type"] == "podcast" and job["notify_base_url"] == "https://p"
        assert job["email_registered"] is True and job["_auto_batch_notify"] is True
        assert audiobook_app._arm_email_delivery(job, "jt-1", "other@y.it") is False
        assert job["notify_email"] == "x@y.it"


def test_register_paid_job_batch_attaches_history_by_email(env):
    acct = _login(audiobook_app.app.test_client())
    job = _job("jt-2", payment_amount_eur=3.5)
    with audiobook_app.app.test_request_context("/", headers=HDR):
        ok = audiobook_app._register_paid_job_batch("jt-2", job, "tok", engine="Gemini",
                                                    lang="it", email="A@B.it", output_format="m4b")
    assert ok is True
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 1 and rows[0]["job_id"] == "jt-2" and rows[0]["source"] == "payments"
    assert rows[0]["paid_eur"] == pytest.approx(3.5) and rows[0]["book_title"] == "Il Gattopardo"


def test_register_paid_job_batch_unknown_email_no_history(env):
    job = _job("jt-3")
    with audiobook_app.app.test_request_context("/", headers=HDR):
        audiobook_app._register_paid_job_batch("jt-3", job, "tok", email="nobody@b.it")
    assert accounts.account_for_email("nobody@b.it") is None


def test_apply_account_to_job_arms_and_records(env):
    acct = _login(audiobook_app.app.test_client())
    job = _job("jt-4", payment_amount_eur=1.25)
    sess = accounts.open_session(acct["id"])
    with audiobook_app.app.test_request_context("/", headers={**HDR, "Authorization": "Bearer " + sess}):
        out = audiobook_app._apply_account_to_job(job, "jt-4", "generate", output_format="m4b",
                                                  voice="it-IT-IsabellaNeural", lang="it")
    assert out and out["id"] == acct["id"]
    assert job["notify_email"] == "a@b.it" and job["email_registered"] is True
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 1
    r = rows[0]
    assert (r["kind"], r["status"], r["source"]) == ("generate", "running", "forced")
    assert r["output_format"] == "m4b" and r["voice"] == "it-IT-IsabellaNeural"
    assert r["paid_eur"] == pytest.approx(1.25) and r["book_title"] == "Il Gattopardo"


def test_apply_account_to_job_without_session_is_noop(env):
    job = _job("jt-5")
    with audiobook_app.app.test_request_context("/", headers=HDR):
        assert audiobook_app._apply_account_to_job(job, "jt-5", "generate") is None
    assert "notify_email" not in job


def test_apply_account_keeps_existing_manual_email(env):
    acct = _login(audiobook_app.app.test_client())
    job = _job("jt-6", notify_email="manual@x.it", email_registered=True)
    sess = accounts.open_session(acct["id"])
    with audiobook_app.app.test_request_context("/", headers={**HDR, "Authorization": "Bearer " + sess}):
        audiobook_app._apply_account_to_job(job, "jt-6", "optimize")
    assert job["notify_email"] == "manual@x.it"
    assert accounts.list_jobs(acct["id"])[1] == 1


def test_acct_forced_batch(env):
    acct = _login(audiobook_app.app.test_client())
    sess = accounts.open_session(acct["id"])
    with audiobook_app.app.test_request_context("/", headers={"Authorization": "Bearer " + sess}):
        assert audiobook_app._acct_forced_batch(False, "") == (True, "a@b.it")
        assert audiobook_app._acct_forced_batch(True, "x@y.it") == (True, "a@b.it")
    with audiobook_app.app.test_request_context("/"):
        assert audiobook_app._acct_forced_batch(False, "x@y.it") == (False, "x@y.it")


def test_register_email_409_when_logged_in_with_other_email(env):
    c = audiobook_app.app.test_client()
    _login(c)
    _job("jt-7", status="generating")
    r = c.post("/api/register_email", json={"job_id": "jt-7", "email": "other@x.it"}, headers=HDR)
    assert r.status_code == 409
    d = r.get_json()
    assert d["error_code"] == "logged_in_email_forced" and d["email"] == "a@b.it"
    r = c.post("/api/register_email", json={"job_id": "jt-7", "email": "A@B.it"}, headers=HDR)
    assert r.status_code == 200
    assert audiobook_app.jobs["jt-7"]["notify_email"] == "a@b.it"


def test_job_paid_eur_reads_both_pockets():
    f = audiobook_app._job_paid_eur
    assert f({}) == 0.0
    assert f({"payment_amount_eur": "2.5"}) == 2.5
    assert f({"payment": {"total_eur": 4}}) == 4.0
    assert f({"payment_amount_eur": 1, "payment": {"total_eur": 4}}) == 4.0
```

Nota: `_register_paid_job_batch` con `email=...` passato esplicitamente non consulta `payment.email_for_token`; il test lo usa così per non dipendere da `_payments.json`. `_voice_for_log` (:2905) è l'helper esistente che normalizza il descrittore voce per il log; `auto_generate`, `lang`, `out_format` sono variabili già presenti nelle route indicate.

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_account_forced_email.py -v --tb=short`
Expected: FAIL con `AttributeError: module 'audiobook_app' has no attribute '_arm_email_delivery'` (e simili per gli altri helper); `test_register_email_409...` fallisce con 200.

- [ ] **Step 3: Fattorizzare `_register_paid_job_batch`**

Sostituire il corpo da `job["notify_email"] = _pay_email` fino al `return True` (righe :1405-1428) con:

```python
    armed = _arm_email_delivery(job, job_id, _pay_email, lang=lang,
                                output_format=output_format,
                                podcast_base_url=podcast_base_url,
                                pending_kind=pending_kind, engine=engine)
    # Storico account: un pagamento con email nota aggancia il job all'account
    # (se esiste) anche senza sessione; e' l'adozione "in corso d'opera".
    try:
        if accounts.enabled() and accounts.attach_if_known(
                job_id, _pay_email, kind=pending_kind or "generate",
                book_title=_job_book_title(job), output_format=output_format or "",
                lang=lang or "", paid_eur=_job_paid_eur(job)):
            _acct_log("ACCOUNT_ADOPT", _pay_email, job_id)
    except Exception as _e:
        print(f"[{job_id}] accounts.attach_if_known failed (non-fatal): {_e}", flush=True)
    return armed
```

e inserire **prima** di `_register_paid_job_batch` le nuove funzioni:

```python
def _job_paid_eur(job):
    """Importo incassato per il job: pocket `payment.total_eur` (price lock D1)
    o, in sua assenza, `payment_amount_eur`."""
    try:
        pocket = job.get("payment") or {}
        v = pocket.get("total_eur")
        if v is None:
            v = job.get("payment_amount_eur")
        return float(v or 0)
    except Exception:
        return 0.0


def _job_book_title(job):
    info = job.get("info")
    return (getattr(info, "title", "") or job.get("original_filename", "") or "")[:200]


def _arm_email_delivery(job, job_id, email, *, lang="en", output_format=None,
                        podcast_base_url="", pending_kind="", engine=""):
    """Porta il job in modalita' email sull'indirizzo dato: notifica a fine
    lavoro, esenzione dall'heartbeat (`email_registered`), marker pending e
    descrittore di recupero. Idempotente: se un'email e' gia' registrata non
    tocca nulla. Usata dal batch implicito dei job pagati e dalla notifica
    forzata degli utenti con account."""
    if job.get("email_registered"):
        return False
    email = (email or "").strip()
    if not email:
        return False
    job["notify_email"] = email
    if output_format is not None:
        job.setdefault("notify_download_type",
                       "podcast" if output_format == "zip_rss" else "audio")
        job.setdefault("notify_base_url", podcast_base_url or "")
    job["notify_lang"] = lang or "en"
    job["email_registered"] = True
    job["_auto_batch_notify"] = True
    _write_email_pending_marker(UPLOAD_DIR / job_id)
    if pending_kind:
        try:
            pending_jobs.register(job_id, pending_kind,
                                  _build_job_descriptor(job, pending_kind))
        except Exception as _e:
            print(f"[{job_id}] pending_jobs.register ({engine or 'batch'}) "
                  f"failed (non-fatal): {_e}", flush=True)
    print(f"[{job_id}] {engine or 'batch'} -> email mode (notify {email}, "
          f"heartbeat disabilitato)", flush=True)
    return True


def _acct_forced_batch(batch, email):
    """Notifica forzata: con sessione attiva il job e' sempre batch
    sull'email dell'account, qualunque cosa dica il body."""
    try:
        if accounts.enabled() and _smtp_available():
            acct = _current_account()
            if acct:
                return True, acct["email"]
    except Exception as _e:
        print(f"WARNING _acct_forced_batch: {_e}", flush=True)
    return batch, email


def _apply_account_to_job(job, job_id, kind, *, output_format=None, podcast_base_url="",
                          voice="", lang=""):
    """Se la richiesta ha una sessione: consegna via email all'account (senza
    descrittore: lo scrive la partenza) e riga nello storico. Best-effort."""
    try:
        if not accounts.enabled() or not _smtp_available():
            return None
        acct = _current_account()
        if not acct:
            return None
        _arm_email_delivery(job, job_id, acct["email"], lang=acct.get("lang") or lang or "en",
                            output_format=output_format, podcast_base_url=podcast_base_url,
                            pending_kind="", engine="account")
        accounts.record_job(acct["id"], job_id, kind=kind, book_title=_job_book_title(job),
                            output_format=output_format or "", voice=voice or "",
                            lang=lang or "", paid_eur=_job_paid_eur(job),
                            source="forced", status="running")
        return acct
    except Exception as _e:
        print(f"[{job_id}] _apply_account_to_job failed (non-fatal): {_e}", flush=True)
        return None
```

Nota d'ordine: `_acct_log`, `_current_account` e `_smtp_available` sono definiti più avanti nel file (Task 5, sezione dopo `_hash_ip`); sono risolti a runtime, non all'import, quindi l'ordine è indifferente.

- [ ] **Step 4: Agganciare `/api/generate`**

Subito **prima** del blocco (:13395):

```python
    if job.get("email_registered") and job.get("notify_download_type") != "translated":
        try:
            pending_jobs.register(job_id, "generate", _build_job_descriptor(job, "generate"))
```

inserire:

```python
    # Account: consegna forzata all'email dell'account + riga nello storico.
    # Prima del descrittore di partenza, cosi' lo cattura gia' in modalita' email.
    _apply_account_to_job(job, job_id, "generate", output_format=output_format,
                          podcast_base_url=podcast_base_url, voice=_voice_for_log(voice),
                          lang=(data.get("lang") or job.get("browser_lang") or "en"))
```

- [ ] **Step 5: Agganciare `/api/optimize`**

Subito **prima** di `if batch:` della validazione (:15555, commento "Batch mode validation"):

```python
    batch, email = _acct_forced_batch(batch, email)
```

Dopo il blocco di assegnazione notify (:16155-16159, `if batch: job["notify_email"] = email ...`), prima di `# Store auto-generate params for batch mode`:

```python
    _apply_account_to_job(job, job_id, "optimize",
                          output_format=(data.get("output_format", "m4b") if auto_generate else None),
                          podcast_base_url=(data.get("podcast_base_url") or "").strip(),
                          voice=(_voice_for_log(data.get("voice", "")) if auto_generate else ""),
                          lang=(lang or "en"))
```

- [ ] **Step 6: Agganciare `/api/translate`**

Dopo `email = (data.get("email") or "").strip()` (:16406) e prima di `if batch:`:

```python
    batch, email = _acct_forced_batch(batch, email)
```

Dopo il blocco notify (:16490-16494, che termina con `job["notify_download_type"] = "translated"`), prima di `job["tr_cancelled"] = False`:

```python
    _apply_account_to_job(job, job_id, "translate", output_format=out_format,
                          lang=(data.get("lang") or "en"))
```

`out_format` è la variabile già presente nella route (usata in `tr_params`).

- [ ] **Step 7: Agganciare `/api/register_email`**

Dopo il controllo del formato email e prima di `if not _smtp_available():` (:13836):

```python
    # Con sessione attiva la notifica e' vincolata all'email dell'account.
    try:
        _acct = _current_account() if accounts.enabled() else None
    except Exception:
        _acct = None
    if _acct and _acct["email"] != email:
        return jsonify({"error": "Notifications go to your account email",
                        "error_code": "logged_in_email_forced",
                        "email": _acct["email"]}), 409
```

- [ ] **Step 8: Compilare ed eseguire i test**

Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_account_forced_email.py test/test_account_routes.py -v --tb=short`
Run: `pytest test/ -x -q -k "paid or batch or register_email or heartbeat"` (regressioni sui path del batch implicito)
Expected: tutti PASS

- [ ] **Step 9: Commit**

```bash
git add audiobook_app.py test/test_account_forced_email.py
git commit -m "feat(account): notifica forzata all'email dell'account e storico dai flussi generate/optimize/translate"
```

---

### Task 8: Hook di stato e token in `generation_engine`

**Files:**
- Modify: `generation_engine.py` — default globali :222-227, `_set_job_status` :425, `configure` :484, `_create_download_token` :1889 (prima del `return token` finale :1940), siti token :2299 (`optimized_abm`, dopo `_save_tokens()`), :3612 (`translated`, dopo `_save_tokens()`), :7471 (parziale, dopo `_save_tokens()`)
- Modify: `audiobook_app.py` — chiamata `generation_engine.configure(...)` :19981
- Test: `test/test_account_engine_hooks.py`

**Interfaces:**
- Consumes: `accounts.update_status(job_id, status, download_token="") -> bool`, `accounts.set_download_token(job_id, token) -> bool`.
- Produces: `generation_engine.configure(..., account_job_status_fn=None, account_token_fn=None)`; globali `_account_job_status`, `_account_token`; helper `_account_notify_status(job, status)` e `_account_notify_token(job_id, token)` (best-effort, mai sollevano).

- [ ] **Step 1: Scrivere `test/test_account_engine_hooks.py`**

```python
# test/test_account_engine_hooks.py
"""Gli esiti dei job e i token di download arrivano allo storico account
tramite due callback iniettate con configure(); mai fatali."""
import pytest

import accounts
import audiobook_app  # noqa: F401  (configura generation_engine all'import)
import generation_engine as ge


@pytest.fixture
def hooks(monkeypatch):
    calls = {"status": [], "token": []}
    monkeypatch.setattr(ge, "_account_job_status", lambda jid, st: calls["status"].append((jid, st)))
    monkeypatch.setattr(ge, "_account_token", lambda jid, tok: calls["token"].append((jid, tok)))
    return calls


def test_configure_wires_accounts_functions():
    assert ge._account_job_status is accounts.update_status
    assert ge._account_token is accounts.set_download_token


@pytest.mark.parametrize("status,expected", [
    ("done", "done"), ("partial", "done"), ("error", "error"),
    ("cancelled", "cancelled"), ("canceled", "cancelled"),
])
def test_terminal_status_reaches_hook(hooks, status, expected):
    job = {"job_id": "jh-1"}
    ge._set_job_status(job, status)
    assert hooks["status"] == [("jh-1", expected)]


def test_non_terminal_status_does_not_call_hook(hooks):
    ge._set_job_status({"job_id": "jh-2"}, "generating")
    assert hooks["status"] == []


def test_hook_exception_is_swallowed(monkeypatch):
    def boom(jid, st):
        raise RuntimeError("db down")
    monkeypatch.setattr(ge, "_account_job_status", boom)
    job = {"job_id": "jh-3"}
    ge._set_job_status(job, "done")
    assert job["status"] == "done"


def test_hook_none_is_fine(monkeypatch):
    monkeypatch.setattr(ge, "_account_job_status", None)
    monkeypatch.setattr(ge, "_account_token", None)
    ge._set_job_status({"job_id": "jh-4"}, "done")
    ge._account_notify_token("jh-4", "tok")


def test_create_download_token_notifies(hooks, monkeypatch, tmp_path):
    jobs = {"jh-5": {"status": "done", "info": None, "original_filename": "x.epub",
                     "output_files": [str(tmp_path / "a.mp3")], "voice": "it-IT-IsabellaNeural"}}
    tokens = {}
    monkeypatch.setattr(ge, "_jobs", jobs)
    monkeypatch.setattr(ge, "_download_tokens", tokens)
    monkeypatch.setattr(ge, "_save_tokens", lambda: None)
    tok = ge._create_download_token("jh-5")
    assert tok and tokens[tok]["job_id"] == "jh-5"
    assert hooks["token"] == [("jh-5", tok)]
    assert ge._create_download_token("jh-5") == tok
    assert hooks["token"] == [("jh-5", tok)]  # il riuso idempotente non rinotifica


def test_token_sites_in_source_notify():
    src = open("generation_engine.py", encoding="utf-8").read()
    for marker in ('"download_type": "optimized_abm"', '"download_type": "translated"',
                   '"partial_cancel": True'):
        i = src.index(marker)
        window = src[i:i + 1500]
        assert "_account_notify_token(job_id, token)" in window, marker
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_account_engine_hooks.py -v --tb=short`
Expected: FAIL con `AttributeError: module 'generation_engine' has no attribute '_account_job_status'`

- [ ] **Step 3: Aggiungere globali, helper e hook in `generation_engine.py`**

Dopo `_client_gen_cap_reached = None` (:227):

```python
# Storico account (accounts.py): esito terminale del job e token di download.
_account_job_status = None  # callable(job_id, status) -> bool
_account_token = None       # callable(job_id, token) -> bool


def _account_notify_status(job, status):
    """Riporta l'esito allo storico account. `partial` vale come consegna."""
    if _account_job_status is None or not isinstance(job, dict):
        return
    try:
        jid = job.get("job_id") or _job_id_for(job)
        if not jid:
            return
        st = {"partial": "done", "canceled": "cancelled"}.get(status, status)
        _account_job_status(jid, st)
    except Exception as e:  # noqa: BLE001
        print(f"[account] status hook failed (non-fatal): {e}", flush=True)


def _account_notify_token(job_id, token):
    if _account_token is None or not job_id or not token:
        return
    try:
        _account_token(job_id, token)
    except Exception as e:  # noqa: BLE001
        print(f"[{job_id}] account token hook failed (non-fatal): {e}", flush=True)
```

`_job_id_for` è definito a :414, dopo questo punto: è una chiamata a runtime, l'ordine di definizione non conta.

In `_set_job_status`, in coda alla funzione (dopo il blocco telemetria `load_metrics`):

```python
    if status in _TERMINAL_STATUSES:
        _account_notify_status(job, status)
```

In `configure` (:484): aggiungere alla firma i due kwarg `account_job_status_fn=None, account_token_fn=None`, al `global` i nomi `_account_job_status, _account_token`, e in coda al corpo:

```python
    if account_job_status_fn is not None:
        _account_job_status = account_job_status_fn
    if account_token_fn is not None:
        _account_token = account_token_fn
```

In `_create_download_token`, sostituire il finale `_save_tokens()\n    return token` (:1939-1940) con:

```python
    _save_tokens()
    _account_notify_token(job_id, token)
    return token
```

Nei tre siti inline, subito dopo la rispettiva `_save_tokens()`:
- :2299 (`optimized_abm`, riga `_save_tokens()` seguita da `job["email_token"] = token`): aggiungere `_account_notify_token(job_id, token)`.
- :3612 (`translated`, stesso schema): aggiungere `_account_notify_token(job_id, token)`.
- :7471 (parziale su cancel, dentro il `try`): dopo `_save_tokens()` aggiungere `_account_notify_token(job_id, token)`.

- [ ] **Step 4: Cablare in `audiobook_app.py`**

Nella chiamata `generation_engine.configure(` (:19981) aggiungere dopo `client_gen_cap_fn=_client_gen_cap_reached`:

```python
    client_gen_cap_fn=_client_gen_cap_reached,
    account_job_status_fn=accounts.update_status,
    account_token_fn=accounts.set_download_token,
```

- [ ] **Step 5: Compilare ed eseguire i test**

Run: `python -m py_compile generation_engine.py`
Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_account_engine_hooks.py test/test_accounts.py -v --tb=short`
Run: `pytest test/ -q -x --tb=short` (suite completa: `_set_job_status` è sul percorso di tutti i job)
Expected: tutti PASS

- [ ] **Step 6: Commit**

```bash
git add generation_engine.py audiobook_app.py test/test_account_engine_hooks.py
git commit -m "feat(account): esiti dei job e token di download riportati nello storico account"
```

---

### Task 9: SPA — bottone account, modale di login, notifica forzata nel frontend

**Files:**
- Modify: `templates/_fragments/html_head.html` — toolbar :129-149 (prima di `<div class="theme-sep"></div>` :147), modali dopo `#ttsQuotaModal` :1426-1443
- Modify: `static/css/style.css` — dopo `.theme-btn` :85-86
- Modify: `static/js/app.js` — `_showAutoBatchNotice` :4329, `_lockEmailLateBoxAutoBatch` :4350, `submitEmailLate` :5865, `submitEmailLateTr` :3333, `DOMContentLoaded` :485 (dopo `_restoreActiveJob()`), nuova sezione ACCOUNT in coda al file
- Modify: `templates/_fragments/i18n_data.js` — sette blocchi lingua (`it:{` :3, `en:{` :7, `fr:{` :11, `es:{` :15, `de:{` :19, `zh:{` :23, `hi:{` :26); ogni blocco è una riga lunga: inserire le nuove chiavi subito **prima** di `tts_quota_title:` (presente in tutti e sette)
- Test: `test/test_app_js_account.py`

Nota: la cartella `i18n/` contiene solo `download_pages.json`, `voice_clone_*.json` (e i nuovi `account_*.json` dei Task 4-5). Le stringhe della SPA vivono **solo** in `i18n_data.js`.

**Interfaces:**
- Consumes: `GET /api/auth/me` → `{logged_in, enabled, email?, lang?, plan?}`; `POST /api/auth/request {email, lang}` → `{ok:true}` | 429; `POST /api/auth/verify {email, code}` → `{ok, email, ...}` | 401 `{error_code: wrong|expired|locked|none}`; `POST /api/auth/logout`; `/api/register_email` 409 `error_code: logged_in_email_forced`; `/api/generate` risponde `auto_batch_email` (mascherata) anche per la notifica forzata dell'account (Task 7 imposta `_auto_batch_notify`).
- Produces (JS globali): `_acctMe` (ultimo payload di `/api/auth/me` o `null`), `_acctBoot()`, `_acctRender()`, `openLoginModal()`, `closeLoginModal()`, `_acctRequest()`, `_acctVerify()`, `_acctLogout()`, `_acctApplyForcedEmail()`, `_acctLoggedIn()`; chiavi i18n `acct_*`.

Comportamento:
- Bottone `#acctBtn` nella toolbar (icona utente). Non loggato → apre `#loginModal`. Loggato → apre/chiude `#acctMenu` (email, link "Storico" → `/account`, "Esci").
- Modale login in due fasi: email → "Invia codice"; poi campo codice a 6 cifre → "Accedi". Il messaggio ricorda che il link nell'email funziona ugualmente.
- `?login=1` nell'URL (redirect di `/account` senza sessione) → apre la modale; al login riuscito naviga a `/account`.
- Loggato: `_acctApplyForcedEmail()` nasconde `#emailLateArea`, `#emailLateAreaTr`, `#payEmailNotice` e mostra il banner "Le notifiche vanno a {email}" (`#acctForcedNotice`) sopra `#generationProgress`; `_showAutoBatchNotice` usa `acct_forced_notice` invece di `auto_batch_notify` e non aggiunge il link "cambia indirizzo".
- `submitEmailLate*`: su `error_code==='logged_in_email_forced'` mostra `acct_forced_notice` con l'email e non `alert`.
- Il bottone e la modale sono nascosti se `/api/auth/me` risponde `enabled:false` o non risponde.

- [ ] **Step 1: Scrivere `test/test_app_js_account.py`**

```python
# test/test_app_js_account.py
"""La SPA espone login/logout via magic link + codice e, da loggata, vincola
le notifiche all'email dell'account. Test statici sul sorgente JS/HTML,
piu' `node --check` se node e' disponibile."""
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path("static/js/app.js").read_text(encoding="utf-8")
HEAD = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")

ACCT_KEYS = [
    "acct_login", "acct_logout", "acct_history", "acct_modal_title", "acct_modal_intro",
    "acct_email_ph", "acct_send_code", "acct_code_ph", "acct_code_intro", "acct_verify",
    "acct_sent", "acct_err_wrong", "acct_err_expired", "acct_err_locked", "acct_err_none",
    "acct_err_rate", "acct_err_generic", "acct_forced_notice", "acct_signed_in_as",
]


def _extract_fn(name):
    marker = "function %s(" % name
    start = APP.find(marker)
    assert start >= 0, "%s non trovata" % name
    depth = 0
    i = APP.index("{", start)
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError("parentesi non bilanciate in %s" % name)


def test_markup_has_button_menu_and_modal():
    assert 'id="acctBtn"' in HEAD and 'id="acctMenu"' in HEAD
    assert 'id="loginModal"' in HEAD and 'id="acctEmail"' in HEAD and 'id="acctCode"' in HEAD
    assert 'id="acctForcedNotice"' in HEAD
    # il bottone sta nella toolbar, prima del separatore del tema
    assert HEAD.index('id="acctBtn"') < HEAD.index('<div class="theme-sep"></div>')
    # nascosto finche' /api/auth/me non conferma la feature
    m = re.search(r'<button[^>]*id="acctBtn"[^>]*>', HEAD)
    assert m and "display:none" in m.group(0)


def test_boot_queries_me_and_handles_login_param():
    fn = _extract_fn("_acctBoot")
    assert "/api/auth/me" in fn
    assert "login=1" in fn
    assert "_acctApplyForcedEmail()" in fn or "_acctRender()" in fn


def test_boot_is_called_at_dom_ready():
    i = APP.index("_restoreActiveJob();")
    assert "_acctBoot()" in APP[i:i + 400]


def test_request_and_verify_hit_auth_endpoints():
    assert "'/api/auth/request'" in _extract_fn("_acctRequest")
    v = _extract_fn("_acctVerify")
    assert "'/api/auth/verify'" in v
    for code in ("wrong", "expired", "locked", "none"):
        assert "acct_err_" + code in v
    assert "_acctAfterLogin" in v
    assert "location.href='/account'" in _extract_fn("_acctBoot")


def test_logout_hits_endpoint_and_rerenders():
    fn = _extract_fn("_acctLogout")
    assert "'/api/auth/logout'" in fn and "_acctRender()" in fn


def test_forced_email_hides_manual_inputs():
    fn = _extract_fn("_acctApplyForcedEmail")
    for el in ("emailLateArea", "emailLateAreaTr", "payEmailNotice", "acctForcedNotice"):
        assert el in fn, el


@pytest.mark.parametrize("fn_name", ["submitEmailLate", "submitEmailLateTr"])
def test_register_email_handles_forced_conflict(fn_name):
    fn = _extract_fn(fn_name)
    assert "logged_in_email_forced" in fn
    # il conflitto non deve finire nell'alert generico
    assert fn.index("logged_in_email_forced") < fn.index("alert(d.error)")


def test_auto_batch_notice_uses_account_wording_when_logged_in():
    fn = _extract_fn("_showAutoBatchNotice")
    assert "_acctLoggedIn()" in fn and "acct_forced_notice" in fn
    lock = _extract_fn("_lockEmailLateBoxAutoBatch")
    assert "_acctLoggedIn()" in lock  # niente link "cambia indirizzo"


@pytest.mark.parametrize("key", ACCT_KEYS)
def test_i18n_key_in_all_seven_languages(key):
    assert len(re.findall(r"\b%s:" % key, I18N)) == 7, key


def test_i18n_no_provider_names_in_account_strings():
    for line in I18N.splitlines():
        if "acct_" in line:
            assert not re.search(r"DeepSeek|Gemini|Speechify|VoxCPM", line)


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_js_syntax():
    for f in ("static/js/app.js", "templates/_fragments/i18n_data.js"):
        subprocess.run(["node", "--check", f], check=True)
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_app_js_account.py -v --tb=short`
Expected: FAIL (`acctBtn` assente, `_acctBoot non trovata`, chiavi i18n a 0 occorrenze)

- [ ] **Step 3: Markup in `html_head.html`**

Nella toolbar, subito **prima** di `<div class="theme-sep"></div>` (:147):

```html
      <div class="acct-wrap" id="acctWrap">
        <button class="theme-btn acct-btn" id="acctBtn" style="display:none" title="Account" aria-label="Account" aria-haspopup="true" aria-expanded="false" onclick="_acctBtnClick()">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
        </button>
        <div class="acct-menu" id="acctMenu" role="menu" style="display:none">
          <div class="acct-menu-email" id="acctMenuEmail"></div>
          <a class="acct-menu-item" href="/account" role="menuitem" data-t="acct_history"></a>
          <button class="acct-menu-item" type="button" role="menuitem" onclick="_acctLogout()" data-t="acct_logout"></button>
        </div>
      </div>
```

Dopo la chiusura di `#ttsQuotaModal` (:1443), aggiungere:

```html
  <div class="modal-overlay" id="loginModal" role="dialog" aria-modal="true" aria-labelledby="acctModalTitle" onclick="if(event.target===this)closeLoginModal()">
    <div class="modal" style="max-width:440px">
      <div class="modal-head">
        <span data-t="acct_modal_title" id="acctModalTitle"></span>
        <button class="modal-close" onclick="closeLoginModal()" aria-label="Close">&times;</button>
      </div>
      <div class="modal-body">
        <div id="acctStepEmail">
          <p data-t="acct_modal_intro" style="margin:0 0 12px;line-height:1.6;font-size:.92rem"></p>
          <input type="email" id="acctEmail" placeholder="" autocomplete="email" aria-label="Email" style="width:100%;box-sizing:border-box;margin-bottom:10px" onkeydown="if(event.key==='Enter'){event.preventDefault();_acctRequest()}">
        </div>
        <div id="acctStepCode" style="display:none">
          <p id="acctCodeIntro" style="margin:0 0 12px;line-height:1.6;font-size:.92rem"></p>
          <input type="text" id="acctCode" inputmode="numeric" pattern="[0-9]*" maxlength="6" autocomplete="one-time-code" placeholder="" aria-label="Code" style="width:100%;box-sizing:border-box;margin-bottom:10px;letter-spacing:.3em;font-size:1.2rem;text-align:center" onkeydown="if(event.key==='Enter'){event.preventDefault();_acctVerify()}">
        </div>
        <div id="acctErr" style="color:var(--err,#c0392b);font-size:.85rem;margin:0 0 10px;display:none"></div>
        <div style="display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end">
          <button class="btn btn-outline" onclick="closeLoginModal()" data-t="btn_cancel"></button>
          <button class="btn btn-ok" id="acctSendBtn" onclick="_acctRequest()" data-t="acct_send_code"></button>
          <button class="btn btn-ok" id="acctVerifyBtn" onclick="_acctVerify()" data-t="acct_verify" style="display:none"></button>
        </div>
      </div>
    </div>
  </div>
```

Il banner della notifica forzata viene creato da JS (come `#autoBatchNotice`), ma per i test statici e l'i18n mettiamo il contenitore vuoto nel markup. Subito **prima** del nodo `<div class="email-late-area" id="emailLateArea">` (:756):

```html
        <div class="al al-ok" id="acctForcedNotice" style="display:none;margin-top:10px"></div>
```

- [ ] **Step 4: CSS in `style.css`**

Dopo la riga `[data-theme="dark"] .theme-btn{...}` (:86):

```css
.acct-wrap{position:relative;flex-shrink:0}
.acct-btn.on{color:var(--ac,#b5651d);border-color:currentColor}
.acct-menu{position:absolute;right:0;top:34px;min-width:200px;background:var(--srf);border:1px solid var(--brd);border-radius:var(--rs);box-shadow:0 8px 24px rgba(0,0,0,.18);padding:6px;z-index:900;display:flex;flex-direction:column;gap:2px}
.acct-menu-email{font-size:.78rem;color:var(--txm);padding:6px 10px;border-bottom:1px solid var(--brd);margin-bottom:4px;word-break:break-all}
.acct-menu-item{display:block;width:100%;text-align:left;background:none;border:0;padding:8px 10px;border-radius:6px;font:inherit;font-size:.88rem;color:var(--tx);cursor:pointer;text-decoration:none}
.acct-menu-item:hover{background:var(--srf2)}
```

- [ ] **Step 5: Chiavi i18n in `i18n_data.js`**

In ognuno dei sette blocchi, inserire il frammento della lingua subito **prima** di `tts_quota_title:` (stessa riga; le chiavi terminano con virgola).

it (:3):
```js
acct_login:"Accedi",acct_logout:"Esci",acct_history:"I miei audiolibri",acct_modal_title:"Accedi o crea un account",acct_modal_intro:"Niente password: ti inviamo via email un link e un codice a 6 cifre. Con l'account ritrovi i tuoi audiolibri e ricevi ogni lavoro via email.",acct_email_ph:"La tua email",acct_send_code:"Invia codice",acct_code_ph:"Codice a 6 cifre",acct_code_intro:"Abbiamo inviato un codice a {email}. Inseriscilo qui oppure apri il link nell'email (vale 10 minuti).",acct_verify:"Accedi",acct_sent:"Codice inviato.",acct_err_wrong:"Codice errato.",acct_err_expired:"Codice scaduto: richiedine uno nuovo.",acct_err_locked:"Troppi tentativi: richiedi un nuovo codice.",acct_err_none:"Nessun codice attivo: richiedine uno nuovo.",acct_err_rate:"Troppe richieste: riprova tra qualche minuto.",acct_err_generic:"Errore imprevisto, riprova.",acct_forced_notice:"Sei connesso: riceverai il risultato via email a {email}. Puoi chiudere questa pagina.",acct_signed_in_as:"Connesso come {email}",
```

en (:7):
```js
acct_login:"Sign in",acct_logout:"Sign out",acct_history:"My audiobooks",acct_modal_title:"Sign in or create an account",acct_modal_intro:"No password: we email you a link and a 6-digit code. With an account you can find your audiobooks again and every job is delivered by email.",acct_email_ph:"Your email",acct_send_code:"Send code",acct_code_ph:"6-digit code",acct_code_intro:"We sent a code to {email}. Enter it here or open the link in the email (valid for 10 minutes).",acct_verify:"Sign in",acct_sent:"Code sent.",acct_err_wrong:"Wrong code.",acct_err_expired:"Code expired: request a new one.",acct_err_locked:"Too many attempts: request a new code.",acct_err_none:"No active code: request a new one.",acct_err_rate:"Too many requests: try again in a few minutes.",acct_err_generic:"Unexpected error, please retry.",acct_forced_notice:"You are signed in: the result will be emailed to {email}. You can close this page.",acct_signed_in_as:"Signed in as {email}",
```

fr (:11):
```js
acct_login:"Se connecter",acct_logout:"Se déconnecter",acct_history:"Mes livres audio",acct_modal_title:"Se connecter ou créer un compte",acct_modal_intro:"Sans mot de passe : nous vous envoyons par e-mail un lien et un code à 6 chiffres. Avec un compte, vous retrouvez vos livres audio et chaque travail vous est livré par e-mail.",acct_email_ph:"Votre e-mail",acct_send_code:"Envoyer le code",acct_code_ph:"Code à 6 chiffres",acct_code_intro:"Nous avons envoyé un code à {email}. Saisissez-le ici ou ouvrez le lien dans l'e-mail (valable 10 minutes).",acct_verify:"Se connecter",acct_sent:"Code envoyé.",acct_err_wrong:"Code incorrect.",acct_err_expired:"Code expiré : demandez-en un nouveau.",acct_err_locked:"Trop de tentatives : demandez un nouveau code.",acct_err_none:"Aucun code actif : demandez-en un nouveau.",acct_err_rate:"Trop de demandes : réessayez dans quelques minutes.",acct_err_generic:"Erreur inattendue, veuillez réessayer.",acct_forced_notice:"Vous êtes connecté : le résultat sera envoyé par e-mail à {email}. Vous pouvez fermer cette page.",acct_signed_in_as:"Connecté en tant que {email}",
```

es (:15):
```js
acct_login:"Iniciar sesión",acct_logout:"Cerrar sesión",acct_history:"Mis audiolibros",acct_modal_title:"Inicia sesión o crea una cuenta",acct_modal_intro:"Sin contraseña: te enviamos por correo un enlace y un código de 6 cifras. Con la cuenta recuperas tus audiolibros y recibes cada trabajo por correo.",acct_email_ph:"Tu correo",acct_send_code:"Enviar código",acct_code_ph:"Código de 6 cifras",acct_code_intro:"Hemos enviado un código a {email}. Introdúcelo aquí o abre el enlace del correo (válido 10 minutos).",acct_verify:"Entrar",acct_sent:"Código enviado.",acct_err_wrong:"Código incorrecto.",acct_err_expired:"Código caducado: solicita uno nuevo.",acct_err_locked:"Demasiados intentos: solicita un código nuevo.",acct_err_none:"No hay ningún código activo: solicita uno nuevo.",acct_err_rate:"Demasiadas solicitudes: inténtalo de nuevo en unos minutos.",acct_err_generic:"Error inesperado, vuelve a intentarlo.",acct_forced_notice:"Has iniciado sesión: recibirás el resultado por correo en {email}. Puedes cerrar esta página.",acct_signed_in_as:"Sesión iniciada como {email}",
```

de (:19):
```js
acct_login:"Anmelden",acct_logout:"Abmelden",acct_history:"Meine Hörbücher",acct_modal_title:"Anmelden oder Konto erstellen",acct_modal_intro:"Kein Passwort: Wir schicken dir per E-Mail einen Link und einen 6-stelligen Code. Mit einem Konto findest du deine Hörbücher wieder und erhältst jeden Auftrag per E-Mail.",acct_email_ph:"Deine E-Mail",acct_send_code:"Code senden",acct_code_ph:"6-stelliger Code",acct_code_intro:"Wir haben einen Code an {email} gesendet. Gib ihn hier ein oder öffne den Link in der E-Mail (10 Minuten gültig).",acct_verify:"Anmelden",acct_sent:"Code gesendet.",acct_err_wrong:"Falscher Code.",acct_err_expired:"Code abgelaufen: Fordere einen neuen an.",acct_err_locked:"Zu viele Versuche: Fordere einen neuen Code an.",acct_err_none:"Kein aktiver Code: Fordere einen neuen an.",acct_err_rate:"Zu viele Anfragen: Versuche es in ein paar Minuten erneut.",acct_err_generic:"Unerwarteter Fehler, bitte erneut versuchen.",acct_forced_notice:"Du bist angemeldet: Das Ergebnis geht per E-Mail an {email}. Du kannst diese Seite schließen.",acct_signed_in_as:"Angemeldet als {email}",
```

zh (:23):
```js
acct_login:"登录",acct_logout:"退出登录",acct_history:"我的有声书",acct_modal_title:"登录或创建账户",acct_modal_intro:"无需密码：我们会通过电子邮件发送一个链接和一个6位数验证码。有了账户，您可以找回您的有声书，每项任务都会通过邮件送达。",acct_email_ph:"您的邮箱",acct_send_code:"发送验证码",acct_code_ph:"6位数验证码",acct_code_intro:"验证码已发送至 {email}。请在此输入，或打开邮件中的链接（10分钟内有效）。",acct_verify:"登录",acct_sent:"验证码已发送。",acct_err_wrong:"验证码错误。",acct_err_expired:"验证码已过期：请重新获取。",acct_err_locked:"尝试次数过多：请重新获取验证码。",acct_err_none:"没有有效的验证码：请重新获取。",acct_err_rate:"请求过于频繁：请几分钟后再试。",acct_err_generic:"发生意外错误，请重试。",acct_forced_notice:"您已登录：结果将发送至 {email}。您可以关闭此页面。",acct_signed_in_as:"已登录：{email}",
```

hi (:26):
```js
acct_login:"साइन इन करें",acct_logout:"साइन आउट करें",acct_history:"मेरी ऑडियोबुक्स",acct_modal_title:"साइन इन करें या खाता बनाएँ",acct_modal_intro:"कोई पासवर्ड नहीं: हम आपको ईमेल से एक लिंक और 6 अंकों का कोड भेजते हैं। खाते के साथ आप अपनी ऑडियोबुक्स दोबारा पा सकते हैं और हर काम ईमेल से मिलता है।",acct_email_ph:"आपका ईमेल",acct_send_code:"कोड भेजें",acct_code_ph:"6 अंकों का कोड",acct_code_intro:"हमने {email} पर एक कोड भेजा है। इसे यहाँ दर्ज करें या ईमेल का लिंक खोलें (10 मिनट तक मान्य)।",acct_verify:"साइन इन करें",acct_sent:"कोड भेज दिया गया।",acct_err_wrong:"गलत कोड।",acct_err_expired:"कोड की अवधि समाप्त: नया कोड माँगें।",acct_err_locked:"बहुत अधिक प्रयास: नया कोड माँगें।",acct_err_none:"कोई सक्रिय कोड नहीं: नया कोड माँगें।",acct_err_rate:"बहुत अधिक अनुरोध: कुछ मिनट बाद फिर कोशिश करें।",acct_err_generic:"अप्रत्याशित त्रुटि, कृपया फिर कोशिश करें।",acct_forced_notice:"आप साइन इन हैं: परिणाम {email} पर ईमेल किया जाएगा। आप यह पेज बंद कर सकते हैं।",acct_signed_in_as:"{email} के रूप में साइन इन",
```

- [ ] **Step 6: JavaScript — sezione ACCOUNT in coda ad `app.js`**

```js
// ═══════════════════ ACCOUNT (magic link + codice) ═══════════════════
// Il bottone e la modale esistono solo se /api/auth/me risponde enabled:true.
// Da loggati la consegna e' sempre via email all'indirizzo dell'account
// (Task 7 lato server): la SPA nasconde i campi email manuali e lo dice.
let _acctMe=null;
let _acctPendingEmail='';
let _acctAfterLogin=null;

function _acctLoggedIn(){return !!(_acctMe&&_acctMe.logged_in&&_acctMe.email)}

async function _acctBoot(){
  try{
    const r=await fetch('/api/auth/me',{cache:'no-store'});
    _acctMe=r.ok?await r.json():null;
  }catch(e){_acctMe=null}
  _acctRender();
  let wantLogin=false;
  try{wantLogin=new URLSearchParams(location.search).get('login')==='1'}catch(e){}
  if(wantLogin&&_acctMe&&_acctMe.enabled){
    try{history.replaceState(null,'',location.pathname)}catch(e){}
    if(_acctLoggedIn()){location.href='/account';return}
    _acctAfterLogin=function(){location.href='/account'};
    openLoginModal();
  }
}

function _acctRender(){
  const btn=document.getElementById('acctBtn');
  const menu=document.getElementById('acctMenu');
  if(!btn)return;
  const on=!!(_acctMe&&_acctMe.enabled);
  btn.style.display=on?'':'none';
  btn.classList.toggle('on',_acctLoggedIn());
  btn.title=_acctLoggedIn()?t('acct_signed_in_as',{email:_acctMe.email}):t('acct_login');
  btn.setAttribute('aria-label',btn.title);
  if(menu){
    menu.style.display='none';
    btn.setAttribute('aria-expanded','false');
    const em=document.getElementById('acctMenuEmail');
    if(em)em.textContent=_acctLoggedIn()?_acctMe.email:'';
  }
  _acctApplyForcedEmail();
}

function _acctBtnClick(){
  if(!_acctLoggedIn()){openLoginModal();return}
  const menu=document.getElementById('acctMenu');
  const btn=document.getElementById('acctBtn');
  if(!menu)return;
  const open=menu.style.display!=='none';
  menu.style.display=open?'none':'';
  if(btn)btn.setAttribute('aria-expanded',open?'false':'true');
}
document.addEventListener('click',function(ev){
  const wrap=document.getElementById('acctWrap');
  const menu=document.getElementById('acctMenu');
  if(menu&&wrap&&!wrap.contains(ev.target)&&menu.style.display!=='none'){
    menu.style.display='none';
    const btn=document.getElementById('acctBtn');if(btn)btn.setAttribute('aria-expanded','false');
  }
});

function _acctShowErr(msg){
  const e=document.getElementById('acctErr');
  if(!e)return;
  if(!msg){e.style.display='none';e.textContent='';return}
  e.textContent=msg;e.style.display='block';
}

function openLoginModal(){
  const m=document.getElementById('loginModal');
  if(!m)return;
  _acctShowErr('');
  const se=document.getElementById('acctStepEmail'), sc=document.getElementById('acctStepCode');
  if(se)se.style.display='';
  if(sc)sc.style.display='none';
  const sb=document.getElementById('acctSendBtn'), vb=document.getElementById('acctVerifyBtn');
  if(sb){sb.style.display='';sb.disabled=false}
  if(vb)vb.style.display='none';
  const inp=document.getElementById('acctEmail');
  if(inp){
    inp.placeholder=t('acct_email_ph');
    if(!inp.value){try{inp.value=(localStorage.getItem('abm_v_email')||'').trim()}catch(e){}}
  }
  const code=document.getElementById('acctCode');
  if(code){code.placeholder=t('acct_code_ph');code.value=''}
  m.classList.add('open');
  try{inp&&inp.focus()}catch(e){}
}
function closeLoginModal(){const m=document.getElementById('loginModal');if(m)m.classList.remove('open');_acctAfterLogin=null}

async function _acctRequest(){
  const inp=document.getElementById('acctEmail');
  const email=((inp&&inp.value)||'').trim();
  if(!email||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)){_acctShowErr(t('acct_err_generic'));return}
  _acctShowErr('');
  const sb=document.getElementById('acctSendBtn');if(sb)sb.disabled=true;
  try{
    const r=await fetch('/api/auth/request',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:email,lang:cl})});
    if(r.status===429){_acctShowErr(t('acct_err_rate'));if(sb)sb.disabled=false;return}
    if(!r.ok){_acctShowErr(t('acct_err_generic'));if(sb)sb.disabled=false;return}
    _acctPendingEmail=email;
    try{localStorage.setItem('abm_v_email',email)}catch(e){}
    const se=document.getElementById('acctStepEmail'), sc=document.getElementById('acctStepCode');
    if(se)se.style.display='none';
    if(sc)sc.style.display='';
    const intro=document.getElementById('acctCodeIntro');
    if(intro)intro.textContent=t('acct_code_intro',{email:email});
    if(sb)sb.style.display='none';
    const vb=document.getElementById('acctVerifyBtn');if(vb){vb.style.display='';vb.disabled=false}
    const code=document.getElementById('acctCode');try{code&&code.focus()}catch(e){}
  }catch(e){_acctShowErr(t('acct_err_generic'));if(sb)sb.disabled=false}
}

async function _acctVerify(){
  const code=((document.getElementById('acctCode')||{}).value||'').replace(/\D/g,'');
  if(code.length!==6){_acctShowErr(t('acct_err_wrong'));return}
  _acctShowErr('');
  const vb=document.getElementById('acctVerifyBtn');if(vb)vb.disabled=true;
  try{
    const r=await fetch('/api/auth/verify',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({email:_acctPendingEmail,code:code})});
    const d=await r.json().catch(()=>({}));
    if(!r.ok||!d.ok){
      const k={wrong:'acct_err_wrong',expired:'acct_err_expired',locked:'acct_err_locked',none:'acct_err_none'}[d.error_code]||'acct_err_generic';
      _acctShowErr(t(k));
      if(vb)vb.disabled=false;
      // codice scaduto/bloccato/inesistente: si torna al primo passo
      if(d.error_code&&d.error_code!=='wrong'){const se=document.getElementById('acctStepEmail'),sc=document.getElementById('acctStepCode'),sb=document.getElementById('acctSendBtn');if(se)se.style.display='';if(sc)sc.style.display='none';if(sb){sb.style.display='';sb.disabled=false}if(vb)vb.style.display='none'}
      return;
    }
    const after=_acctAfterLogin;
    _acctAfterLogin=null;
    closeLoginModal();
    if(after){after();return}
    // ricarica lo stato dal server (email, lingua, piano)
    try{const m=await fetch('/api/auth/me',{cache:'no-store'});_acctMe=m.ok?await m.json():_acctMe}catch(e){}
    if(!_acctLoggedIn()&&d.email)_acctMe={enabled:true,logged_in:true,email:d.email};
    // Si resta sulla pagina: un login a meta' lavorazione non tocca il job in
    // corso (il server vincola solo i job avviati da loggati).
    _acctRender();
  }catch(e){_acctShowErr(t('acct_err_generic'));if(vb)vb.disabled=false}
}

async function _acctLogout(){
  try{await fetch('/api/auth/logout',{method:'POST'})}catch(e){}
  _acctMe=_acctMe?{enabled:_acctMe.enabled,logged_in:false}:null;
  _acctRender();
}

function _acctApplyForcedEmail(){
  // Da loggati: niente campi email manuali (il server li rifiuterebbe con
  // 409), un banner che dice dove arriva la notifica.
  const on=_acctLoggedIn();
  const notice=document.getElementById('acctForcedNotice');
  if(notice){
    notice.style.display=on?'block':'none';
    if(on)notice.textContent=t('acct_forced_notice',{email:_acctMe.email});
  }
  ['emailLateArea','emailLateAreaTr'].forEach(function(id){
    const a=document.getElementById(id);
    if(!a)return;
    if(on){a.classList.remove('visible');a.dataset.acctHidden='1'}
    else if(a.dataset.acctHidden){delete a.dataset.acctHidden}
  });
  const pn=document.getElementById('payEmailNotice');
  if(pn)pn.textContent=on?t('acct_forced_notice',{email:_acctMe.email}):t('pay_email_notice');
}
```

Nota su `submitEmailLate*`: il server vincola solo i job **avviati** da loggati; se l'utente accede a metà lavorazione (`_acctVerify` con `after` nullo), la pagina naviga a `/account` e il job continua da solo (ha già l'email o l'heartbeat: `_restoreActiveJob` lo riaggancia al rientro).

- [ ] **Step 7: JavaScript — modifiche puntuali**

In `DOMContentLoaded` (:485), dopo `if(typeof _restoreActiveJob==='function')_restoreActiveJob();`:

```js
  if(typeof _acctBoot==='function')_acctBoot();
```

In `_showAutoBatchNotice` (:4344-4345), sostituire:

```js
  const tmpl=t('auto_batch_notify')||"Pagamento ricevuto: ti invieremo l'audiolibro via email a {email}. Puoi chiudere questa pagina.";
  n.textContent=tmpl.replace('{email}',maskedEmail);
```

con:

```js
  // Utente con account: la notifica e' forzata sull'email dell'account, non
  // e' un effetto del pagamento. Wording dedicato, email in chiaro.
  const tmpl=_acctLoggedIn()?t('acct_forced_notice'):(t('auto_batch_notify')||"Pagamento ricevuto: ti invieremo l'audiolibro via email a {email}. Puoi chiudere questa pagina.");
  n.textContent=tmpl.replace('{email}',_acctLoggedIn()?_acctMe.email:maskedEmail);
```

In `_lockEmailLateBoxAutoBatch` (:4350), sostituire l'ultima riga `_addAutoBatchChangeEmailLink();` con:

```js
  // Da loggati l'indirizzo non e' cambiabile (409 lato server): niente link.
  if(_acctLoggedIn()){const a=document.getElementById('emailLateArea');if(a)a.classList.remove('visible');return}
  _addAutoBatchChangeEmailLink();
```

In `submitEmailLate` (:5875) e `submitEmailLateTr` (:3340), sostituire la riga `if(d.error){alert(d.error);return}` con:

```js
    if(d.error_code==='logged_in_email_forced'){
      const area=document.getElementById(FORCED_AREA_ID);
      _setEmailLateConfirm(area,t('acct_forced_notice',{email:d.email||''}));
      return;
    }
    if(d.error){alert(d.error);return}
```

dove `FORCED_AREA_ID` va scritto letteralmente come `'emailLateArea'` in `submitEmailLate` e `'emailLateAreaTr'` in `submitEmailLateTr`.

- [ ] **Step 8: Verificare ed eseguire i test**

Run: `node --check static/js/app.js` (se node è installato; altrimenti il test lo salta)
Run: `node --check templates/_fragments/i18n_data.js`
Run: `pytest test/test_app_js_account.py test/test_app_js_cold_redirect.py test/test_app_js_payment_modal.py -v --tb=short`
Expected: tutti PASS

Collaudo manuale rapido (facoltativo qui, obbligatorio nel Task 12): avviare `python audiobook_app.py` con `ABM_ACCOUNT_ENABLE=1`, SMTP configurato e `ABM_BASE_URL=http://localhost:5601`; verificare che il bottone compaia, la modale invii il codice, il login mostri il banner e nasconda il campo email.

- [ ] **Step 9: Commit**

```bash
git add templates/_fragments/html_head.html templates/_fragments/i18n_data.js static/css/style.css static/js/app.js test/test_app_js_account.py
git commit -m "feat(account): login magic link nella SPA e notifica forzata all'email dell'account"
```

---

### Task 10: Manutenzione periodica, backup del DB e replica su R2

**Files:**
- Modify: `audiobook_app.py` — nuove funzioni accanto a `_voice_clone_sweep_supervisor` :19623; avvio thread dopo `threading.Thread(target=_cleanup_supervisor, daemon=True).start()` :20056
- Modify: `scripts/backup_ABM.sh` :58-66 (sezione «5. Dati applicazione»)
- Test: `test/test_account_maintenance.py`

**Interfaces:**
- Consumes: `accounts.purge_expired(now=None) -> {"jobs","codes","sessions"}`, `db.is_ready()`, `db.backup_to(dest_path)`, `db.path()`, `storage_backend.is_enabled()`, `storage_backend.upload_file(local_path, key)`, `storage_backend.list_prefix(prefix)`, `storage_backend.delete_object(key)`.
- Produces: `_account_maintenance_once(now=None) -> dict` (`{"purged": {...}, "backup": str|None, "r2_key": str|None, "r2_pruned": int}`), `_account_maintenance_supervisor()`; costanti `_ACCT_MAINT_FIRST_SEC = 300`, `_ACCT_MAINT_INTERVAL_SEC = 6 * 3600`, `_ACCT_R2_PREFIX = "accounts/"`, `_ACCT_R2_KEEP = 14`.

Perché: `abm.db` è l'unico stato non-JSON e non è coperto da `backup_ABM.sh`, dalla replica `voice_clone` né dal tiering. La copia locale `abm.db.bak` (API di backup online di SQLite: coerente anche sotto scrittura) e una copia giornaliera su R2 con rotazione a 14 chiudono il buco. La purge scade codici, sessioni e righe di storico oltre retention (`accounts.purge_expired`, Task 3).

- [ ] **Step 1: Scrivere `test/test_account_maintenance.py`**

```python
# test/test_account_maintenance.py
"""Manutenzione account: purge periodica, backup locale coerente, copia
giornaliera su R2 con rotazione. Tutto best-effort, mai fatale."""
import sqlite3
import time

import pytest

import accounts
import audiobook_app
import db


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "_DATA_DIR", str(tmp_path))
    yield tmp_path
    db.close()


class _R2:
    def __init__(self, enabled=True, keys=()):
        self.enabled = enabled
        self.uploaded = []
        self.deleted = []
        self.keys = list(keys)

    def is_enabled(self):
        return self.enabled

    def upload_file(self, local_path, key):
        self.uploaded.append((str(local_path), key))
        self.keys.append(key)

    def list_prefix(self, prefix):
        return [k for k in self.keys if k.startswith(prefix)]

    def delete_object(self, key):
        self.deleted.append(key)
        self.keys.remove(key)


def test_once_purges_backs_up_and_uploads(env, monkeypatch):
    r2 = _R2()
    monkeypatch.setattr(audiobook_app, "storage_backend", r2)
    token, _ = accounts.request_code("a@b.it", now=1000)
    # purge_expired butta i codici scaduti da piu' di 24 h: 48 h dopo e' sicuro
    out = audiobook_app._account_maintenance_once(now=1000 + 3600 * 48)
    assert out["purged"]["codes"] == 1
    bak = env / "abm.db.bak"
    assert bak.exists() and out["backup"] == str(bak)
    # la copia e' un database SQLite leggibile con lo schema completo
    c = sqlite3.connect(str(bak))
    names = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    c.close()
    assert {"accounts", "auth_codes", "sessions", "account_jobs"} <= names
    assert len(r2.uploaded) == 1
    assert r2.uploaded[0][1].startswith("accounts/abm-") and r2.uploaded[0][1].endswith(".db")
    assert out["r2_key"] == r2.uploaded[0][1]


def test_once_prunes_old_r2_copies(env, monkeypatch):
    old = [f"accounts/abm-2026-01-{d:02d}.db" for d in range(1, 21)]
    r2 = _R2(keys=old)
    monkeypatch.setattr(audiobook_app, "storage_backend", r2)
    out = audiobook_app._account_maintenance_once()
    assert len(r2.list_prefix("accounts/")) == audiobook_app._ACCT_R2_KEEP
    assert out["r2_pruned"] == 21 - audiobook_app._ACCT_R2_KEEP
    # restano le piu' recenti (ordinamento lessicografico delle date ISO)
    assert "accounts/abm-2026-01-20.db" in r2.keys
    assert "accounts/abm-2026-01-01.db" not in r2.keys


def test_once_without_r2(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "storage_backend", _R2(enabled=False))
    out = audiobook_app._account_maintenance_once()
    assert out["r2_key"] is None and out["r2_pruned"] == 0
    assert (env / "abm.db.bak").exists()


def test_once_survives_r2_failure(env, monkeypatch):
    class _Boom(_R2):
        def upload_file(self, local_path, key):
            raise RuntimeError("r2 down")
    monkeypatch.setattr(audiobook_app, "storage_backend", _Boom())
    out = audiobook_app._account_maintenance_once()
    assert out["r2_key"] is None and (env / "abm.db.bak").exists()


def test_once_noop_when_db_not_ready(monkeypatch, tmp_path):
    db.close()
    monkeypatch.setattr(audiobook_app, "_DATA_DIR", str(tmp_path))
    assert audiobook_app._account_maintenance_once() == {"purged": {}, "backup": None,
                                                         "r2_key": None, "r2_pruned": 0}


def test_supervisor_runs_once_then_sleeps(env, monkeypatch):
    calls = []
    sleeps = []
    monkeypatch.setattr(audiobook_app, "_account_maintenance_once",
                        lambda: calls.append(1) or {"purged": {}, "backup": None,
                                                    "r2_key": None, "r2_pruned": 0})

    def fake_sleep(s):
        sleeps.append(s)
        if len(sleeps) >= 3:
            raise KeyboardInterrupt
    monkeypatch.setattr(audiobook_app.time, "sleep", fake_sleep)
    with pytest.raises(KeyboardInterrupt):
        audiobook_app._account_maintenance_supervisor()
    assert sleeps[0] == audiobook_app._ACCT_MAINT_FIRST_SEC
    assert sleeps[1] == audiobook_app._ACCT_MAINT_INTERVAL_SEC
    assert len(calls) == 2


def test_backup_script_covers_sqlite():
    src = open("scripts/backup_ABM.sh", encoding="utf-8").read()
    assert "abm.db" in src and ".backup" in src
```

- [ ] **Step 2: Eseguire i test e verificare che falliscano**

Run: `pytest test/test_account_maintenance.py -v --tb=short`
Expected: FAIL con `AttributeError: module 'audiobook_app' has no attribute '_account_maintenance_once'`; `test_backup_script_covers_sqlite` fallisce sull'`assert`.

- [ ] **Step 3: Implementare in `audiobook_app.py`**

Subito dopo `_voice_clone_sweep_supervisor` (:19646) aggiungere:

```python
_ACCT_MAINT_FIRST_SEC = 300          # prima manutenzione 5 min dopo il boot
_ACCT_MAINT_INTERVAL_SEC = 6 * 3600  # poi ogni 6 ore
_ACCT_R2_PREFIX = "accounts/"
_ACCT_R2_KEEP = 14                   # copie giornaliere conservate su R2


def _account_maintenance_once(now=None):
    """Un giro di manutenzione dello stato account: purge di codici/sessioni
    scaduti e storico oltre retention, backup locale coerente di abm.db
    (API online di SQLite) e copia del giorno su R2 con rotazione.
    Ogni passo e' indipendente e best-effort."""
    out = {"purged": {}, "backup": None, "r2_key": None, "r2_pruned": 0}
    if not db.is_ready():
        return out
    try:
        out["purged"] = accounts.purge_expired(now=now)
    except Exception as e:  # noqa: BLE001
        print(f"[account] purge_expired failed: {e}", flush=True)
    bak = Path(_DATA_DIR) / (db.DB_FILENAME + ".bak")
    try:
        db.backup_to(bak)
        out["backup"] = str(bak)
    except Exception as e:  # noqa: BLE001
        print(f"[account] db backup failed: {e}", flush=True)
        return out
    try:
        if not storage_backend.is_enabled():
            return out
        day = time.strftime("%Y-%m-%d", time.gmtime(now if now is not None else time.time()))
        key = f"{_ACCT_R2_PREFIX}abm-{day}.db"
        storage_backend.upload_file(str(bak), key)
        out["r2_key"] = key
        keys = sorted(k for k in storage_backend.list_prefix(_ACCT_R2_PREFIX)
                      if k.endswith(".db"))
        for old in keys[:-_ACCT_R2_KEEP]:
            try:
                storage_backend.delete_object(old)
                out["r2_pruned"] += 1
            except Exception as e:  # noqa: BLE001
                print(f"[account] R2 prune {old} failed: {e}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"[account] R2 backup failed (non-fatal): {e}", flush=True)
    return out


def _account_maintenance_supervisor():
    """Manutenzione periodica dello stato account, riavviata su crash come
    _cleanup_supervisor (incidente 2026-06-15)."""
    import traceback
    delay = _ACCT_MAINT_FIRST_SEC
    while True:
        try:
            time.sleep(delay)
            delay = _ACCT_MAINT_INTERVAL_SEC
            out = _account_maintenance_once()
            if any(out["purged"].values()) or out["r2_pruned"]:
                print(f"[account] maintenance: {out}", flush=True)
        except KeyboardInterrupt:
            raise
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            print(f"[account] maintenance crashed, restarting: {type(e).__name__}: {e}", flush=True)
            delay = 60
```

Dopo `threading.Thread(target=_cleanup_supervisor, daemon=True).start()` (:20056):

```python
    if db.is_ready():
        threading.Thread(target=_account_maintenance_supervisor, daemon=True).start()
```

Nota: in `test_supervisor_runs_once_then_sleeps` la terza `sleep` solleva `KeyboardInterrupt` che il supervisor rilancia: per questo il ramo `except KeyboardInterrupt: raise` va **prima** dell'`except Exception` (che comunque non lo prenderebbe, essendo `KeyboardInterrupt` un `BaseException`; il ramo esplicito documenta l'intenzione).

- [ ] **Step 4: Aggiornare `scripts/backup_ABM.sh`**

Dopo il ciclo `for f in _download_tokens.json ...; done` (:66) aggiungere:

```bash
# Database SQLite degli account (abm.db): copia coerente via API di backup
# (sicura anche con l'app in scrittura); fallback a cp se manca sqlite3.
if [ -f "$DATA_DIR/abm.db" ]; then
    if command -v sqlite3 >/dev/null 2>&1; then
        sqlite3 "$DATA_DIR/abm.db" ".backup '$BACKUP_DIR/data/abm.db'"
    else
        cp "$DATA_DIR/abm.db" "$BACKUP_DIR/data/abm.db"
        [ -f "$DATA_DIR/abm.db-wal" ] && cp "$DATA_DIR/abm.db-wal" "$BACKUP_DIR/data/"
    fi
fi
```

Il file `restore_ABM.sh` ripristina `data/` per directory: `abm.db` torna al suo posto senza modifiche allo script. Verificare con `grep -n "data" scripts/restore_ABM.sh` che il ripristino copi l'intera cartella `data/` e non un elenco di file: se è un elenco, aggiungere `abm.db`.

- [ ] **Step 5: Compilare ed eseguire i test**

Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_account_maintenance.py -v --tb=short`
Expected: tutti PASS

- [ ] **Step 6: Commit**

```bash
git add audiobook_app.py scripts/backup_ABM.sh test/test_account_maintenance.py
git commit -m "feat(account): manutenzione periodica, backup di abm.db e copia giornaliera su R2"
```

---

### Task 11: Documentazione e versione

**Files:**
- Modify: `md_files/PARAMETRI_CONFIGURAZIONE.md` — tabella §1 (:11-…) e nuova sezione «18. Account e storico» in coda (prima della tabella riepilogativa finale, che va aggiornata)
- Modify: `docs/FORENSICS_PLAYBOOK.md` — sezione «Persistent state files» :23-25
- Modify: `CLAUDE.md` — **non tracciato da git, vive solo nel checkout principale** `C:\Users\gfran\NEXT srl\Progetti - Documenti\AudioBook-Maker\CLAUDE.md`: modificarlo per percorso assoluto, mai `git add`
- Modify: `version.py` — `__version__`

- [ ] **Step 1: `md_files/PARAMETRI_CONFIGURAZIONE.md`**

Nella tabella di §1 aggiungere le righe (numero di riga da leggere con `grep -n "ABM_ACCOUNT_ENABLE" accounts.py` a implementazione fatta):

```markdown
| `ABM_ACCOUNT_ENABLE` | `"1"` (account opzionale con magic link; `0` = bottone, route `/auth/*`, `/account` e API rispondono 404) | `accounts.py` | N |
| `ABM_ACCOUNT_SESSION_DAYS` | `90` (durata sessione, rolling: rinnovata a ogni richiesta se l'ultimo tocco risale a più di 1 h) | `accounts.py` | N |
| `ABM_ACCOUNT_CODE_TTL_MIN` | `10` (validità del link/codice di login e di cancellazione) | `accounts.py` | N |
| `ABM_ACCOUNT_CODE_MAX_ATTEMPTS` | `5` (tentativi sul codice a 6 cifre prima del blocco: serve un nuovo codice) | `accounts.py` | N |
| `ABM_ACCOUNT_HISTORY_MONTHS` | `24` (retention dello storico per account free e per account a pagamento dopo la grace) | `accounts.py` | N |
| `ABM_ACCOUNT_GRACE_DAYS` | `90` (grace dopo la disdetta di un piano a pagamento prima che scatti la retention free) | `accounts.py` | N |
```

Nuova sezione in coda (prima della tabella «Totale»):

```markdown
## 18. Account opzionale e storico (`db.py`, `accounts.py`, `account_page.py`)

Login senza password: magic link `/auth/<token>` + codice a 6 cifre nella stessa email (`i18n/account_emails.json`). Sessione in cookie `abm_session` (HttpOnly, Secure se `ABM_BASE_URL` è https, SameSite=Lax, 90 giorni rolling) o `Authorization: Bearer` (app mobile, con `X-ABM-Cid`). Stato in **SQLite** `ABM_DATA_DIR/abm.db` (WAL, connessione singola, migrazioni per nome): tabelle `accounts`, `auth_codes`, `sessions`, `account_jobs`.

| Costante | Valore | File |
|----------|--------|------|
| Rate limit richiesta codice per IP | 5/min, 30/h (`_ip_rl_check("auth_request")`) → 429 | `audiobook_app.py` |
| Rate limit richiesta codice per email | 3 ogni 10 min (risposta neutra `{ok:true}`) | `accounts.py` |
| Hash di token e codice in DB | sha256; token 32 byte urlsafe | `accounts.py` |
| Rinnovo sessione | se `now - last_seen_at > 3600` | `accounts.py` |
| Storico per pagina | `_ACCT_PER_PAGE = 50` | `audiobook_app.py` |
| Manutenzione | prima a 300 s dal boot, poi ogni 6 h: purge + `abm.db.bak` + copia su R2 `accounts/abm-YYYY-MM-DD.db` (14 conservate) | `audiobook_app.py` |
| Adozione retroattiva | solo `_payments.json` (email+job_id) e `_voice_clones.json` (`owner_email`), alla creazione dell'account | `accounts.py` |
| Notifica forzata | con sessione attiva ogni job (generate/optimize/translate) è in modalità email sull'indirizzo dell'account, esente da heartbeat; `/api/register_email` con altra email → 409 `logged_in_email_forced` | `audiobook_app.py` |
| Log activity | `ACCOUNT_LOGIN`, `ACCOUNT_LOGOUT`, `ACCOUNT_LOGOUT_ALL`, `ACCOUNT_DELETE`, `ACCOUNT_ADOPT` con sid `acct-<hash8>`, mai l'email in chiaro | `audiobook_app.py` |
```

Nella tabella riepilogativa finale aggiungere la riga `| Account e storico (\`accounts.py\`) | 6 |` e aggiornare il totale (`132` → `138`).

- [ ] **Step 2: `docs/FORENSICS_PLAYBOOK.md`**

Nella sezione «Persistent state files» (:25), aggiungere in coda al paragrafo:

```markdown
`abm.db` (SQLite, WAL: `abm.db-wal`/`abm.db-shm` accanto; `abm.db.bak` = ultima copia coerente della manutenzione, copie giornaliere su R2 `accounts/abm-YYYY-MM-DD.db`). Query rapide, senza fermare l'app: `sqlite3 -readonly /opt/audiobook-maker/data/abm.db "SELECT job_id,status,download_token,datetime(created_at,'unixepoch') FROM account_jobs WHERE job_id='<jid>'"`; account di un job: `"SELECT a.id,a.email_hash,a.plan FROM account_jobs j JOIN accounts a ON a.id=j.account_id WHERE j.job_id='<jid>'"`; sessioni attive: `"SELECT count(*) FROM sessions WHERE revoked_at IS NULL AND expires_at>strftime('%s','now')"`. L'email in chiaro sta in `accounts.email`: non incollarla nei ticket, usare `email_hash`. Log: `ACCOUNT_*` nell'activity log con sid `acct-<hash8>` = primi 8 hex di `sha256(email)`.
```

- [ ] **Step 3: `CLAUDE.md` (checkout principale, non tracciato)**

Nella tabella «Backend Modules» aggiungere tre righe dopo `cost_carry.py`:

```markdown
| `db.py` | SQLite di processo (stdlib): `abm.db` in `ABM_DATA_DIR`, WAL, connessione singola sotto `RLock`, `tx()` annidabile, migrazioni per nome, `backup_to()` con l'API online. Modulo foglia. Primo consumatore: `accounts.py`; l'activity log resta su file (migrazione rinviata). |
| `accounts.py` | Account opzionale con magic link + codice a 6 cifre (tabelle `accounts`, `auth_codes`, `sessions`, `account_jobs`): `request_code`/`verify`/`open_session`/`resolve_session`, storico job (`record_job`, `update_status`, `set_download_token`, `attach_if_known`, `list_jobs`), adozione retroattiva da `_payments.json` e voci campionate alla creazione, `delete_account`, `purge_expired`. Modulo foglia configurato via `configure()`. Env `ABM_ACCOUNT_*` (§18 di `PARAMETRI_CONFIGURAZIONE.md`). |
| `account_page.py` | Rendering server-side delle pagine account (`/auth/<token>` conferma/errore, `/account` storico con download) da `i18n/account_pages.json`. Solo HTML: nessuno stato. |
```

Nella sezione «Background Threads» aggiungere:

```markdown
- **Manutenzione account** — `_account_maintenance_supervisor`: 5 min dopo il boot e poi ogni 6 h, `accounts.purge_expired()` + backup coerente `abm.db.bak` + copia giornaliera su R2 `accounts/` (14 conservate). Parte solo se `db.is_ready()`.
```

Nella sezione «Key Configuration» aggiungere una tabella **Account**:

```markdown
**Account (magic link)**

| Variable | Description | Default |
|----------|-------------|---------|
| `ABM_ACCOUNT_ENABLE` | Account opzionale con login via magic link/codice. `0` = tutte le route account rispondono 404 | `1` |
| `ABM_ACCOUNT_SESSION_DAYS` | Durata sessione (rolling) | `90` |
| `ABM_ACCOUNT_CODE_TTL_MIN` | Validità del link/codice | `10` |
| `ABM_ACCOUNT_CODE_MAX_ATTEMPTS` | Tentativi sul codice prima del blocco | `5` |
| `ABM_ACCOUNT_HISTORY_MONTHS` | Retention storico (free; paganti dopo la grace) | `24` |
| `ABM_ACCOUNT_GRACE_DAYS` | Grace dopo disdetta piano a pagamento | `90` |
```

Nella sezione «Directory Structure» aggiungere `db.py`, `accounts.py`, `account_page.py` con la descrizione a una riga.

- [ ] **Step 4: `version.py`**

Portare `__version__` alla **minor** successiva rispetto al valore corrente del file (feature nuova, retrocompatibile: al momento della stesura del piano `3.60.0` → `3.61.0`).

- [ ] **Step 5: Verifica**

Run: `pytest test/ -q --tb=short`
Expected: tutti PASS (la suite completa: nessun test dipende dal numero di versione, ma le modifiche ai docs possono scoprire test che li leggono, es. sui `.md` referenziati).

- [ ] **Step 6: Commit**

```bash
git add -f md_files/PARAMETRI_CONFIGURAZIONE.md docs/FORENSICS_PLAYBOOK.md
git add version.py
git commit -m "docs(account): parametri ABM_ACCOUNT_*, playbook forense e bump versione"
```

`CLAUDE.md` **non** va aggiunto (è ignorato e non deve mai finire nel repo).

---

### Task 12: Collaudo manuale (nessun push)

Nessun file modificato. L'utente prova in locale prima di qualunque push (vincolo di progetto); il piano si chiude con questa checklist da eseguire con `python audiobook_app.py` e:

```
ABM_ACCOUNT_ENABLE=1
ABM_BASE_URL=http://localhost:5601
ABM_SMTP_HOST/PORT/USER/PASS  (SMTP reale: le email di codice devono arrivare)
ABM_DATA_DIR=<cartella dati locale>
```

- [ ] **Login da SPA**: bottone utente in toolbar → email → codice ricevuto → accesso; il bottone passa a "connesso", il menu mostra email, "I miei audiolibri", "Esci".
- [ ] **Magic link**: dalla stessa email aprire il link → pagina di conferma → "Accedi" → redirect a `/account`; riaprire il link → pagina 410 "link già usato/scaduto".
- [ ] **Codice sbagliato ×5** → messaggio "troppi tentativi"; nuovo codice dalla modale funziona.
- [ ] **Job da loggato (voce standard, m4b)**: il campo email a fine avvio non compare; il banner dice "Sei connesso: riceverai… a <email>"; chiudere la scheda per >60 s: il job **non** viene annullato; email di completamento ricevuta; `/account` mostra la riga con stato «completato» e i bottoni di download funzionanti.
- [ ] **Job da loggato con ottimizzazione AI (wizard, sotto soglia gratuita)**: riga in storico con `kind` ottimizzazione, poi generazione; bottone ABM presente.
- [ ] **Traduzione da loggato** (se `ABM_TRANSLATE_MODEL` configurato): riga con `kind` traduzione e download «tradotto».
- [ ] **Job pagato senza sessione con voucher intestato all'email dell'account** → la riga compare in `/account` (`source` pagamenti) al login successivo o subito se l'account esiste già.
- [ ] **`/api/register_email` con altra email da loggato** (da console: `fetch('/api/register_email',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:'<jid>',email:'altro@x.it'})})`) → 409 `logged_in_email_forced`.
- [ ] **Scadenza download**: forzare `created_at` di un token indietro di 2 giorni in `_download_tokens.json` (app ferma), riavviare: `/account` mostra «scaduto» al posto dei bottoni.
- [ ] **Logout / Esci da tutti i dispositivi**: la sessione del secondo browser cade (`/account` → redirect con `?login=1` → modale aperta).
- [ ] **Cancellazione account**: da `/account` → email di conferma → link `?p=delete` → pagina "account cancellato" + email di conferma; il login con la stessa email crea un account **nuovo** con storico vuoto (adozione retroattiva solo dai pagamenti).
- [ ] **Feature spenta** (`ABM_ACCOUNT_ENABLE=0`): nessun bottone in toolbar; `/account` e `/auth/x` → 404; i job si comportano come prima (campo email manuale visibile).
- [ ] **Manutenzione**: dopo 5 min dal boot compare `abm.db.bak` nella data dir; con R2 configurato la chiave `accounts/abm-<oggi>.db` esiste nel bucket.
- [ ] **Mobile (se disponibile)**: `POST /api/auth/verify` con header `X-ABM-Cid` ritorna `session_token`; `GET /api/auth/me` con `Authorization: Bearer` risponde `logged_in:true`.

Esito atteso: tutte le voci spuntate. Difetti trovati → fix con test di regressione nel task di competenza, commit separato `fix(account): …`. **Nessun `git push`** finché l'utente non lo chiede esplicitamente.

---

## Note di chiusura

- **Ordine dei task**: 1→2→3→4 sono modulo foglia + email e non toccano `audiobook_app.py`; 5→6 aggiungono le route; 7→8 vincolano i flussi esistenti; 9 la SPA; 10 la manutenzione; 11 docs; 12 collaudo. Ogni task lascia la suite verde e l'app avviabile.
- **Kill switch**: `ABM_ACCOUNT_ENABLE=0` spegne tutto tranne `db.init` (innocuo: crea un file vuoto con lo schema) e gli hook di `generation_engine`, che sono no-op perché `update_status`, `set_download_token` e `attach_if_known` cominciano con `if not enabled(): return False` (Task 3).
- **Privacy**: l'email in chiaro sta solo in `accounts.email` e nelle email inviate; log, digest e API admin usano `email_hash`/`acct-<hash8>`. Nessun nome di provider AI/TTS nelle stringhe utente.
- **Rinviato (fuori Blocco 1)**: piani a pagamento e disdetta (oggi `plan='free'` fisso, `GRACE_DAYS` letto ma senza transizioni), migrazione dell'activity log su SQLite, storico nell'app mobile (le API Bearer sono già pronte), notifica push al posto dell'email.
