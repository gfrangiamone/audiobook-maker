"""Audit di sicurezza del 21/11/2026: i quattro rilievi gravi.

1. Un rifiuto di /api/generate rimborsava il pagamento che un'altra richiesta
   aveva consumato sullo stesso job (due POST in parallelo = libro gratis).
2. La capture PayPal non controllava la valuta: 1000 JPY valevano 1000 EUR.
3-4. `esc()` della console admin non codificava le virgolette: un valore
   dell'utente in `title="${esc(v)}"` diventava codice eseguito dall'admin.
"""
import re
import time
from pathlib import Path

import pytest

import audiobook_app
import payment

ROOT = Path(audiobook_app.__file__).resolve().parent


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    yield


def _voucher_spent(job_id, amount=1.5):
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    payment._voucher_consume(code, amount, job_id=job_id)
    return code, {"token": code, "total_eur": amount, "method": "voucher"}


def test_rejected_request_without_payment_leaves_the_other_payment(isolated_store):
    code, pocket = _voucher_spent("job-race")
    before = payment._voucher_remaining(payment._vouchers[code])
    job = {"payment": pocket}
    assert audiobook_app._refund_payment_on_orphan(
        "job-race", job, "status_conflict", own=None) is None
    assert payment._voucher_remaining(payment._vouchers[code]) == before
    assert job["payment"] is pocket


def test_rejected_request_refunds_only_its_own_payment(isolated_store):
    code_a, pocket_a = _voucher_spent("job-race2")
    code_b, own_b = _voucher_spent("job-race2")
    before_a = payment._voucher_remaining(payment._vouchers[code_a])
    before_b = payment._voucher_remaining(payment._vouchers[code_b])
    job = {"payment": pocket_a}
    audiobook_app._refund_payment_on_orphan(
        "job-race2", job, "status_conflict", own=own_b)
    assert payment._voucher_remaining(payment._vouchers[code_a]) == before_a
    assert payment._voucher_remaining(payment._vouchers[code_b]) > before_b
    assert job["payment"] is pocket_a


def test_generate_rejects_before_the_claim_pass_the_request_payment():
    src = (ROOT / "audiobook_app.py").read_text(encoding="utf-8")
    for reason in ("status_conflict", "concurrent_limit", "server_busy"):
        assert f'job, "{reason}", own=_own_payment)' in src, reason


def test_reset_to_chapters_drops_the_delivered_payment(monkeypatch):
    job_id = "a" * 22
    info = type("I", (), {"chapters": [object()]})()
    job = {"status": "done", "info": info, "client_id": "",
           "payment": {"token": "T", "total_eur": 3.0, "method": "voucher"},
           "payment_token": "T", "payment_amount_eur": 3.0}
    monkeypatch.setitem(audiobook_app.jobs, job_id, job)
    monkeypatch.setattr(audiobook_app, "_check_job_owner",
                        lambda jid: (job, None, 200))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    c = audiobook_app.app.test_client()
    r = c.post(f"/api/reset_to_chapters/{job_id}",
               headers={"Origin": "http://localhost"})
    assert r.status_code == 200, r.get_data(as_text=True)
    assert job["status"] == "analyzed"
    for key in ("payment", "payment_token", "payment_amount_eur"):
        assert key not in job


def _captured(currency):
    amount = {"value": "1000.00"}
    if currency:
        amount["currency_code"] = currency
    return {"payer": {"email_address": "buyer@x.it"},
            "purchase_units": [{"payments": {"captures": [{
                "id": "CAPX", "status": "COMPLETED", "amount": amount}]}}]}


@pytest.mark.parametrize("currency", ["JPY", "USD", ""])
def test_capture_in_another_currency_is_not_credited(isolated_store, monkeypatch, currency):
    monkeypatch.setattr(payment, "_paypal_capture_order", lambda oid: _captured(currency))
    with pytest.raises(payment.CaptureAmountMismatchError):
        payment.capture_and_store_order("ORDJPY1", job_id="job-cur")
    assert "ORDJPY1" not in payment._payments


def test_capture_in_eur_is_credited(isolated_store, monkeypatch):
    monkeypatch.setattr(payment, "_paypal_capture_order", lambda oid: _captured("EUR"))
    res = payment.capture_and_store_order("ORDEUR1", job_id="job-cur2")
    assert res["amount_eur"] == 1000.0 and "ORDEUR1" in payment._payments


def test_admin_esc_encodes_quotes():
    page = (ROOT / "templates" / "pages" / "admin_audit_premium.html").read_text(encoding="utf-8")
    body = re.search(r"function esc\(s\)\{(.*?)\n  \}", page, flags=re.S).group(1)
    assert "&quot;" in body and "&#39;" in body
