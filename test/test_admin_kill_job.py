"""Admin kill job da /admin/log-activity: log ADMIN_CANCEL + render pannello."""
from unittest.mock import patch

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def _seed_job(job_id, status, voice="it-IT-DiegoNeural"):
    audiobook_app.jobs[job_id] = {
        "status": status,
        "voice": voice,
        "client_id": "c1",
        "original_filename": "libro.epub",
        "progress_current": 10,
        "progress_total": 100,
    }


def test_admin_cancel_logs_admin_cancel(client):
    _seed_job("K1", "generating")
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["K1"], None, None)), \
         patch("audiobook_app._admin_auth_ok", return_value=True), \
         patch("audiobook_app._log_activity") as mock_log:
        r = client.post("/api/cancel/K1?force=1")
    assert r.status_code == 200
    ops = [c.args[2] for c in mock_log.call_args_list]
    assert "ADMIN_CANCEL" in ops
    del audiobook_app.jobs["K1"]


def test_user_cancel_does_not_log_admin_cancel(client):
    _seed_job("K2", "generating")
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["K2"], None, None)), \
         patch("audiobook_app._admin_auth_ok", return_value=False), \
         patch("audiobook_app._log_activity") as mock_log:
        r = client.post("/api/cancel/K2")
    assert r.status_code == 200
    ops = [c.args[2] for c in mock_log.call_args_list]
    assert "ADMIN_CANCEL" not in ops
    del audiobook_app.jobs["K2"]


def test_admin_cancel_optimize_logs_admin_cancel(client):
    _seed_job("K3", "optimizing")
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["K3"], None, None)), \
         patch("audiobook_app._admin_auth_ok", return_value=True), \
         patch("audiobook_app._log_activity") as mock_log:
        r = client.post("/api/cancel_optimize/K3")
    assert r.status_code == 200
    ops = [c.args[2] for c in mock_log.call_args_list]
    assert "ADMIN_CANCEL" in ops
    del audiobook_app.jobs["K3"]


def test_log_activity_page_contains_kill_ui(client):
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = client.get("/admin/log-activity")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "kmodalOverlay" in html
    assert "openKillModal" in html
    assert "Interrompere questo job?" in html


def test_kill_modal_markup_precedes_script(client):
    """Il markup di modale/toast deve precedere lo <script> che li risolve.

    Lo script viene eseguito in parsing sincrono: se #kmodalOverlay/#ktoast
    stanno dopo, getElementById restituisce null e il bottone ⛔ è morto
    (TypeError al click, nessun modale/toast).
    """
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = client.get("/admin/log-activity")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert html.index('id="kmodalOverlay"') < html.index("getElementById('kmodalOverlay')")
    assert html.index('id="ktoast"') < html.index("getElementById('ktoast')")
