"""Test that /api/generate refunds payment when post-payment gate rejects the job.

Covers the orphan-consumption window between the payment preflight (Gemini path
in /api/generate) and the atomic concurrency claim. If the job slot is denied
(concurrent limit or status conflict) after the token was consumed, the route
must refund the user.
"""
import time
import pytest
import payment
import audiobook_app


def test_refund_payment_on_orphan_voucher_path(monkeypatch):
    """When job is rejected after voucher consume, balance is restored."""
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    payment._voucher_consume(code, 1.5, job_id="job-orphan-1")
    rem_before = payment._voucher_remaining(payment._vouchers[code])
    job = {"payment": {"token": code, "total_eur": 1.5, "method": "voucher"}}
    audiobook_app._refund_payment_on_orphan("job-orphan-1", job, "concurrent_limit")
    rem_after = payment._voucher_remaining(payment._vouchers[code])
    assert rem_after > rem_before
    assert abs((rem_after - rem_before) - 1.5) < 0.01
    # job["payment"] must be cleared so a retry sees no stale state
    assert "payment" not in job


def test_refund_payment_on_orphan_paypal_emits_voucher(monkeypatch):
    """For PayPal payments, an orphan rejection emits a refund voucher."""
    payment._payments["ORPH_ORD"] = {
        "order_id": "ORPH_ORD", "amount_eur": 2.0, "email": "buyer@x.it",
        "captured_at": time.time(), "used": True,
    }
    vouchers_before = len(payment._vouchers)
    job = {"payment": {"token": "ORPH_ORD", "total_eur": 2.0, "method": "paypal"}}
    audiobook_app._refund_payment_on_orphan("job-orphan-2", job, "concurrent_limit")
    assert len(payment._vouchers) == vouchers_before + 1
    assert "payment" not in job
    del payment._payments["ORPH_ORD"]


def test_refund_payment_on_orphan_no_payment_is_noop():
    job = {}  # never paid
    # Must not raise
    audiobook_app._refund_payment_on_orphan("job-x", job, "noop")
