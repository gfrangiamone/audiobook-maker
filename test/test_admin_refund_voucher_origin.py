"""I rimborsi manuali creati dall'admin devono restare tracciabili al job.

payment.has_refund_for_job() riconosce un rimborso solo se il voucher porta
origin_job_id: senza quel campo i rimborsi fatti a mano erano invisibili al
guard anti-doppio-rimborso e il recovery ne emetteva un secondo sullo stesso job.
"""
import time
import pytest
import payment
import audiobook_app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **k: None)
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


HDRS = {"X-Admin-Token": "test-admin-token"}


def test_refund_voucher_carries_explicit_job_id(client):
    r = client.post("/admin/api/vouchers", json={
        "email": "buyer@x.it", "amount_eur": 5.0, "kind": "refund",
        "note": "rimborso manuale", "job_id": "9dmJT_I3lHSeD2Vwz0Bu1A",
    }, headers=HDRS)
    assert r.status_code == 200
    code = r.get_json()["code"]
    assert payment._vouchers[code]["origin_job_id"] == "9dmJT_I3lHSeD2Vwz0Bu1A"
    assert payment.has_refund_for_job("9dmJT_I3lHSeD2Vwz0Bu1A")


def test_job_id_extracted_from_note_and_order_derived(client):
    payment._payments["ORD_X"] = {
        "order_id": "ORD_X", "amount_eur": 5.0, "email": "buyer@x.it",
        "captured_at": time.time(), "used": True,
        "used_for_job": "AbCdEfGhIjKlMnOpQrStUv",
    }
    r = client.post("/admin/api/vouchers", json={
        "email": "buyer@x.it", "amount_eur": 5.0, "kind": "refund",
        "note": "rimborso job AbCdEfGhIjKlMnOpQrStUv audio troncato",
    }, headers=HDRS)
    assert r.status_code == 200
    body = r.get_json()
    assert body["origin_job_id"] == "AbCdEfGhIjKlMnOpQrStUv"
    assert body["origin_order_id"] == "ORD_X"
    assert payment.has_refund_for_job("AbCdEfGhIjKlMnOpQrStUv", "ORD_X")


def test_promo_voucher_never_gets_origin_fields(client):
    r = client.post("/admin/api/vouchers", json={
        "email": "buyer@x.it", "amount_eur": 5.0, "kind": "promo",
        "note": "campagna AbCdEfGhIjKlMnOpQrStUv", "job_id": "AbCdEfGhIjKlMnOpQrStUv",
    }, headers=HDRS)
    assert r.status_code == 200
    code = r.get_json()["code"]
    assert payment._vouchers[code].get("origin_job_id") is None
    assert not payment.has_refund_for_job("AbCdEfGhIjKlMnOpQrStUv")
