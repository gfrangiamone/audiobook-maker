"""Il link dell'email di un libro in formato podcast (zip_rss) deve seguire la
copia cold dello ZIP dopo l'hot-evict.

Job I8owhF0k (18-19/11/2026): ZIP evacuato 2 h dopo la fine, MP3 sciolti gia'
cancellati dal "ZIP cleanup"; /dl/<token>/download rispondeva 410 "File non piu'
disponibili" mentre /api/download_podcast serviva lo stesso ZIP dal cold."""
import os
import time

import pytest

import token_store as _tkstore


@pytest.fixture
def app_env(fresh_app, tmp_path):
    audiobook_app = fresh_app(env={"ABM_DATA_DIR": str(tmp_path / "data")})
    audiobook_app.app.config["TESTING"] = True
    added = []
    yield audiobook_app, tmp_path, added
    for tok in added:
        _tkstore.download_tokens.pop(tok, None)


def _patch_cold(monkeypatch, cold_names):
    import storage_backend, storage_tiering
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_tiering, "key_for_path",
                        lambda p: f"cold/{os.path.basename(p)}" if p else None)
    monkeypatch.setattr(storage_backend, "object_exists",
                        lambda k: k in {f"cold/{n}" for n in cold_names})
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda k, download_name=None, ttl=None: f"https://cold/{k}")


def _podcast_token(added, tmp_path, tok, job_id, zip_name):
    zip_path = tmp_path / "data" / job_id / "output_1" / zip_name
    _tkstore.download_tokens[tok] = {
        "job_id": job_id, "created_at": time.time(), "download_type": "podcast",
        "podcast_ready": True, "output_zip": str(zip_path), "output_format": "zip_rss",
        "podcast_mp3s": [str(zip_path.parent / "001.mp3")], "book_title": "Libro"}
    added.append(tok)
    return zip_path


def test_evicted_podcast_zip_redirects_to_cold(app_env, monkeypatch):
    audiobook_app, tmp_path, added = app_env
    _podcast_token(added, tmp_path, "tokPod", "jobPod", "Libro.zip")
    _patch_cold(monkeypatch, ["Libro.zip"])
    resp = audiobook_app.app.test_client().get("/dl/tokPod/download", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://cold/cold/Libro.zip"


def test_evicted_podcast_zip_without_cold_copy_stays_410(app_env, monkeypatch):
    audiobook_app, tmp_path, added = app_env
    _podcast_token(added, tmp_path, "tokPodGone", "jobPodGone", "Libro.zip")
    _patch_cold(monkeypatch, [])
    resp = audiobook_app.app.test_client().get("/dl/tokPodGone/download", follow_redirects=False)
    assert resp.status_code == 410
