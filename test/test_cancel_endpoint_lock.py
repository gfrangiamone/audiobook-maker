"""Test del gate ABM_GEMINI_CANCEL_LOCK_PCT su /api/cancel/<job_id>."""
from unittest.mock import patch

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def _seed_job(job_id, voice, progress_current, progress_total):
    audiobook_app.jobs[job_id] = {
        "voice": voice,
        "progress_current": progress_current,
        "progress_total": progress_total,
        "client_id": "c1",
        "client_ip": "127.0.0.1",
    }


def test_cancel_gemini_below_threshold_allowed(client):
    _seed_job("J1", "gemini:flash25:Zephyr", 30, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J1"], None, None)):
        r = client.post("/api/cancel/J1")
    assert r.status_code == 200
    assert audiobook_app.jobs["J1"].get("cancelled") is True
    del audiobook_app.jobs["J1"]


def test_cancel_gemini_above_threshold_blocked(client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CANCEL_LOCK_PCT", "70")
    _seed_job("J2", "gemini:flash25:Zephyr", 80, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J2"], None, None)):
        r = client.post("/api/cancel/J2")
    assert r.status_code == 409
    body = r.get_json()
    assert body["error"] == "cancel_locked_progress"
    assert body["progress_pct"] == 80
    assert body["lock_pct"] == 70
    assert audiobook_app.jobs["J2"].get("cancelled") is not True
    del audiobook_app.jobs["J2"]


def test_cancel_non_gemini_above_threshold_allowed(client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CANCEL_LOCK_PCT", "70")
    _seed_job("J3", "it-IT-DiegoNeural", 95, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J3"], None, None)):
        r = client.post("/api/cancel/J3")
    assert r.status_code == 200
    assert audiobook_app.jobs["J3"].get("cancelled") is True
    del audiobook_app.jobs["J3"]


def test_cancel_lock_disabled_by_env_100(client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CANCEL_LOCK_PCT", "100")
    _seed_job("J4", "gemini:flash25:Zephyr", 99, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J4"], None, None)):
        r = client.post("/api/cancel/J4")
    assert r.status_code == 200
    del audiobook_app.jobs["J4"]


def test_cancel_lock_disabled_by_env_0(client, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CANCEL_LOCK_PCT", "0")
    _seed_job("J5", "gemini:flash25:Zephyr", 99, 100)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["J5"], None, None)):
        r = client.post("/api/cancel/J5")
    assert r.status_code == 200
    del audiobook_app.jobs["J5"]
