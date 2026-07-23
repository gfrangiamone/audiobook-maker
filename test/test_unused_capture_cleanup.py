"""Integrazione: la cleanup di un job pagato rimborsa i capture non consumati.

Verifica che `_cleanup_job` (e l'helper `_reconcile_unused_capture_for_job`)
emettano il rimborso del capture PayPal orfano PRIMA di distruggere il job —
chiusura del difetto project_incident_paid_translation_lost.
"""
import threading
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
    monkeypatch.setattr(payment, "AUTO_REFUND_UNUSED_CAPTURES", True)
    # ADMIN_EMAIL vuoto in audiobook_app → _notify esce subito (no SMTP nei test)
    monkeypatch.setattr(audiobook_app, "ADMIN_EMAIL", "")
    yield


def _unused_capture(order_id, job_id, amount=2.27, email="buyer@x.it"):
    payment._payments[order_id] = {
        "order_id": order_id, "amount_eur": amount, "email": email,
        "job_id": job_id, "captured_at": time.time(), "used": False,
        "used_at": None, "capture_id": "C" + order_id,
    }


def test_reconcile_refunds_unused_capture(isolated_store):
    _unused_capture("ORD_RC", "job-paid")
    vouchers_before = len(payment._vouchers)
    audiobook_app._reconcile_unused_capture_for_job("job-paid", "stale analyzed")
    assert len(payment._vouchers) == vouchers_before + 1
    assert payment._payments["ORD_RC"]["used"] is True
    assert payment._payments["ORD_RC"]["used_for"] == "auto_refund_unused"


def test_cleanup_job_triggers_refund(isolated_store):
    _unused_capture("ORD_CJ", "job-cleanup")
    # job non presente su disco né in jobs: _cleanup_job procede comunque e
    # deve rimborsare il capture orfano prima di terminare.
    audiobook_app._cleanup_job("job-cleanup", "stale analyzed")
    pay = payment._payments["ORD_CJ"]
    assert pay["used"] is True
    assert pay.get("refund_voucher")


def test_cleanup_job_no_capture_is_noop(isolated_store):
    # job senza alcun pagamento: nessun voucher, nessun errore
    audiobook_app._cleanup_job("job-free", "done retention")
    assert len(payment._vouchers) == 0


def test_admin_email_escapes_payer_email(isolated_store, monkeypatch):
    """L'email del pagante (payer PayPal, attacker-influenced) deve essere
    HTML-escaped nel corpo dell'alert admin (no XSS/HTML injection)."""
    captured = {}
    done = threading.Event()

    def _fake_send_email(to_addr, subject, body):
        captured["to"] = to_addr
        captured["subject"] = subject
        captured["body"] = body
        done.set()

    monkeypatch.setattr(audiobook_app, "ADMIN_EMAIL", "admin@x.it")
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_send_email", _fake_send_email)

    payment._payments["ORD_XSS"] = {
        "order_id": "ORD_XSS", "amount_eur": 2.27,
        "email": "<script>alert(1)</script>@x.it",
        "job_id": "job-xss", "captured_at": time.time(), "used": False,
        "used_at": None, "capture_id": "CX",
    }
    audiobook_app._reconcile_unused_capture_for_job("job-xss", "stale analyzed")
    assert done.wait(timeout=5), "admin email non inviata"
    body = captured["body"]
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_consumed_payment_not_refunded_on_cleanup(isolated_store):
    # capture già consumato (used=True): la cleanup NON deve rimborsare
    payment._payments["ORD_USED"] = {
        "order_id": "ORD_USED", "amount_eur": 2.27, "email": "buyer@x.it",
        "job_id": "job-done", "captured_at": time.time(), "used": True,
        "used_at": time.time(), "capture_id": "CU",
    }
    audiobook_app._cleanup_job("job-done", "done retention")
    assert len(payment._vouchers) == 0
    assert payment._payments["ORD_USED"]["used"] is True
