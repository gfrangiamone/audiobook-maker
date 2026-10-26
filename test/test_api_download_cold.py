"""/api/download deve seguire la copia cold per ogni tipo, non solo per l'M4B.

Incidente 2026-10-24 (job FHJz, 8 h di sintesi): con ABM_HOT_WINDOW_SEC=7200
l'hot-evict toglie lo zip dal disco 2 h dopo la fine; il bottone della SPA
chiede /api/download?type=zip, che guardava solo il disco e rispondeva 404.
La SPA dice "file non piu' disponibile", l'utente chiude la scheda e il
cleanup (heartbeat perso, nessuna email) cancella anche la copia cold.
Dal 20/09 al 24/10 cosi' si sono persi 39 libri. Il ramo M4B era gia'
cold-aware dal 2026-07-01; zip, mp3, ripiego MP3, kit e podcast no."""
import os

import pytest


@pytest.fixture
def app_env(fresh_app, monkeypatch, tmp_path):
    audiobook_app = fresh_app(env={"ABM_DATA_DIR": str(tmp_path / "data")})
    audiobook_app.app.config["TESTING"] = True
    log_dir = tmp_path / "app"
    log_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", log_dir)
    import activity_log
    activity_log.reset()
    return audiobook_app, tmp_path


def _patch_cold(monkeypatch, cold_names):
    """Cold con gli oggetti `cold_names` (basename del path locale snapshottato)."""
    import storage_backend, storage_tiering
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_tiering, "key_for_path",
                        lambda p: f"cold/{os.path.basename(p)}" if p else None)
    monkeypatch.setattr(storage_backend, "object_exists",
                        lambda k: k in {f"cold/{n}" for n in cold_names})
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda k, download_name=None, ttl=None: f"https://cold/{k}")


class _Info:
    title = "Il Libro"


def _job(audiobook_app, tmp_path, job_id, **fields):
    out = tmp_path / "data" / job_id / "output_1"
    job = {"status": "done", "voice": "en-US-AndrewNeural",
           "original_filename": "book.epub", "info": _Info(), **fields}
    audiobook_app.jobs[job_id] = job
    return job, out


def _get(audiobook_app, url):
    return audiobook_app.app.test_client().get(url, follow_redirects=False)


def test_zip_evicted_redirects_to_cold(app_env, monkeypatch):
    audiobook_app, tmp_path = app_env
    job, out = _job(audiobook_app, tmp_path, "jobZip", output_name="Il_Libro.zip")
    job["output_zip"] = str(out / "Il_Libro.zip")
    _patch_cold(monkeypatch, ["Il_Libro.zip"])

    resp = _get(audiobook_app, "/api/download/jobZip?type=zip")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://cold/cold/Il_Libro.zip"
    # il redirect non e' una consegna: niente downloaded_at
    assert not job.get("downloaded_at")


def test_zip_missing_everywhere_is_still_404(app_env, monkeypatch):
    audiobook_app, tmp_path = app_env
    job, out = _job(audiobook_app, tmp_path, "jobZipGone", output_name="Il_Libro.zip")
    job["output_zip"] = str(out / "Il_Libro.zip")
    _patch_cold(monkeypatch, [])

    assert _get(audiobook_app, "/api/download/jobZipGone?type=zip").status_code == 404


def test_single_mp3_evicted_redirects_to_cold(app_env, monkeypatch):
    """Bottone MP3 (type=mp3): nessun ramo dedicato, passa dalla logica di default."""
    audiobook_app, tmp_path = app_env
    job, out = _job(audiobook_app, tmp_path, "jobMp3", output_name="Il_Libro.mp3")
    job["output_files"] = [str(out / "Il_Libro.mp3")]
    _patch_cold(monkeypatch, ["Il_Libro.mp3"])

    resp = _get(audiobook_app, "/api/download/jobMp3?type=mp3")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://cold/cold/Il_Libro.mp3"


def test_m4b_missing_falls_back_to_cold_mp3(app_env, monkeypatch):
    """M4B mai prodotto (output_m4b None) e MP3 evacuato: il ripiego MP3 segue il cold."""
    audiobook_app, tmp_path = app_env
    job, out = _job(audiobook_app, tmp_path, "jobM4bMp3", output_name="Il_Libro.m4b",
                    output_m4b=None)
    job["output_files"] = [str(out / "Il_Libro.mp3")]
    _patch_cold(monkeypatch, ["Il_Libro.mp3"])

    resp = _get(audiobook_app, "/api/download/jobM4bMp3?type=m4b")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://cold/cold/Il_Libro.mp3"


def test_mp3_fallback_prefers_cold_over_preview_in_job_root(app_env, monkeypatch):
    """L'hot-evict svuota solo output*/: lo scan della job dir troverebbe un
    preview_*.mp3 (campione voce) e lo consegnerebbe come libro."""
    audiobook_app, tmp_path = app_env
    job, out = _job(audiobook_app, tmp_path, "jobPreview", output_name="Il_Libro.m4b",
                    output_m4b=None)
    job["output_files"] = [str(out / "Il_Libro.mp3")]
    out.mkdir(parents=True)
    (out.parent / "preview_en-US-AndrewNeural.mp3").write_bytes(b"ID3" + b"x" * 64)
    _patch_cold(monkeypatch, ["Il_Libro.mp3"])

    resp = _get(audiobook_app, "/api/download/jobPreview?type=m4b")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://cold/cold/Il_Libro.mp3"


def test_m4bkit_evicted_redirects_to_cold(app_env, monkeypatch):
    audiobook_app, tmp_path = app_env
    job, out = _job(audiobook_app, tmp_path, "jobKit", output_name="Il_Libro.m4b")
    job["output_m4b_fallback_zip"] = str(out / "Il_Libro_audiolibro_capitoli.zip")
    job["output_files"] = [str(out / "Il_Libro.mp3")]
    _patch_cold(monkeypatch, ["Il_Libro_audiolibro_capitoli.zip", "Il_Libro.mp3"])

    resp = _get(audiobook_app, "/api/download/jobKit?type=m4bkit")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://cold/cold/Il_Libro_audiolibro_capitoli.zip"


def test_podcast_zip_with_rss_evicted_redirects_to_cold(app_env, monkeypatch):
    audiobook_app, tmp_path = app_env
    job, out = _job(audiobook_app, tmp_path, "jobPod", output_name="Il_Libro.zip",
                    podcast_ready=True, podcast_rss_included=True)
    job["output_zip"] = str(out / "Il_Libro.zip")
    _patch_cold(monkeypatch, ["Il_Libro.zip"])

    resp = _get(audiobook_app, "/api/download_podcast/jobPod")

    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://cold/cold/Il_Libro.zip"
