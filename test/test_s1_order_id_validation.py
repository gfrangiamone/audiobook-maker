"""S1 (2026-10-12): l'order_id arriva dal client e finisce nel PATH di una
richiesta PayPal firmata con il token del commerciante. Senza controllo di
forma, `../../payments/captures/<id>/refund?` trasformerebbe la capture in un
rimborso. La forma si verifica prima di ogni chiamata HTTP, nel route e nel
debug admin; il job_id (log e card admin) ha la sua regola in activity_log."""
import pytest

import activity_log
import audiobook_app
import payment
import routes_admin_jobs

TRAVERSAL = "../../payments/captures/7XX123456/refund?"


def test_order_id_shape():
    assert payment.is_order_id("36M6852033504281N")
    assert payment.is_order_id("ORDVC1") and payment.is_order_id("ORD_E") and payment.is_order_id("ORD-X")
    for bad in (TRAVERSAL, "", None, "abc", "36M68520 33504281N", "36M6852033504281N/capture",
                "ORD?x=1", "ORD#1", "ORD.1", "x" * 65):
        assert not payment.is_order_id(bad), bad
    assert activity_log.is_job_id("Ab3_-xyz") and activity_log.is_job_id("vc:abc123")
    for bad in ("<img onerror=1>", "a b", "a\nb", "a # b", "", "x" * 81):
        assert not activity_log.is_job_id(bad), bad


def test_capture_never_calls_paypal_with_a_malformed_id(monkeypatch):
    calls = []
    import requests
    monkeypatch.setattr(payment, "_paypal_get_access_token", lambda: "tok")
    monkeypatch.setattr(requests, "post", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(AssertionError("HTTP")))
    with pytest.raises(ValueError):
        payment._paypal_capture_order(TRAVERSAL)
    with pytest.raises(ValueError):
        payment.capture_and_store_order(TRAVERSAL, job_id="")
    assert calls == []


def test_route_rejects_malformed_ids_before_any_capture(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_paypal_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_maintenance_gate", lambda: None)
    called = []
    monkeypatch.setattr(payment, "capture_and_store_order", lambda *a, **k: called.append(a) or {})
    c = audiobook_app.app.test_client()
    r = c.post("/api/paypal_capture_order", json={"order_id": TRAVERSAL, "job_id": "j1"})
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_order_id"
    r = c.post("/api/paypal_capture_order", json={"order_id": "36M6852033504281N", "job_id": "<img onerror=1>"})
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_job_id"
    assert called == []


def test_admin_debug_order_rejects_malformed_id(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-admin")
    monkeypatch.setattr(routes_admin_jobs, "_paypal_available", lambda *a, **k: True, raising=False)
    import requests
    monkeypatch.setattr(requests, "get", lambda *a, **k: (_ for _ in ()).throw(AssertionError("HTTP")))
    c = audiobook_app.app.test_client()
    r = c.get("/api/paypal_debug_order/" + "..%2F..%2Fpayments", headers={"X-Admin-Token": "tok-admin"})
    assert r.status_code in (400, 404)
    r = c.get("/api/paypal_debug_order/abc.def%3Fx", headers={"X-Admin-Token": "tok-admin"})
    assert r.status_code == 400 and r.get_json()["error"] == "invalid_order_id"
