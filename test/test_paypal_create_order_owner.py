"""E2: i tre create-order PayPal passano da _check_job_owner (prima leggevano
jobs[job_id] senza guardia: un client poteva aprire un ordine sul job di un altro)."""
import pytest

import audiobook_app as app
from epub_to_tts import BookInfo, Chapter

ROUTES = ("/api/paypal_create_order", "/api/paypal_create_order_gemini", "/api/paypal_create_order_translate")


@pytest.fixture
def env(monkeypatch):
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "_paypal_available", lambda: True)
    monkeypatch.setattr(app, "_maintenance_gate", lambda: None)
    ch = Chapter(index=0, title="C", text="x" * 50000)
    info = BookInfo(title="T", author="A", language="it", chapters=[ch], total_words=ch.word_count,
                    total_chars=ch.char_count, estimated_duration_minutes=1.0)
    with app._jobs_lock:
        app.jobs["own-1"] = {"info": info, "status": "analyzed", "client_id": "owner-cid"}
        app.jobs["legacy-1"] = {"info": info, "status": "analyzed"}
    yield
    with app._jobs_lock:
        app.jobs.pop("own-1", None)
        app.jobs.pop("legacy-1", None)


def _post(client, route, job_id):
    return client.post(route, json={"job_id": job_id, "voice_id": "gemini:flash31:Zephyr",
                                    "amount_eur": 1.0, "selected_chapters": []})


def test_other_client_gets_403_on_every_create_order(env):
    c = app.app.test_client()
    c.set_cookie("abm_cid", "someone-else")
    for route in ROUTES:
        r = _post(c, route, "own-1")
        assert r.status_code == 403 and r.get_json() == {"error": "Forbidden"}, route
    c = app.app.test_client()                    # nessun cookie
    for route in ROUTES:
        assert _post(c, route, "own-1").status_code == 403, route


def test_owner_admin_and_legacy_pass_the_guard(env, monkeypatch):
    monkeypatch.setattr(app, "ADMIN_TOKEN", "tok-test")
    c = app.app.test_client()
    c.set_cookie("abm_cid", "owner-cid")
    for route in ROUTES:
        assert _post(c, route, "own-1").status_code != 403, route
    c = app.app.test_client()
    for route in ROUTES:
        assert c.post(route, json={"job_id": "own-1", "voice_id": "gemini:flash31:Zephyr", "amount_eur": 1.0},
                      headers={"X-Admin-Token": "tok-test"}).status_code != 403, route
        assert _post(c, route, "legacy-1").status_code != 403, route    # job senza client_id: compatibilita'
    for route in ROUTES:
        assert _post(c, route, "manca").status_code == 404, route
