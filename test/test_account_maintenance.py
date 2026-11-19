# test/test_account_maintenance.py
"""Manutenzione account: purge periodica, backup locale coerente, copia
giornaliera su R2 con rotazione. Tutto best-effort, mai fatale."""
import shutil
from pathlib import Path
import sqlite3
import subprocess
import time

import os
import pytest

import accounts
import audiobook_app
import cleanup
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
    monkeypatch.setattr(cleanup, "storage_backend", r2)
    token, _ = accounts.request_code("a@b.it", now=1000)
    # purge_expired butta i codici scaduti da piu' di 24 h: 48 h dopo e' sicuro
    out = cleanup._account_maintenance_once(now=1000 + 3600 * 48)
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
    monkeypatch.setattr(cleanup, "storage_backend", r2)
    out = cleanup._account_maintenance_once()
    assert len(r2.list_prefix("accounts/")) == cleanup._ACCT_R2_KEEP
    assert out["r2_pruned"] == 21 - cleanup._ACCT_R2_KEEP
    # restano le piu' recenti (ordinamento lessicografico delle date ISO)
    assert "accounts/abm-2026-01-20.db" in r2.keys
    assert "accounts/abm-2026-01-01.db" not in r2.keys


def test_once_without_r2(env, monkeypatch):
    monkeypatch.setattr(cleanup, "storage_backend", _R2(enabled=False))
    out = cleanup._account_maintenance_once()
    assert out["r2_key"] is None and out["r2_pruned"] == 0
    assert (env / "abm.db.bak").exists()


def test_once_survives_r2_failure(env, monkeypatch):
    class _Boom(_R2):
        def upload_file(self, local_path, key):
            raise RuntimeError("r2 down")
    monkeypatch.setattr(cleanup, "storage_backend", _Boom())
    out = cleanup._account_maintenance_once()
    assert out["r2_key"] is None and (env / "abm.db.bak").exists()


def test_once_noop_when_db_not_ready(monkeypatch, tmp_path):
    db.close()
    monkeypatch.setattr(audiobook_app, "_DATA_DIR", str(tmp_path))
    assert cleanup._account_maintenance_once() == {"purged": {}, "backup": None,
                                                         "r2_key": None, "r2_pruned": 0}


