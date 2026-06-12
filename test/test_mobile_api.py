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
