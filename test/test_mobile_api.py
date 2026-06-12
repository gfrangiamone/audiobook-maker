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
