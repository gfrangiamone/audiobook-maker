"""Il business log deve distinguere una consegna reale (byte serviti da noi) da
un semplice redirect 302 alla copia cold: sul redirect non sappiamo se l'utente
abbia davvero ricevuto il file (vedi incidente filtro IP sul token R2, dove ogni
redirect finiva in 403 ma il log registrava un download riuscito)."""
import importlib
import time
from datetime import datetime

import pytest


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path / "data"))
    import audiobook_app
    importlib.reload(audiobook_app)
    audiobook_app.app.config["TESTING"] = True
    # il log mensile va scritto in tmp, non nella working copy
    log_dir = tmp_path / "app"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", log_dir)
    audiobook_app._logged_sids_ops.clear()
    return audiobook_app, tmp_path, log_dir


def _patch_cold(monkeypatch, key):
    import storage_backend, storage_tiering
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: k == key)
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda k, download_name=None, ttl=None: f"https://cold/{k}")
    monkeypatch.setattr(storage_tiering, "key_for_path", lambda p: key)


def _logged_ops(log_dir, job_id):
    """Operazioni registrate nel business log per un job_id."""
    path = log_dir / f"activity_{datetime.now().strftime('%Y-%m')}.log"
    if not path.exists():
        return []
    ops = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = [p.strip() for p in line.split("#")]
        if len(parts) > 3 and parts[0] == job_id:
            ops.append(parts[3])
    return ops


def test_cold_redirect_is_logged_as_cold_not_as_delivered_download(app_env, monkeypatch):
    """M4B evacuato → 302 al presigned: il log deve marcare il redirect, non un download."""
    audiobook_app, tmp_path, log_dir = app_env
    job_id = "jobCold"
    missing_m4b = str(tmp_path / "data" / job_id / "output_1" / "book.m4b")
    _patch_cold(monkeypatch, "jobCold/output_1/book.m4b")

    audiobook_app._download_tokens.clear()
    audiobook_app._download_tokens["tokCold"] = {
        "job_id": job_id,
        "created_at": time.time(),
        "output_m4b": missing_m4b,
        "book_title": "Il Libro",
        "original_filename": "book.epub",
    }

    resp = audiobook_app.app.test_client().get("/dl/tokCold/m4b", follow_redirects=False)

    assert resp.status_code == 302
    assert _logged_ops(log_dir, job_id) == ["DOWNLOAD_M4B_TOKEN_COLD"]


def test_local_serving_is_logged_as_delivered_download(app_env, monkeypatch):
    """M4B ancora locale → i byte passano da noi: resta l'operazione di consegna."""
    audiobook_app, tmp_path, log_dir = app_env
    job_id = "jobHot"
    out_dir = tmp_path / "data" / job_id / "output_1"
    out_dir.mkdir(parents=True, exist_ok=True)
    m4b = out_dir / "book.m4b"
    m4b.write_bytes(b"\x00\x00\x00\x1cftypM4A " + b"x" * 64)

    audiobook_app._download_tokens.clear()
    audiobook_app._download_tokens["tokHot"] = {
        "job_id": job_id,
        "created_at": time.time(),
        "output_m4b": str(m4b),
        "book_title": "Il Libro",
        "original_filename": "book.epub",
    }

    resp = audiobook_app.app.test_client().get("/dl/tokHot/m4b", follow_redirects=False)

    assert resp.status_code == 200
    assert _logged_ops(log_dir, job_id) == ["DOWNLOAD_M4B_TOKEN"]


def test_cold_redirect_keeps_premium_no_download_retention(app_env, monkeypatch):
    """Redirect 302 su token PREMIUM: senza prova di consegna la protezione
    no-download deve restare attiva (un 403 sul presigned non deve costare
    all'utente meta' della finestra di disponibilita')."""
    audiobook_app, tmp_path, log_dir = app_env
    job_id = "jobColdPrem"
    missing_m4b = str(tmp_path / "data" / job_id / "output_1" / "book.m4b")
    _patch_cold(monkeypatch, "jobColdPrem/output_1/book.m4b")

    tok = {
        "job_id": job_id,
        "created_at": time.time(),
        "output_m4b": missing_m4b,
        "book_title": "Il Libro",
        "original_filename": "book.epub",
        "is_gemini": True,
    }
    audiobook_app._download_tokens.clear()
    audiobook_app._download_tokens["tokColdPrem"] = tok
    base = audiobook_app._retention_for_token_info(tok)

    resp = audiobook_app.app.test_client().get("/dl/tokColdPrem/m4b", follow_redirects=False)

    assert resp.status_code == 302
    assert not tok.get("downloaded_at")
    assert (audiobook_app._effective_retention_for_token_info(tok)
            == base * audiobook_app.GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER)


