"""M4: lo stato di payment si legge con payment_info / voucher_info /
iter_vouchers / order_id_for_job / email_for_token e si cambia con
revoke_voucher; fuori da payment.py restano solo i claim sotto lock di
audiobook_app (M1). Il ratchet `payment_private_state` tiene il conto."""
import time

import pytest

import audiobook_app
import payment


@pytest.fixture
def store(monkeypatch, tmp_path):
    saved = []
    monkeypatch.setattr(payment, "_payments", {
        "ORD_A": {"order_id": "ORD_A", "amount_eur": 2.5, "email": "Buyer@X.it",
                  "job_id": "job-a", "used": False},
        "ORD_B": {"order_id": "ORD_B", "amount_eur": 1.0, "email": "b@x.it",
                  "used": True, "used_job_id": "job-b"},
        "ORD_C": {"order_id": "ORD_C", "amount_eur": 1.0, "email": "c@x.it",
                  "used": True, "used_for_job": "job-c"},
    })
    monkeypatch.setattr(payment, "_vouchers", {
        "AAAA-BBBB-CCCC": {"email": "v@x.it", "amount_eur": 3.0, "remaining_eur": 3.0,
                           "created_at": time.time(), "expires_at": time.time() + 86400,
                           "used": False},
    })
    monkeypatch.setattr(payment, "_save_vouchers", lambda: saved.append("v"))
    return saved


def test_payment_info_e_una_copia(store):
    pay = payment.payment_info("ORD_A")
    assert pay["email"] == "Buyer@X.it"
    pay["used"] = True
    assert payment._payments["ORD_A"]["used"] is False
    assert payment.payment_info("ORD_NO") is None
    assert payment.payment_info("") is None and payment.payment_info(None) is None


def test_voucher_info_e_una_copia(store):
    v = payment.voucher_info("AAAA-BBBB-CCCC")
    assert v["amount_eur"] == 3.0
    v["remaining_eur"] = 0.0
    assert payment._vouchers["AAAA-BBBB-CCCC"]["remaining_eur"] == 3.0
    assert payment.voucher_info("ZZZZ") is None and payment.voucher_info(None) is None


def test_iter_vouchers_istantanea(store):
    items = payment.iter_vouchers()
    assert [c for c, _v in items] == ["AAAA-BBBB-CCCC"]
    items[0][1]["used"] = True
    assert payment._vouchers["AAAA-BBBB-CCCC"]["used"] is False


def test_order_id_for_job_tre_chiavi(store):
    assert payment.order_id_for_job("job-a") == "ORD_A"      # job_id della capture
    assert payment.order_id_for_job("job-b") == "ORD_B"      # used_job_id (claim app)
    assert payment.order_id_for_job("job-c") == "ORD_C"      # used_for_job (consume_payment_token)
    assert payment.order_id_for_job("job-x") == ""
    assert payment.order_id_for_job("") == ""


def test_email_for_token_normalizza(store):
    assert payment.email_for_token("ORD_A") == "buyer@x.it"
    assert payment.email_for_token("AAAA-BBBB-CCCC") == "v@x.it"
    assert payment.email_for_token("nope") == "" and payment.email_for_token(None) == ""


def test_revoke_voucher(store):
    assert payment.revoke_voucher("ZZZZ", "x") is False
    assert store == []
    assert payment.revoke_voucher("AAAA-BBBB-CCCC", "frode") is True
    v = payment._vouchers["AAAA-BBBB-CCCC"]
    assert v["used"] is True and v["revoked"] is True and v["remaining_eur"] == 0.0
    assert v["revoke_reason"] == "frode" and v["used_at"] > 0
    assert payment._voucher_remaining(v) == 0.0
    assert store == ["v"]


def test_route_revoke_passa_da_revoke_voucher(store, monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-m4")
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: True)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    c = audiobook_app.app.test_client()
    h = {"X-Admin-Token": "tok-m4"}
    r = c.post("/admin/api/vouchers/ZZZZ/revoke", json={"reason": "x"}, headers=h)
    assert r.status_code == 404
    r = c.post("/admin/api/vouchers/aaaa-bbbb-cccc/revoke", json={"reason": "frode"}, headers=h)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert payment._vouchers["AAAA-BBBB-CCCC"]["revoked"] is True
    assert store == ["v"]


def test_fuori_da_payment_restano_solo_i_claim_sotto_lock():
    """Gli accessi residui sono i check-and-set `with payment._payments_lock`
    dei claim in audiobook_app (M1): nessuna lettura diretta altrove."""
    import json
    from pathlib import Path
    base = json.loads((Path(__file__).with_name("boundaries_baseline.json")).read_text(encoding="utf-8"))
    left = base["payment_private_state"]
    assert set(left) == {"audiobook_app.py"}, left
    assert left["audiobook_app.py"] <= 10
