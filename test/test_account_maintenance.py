# test/test_account_maintenance.py
"""Manutenzione account: purge periodica, backup locale coerente, copia
giornaliera su R2 con rotazione. Tutto best-effort, mai fatale."""
import shutil
import sqlite3
import subprocess
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
    # abm.db e activity.db passano entrambi dalla stessa funzione
    # backup_sqlite() (copia coerente via API sqlite3, fallback a cp a
    # freddo se sqlite3 manca o il backup a caldo fallisce).
    assert "backup_sqlite abm.db" in src
    assert "backup_sqlite activity.db" in src
    assert "abm.db" in src and ".backup" in src
    # Non basta che i due token esistano da qualche parte nel file: la
    # chiamata sqlite3 deve essere effettivamente guardata (lo script ha
    # `set -e` in testa, riga 8), con un fallback a `cp` a freddo visibile
    # in un messaggio di avviso, cosi' un fallimento del backup di un DB
    # non fa saltare il resto del backup giornaliero (log, chiavi, tar,
    # rotazione).
    backup_line = next(
        line for line in src.splitlines()
        if "sqlite3" in line and ".backup" in line
    )
    assert "&& return 0" in backup_line or "||" in backup_line, (
        "la chiamata `sqlite3 ... \".backup\"` non e' guardata: sotto "
        "`set -e` un suo fallimento aborterebbe l'intero script"
    )
    assert "ATTENZIONE" in src, "manca il messaggio di avviso sul fallback a cp"
    # il fallback a cp a freddo deve comparire, con il file-per-nome
    # generico della funzione, non piu' hardcoded su abm.db
    assert 'cp "$DATA_DIR/$name"' in src
    # copia anche il file -wal, se presente, accanto al fallback a freddo
    assert '$name-wal' in src
    bash = shutil.which("bash")
    if bash:
        out = subprocess.run([bash, "-n", "scripts/backup_ABM.sh"],
                             capture_output=True, text=True)
        assert out.returncode == 0, out.stderr


def test_restore_script_act_dir_takes_last_uncommented(tmp_path):
    """ACT_DIR (riga ~133 di restore_ABM.sh) deve leggere solo l'ultima
    riga Environment= non commentata di override.conf: senza ancoraggio
    all'inizio riga, una riga commentata o duplicata finisce comunque nel
    grep e produce un ACT_DIR multi-riga che fa fallire silenziosamente
    la `cp` successiva (`|| true`), pur stampando 'ripristinati'."""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("bash non disponibile")
    src = open("scripts/restore_ABM.sh", encoding="utf-8").read()
    line = next(
        l for l in src.splitlines()
        if l.strip().startswith("ACT_DIR=$(grep")
    )
    override = tmp_path / "override.conf"
    override.write_text(
        '# Environment="ABM_ACTIVITY_LOG_DIR=/old"\n'
        'Environment="ABM_ACTIVITY_LOG_DIR=/a"\n'
        'Environment=ABM_ACTIVITY_LOG_DIR=/b\n',
        encoding="utf-8",
    )
    patched = line.replace(
        "/etc/systemd/system/audiobook-maker.service.d/override.conf",
        override.as_posix(),
    )
    script = tmp_path / "extract_act_dir.sh"
    script.write_text(patched + '\necho "$ACT_DIR"\n', encoding="utf-8")
    out = subprocess.run([bash, script.as_posix()], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == "/b"
