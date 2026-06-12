"""Guard anti-doppio-refund per _refund_payment_on_orphan.

Scenario reale (incidente classe B1): _orphan_fallback ricostruisce job_like
dal descrittore persistente e chiama _refund_payment_on_orphan. Il pop di
job["payment"] previene il doppio refund nello STESSO processo, ma non
sopravvive a un restart: se il recovery ri-esegue _orphan_fallback per lo
stesso job (es. crash tra refund e mark_failed), senza un guard persistente
il rimborso verrebbe duplicato. Specchio del guard gia' presente in
generation_engine._refund_gemini_payment (payment.has_refund_for_job).

Stato voucher/payment ISOLATO su tmp: senza isolamento il voucher di rimborso
creato qui finirebbe nel _vouchers.json reale e il guard, correttamente,
salterebbe il refund ai run successivi facendo fallire i test.
"""
import time

import pytest

import payment
import audiobook_app


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    yield


def test_orphan_paypal_double_call_emits_single_refund(isolated_store):
    """Due chiamate (seconda = recovery dopo restart) emettono UN solo voucher."""
    payment._payments["ORD_DBL"] = {
        "order_id": "ORD_DBL", "amount_eur": 2.0, "email": "buyer@x.it",
        "captured_at": time.time(), "used": True,
    }
    job1 = {"payment": {"token": "ORD_DBL", "total_eur": 2.0, "method": "paypal"}}
    code1 = audiobook_app._refund_payment_on_orphan("job-dbl", job1, "recover_failed")
    assert isinstance(code1, str) and code1
    refund_vouchers_after_first = [v for v in payment._vouchers.values()
                                   if v.get("kind") == "refund"]
    assert len(refund_vouchers_after_first) == 1

    # Seconda esecuzione: job_like ricostruito dal descrittore (pop non persistito).
    job2 = {"payment": {"token": "ORD_DBL", "total_eur": 2.0, "method": "paypal"}}
    code2 = audiobook_app._refund_payment_on_orphan("job-dbl", job2, "recover_failed")
    # Il guard deve impedire un secondo voucher di rimborso.
    refund_vouchers_after_second = [v for v in payment._vouchers.values()
                                    if v.get("kind") == "refund"]
    assert len(refund_vouchers_after_second) == 1, \
        "doppio refund: il guard has_refund_for_job non ha bloccato la seconda chiamata"
    assert code2 is None


def test_orphan_voucher_double_call_credits_once(isolated_store):
    """Voucher path: due chiamate riaccreditano l'importo una sola volta."""
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    payment._voucher_consume(code, 1.5, job_id="job-vdbl")
    rem_after_consume = payment._voucher_remaining(payment._vouchers[code])

    job1 = {"payment": {"token": code, "total_eur": 1.5, "method": "voucher"}}
    audiobook_app._refund_payment_on_orphan("job-vdbl", job1, "recover_failed")
    rem_after_first = payment._voucher_remaining(payment._vouchers[code])
    assert abs((rem_after_first - rem_after_consume) - 1.5) < 0.01

    job2 = {"payment": {"token": code, "total_eur": 1.5, "method": "voucher"}}
    audiobook_app._refund_payment_on_orphan("job-vdbl", job2, "recover_failed")
    rem_after_second = payment._voucher_remaining(payment._vouchers[code])
    # Nessun secondo riaccredito.
    assert abs(rem_after_second - rem_after_first) < 0.01, \
        "doppio refund voucher: il guard non ha bloccato la seconda chiamata"


def test_orphan_first_refund_still_works(isolated_store):
    """Regressione: la PRIMA chiamata (caso normale) rimborsa regolarmente."""
    payment._payments["ORD_OK"] = {
        "order_id": "ORD_OK", "amount_eur": 3.0, "email": "b@x.it",
        "captured_at": time.time(), "used": True,
    }
    job = {"payment": {"token": "ORD_OK", "total_eur": 3.0, "method": "paypal"}}
    code = audiobook_app._refund_payment_on_orphan("job-ok", job, "concurrent_limit")
    assert isinstance(code, str) and code
    assert "payment" not in job  # stato ripulito per il retry
