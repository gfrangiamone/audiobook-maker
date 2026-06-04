"""Guard persistente anti-doppio-refund (payment.has_refund_for_job).

Il flag in-memory job["refund_done"] si perde al restart: un job recovered
gia' rimborsato non deve generare un secondo refund su cancel/error.
"""
from unittest.mock import patch

import pytest

import generation_engine
import payment


def _voucher_with_uses(uses):
    return {"VCR-ABC": {"email": "u@x.it", "uses": uses}}


# ---------------------------------------------------------------------------
# payment.has_refund_for_job
# ---------------------------------------------------------------------------

def test_no_trace_returns_false():
    with patch.object(payment, "_vouchers", _voucher_with_uses([])):
        assert payment.has_refund_for_job("job1") is False


def test_voucher_refund_trace_returns_true():
    uses = [
        {"job_id": "job1", "amount_eur": 2.00, "at": 1.0},
        {"job_id": "job1", "amount_eur": -2.00, "at": 2.0},
    ]
    with patch.object(payment, "_vouchers", _voucher_with_uses(uses)):
        assert payment.has_refund_for_job("job1") is True
        assert payment.has_refund_for_job("job1", "VCR-ABC") is True


def test_repay_after_refund_is_refundable_again():
    """Stesso job ri-pagato dopo un refund: addebiti(2) > riaccrediti(1)."""
    uses = [
        {"job_id": "job1", "amount_eur": 2.00, "at": 1.0},
        {"job_id": "job1", "amount_eur": -2.00, "at": 2.0},
        {"job_id": "job1", "amount_eur": 2.00, "at": 3.0},
    ]
    with patch.object(payment, "_vouchers", _voucher_with_uses(uses)):
        assert payment.has_refund_for_job("job1", "VCR-ABC") is False


def test_paypal_refund_voucher_trace_returns_true():
    vouchers = {"REF-001": {"kind": "refund", "origin_job_id": "job1",
                            "origin_order_id": "PAY-XYZ", "uses": []}}
    with patch.object(payment, "_vouchers", vouchers):
        assert payment.has_refund_for_job("job1") is True
        assert payment.has_refund_for_job("job1", "PAY-XYZ") is True
        # Ordine diverso (re-pagamento PayPal dello stesso job): non blocca.
        assert payment.has_refund_for_job("job1", "PAY-NEW") is False


def test_other_job_trace_does_not_block():
    uses = [{"job_id": "jobX", "amount_eur": -2.00, "at": 1.0}]
    with patch.object(payment, "_vouchers", _voucher_with_uses(uses)):
        assert payment.has_refund_for_job("job1") is False


def test_empty_job_id_returns_false():
    assert payment.has_refund_for_job("") is False


# ---------------------------------------------------------------------------
# Guard nei refund handler di generation_engine
# ---------------------------------------------------------------------------

def test_refund_job_payment_skips_when_trace_exists():
    uses = [
        {"job_id": "job1", "amount_eur": 2.00, "at": 1.0},
        {"job_id": "job1", "amount_eur": -2.00, "at": 2.0},
    ]
    job = {"payment_amount_eur": 2.00, "payment_type": "voucher",
           "payment_token": "VCR-ABC"}
    with patch.object(payment, "_vouchers", _voucher_with_uses(uses)), \
         patch.object(payment, "_voucher_refund") as mock_refund:
        generation_engine._refund_job_payment("job1", job, "cancel")
        mock_refund.assert_not_called()
    assert job.get("refund_done") is True


def test_refund_gemini_payment_skips_when_trace_exists():
    uses = [
        {"job_id": "job1", "amount_eur": 2.00, "at": 1.0},
        {"job_id": "job1", "amount_eur": -2.00, "at": 2.0},
    ]
    job = {"payment": {"token": "VCR-ABC", "total_eur": 2.00, "method": "voucher"}}
    with patch.object(payment, "_vouchers", _voucher_with_uses(uses)), \
         patch.object(payment, "_voucher_refund") as mock_refund:
        out = generation_engine._refund_gemini_payment("job1", job, "test")
        mock_refund.assert_not_called()
    assert out is None


def test_refund_gemini_payment_proceeds_without_trace():
    job = {"payment": {"token": "VCR-ABC", "total_eur": 2.00, "method": "voucher"}}
    with patch.object(payment, "_vouchers",
                      {"VCR-ABC": {"email": "u@x.it", "uses": []}}), \
         patch.object(payment, "_voucher_refund") as mock_refund:
        out = generation_engine._refund_gemini_payment("job1", job, "test")
        mock_refund.assert_called_once()
    assert out["amount_eur"] == pytest.approx(2.00)
