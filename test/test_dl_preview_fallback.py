"""Regression (incidente 2026-06-10, job K9v-PxIXyUVUKqVkg3vjZg):

Un download via token email di tipo 'chapters' il cui ZIP locale era stato
evacuato su cold (R2) serviva, invece della copia cold autoritativa, uno ZIP
costruito al volo dai `preview_*.mp3` rimasti nella job root.

Cause:
  B-ORDER : il fallback scan-directory veniva tentato PRIMA del cold-serve.
  B-PREVIEW: il fallback includeva i preview_*.mp3 (campioni voce, mai deliverable).

Questi test bloccano la regressione di entrambi.
"""
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


def _make_job_with_previews(tmp_path, job_id):
    """Crea la job dir con SOLO preview_*.mp3 (lo ZIP reale è evacuato)."""
    job_dir = tmp_path / job_id
    (job_dir / "output_1").mkdir(parents=True)
    for i in range(10):
        (job_dir / f"preview_{i:016x}.mp3").write_bytes(b"ID3preview" + bytes(100))
    return job_dir


def test_chapters_dl_redirects_to_cold_not_preview_zip(app_env, monkeypatch):
    """ZIP evacuato + cold presente + preview_*.mp3 nella root → 302 cold,
    NON 200 con uno zip di preview."""
    audiobook_app, tmp_path = app_env
    job_id = "K9vPreviewJob"
    _make_job_with_previews(tmp_path, job_id)
    missing_zip = str(tmp_path / job_id / "output_1" / "book.zip")
    key = f"{job_id}/output_1/book.zip"
    _patch_cold(monkeypatch, key)

    audiobook_app._download_tokens.clear()
    audiobook_app._download_tokens["tokZ"] = {
        "job_id": job_id,
        "created_at": time.time(),
        "download_type": "chapters",
        "output_zip": missing_zip,
        "output_name": "book.zip",
        "book_title": "Libro",
        "original_filename": "book.pdf",
    }

    client = audiobook_app.app.test_client()
    resp = client.get("/dl/tokZ/download", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["Location"] == f"https://cold/{key}"


def test_chapters_dl_never_serves_preview_when_cold_unavailable(app_env, monkeypatch):
    """Anche senza cold disponibile, i preview_*.mp3 non vanno MAI serviti:
    il download è non più disponibile (410), non uno zip di preview (200)."""
    audiobook_app, tmp_path = app_env
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)

    job_id = "PreviewOnlyJob"
    _make_job_with_previews(tmp_path, job_id)

    audiobook_app._download_tokens.clear()
    audiobook_app._download_tokens["tokP"] = {
        "job_id": job_id,
        "created_at": time.time(),
        "download_type": "chapters",
        "output_zip": str(tmp_path / job_id / "output_1" / "book.zip"),
        "output_name": "book.zip",
        "book_title": "Libro",
        "original_filename": "book.pdf",
    }

    client = audiobook_app.app.test_client()
    resp = client.get("/dl/tokP/download", follow_redirects=False)
    assert resp.status_code == 410
