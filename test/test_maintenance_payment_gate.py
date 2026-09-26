# test/test_maintenance_payment_gate.py
"""Con la sospensione admin attiva non si incassa nulla.

Caso d'origine (26/09/2026): libro caricato prima della sospensione, ordine
PayPal creato e catturato durante la manutenzione, poi `/api/generate` -> 503.
La capture restava orfana e dopo 30 minuti tornava all'utente come voucher,
invece del servizio. La guardia deve stare su creazione ordine, capture e
`/api/translate` (preflight di pagamento), non solo su generate/optimize.
"""
import pytest

import audiobook_app
import payment
import translation_core


@pytest.fixture
def client(monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app, "_suspend_new_jobs", True)
    monkeypatch.setattr(audiobook_app, "_paypal_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_vc_gate", lambda: None)
    monkeypatch.setattr(translation_core, "is_available", lambda: True)
    return audiobook_app.app.test_client()


@pytest.mark.parametrize("endpoint", [
    "/api/paypal_create_order",
    "/api/paypal_create_order_gemini",
    "/api/paypal_create_order_translate",
    "/api/paypal_create_order_voice_clone",
])
def test_create_order_refused_during_maintenance(client, endpoint):
    r = client.post(endpoint, json={"job_id": "nope"})
    assert r.status_code == 503
    assert r.get_json()["error_code"] == "maintenance"


def test_capture_not_attempted_during_maintenance(client, monkeypatch):
    called = []
    monkeypatch.setattr(payment, "capture_and_store_order",
                        lambda *a, **k: called.append(a))
    r = client.post("/api/paypal_capture_order",
                    json={"order_id": "ORDER1", "job_id": "j1"})
    assert r.status_code == 503
    assert r.get_json()["error_code"] == "maintenance"
    assert called == []


def test_translate_refused_during_maintenance(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_check_job_owner",
                        lambda jid: ({"info": type("I", (), {"chapters": [1]})(),
                                      "status": "analyzed"}, None, 200))
    r = client.post("/api/translate", json={"job_id": "j1"})
    assert r.status_code == 503
    assert r.get_json()["error_code"] == "maintenance"


def test_create_order_passes_gate_when_not_suspended(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_suspend_new_jobs", False)
    r = client.post("/api/paypal_create_order", json={"job_id": "nope"})
    assert r.status_code == 404
