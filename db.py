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


MIGRATIONS_DDL = ("CREATE TABLE IF NOT EXISTS schema_migrations "
                  "(name TEXT PRIMARY KEY, applied_at INTEGER NOT NULL)")


def configure_connection(conn, *, busy_ms=5000, foreign_keys=True, migrations_table=True):
    """PRAGMA comuni a ogni DB dell'app (WAL, synchronous=NORMAL, busy_timeout)
    piu' la tabella delle migrazioni; `foreign_keys` dove lo schema li usa."""
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    if foreign_keys:
        conn.execute("PRAGMA foreign_keys=ON")
    conn.execute(f"PRAGMA busy_timeout={int(busy_ms)}")
    if migrations_table:
        conn.execute(MIGRATIONS_DDL)
    return conn


def apply_migration(conn, name, statements):
    """`statements` una sola volta sotto `name`, in una transazione propria
    (BEGIN IMMEDIATE) su una connessione qualsiasi in autocommit. Ritorna
    True se applicata ora. Per la connessione condivisa di questo modulo
    c'e' `migrate()`, che passa da `tx()`."""
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
    return done is None


def open_readonly(path, *, timeout=2.0):
    """Connessione di sola lettura su un DB esistente: se il file manca
    solleva sqlite3.OperationalError invece di crearlo vuoto.

    `mode=ro`, non `rw` + query_only: chiudendosi come ultima connessione
    (script lanciato a servizio fermo) una connessione rw fa il checkpoint
    del WAL dentro il DB, cioe' scrive."""
    from pathlib import Path
    uri = Path(path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False, timeout=timeout)
    conn.execute("PRAGMA query_only=1")
    return conn


def init(data_dir):
    """Apre (o crea) il DB in data_dir e prepara la tabella delle migrazioni."""
    global _conn, _path
    os.makedirs(str(data_dir), exist_ok=True)
    _path = os.path.join(str(data_dir), DB_FILENAME)
    c = sqlite3.connect(_path, check_same_thread=False, isolation_level=None)
    c.row_factory = sqlite3.Row
    configure_connection(c, busy_ms=5000, foreign_keys=True)
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
