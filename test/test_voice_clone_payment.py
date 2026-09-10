"""Prezzo della voce campione e rollback del consumo (spec §7.1, §7.2)."""
import time

import pytest

import payment


@pytest.fixture(autouse=True)
def isolamento(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_opt_done", set())
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "VOUCHER_BONUS_PERCENT", 10)
    yield


def test_prezzo_default_e_virgola(monkeypatch):
    assert payment.voice_clone_price_eur() == pytest.approx(payment.EUR_CLONED_VOICE)
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 4.5)
    assert payment.voice_clone_price_eur() == 4.5
    monkeypatch.setattr(payment, "EUR_CLONED_VOICE", 0.0)
    assert payment.voice_clone_price_eur() <= 0


def test_release_voucher_ripristina_il_saldo():
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    metodo = payment.consume_payment_token(code, 5.0, "vc:abc", purpose="voice_clone")
    assert metodo == "voucher"
    prima = payment._voucher_remaining(payment._vouchers[code])
    assert payment.release_payment_token(code, 5.0, "vc:abc", "voucher", reason="rollback") is True
    dopo = payment._voucher_remaining(payment._vouchers[code])
    assert dopo == pytest.approx(prima + 5.0, abs=0.01)


def test_release_paypal_riapre_l_ordine():
    payment._payments["VCORDER1"] = {"order_id": "VCORDER1", "amount_eur": 5.0,
                                    "email": "x@y.it", "captured_at": time.time(),
                                    "used": False}
    try:
        assert payment.consume_payment_token("VCORDER1", 5.0, "vc:abc", purpose="voice_clone") == "paypal"
        assert payment._payments["VCORDER1"]["used"] is True
        assert payment.release_payment_token("VCORDER1", 5.0, "vc:abc", "paypal") is True
        rec = payment._payments["VCORDER1"]
        assert rec["used"] is False
        assert "used_for_job" not in rec and "used_at" not in rec
        # e si puo' consumare di nuovo
        assert payment.consume_payment_token("VCORDER1", 5.0, "vc:abc", purpose="voice_clone") == "paypal"
    finally:
        payment._payments.pop("VCORDER1", None)


def test_release_ignoto_non_solleva():
    assert payment.release_payment_token("NOPE", 5.0, "vc:x", "paypal") is False
    assert payment.release_payment_token("NOPE", 5.0, "vc:x", "voucher") is False
    assert payment.release_payment_token("NOPE", 5.0, "vc:x", "free") is False


def test_release_paypal_registra_reason_e_timestamp():
    payment._payments["VCORDER2"] = {"order_id": "VCORDER2", "amount_eur": 5.0,
                                    "email": "x@y.it", "captured_at": time.time(),
                                    "used": False}
    try:
        assert payment.consume_payment_token("VCORDER2", 5.0, "vc:abc", purpose="voice_clone") == "paypal"
        prima = time.time()
        assert payment.release_payment_token("VCORDER2", 5.0, "vc:abc", "paypal",
                                              reason="voice_clone_gone") is True
        rec = payment._payments["VCORDER2"]
        assert rec["released_reason"] == "voice_clone_gone"
        assert rec["released_at"] >= prima
    finally:
        payment._payments.pop("VCORDER2", None)


def test_capture_senza_job_id_eredita_purpose_vc(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_pending_orders", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    payment._register_pending_order("ORDVC1", 5.0, purpose="vc:vc_abc123")

    def fake_captured(oid):
        return {
            "payer": {"email_address": "buyer@x.it"},
            "purchase_units": [{
                "payments": {"captures": [{
                    "id": "CAPORDVC1", "status": "COMPLETED",
                    "amount": {"value": "5.00"},
                }]},
            }],
        }
    monkeypatch.setattr(payment, "_paypal_capture_order", fake_captured)
    res = payment.capture_and_store_order("ORDVC1", job_id="")
    assert res["already_captured"] is False
    assert payment._payments["ORDVC1"]["job_id"] == "vc:vc_abc123"


def test_capture_senza_job_id_purpose_non_vc_resta_vuoto(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_pending_orders", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    payment._register_pending_order("ORDOPT1", 5.0, purpose="optimize:job-9")

    def fake_captured(oid):
        return {
            "payer": {"email_address": "buyer@x.it"},
            "purchase_units": [{
                "payments": {"captures": [{
                    "id": "CAPORDOPT1", "status": "COMPLETED",
                    "amount": {"value": "5.00"},
                }]},
            }],
        }
    monkeypatch.setattr(payment, "_paypal_capture_order", fake_captured)
    res = payment.capture_and_store_order("ORDOPT1", job_id="")
    assert res["already_captured"] is False
    assert payment._payments["ORDOPT1"]["job_id"] == ""