def test_supervisor_runs_once_then_sleeps(env, monkeypatch, sleeps):
    calls = []
    monkeypatch.setattr(cleanup, "_account_maintenance_once",
                        lambda: calls.append(1) or {"purged": {}, "backup": None,
                                                    "r2_key": None, "r2_pruned": 0})
    sleeps.stop_after(3, KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        cleanup._account_maintenance_supervisor()
    assert sleeps[0] == cleanup._ACCT_MAINT_FIRST_SEC
    assert sleeps[1] == cleanup._ACCT_MAINT_INTERVAL_SEC
    assert len(calls) == 2


def _posix_bash():
    """bash utilizzabile dai test. Su Windows scarta la bash di WSL in
    System32/WindowsApps (non vede i path Windows dei file temporanei) e
    ripiega su quella installata accanto a git."""
    bash = shutil.which("bash")
    low = (bash or "").lower().replace("/", "\\")
    if bash and "\\system32\\" not in low and "\\windowsapps\\" not in low:
        return bash
    git = shutil.which("git")
    if git:
        for cand in (Path(git).parent.parent / "bin" / "bash.exe",
                     Path(git).parent.parent / "usr" / "bin" / "bash.exe"):
            if cand.is_file():
                return str(cand)
    return None


@pytest.mark.skipif(not os.path.exists("scripts/backup_ABM.sh"),
                    reason="scripts/ non e' tracciata: lo script manca in questo checkout")
def test_backup_script_covers_sqlite():
    src = open("scripts/backup_ABM.sh", encoding="utf-8", errors="replace").read()
    # abm.db e activity.db passano entrambi dalla stessa funzione
    # backup_sqlite() (copia coerente via API di backup del modulo sqlite3
    # di python3, che sul server sostituisce la CLI assente; fallback a cp
    # a freddo se il backup a caldo fallisce).
    assert 'backup_sqlite "$DATA_DIR/abm.db"' in src
    assert 'backup_sqlite "$ACT_DIR/activity.db"' in src
    assert "s.backup(d)" in src and "PRAGMA quick_check" in src
    # Non basta che i token esistano da qualche parte nel file: la
    # chiamata python3 deve essere effettivamente guardata (lo script ha
    # `set -e` in testa, riga 8), con un fallback a `cp` a freddo visibile
    # in un messaggio di avviso, cosi' un fallimento del backup di un DB
    # non fa saltare il resto del backup giornaliero (log, chiavi, tar,
    # rotazione).
    backup_line = next(
        line for line in src.splitlines()
        if "python3 -" in line and '"$src"' in line
    )
    assert backup_line.strip().startswith("if "), (
        "la chiamata `python3 - \"$src\" ...` non e' guardata: sotto "
        "`set -e` un suo fallimento aborterebbe l'intero script"
    )
    assert "ATTENZIONE" in src, "manca il messaggio di avviso sul fallback a cp"
    # il fallback a cp a freddo deve comparire, con il file generico della
    # funzione, non hardcoded su abm.db
    assert 'cp "$src" "$dst"' in src
    # copia anche il file -wal, se presente, accanto al fallback a freddo
    assert '$src-wal' in src
    bash = _posix_bash()
    if bash:
        # via stdin: la copia di lavoro puo' avere CRLF (autocrlf), il
        # server riceve LF
        out = subprocess.run([bash, "-n"], input=src,
                             capture_output=True, text=True, encoding="utf-8")
        assert out.returncode == 0, out.stderr


def _restore_env_get(tmp_path, files, name):
    """Lancia `abm_env_get` di restore_ABM.sh su una cartella di drop-in finta."""
    bash = _posix_bash()
    if not bash:
        pytest.skip("bash POSIX non disponibile")
    src = open("scripts/restore_ABM.sh", encoding="utf-8").read().splitlines()
    start = next(i for i, l in enumerate(src) if l.startswith("abm_env_get() {"))
    end = next(i for i in range(start, len(src)) if src[i] == "}")
    dropin = tmp_path / "dropin"
    dropin.mkdir()
    for fname, text in files.items():
        (dropin / fname).write_text(text, encoding="utf-8", newline="\n")
    script = tmp_path / "env_get.sh"
    script.write_text(
        f'DROPIN_DIR="{dropin.as_posix()}"\n' + "\n".join(src[start:end + 1])
        + f'\nabm_env_get {name}\n', encoding="utf-8", newline="\n")
    out = subprocess.run([bash, script.as_posix()], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    return out.stdout.strip()


def test_restore_script_act_dir_takes_last_uncommented(tmp_path):
    """Backup vecchi (Environment= in override.conf): conta solo l'ultima
    riga non commentata. Senza ancoraggio all'inizio riga, una riga commentata
    o duplicata finisce nel grep e produce un ACT_DIR multi-riga che fa
    fallire in silenzio la `cp` successiva (`|| true`), pur stampando
    'ripristinati'."""
    assert _restore_env_get(tmp_path, {"override.conf": (
        '# Environment="ABM_ACTIVITY_LOG_DIR=/old"\n'
        'Environment="ABM_ACTIVITY_LOG_DIR=/a"\n'
        'Environment=ABM_ACTIVITY_LOG_DIR=/b\n')}, "ABM_ACTIVITY_LOG_DIR") == "/b"


def test_restore_script_env_file_wins_over_environment(tmp_path):
    """Dal 19/11/2026 i valori stanno in override.env (NOME='valore'), che
    in systemd vince sulle Environment= dei .conf: restore deve leggere lui."""
    assert _restore_env_get(tmp_path, {
        "datadir.conf": 'Environment="ABM_ACTIVITY_LOG_DIR=/vecchio"\n',
        "override.env": ("# ABM_ACTIVITY_LOG_DIR='/commentato'\n"
                         "ABM_ACTIVITY_LOG_DIR='/opt/a b/logs'\n"),
    }, "ABM_ACTIVITY_LOG_DIR") == "/opt/a b/logs"