def test_local_serving_marks_token_downloaded(app_env, monkeypatch):
    """Serving locale: i byte escono da noi, la protezione no-download decade."""
    audiobook_app, tmp_path, log_dir = app_env
    job_id = "jobHotPrem"
    out_dir = tmp_path / "data" / job_id / "output_1"
    out_dir.mkdir(parents=True, exist_ok=True)
    m4b = out_dir / "book.m4b"
    m4b.write_bytes(b"\x00\x00\x00\x1cftypM4A " + b"x" * 64)

    tok = {
        "job_id": job_id,
        "created_at": time.time(),
        "output_m4b": str(m4b),
        "book_title": "Il Libro",
        "original_filename": "book.epub",
        "is_gemini": True,
    }
    audiobook_app._download_tokens.clear()
    audiobook_app._download_tokens["tokHotPrem"] = tok
    base = audiobook_app._retention_for_token_info(tok)

    resp = audiobook_app.app.test_client().get("/dl/tokHotPrem/m4b", follow_redirects=False)

    assert resp.status_code == 200
    assert tok.get("downloaded_at")
    assert audiobook_app._effective_retention_for_token_info(tok) == base


def test_api_download_cold_redirect_keeps_premium_no_download_retention(app_env, monkeypatch):
    """Stesso invariante su /api/download (flusso interattivo e app mobile):
    il redirect al cold non conta come download del job."""
    audiobook_app, tmp_path, log_dir = app_env
    job_id = "jobApiCold"
    missing_m4b = str(tmp_path / "data" / job_id / "output_1" / "book.m4b")
    _patch_cold(monkeypatch, "jobApiCold/output_1/book.m4b")
    monkeypatch.setattr(audiobook_app, "_cold_m4b_valid", lambda p: True)

    class _Info:
        title = "Il Libro"

    job = {
        "status": "done",
        "voice": "gemini:tts-model:Kore",
        "output_m4b": missing_m4b,
        "original_filename": "book.epub",
        "info": _Info(),
    }
    audiobook_app.jobs[job_id] = job
    base = audiobook_app._retention_for_job(job)

    resp = audiobook_app.app.test_client().get(f"/api/download/{job_id}?type=m4b",
                                               follow_redirects=False)

    assert resp.status_code == 302
    assert not job.get("downloaded_at")
    assert (audiobook_app._effective_retention_for_job(job)
            == base * audiobook_app.GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER)


def test_api_download_local_serving_marks_job_downloaded(app_env, monkeypatch):
    """Serving locale da /api/download: consegna reale, protezione disattivata."""
    audiobook_app, tmp_path, log_dir = app_env
    job_id = "jobApiHot"
    out_dir = tmp_path / "data" / job_id / "output_1"
    out_dir.mkdir(parents=True, exist_ok=True)
    m4b = out_dir / "book.m4b"
    m4b.write_bytes(b"\x00\x00\x00\x1cftypM4A " + b"x" * 64)

    class _Info:
        title = "Il Libro"

    job = {
        "status": "done",
        "voice": "gemini:tts-model:Kore",
        "output_m4b": str(m4b),
        "original_filename": "book.epub",
        "info": _Info(),
    }
    audiobook_app.jobs[job_id] = job
    base = audiobook_app._retention_for_job(job)

    resp = audiobook_app.app.test_client().get(f"/api/download/{job_id}?type=m4b",
                                               follow_redirects=False)

    assert resp.status_code == 200
    assert job.get("downloaded_at")
    assert audiobook_app._effective_retention_for_job(job) == base
