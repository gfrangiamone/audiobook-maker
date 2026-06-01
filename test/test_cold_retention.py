"""Cold storage attivo: retention totale raddoppia; S3 off = invariata."""
import importlib


def _reload_app(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app


def test_retention_unchanged_when_s3_off(monkeypatch, tmp_path):
    aa = _reload_app(monkeypatch, tmp_path)
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    assert aa._retention_for_job({"voice": "it-IT-IsabellaNeural"}) == aa.EMAIL_FILE_RETENTION_SEC
    assert aa._retention_for_job({"voice": "gemini:flash25:Zephyr"}) == aa.GEMINI_FILE_RETENTION_SEC
    assert aa._retention_for_token_info({"is_gemini": True}) == aa.GEMINI_FILE_RETENTION_SEC


def test_retention_doubled_when_s3_on(monkeypatch, tmp_path):
    aa = _reload_app(monkeypatch, tmp_path)
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    assert aa._retention_for_job({"voice": "it-IT-IsabellaNeural"}) == aa.EMAIL_FILE_RETENTION_SEC * 2
    assert aa._retention_for_job({"voice": "gemini:flash25:Zephyr"}) == aa.GEMINI_FILE_RETENTION_SEC * 2
    assert aa._retention_for_token_info({"is_gemini": True}) == aa.GEMINI_FILE_RETENTION_SEC * 2
    assert aa._retention_for_token_info({"is_gemini": False}) == aa.EMAIL_FILE_RETENTION_SEC * 2


def test_engine_email_retention_doubles_when_s3_on(monkeypatch, tmp_path):
    import generation_engine, storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    base_std = generation_engine._retention_sec
    assert generation_engine._retention_for_job({"voice": "it-IT-IsabellaNeural"}) == base_std * 2
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    assert generation_engine._retention_for_job({"voice": "it-IT-IsabellaNeural"}) == base_std
