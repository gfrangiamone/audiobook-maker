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
