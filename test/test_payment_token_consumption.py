"""Test consume_payment_token and refund flow for Gemini payments."""
import time
import pytest
import payment


def test_consume_voucher_token_marks_paid_done(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    code, _v = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    method = payment.consume_payment_token(code, 1.0, "job-1", purpose="gemini")
    assert method == "voucher"
    # Remaining decreased
    assert payment._voucher_remaining(payment._vouchers[code]) == pytest.approx(4.5, abs=0.01)
    # Job marked as paid-done
    assert payment._is_paid_job_done("job-1") is True


def test_consume_paypal_token_marks_used(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    payment._payments["ORDER123"] = {
        "order_id": "ORDER123", "amount_eur": 1.50, "email": "x@y.it",
        "captured_at": time.time(), "used": False,
    }
    method = payment.consume_payment_token("ORDER123", 1.50, "job-2", purpose="gemini")
    assert method == "paypal"
    assert payment._payments["ORDER123"]["used"] is True
    assert payment._is_paid_job_done("job-2") is True
    # Cleanup
    del payment._payments["ORDER123"]


def test_consume_paypal_double_spend_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    payment._payments["ORDER999"] = {
        "order_id": "ORDER999", "amount_eur": 1.50, "email": "x@y.it",
        "captured_at": time.time(), "used": False,
    }
    payment.consume_payment_token("ORDER999", 1.50, "job-a")
    # Second attempt must fail
    with pytest.raises(ValueError):
        payment.consume_payment_token("ORDER999", 1.50, "job-b")
    del payment._payments["ORDER999"]


def test_consume_paypal_amount_mismatch_rejected(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    payment._payments["ORDER555"] = {
        "order_id": "ORDER555", "amount_eur": 1.00, "email": "x@y.it",
        "captured_at": time.time(), "used": False,
    }
    with pytest.raises(ValueError, match="amount mismatch"):
        payment.consume_payment_token("ORDER555", 2.50, "job-x")
    del payment._payments["ORDER555"]


def test_consume_invalid_token_raises(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    with pytest.raises(ValueError, match="invalid payment_token"):
        payment.consume_payment_token("NONEXISTENT", 1.0, "job-z")


def test_consume_empty_token_raises():
    with pytest.raises(ValueError, match="missing payment_token"):
        payment.consume_payment_token("", 1.0, "job-z")


def test_paypal_amount_matches_tolerance():
    payment._payments["TOL1"] = {"order_id": "TOL1", "amount_eur": 1.00, "used": False}
    # Within tolerance (0.05 default)
    assert payment._paypal_amount_matches("TOL1", 1.04) is True
    assert payment._paypal_amount_matches("TOL1", 1.05) is True
    # Beyond tolerance
    assert payment._paypal_amount_matches("TOL1", 1.10) is False
    del payment._payments["TOL1"]


def test_refund_gemini_payment_voucher_path(monkeypatch):
    """generation_engine._refund_gemini_payment refunds a voucher token."""
    import generation_engine
    code, _v = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    payment._voucher_consume(code, 1.50, job_id="job-r")
    rem_before = payment._voucher_remaining(payment._vouchers[code])
    job = {"payment": {"token": code, "total_eur": 1.50, "method": "voucher"}}
    generation_engine._refund_gemini_payment("job-r", job, "test-refund")
    rem_after = payment._voucher_remaining(payment._vouchers[code])
    assert rem_after > rem_before
    assert abs((rem_after - rem_before) - 1.50) < 0.01


def test_refund_gemini_payment_paypal_emits_refund_voucher(monkeypatch):
    """For PayPal payments, refund emits a refund voucher to the buyer's email."""
    import generation_engine
    payment._payments["REFUND_ORD"] = {
        "order_id": "REFUND_ORD", "amount_eur": 2.00, "email": "buyer@x.it",
        "captured_at": time.time(), "used": True,
    }
    vouchers_before = len(payment._vouchers)
    job = {"payment": {"token": "REFUND_ORD", "total_eur": 2.00, "method": "paypal"}}
    generation_engine._refund_gemini_payment("job-rp", job, "test-refund")
    # A refund voucher should have been created
    assert len(payment._vouchers) == vouchers_before + 1
    del payment._payments["REFUND_ORD"]


def test_refund_gemini_payment_no_payment_is_noop():
    import generation_engine
    job = {}  # no payment dict
    # Must not raise
    generation_engine._refund_gemini_payment("job-x", job, "noop")
