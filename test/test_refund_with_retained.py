"""Test di _refund_gemini_payment con retained_eur > 0 (cancel volontario)."""
from unittest.mock import patch

import pytest

import generation_engine


@pytest.fixture
def voucher_job():
    return {
        "payment": {"token": "VCR-ABC", "total_eur": 2.00, "method": "voucher"},
    }


@pytest.fixture
def paypal_job():
    return {
        "payment": {"token": "PAY-XYZ", "total_eur": 2.00, "method": "paypal"},
    }


def test_refund_zero_retained_voucher_full_refund(voucher_job):
    with patch.object(generation_engine.payment, "_voucher_refund") as mock_refund, \
         patch.object(generation_engine.payment, "_vouchers",
                      {"VCR-ABC": {"email": "u@x.it"}}):
        out = generation_engine._refund_gemini_payment(
            "job1", voucher_job, "test", retained_eur=0.0)
        mock_refund.assert_called_once()
        assert mock_refund.call_args[0][1] == pytest.approx(2.00)
    assert out["amount_eur"] == pytest.approx(2.00)


def test_refund_partial_voucher(voucher_job):
    with patch.object(generation_engine.payment, "_voucher_refund") as mock_refund, \
         patch.object(generation_engine.payment, "_vouchers",
                      {"VCR-ABC": {"email": "u@x.it"}}):
        out = generation_engine._refund_gemini_payment(
            "job1", voucher_job, "cancelled", retained_eur=0.30)
        assert mock_refund.call_args[0][1] == pytest.approx(1.70)
    assert out["amount_eur"] == pytest.approx(1.70)


def test_refund_partial_paypal_no_bonus(paypal_job):
    with patch.object(generation_engine.payment, "_payments",
                      {"PAY-XYZ": {"email": "u@x.it"}}), \
         patch.object(generation_engine.payment, "_create_voucher",
                      return_value=("REF-001", 1.29)) as mock_create:
        out = generation_engine._refund_gemini_payment(
            "job1", paypal_job, "cancelled", retained_eur=0.71)
        kwargs = mock_create.call_args.kwargs
        amount_arg = kwargs.get("amount_eur")
        if amount_arg is None and len(mock_create.call_args.args) > 1:
            amount_arg = mock_create.call_args.args[1]
        assert amount_arg == pytest.approx(1.29)
        assert kwargs.get("apply_bonus") is False
    assert out["voucher_code"] == "REF-001"
    assert out["amount_eur"] == pytest.approx(1.29)


def test_refund_zero_when_retained_equals_paid(voucher_job):
    with patch.object(generation_engine.payment, "_voucher_refund") as mock_refund, \
         patch.object(generation_engine.payment, "_vouchers",
                      {"VCR-ABC": {"email": "u@x.it"}}):
        out = generation_engine._refund_gemini_payment(
            "job1", voucher_job, "cancelled", retained_eur=2.00)
        mock_refund.assert_not_called()
    assert out["amount_eur"] == pytest.approx(0.0)


def test_refund_zero_retained_default_paypal_keeps_bonus(paypal_job):
    """Comportamento legacy: senza retained_eur il refund e' 100% con apply_bonus default True."""
    with patch.object(generation_engine.payment, "_payments",
                      {"PAY-XYZ": {"email": "u@x.it"}}), \
         patch.object(generation_engine.payment, "_create_voucher",
                      return_value=("REF-002", 2.20)) as mock_create:
        generation_engine._refund_gemini_payment("job1", paypal_job, "error")
        assert mock_create.call_args.kwargs.get("apply_bonus", True) is True
