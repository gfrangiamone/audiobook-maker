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
