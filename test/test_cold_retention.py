"""Finestra di disponibilità utente: indipendente dal cold storage.

Il cold decide solo DOVE si serve il file (locale durante la finestra calda,
presigned URL dopo), non QUANTO resta disponibile. L'unica estensione e' la
salvaguardia no-download per le voci PREMIUM/Gemini (×2 sulla base)."""
import importlib


def _reload_app(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app


def test_retention_same_when_s3_off(monkeypatch, tmp_path):
    aa = _reload_app(monkeypatch, tmp_path)
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    assert aa._retention_for_job({"voice": "it-IT-IsabellaNeural"}) == aa.EMAIL_FILE_RETENTION_SEC
    assert aa._retention_for_job({"voice": "gemini:flash25:Zephyr"}) == aa.GEMINI_FILE_RETENTION_SEC
    assert aa._retention_for_token_info({"is_gemini": True}) == aa.GEMINI_FILE_RETENTION_SEC


def test_retention_unchanged_when_s3_on(monkeypatch, tmp_path):
    """Con S3 attivo la retention base NON cambia (niente raddoppio cieco cold)."""
    aa = _reload_app(monkeypatch, tmp_path)
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    assert aa._retention_for_job({"voice": "it-IT-IsabellaNeural"}) == aa.EMAIL_FILE_RETENTION_SEC
    assert aa._retention_for_job({"voice": "gemini:flash25:Zephyr"}) == aa.GEMINI_FILE_RETENTION_SEC
    assert aa._retention_for_token_info({"is_gemini": True}) == aa.GEMINI_FILE_RETENTION_SEC
    assert aa._retention_for_token_info({"is_gemini": False}) == aa.EMAIL_FILE_RETENTION_SEC


def test_premium_never_downloaded_doubles(monkeypatch, tmp_path):
    """Unica eccezione: job/token PREMIUM mai scaricato -> retention base ×2.
    Voci standard e PREMIUM gia' scaricati: nessuna estensione."""
    aa = _reload_app(monkeypatch, tmp_path)
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    M = aa.GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER
    # PREMIUM mai scaricato -> ×2
    assert aa._effective_retention_for_job({"voice": "gemini:flash25:Zephyr"}) == aa.GEMINI_FILE_RETENTION_SEC * M
    assert aa._effective_retention_for_token_info({"is_gemini": True}) == aa.GEMINI_FILE_RETENTION_SEC * M
    # PREMIUM gia' scaricato -> base
    assert aa._effective_retention_for_job(
        {"voice": "gemini:flash25:Zephyr", "downloaded_at": 1.0}) == aa.GEMINI_FILE_RETENTION_SEC
    assert aa._effective_retention_for_token_info(
        {"is_gemini": True, "downloaded_at": 1.0}) == aa.GEMINI_FILE_RETENTION_SEC
    # Standard -> base, scaricato o no
    assert aa._effective_retention_for_job({"voice": "it-IT-IsabellaNeural"}) == aa.EMAIL_FILE_RETENTION_SEC
    assert aa._effective_retention_for_token_info({"is_gemini": False}) == aa.EMAIL_FILE_RETENTION_SEC


def test_engine_email_retention_independent_of_s3(monkeypatch, tmp_path):
    import generation_engine, storage_backend
    base_std = generation_engine._retention_sec
    base_gem = generation_engine._gemini_retention_sec
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    assert generation_engine._retention_for_job({"voice": "it-IT-IsabellaNeural"}) == base_std
    assert generation_engine._retention_for_job({"voice": "gemini:flash25:Zephyr"}) == base_gem
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    assert generation_engine._retention_for_job({"voice": "it-IT-IsabellaNeural"}) == base_std
