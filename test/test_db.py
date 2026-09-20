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
