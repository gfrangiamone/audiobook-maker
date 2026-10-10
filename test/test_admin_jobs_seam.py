"""E3, seam admin parte 4 (2026-10-10): strumenti admin sui job nel blueprint
`routes_admin_jobs`; stato e policy della app risolti a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_admin_jobs as rj

ROUTES = ("/api/admin/suspend", "/admin/api/job/<path:job_id>/copy-qr", "/admin/job/<path:job_id>/forensic.zip",
          "/api/admin/load_stats", "/api/admin/user_stats", "/api/admin/jobs_progress",
          "/api/paypal_debug_order/<order_id>", "/api/active_jobs")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("admin_jobs."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    for name in ("def _admin_copy_recoverable(", "def _admin_user_dl_link(", "def _admin_notify_email_for_job(",
                 "_USER_STATS_CACHE = {}", "_JOBS_PROGRESS_MAX_IDS = "):
        assert name not in src and name in inspect.getsource(rj), name
    assert "app.register_blueprint(routes_admin_jobs.bp)" in src
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rj), flags=re.M)
    assert "os.environ.get(" not in inspect.getsource(rj)


def test_state_and_policies_resolve_on_the_app(monkeypatch, tmp_path):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda s: None)
    c = audiobook_app.app.test_client()
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "")
    assert c.get("/api/active_jobs").status_code == 404
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-seam")
    assert c.get("/api/active_jobs").status_code == 401
    monkeypatch.setattr(audiobook_app, "jobs", {"J1": {"status": "generating", "progress_current": 1, "progress_total": 4,
                                                       "original_filename": "libro.epub"}})
    r = c.get("/api/active_jobs", headers={"X-Admin-Token": "tok-seam"})
    assert r.status_code == 200 and [j["title"] for j in r.get_json()["jobs"]] == ["libro.epub"]
    assert rj._jobs() is audiobook_app.jobs and rj._jobs_lock is audiobook_app._jobs_lock
    assert rj._suspend_lock is audiobook_app._suspend_lock and rj._YM_RE is audiobook_app._YM_RE
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    assert rj._upload_dir() == tmp_path
    monkeypatch.setattr(audiobook_app, "_client_emails", {"cid-1": " a@x.it "})
    assert rj._admin_notify_email_for_job.__name__ == "_admin_notify_email_for_job" and rj._client_emails() == {"cid-1": " a@x.it "}
    monkeypatch.setattr(audiobook_app, "MAX_CONCURRENT_GLOBAL", 42)
    assert rj._max_concurrent_global() == 42
    monkeypatch.setattr(audiobook_app, "_qr_data_uri", lambda text: f"qr:{text}")
    assert rj._qr_data_uri("x") == "qr:x"
