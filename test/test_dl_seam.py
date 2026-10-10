"""E3, seam /dl + serving (2026-10-10): pagina e download via token, serving e
/api/download* nel blueprint `routes_dl`; helper della app risolti a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_dl as rd

ROUTES = ("/dl/<token>", "/dl/<token>/download", "/dl/<token>/m4b", "/dl/<token>/abm", "/dl/<token>/translated",
          "/api/download/<job_id>", "/api/download_podcast/<job_id>", "/api/download_translation/<job_id>")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("dl."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    for name in ("def _serve_audio_download(", "def _serve_podcast_download(", "def _render_dl_page(",
                 "def _build_podcast_zip(", "def _check_dl_token(", "def _resolve_snapshot_path("):
        assert name not in src and name in inspect.getsource(rd), name
    assert "app.register_blueprint(routes_dl.bp)" in src
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rd), flags=re.M)
    assert "os.environ.get(" not in inspect.getsource(rd)
    # Ogni helper della app richiesto da configure e' davvero una funzione della app.
    for n in rd.FUNCS:
        assert callable(getattr(audiobook_app, n)), n


def test_app_helpers_and_values_resolve_at_call_time(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://seam.test")
    monkeypatch.setattr(audiobook_app, "jobs", {"J": {"status": "done"}})
    monkeypatch.setattr(audiobook_app, "EMAIL_FILE_RETENTION_SEC", 123)
    assert rd._upload_dir() == tmp_path and rd._base_url() == "https://seam.test"
    assert rd._jobs() == {"J": {"status": "done"}} and rd._email_file_retention_sec() == 123
    seen = []
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: seen.append(a))
    monkeypatch.setattr(audiobook_app, "_cold_object_available", lambda p: p == "cold")
    monkeypatch.setattr(audiobook_app, "_try_cold_serve", lambda p, download_name=None: f"served:{p}")
    rd._log_activity("J", "f", "DOWNLOAD")
    assert seen == [("J", "f", "DOWNLOAD")]
    assert rd._cold_object_available("cold") is True and rd._try_cold_serve("x") == "served:x"
    assert rd.FAVICON_B64 == audiobook_app.FAVICON_B64 and rd._DL_PAGES_I18N is audiobook_app._DL_PAGES_I18N
    import generation_engine
    assert rd.generation_engine is generation_engine


def test_dl_page_for_unknown_token_is_the_expired_page():
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    r = c.get("/dl/nope-not-a-token", headers={"Accept-Language": "it"})
    assert r.status_code in (404, 410)
    assert "html" in r.get_data(as_text=True).lower()
