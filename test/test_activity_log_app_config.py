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


def _touch_log(d, ym):
    (d / f"activity_{ym}.log").write_text("", encoding="utf-8")


def test_warn_stale_same_dir_no_warning(tmp_path, capsys):
    _touch_log(tmp_path, "2026-09")
    out = audiobook_app._warn_stale_activity_logs(
        tmp_path, tmp_path, today=datetime(2026, 9, 24))
    assert out == []
    assert "ATTENZIONE" not in capsys.readouterr().out


def test_warn_stale_old_months_no_warning(tmp_path, capsys):
    script_dir = tmp_path / "app"
    log_dir = tmp_path / "data"
    script_dir.mkdir()
    log_dir.mkdir()
    _touch_log(script_dir, "2026-01")  # ben oltre i 3 mesi da settembre
    out = audiobook_app._warn_stale_activity_logs(
        script_dir, log_dir, today=datetime(2026, 9, 24))
    assert out == []
    assert "ATTENZIONE" not in capsys.readouterr().out


def test_warn_stale_recent_months_warns(tmp_path, capsys):
    script_dir = tmp_path / "app"
    log_dir = tmp_path / "data"
    script_dir.mkdir()
    log_dir.mkdir()
    _touch_log(script_dir, "2026-09")  # mese corrente
    _touch_log(script_dir, "2026-08")  # mese precedente
    _touch_log(script_dir, "2026-07")  # due mesi prima: ancora nella finestra
    _touch_log(script_dir, "2026-06")  # fuori dalla finestra di 3 mesi
    out = audiobook_app._warn_stale_activity_logs(
        script_dir, log_dir, today=datetime(2026, 9, 24))
    assert out == ["activity_2026-07.log", "activity_2026-08.log", "activity_2026-09.log"]
    captured = capsys.readouterr().out
    assert "[activity_log] ATTENZIONE: log in SCRIPT_DIR non letti:" in captured
    assert "activity_2026-09.log" in captured and "activity_2026-06.log" not in captured


def test_warn_stale_no_files_no_warning(tmp_path, capsys):
    script_dir = tmp_path / "app"
    log_dir = tmp_path / "data"
    script_dir.mkdir()
    log_dir.mkdir()
    out = audiobook_app._warn_stale_activity_logs(
        script_dir, log_dir, today=datetime(2026, 9, 24))
    assert out == []
    assert "ATTENZIONE" not in capsys.readouterr().out


def test_warn_stale_env_unset_no_warning(tmp_path, monkeypatch, capsys):
    # senza ABM_ACTIVITY_LOG_DIR, activity_log._dir() ricade su SCRIPT_DIR:
    # log_dir e script_dir coincidono, come nella chiamata reale a startup.
    monkeypatch.delenv("ABM_ACTIVITY_LOG_DIR", raising=False)
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmp_path)
    activity_log.reset()
    _touch_log(tmp_path, "2026-09")
    try:
        out = audiobook_app._warn_stale_activity_logs(
            audiobook_app.SCRIPT_DIR, activity_log._dir(), today=datetime(2026, 9, 24))
    finally:
        activity_log.reset()
    assert out == []
    assert "ATTENZIONE" not in capsys.readouterr().out


def test_warn_stale_env_set_warns(tmp_path, monkeypatch, capsys):
    script_dir = tmp_path / "app"
    log_dir = tmp_path / "data"
    script_dir.mkdir()
    log_dir.mkdir()
    monkeypatch.setenv("ABM_ACTIVITY_LOG_DIR", str(log_dir))
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", script_dir)
    activity_log.reset()
    _touch_log(script_dir, "2026-09")
    try:
        out = audiobook_app._warn_stale_activity_logs(
            audiobook_app.SCRIPT_DIR, activity_log._dir(), today=datetime(2026, 9, 24))
    finally:
        activity_log.reset()
    assert out == ["activity_2026-09.log"]
    assert "ATTENZIONE" in capsys.readouterr().out
