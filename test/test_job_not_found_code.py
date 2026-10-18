"""Job sparito dal server (restart, pulizia orfane) con la scheda ancora aperta
(ticket del 18/10/2026): stima e create-order rispondevano 404 senza codice e la
SPA mostrava "PayPal error: Job not found". Ora il 404 porta error_code
job_not_found e la SPA chiede di ricaricare il file."""
import os

import pytest

import audiobook_app as app

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROUTES = ("/api/paypal_create_order", "/api/paypal_create_order_gemini",
          "/api/paypal_create_order_translate", "/api/combined_estimate")


@pytest.fixture
def client(monkeypatch):
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "_paypal_available", lambda: True)
    monkeypatch.setattr(app, "_maintenance_gate", lambda: None)
    return app.app.test_client()


def test_missing_job_404_carries_error_code(client):
    for route in ROUTES:
        r = client.post(route, json={"job_id": "sparito", "voice_id": "gemini:flash31:Zephyr",
                                     "amount_eur": 1.0, "selected_chapters": [1]})
        assert r.status_code == 404, route
        assert r.get_json().get("error_code") == "job_not_found", route


def _read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


def test_spa_localizes_job_not_found():
    js = _read("static/js/app.js")
    # createOrder passa da _VOICE_MODEL_ERR: il codice deve stare nella mappa.
    assert "job_not_found:['err_job_not_found'" in js
    assert "_d.error_code==='job_not_found'" in js
    assert _read("templates/_fragments/i18n_data.js").count("err_job_not_found:") == 7
