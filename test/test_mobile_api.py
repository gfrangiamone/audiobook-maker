"""Test API mobile: header cid, device register, my_jobs."""
import time

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


# ---------------------------------------------------------------- Task 1

def test_client_id_from_header():
    with audiobook_app.app.test_request_context(
        headers={"X-ABM-Cid": "mobile-cid-12345"}
    ):
        assert audiobook_app._get_client_id() == "mobile-cid-12345"


def test_client_id_header_wins_over_cookie():
    with audiobook_app.app.test_request_context(
        headers={"X-ABM-Cid": "mobile-cid-12345", "Cookie": "abm_cid=cookiecid"}
    ):
        assert audiobook_app._get_client_id() == "mobile-cid-12345"


def test_client_id_invalid_header_falls_back_to_cookie():
    # spazi e caratteri non ammessi -> ignorato, vince il cookie
    with audiobook_app.app.test_request_context(
        headers={"X-ABM-Cid": "bad cid!!", "Cookie": "abm_cid=cookiecid"}
    ):
        assert audiobook_app._get_client_id() == "cookiecid"


def test_client_id_too_short_header_ignored():
    with audiobook_app.app.test_request_context(headers={"X-ABM-Cid": "abc"}):
        assert audiobook_app._get_client_id() == ""


# ---------------------------------------------------------------- Task 2

def test_completion_token_records_client_id(monkeypatch, tmp_path):
    import email_service
    import generation_engine as ge
    from unittest.mock import patch

    job_id = "mobtok1"
    audiobook_app.jobs[job_id] = {
        "status": "done",
        "client_id": "mobile-cid-12345",
        "notify_email": "u@x.it",
        "email_registered": True,
        "original_filename": "libro.epub",
        "output_format": "m4b",
        "output_m4b": str(tmp_path / "out.m4b"),
        "info": None,
        "last_poll": time.time(),
    }
    (tmp_path / "out.m4b").write_bytes(b"x")
    captured = {}
    try:
        with patch.object(email_service, "_send_email",
                          side_effect=lambda *a, **k: True), \
             patch.object(email_service, "_smtp_available", return_value=True), \
             patch.object(ge, "_save_tokens", side_effect=lambda: None):
            ge._send_completion_email(job_id)
        toks = [t for t, i in audiobook_app._download_tokens.items()
                if i.get("job_id") == job_id]
        assert toks, "nessun token creato"
        captured["info"] = audiobook_app._download_tokens[toks[0]]
        assert captured["info"].get("client_id") == "mobile-cid-12345"
    finally:
        audiobook_app.jobs.pop(job_id, None)
        for t in list(audiobook_app._download_tokens):
            if audiobook_app._download_tokens[t].get("job_id") == job_id:
                audiobook_app._download_tokens.pop(t, None)


# ---------------------------------------------------------------- Task 2 – round-trip persistenza

def test_token_client_id_survives_save_load_roundtrip(monkeypatch, tmp_path):
    import json
    import pathlib

    tokens_file = tmp_path / "_download_tokens.json"
    monkeypatch.setattr(audiobook_app, "_TOKENS_FILE", pathlib.Path(tokens_file))

    token_key = "TOKRT"
    monkeypatch.setattr(audiobook_app, "_download_tokens", {
        token_key: {
            "job_id": "rtjob",
            "client_id": "mobile-cid-12345",
            "created_at": time.time(),
            "book_title": "B",
            "is_gemini": False,
        }
    })

    audiobook_app._save_tokens()

    data = json.loads(tokens_file.read_text(encoding="utf-8"))
    assert token_key in data, "token non salvato"
    assert data[token_key].get("client_id") == "mobile-cid-12345", \
        "client_id non persistito da _save_tokens"


# ---------------------------------------------------------------- Task 3

HDR = {"X-ABM-Cid": "mobile-cid-12345"}


@pytest.fixture
def device_env(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "_DEVICE_TOKENS_FILE",
                        tmp_path / "_device_tokens.json")
    monkeypatch.setattr(audiobook_app, "_device_tokens", {})
    yield


def test_device_register_ok(client, device_env):
    r = client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": "tok-abc", "platform": "android",
                          "app_version": "1.0.0"})
    assert r.status_code == 200
    assert r.get_json()["ok"] is True
    entries = audiobook_app._device_tokens["mobile-cid-12345"]
    assert entries[0]["fcm_token"] == "tok-abc"
    assert entries[0]["platform"] == "android"
    assert audiobook_app._DEVICE_TOKENS_FILE.exists()


def test_device_register_requires_cid(client, device_env):
    r = client.post("/api/device/register",
                    json={"fcm_token": "tok-abc", "platform": "android"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "no_cid"


def test_device_register_invalid_platform(client, device_env):
    r = client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": "tok-abc", "platform": "windows"})
    assert r.status_code == 400
    assert r.get_json()["error_code"] == "invalid_platform"


def test_device_register_dedup_and_cap(client, device_env):
    for i in range(7):
        client.post("/api/device/register", headers=HDR,
                    json={"fcm_token": f"tok-{i}", "platform": "ios"})
    # ri-registrazione stesso token: niente duplicato
    client.post("/api/device/register", headers=HDR,
                json={"fcm_token": "tok-6", "platform": "ios"})
    entries = audiobook_app._device_tokens["mobile-cid-12345"]
    assert len(entries) == 5  # cap
    assert sum(1 for e in entries if e["fcm_token"] == "tok-6") == 1
