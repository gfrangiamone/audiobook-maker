"""Test detection + refund dei capture PayPal incassati ma mai consumati.

Difetto coperto: un ordine PayPal catturato (used=False) la cui chiamata di
consumo (/api/translate ecc.) non parte mai resta orfano in _payments.json →
cliente addebitato, nessun servizio, nessun rimborso. Vedi memoria
project_incident_paid_translation_lost.
"""
import time
import pytest
import payment


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    """Stato voucher/payment isolato su tmp (come test_orphan_refund)."""
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "AUTO_REFUND_UNUSED_CAPTURES", True)
    yield


def _capture(order_id, *, amount=2.27, email="buyer@x.it", job_id="job-1",
             used=False, captured_at=None, age_sec=None):
    if captured_at is None:
        captured_at = time.time() - (age_sec if age_sec is not None else 0)
    payment._payments[order_id] = {
        "order_id": order_id, "amount_eur": amount, "email": email,
        "job_id": job_id, "captured_at": captured_at, "used": used,
        "used_at": None, "capture_id": "CAP" + order_id,
    }


def test_iter_unused_captures_filters_used_and_age(isolated_store):
    _capture("OLD_UNUSED", age_sec=3600)
    _capture("RECENT_UNUSED", age_sec=10)
    _capture("CONSUMED", used=True, age_sec=3600)
    # min_age 1800 → solo OLD_UNUSED
    res = payment.iter_unused_captures(min_age_sec=1800)
    ids = {r["order_id"] for r in res}
    assert ids == {"OLD_UNUSED"}
    # senza soglia → entrambi gli unused, mai il consumato
    res_all = payment.iter_unused_captures(min_age_sec=0)
    assert {r["order_id"] for r in res_all} == {"OLD_UNUSED", "RECENT_UNUSED"}


def test_refund_unused_capture_emits_voucher_and_marks_used(isolated_store):
    _capture("ORD_A", amount=2.27, email="buyer@x.it", job_id="jobA")
    vouchers_before = len(payment._vouchers)
    res = payment.refund_unused_capture("ORD_A", reason="stale analyzed")
    assert res and res["voucher_code"]
    assert res["manual"] is False
    assert len(payment._vouchers) == vouchers_before + 1
    pay = payment._payments["ORD_A"]
    assert pay["used"] is True
    assert pay["used_for"] == "auto_refund_unused"
    assert pay["refund_voucher"] == res["voucher_code"]
    # il voucher è all'email del pagante e importo base = importo capture
    v = payment._vouchers[res["voucher_code"]]
    assert v["email"] == "buyer@x.it"
    assert abs(v["base_amount_eur"] - 2.27) < 0.001


def test_refund_unused_capture_is_idempotent(isolated_store):
    _capture("ORD_B", job_id="jobB")
    first = payment.refund_unused_capture("ORD_B", reason="x")
    assert first and first["voucher_code"]
    vouchers_after_first = len(payment._vouchers)
    second = payment.refund_unused_capture("ORD_B", reason="x")
    assert second is None  # già used → no-op
    assert len(payment._vouchers) == vouchers_after_first  # nessun doppio voucher


def test_refund_unused_capture_no_email_flags_manual(isolated_store):
    _capture("ORD_C", email="", job_id="jobC")
    res = payment.refund_unused_capture("ORD_C", reason="no-email")
    assert res and res["voucher_code"] is None
    assert res["manual"] is True
    pay = payment._payments["ORD_C"]
    # NON consumato: deve restare visibile per rimborso manuale
    assert not pay.get("used")
    assert pay.get("needs_manual_refund") is True


def test_refund_unused_capture_autorefund_off_flags_manual(isolated_store, monkeypatch):
    monkeypatch.setattr(payment, "AUTO_REFUND_UNUSED_CAPTURES", False)
    _capture("ORD_D", email="buyer@x.it", job_id="jobD")
    res = payment.refund_unused_capture("ORD_D", reason="off")
    assert res["voucher_code"] is None and res["manual"] is True
    assert not payment._payments["ORD_D"].get("used")
    # force=True forza comunque il voucher anche con auto-refund off
    res2 = payment.refund_unused_capture("ORD_D", reason="forced", force=True)
    assert res2 and res2["voucher_code"]
    assert payment._payments["ORD_D"]["used"] is True


def test_refund_unused_captures_for_job_handles_multiple(isolated_store):
    _capture("ORD_E1", job_id="jobE")
    _capture("ORD_E2", job_id="jobE")
    _capture("ORD_OTHER", job_id="jobZ")
    _capture("ORD_E_CONSUMED", job_id="jobE", used=True)
    results = payment.refund_unused_captures_for_job("jobE", reason="cleanup")
    assert {r["order_id"] for r in results} == {"ORD_E1", "ORD_E2"}
    # l'ordine di un altro job e quello già consumato non vengono toccati
    assert not payment._payments["ORD_OTHER"].get("used")
    assert payment._payments["ORD_E_CONSUMED"]["used"] is True


def test_refund_unused_captures_for_job_empty_is_noop(isolated_store):
    assert payment.refund_unused_captures_for_job("", reason="x") == []
    assert payment.refund_unused_captures_for_job("nope", reason="x") == []
