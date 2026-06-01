"""Integration: una richiesta su una rotta di download via token email per un
file evacuato (locale assente) deve fare redirect 302 alla copia cold (presigned
URL), invece di ritornare 404/410. Verifica che il fix della cold-redirect sia
cablato nelle rotte /dl/<token>/* e non solo dentro _send_file_throttled."""
import importlib
import time
import pytest


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import audiobook_app
    importlib.reload(audiobook_app)
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app, tmp_path


def _patch_cold(monkeypatch, key):
    import storage_backend, storage_tiering
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: k == key)
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda k, download_name=None, ttl=None: f"https://cold/{k}")
    monkeypatch.setattr(storage_tiering, "key_for_path", lambda p: key)


def test_token_m4b_route_redirects_to_cold_after_eviction(app_env, monkeypatch):
    """GET /dl/<token>/m4b con M4B locale evacuato → 302 verso il presigned cold."""
    audiobook_app, tmp_path = app_env
    job_id = "jobX"
    # path snapshotato nel token, sotto la data dir ma NON esistente su disco
    missing_m4b = str(tmp_path / job_id / "output_1" / "book.m4b")
    key = "jobX/output_1/book.m4b"
    _patch_cold(monkeypatch, key)

    audiobook_app._download_tokens.clear()
    audiobook_app._download_tokens["tok123"] = {
        "job_id": job_id,
        "created_at": time.time(),
        "output_m4b": missing_m4b,
        "book_title": "Il Libro",
        "original_filename": "book.epub",
    }

    client = audiobook_app.app.test_client()
    resp = client.get("/dl/tok123/m4b", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("https://cold/")
    assert resp.headers["Location"] == f"https://cold/{key}"


def test_token_m4b_route_no_redirect_when_disabled(app_env, monkeypatch):
    """Cold storage disabilitato + locale assente → 404 (comportamento originale)."""
    audiobook_app, tmp_path = app_env
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)

    audiobook_app._download_tokens.clear()
    audiobook_app._download_tokens["tok404"] = {
        "job_id": "jobY",
        "created_at": time.time(),
        "output_m4b": str(tmp_path / "jobY" / "output_1" / "book.m4b"),
        "book_title": "Libro",
        "original_filename": "book.epub",
    }

    client = audiobook_app.app.test_client()
    resp = client.get("/dl/tok404/m4b", follow_redirects=False)
    assert resp.status_code == 404
