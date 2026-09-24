"""Tests for platform field in activity log (Task A5)."""
import activity_log


def test_log_activity_writes_platform(tmp_path, monkeypatch):
    import audiobook_app as app
    monkeypatch.setattr(app, "SCRIPT_DIR", tmp_path)
    activity_log.reset()
    app._log_activity("jobP", "f.epub", "GENERATE", client_id="c", voice="v",
                      browser_lang="it", platform="android")
    log = list(tmp_path.glob("activity_*.log"))[0].read_text(encoding="utf-8")
    assert log.rstrip("\n").split(" # ")[-1] == "android"


def test_log_activity_platform_defaults_empty(tmp_path, monkeypatch):
    import audiobook_app as app
    monkeypatch.setattr(app, "SCRIPT_DIR", tmp_path)
    activity_log.reset()
    app._log_activity("jobQ", "f.epub", "COMPLETE", client_id="c")
    log = list(tmp_path.glob("activity_*.log"))[0].read_text(encoding="utf-8")
    assert log.rstrip("\n").split(" # ")[-1] == ""
