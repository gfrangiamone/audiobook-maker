"""S11 (2026-10-13): il transfer token (QR sulla pagina /dl) non scadeva e il
claim riassegnava il job a chiunque lo presentasse: chi riceveva il link
inoltrato prendeva il controllo del job. Ora scade dopo
ABM_TRANSFER_TOKEN_TTL_SEC (410) e il primo claim lo lega al cid (409 per un
cid diverso, idempotente per lo stesso)."""
import time

import pytest

import audiobook_app
import routes_mobile
import token_store

OWNER, APP_A, APP_B = "cid_s11_owner", "cid_s11_app_a", "cid_s11_app_b"


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(token_store, "save_transfer_tokens", lambda: None)
    monkeypatch.setattr(token_store, "save_tokens", lambda: None)
    monkeypatch.setattr(routes_mobile, "_log_activity", lambda *a, **k: None)
    job = {"status": "generating", "client_id": OWNER, "original_filename": "x.epub", "created_at": 0, "last_poll": 0}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["s11-job"] = job
    token_store.transfer_tokens["s11-tok"] = {"job_id": "s11-job", "created_at": time.time()}
    token_store.transfer_tokens["s11-old"] = {"job_id": "s11-job", "created_at": time.time() - 10 * 86400}
    yield job
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("s11-job", None)
    token_store.transfer_tokens.pop("s11-tok", None)
    token_store.transfer_tokens.pop("s11-old", None)


def _claim(tok, cid):
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", cid)
        return c.post(f"/api/transfer/claim/{tok}", json={})


def test_expired_token_is_refused(setup):
    r = _claim("s11-old", APP_A)
    assert r.status_code == 410 and r.get_json()["error_code"] == "token_expired"
    assert setup["client_id"] == OWNER


def test_first_claim_binds_the_token_to_the_device(setup):
    assert _claim("s11-tok", APP_A).status_code == 200
    assert setup["client_id"] == APP_A and token_store.transfer_tokens["s11-tok"]["claimed_by"] == APP_A
    r = _claim("s11-tok", APP_B)
    assert r.status_code == 409 and r.get_json()["error_code"] == "already_claimed"
    assert setup["client_id"] == APP_A
    assert _claim("s11-tok", APP_A).status_code == 200           # idempotente per lo stesso cid


def test_ttl_default_and_floor():
    assert routes_mobile.TRANSFER_TOKEN_TTL_SEC == 86400
