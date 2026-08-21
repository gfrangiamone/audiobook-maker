"""Capture PayPal PENDING non finanziate (eCheck) — servizio mai erogato.

Incidente 2026-08: un cliente ricorrente pagava tramite eCheck (addebito su
conto bancario). PayPal restituiva la capture con status ``PENDING`` e reason
``ECHECK``; `capture_and_store_order` accettava `PENDING` come pagamento valido,
ABM erogava l'audiolibro all'istante e giorni dopo la banca del pagante
respingeva l'addebito (transazione "Annullato"): servizio consegnato, denaro mai
incassato.

Copre:
  - la capture con reason in blocklist solleva `UnfundedCaptureError` (nessun
    payment token emesso);
  - il record resta tracciato (`pending_unfunded=True`) ma non e' spendibile
    come payment token, ne' rimborsabile/incassabile dalle reti di sicurezza;
  - i PENDING NON in blocklist (es. revisione antifrode) restano accettati;
  - nessuna regressione sul flusso `COMPLETED`.
"""
import time

import pytest

import payment


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE",
                        tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "AUTO_REFUND_UNUSED_CAPTURES", True)
    yield


def _captured(order_id, amount, status="COMPLETED", reason=None):
    cap = {
        "id": "CAP" + order_id,
        "status": status,
        "amount": {"value": f"{amount:.2f}"},
    }
    if reason is not None:
        cap["status_details"] = {"reason": reason}
    return {
        "payer": {"email_address": "buyer@x.it"},
        "purchase_units": [{"payments": {"captures": [cap]}}],
    }


def _stub_capture(monkeypatch, order_id, amount, status, reason=None):
    """Sostituisce la chiamata HTTP a PayPal. Ritorna il contatore chiamate."""
    calls = {"n": 0}

    def fake(oid):
        calls["n"] += 1
        return _captured(oid, amount, status=status, reason=reason)

    monkeypatch.setattr(payment, "_paypal_capture_order", fake)
    return calls


# --------------------------- rifiuto della capture --------------------------

def test_echeck_capture_is_refused(isolated_store, monkeypatch):
    """PENDING/ECHECK -> UnfundedCaptureError: nessun token, nessuna erogazione."""
    _stub_capture(monkeypatch, "ORD_E", 3.67, "PENDING", "ECHECK")

    with pytest.raises(payment.UnfundedCaptureError) as ei:
        payment.capture_and_store_order("ORD_E", job_id="jobE")

    assert ei.value.reason == "ECHECK"
    assert ei.value.order_id == "ORD_E"
    assert ei.value.amount_eur == pytest.approx(3.67)


def test_echeck_record_is_tracked_but_not_spendable(isolated_store, monkeypatch):
    """Il record resta per la riconciliazione, ma non vale come pagamento."""
    _stub_capture(monkeypatch, "ORD_E", 3.67, "PENDING", "ECHECK")
    with pytest.raises(payment.UnfundedCaptureError):
        payment.capture_and_store_order("ORD_E", job_id="jobE")

    rec = payment._payments["ORD_E"]
    assert rec["pending_unfunded"] is True
    assert rec["pending_reason"] == "ECHECK"
    assert rec["used"] is False

    # Il client non puo' usare l'order_id come payment_token per avere il servizio
    with pytest.raises(ValueError):
        payment.consume_payment_token("ORD_E", 3.67, "jobE")
    assert payment._payments["ORD_E"]["used"] is False


def test_retry_same_order_refused_without_calling_paypal(isolated_store, monkeypatch):
    """Ri-tentare la capture non ri-chiama PayPal e resta rifiutata."""
    calls = _stub_capture(monkeypatch, "ORD_E", 3.67, "PENDING", "ECHECK")
    with pytest.raises(payment.UnfundedCaptureError):
        payment.capture_and_store_order("ORD_E", job_id="jobE")
    assert calls["n"] == 1

    with pytest.raises(payment.UnfundedCaptureError):
        payment.capture_and_store_order("ORD_E", job_id="jobE")
    assert calls["n"] == 1  # nessuna seconda chiamata all'API


def test_new_order_same_job_is_not_blocked_by_unfunded_record(isolated_store,
                                                              monkeypatch):
    """Il guard anti-doppio-addebito non deve riusare un capture non finanziato:
    l'utente che ripaga con carta dopo l'eCheck deve poter pagare davvero."""
    _stub_capture(monkeypatch, "ORD_E", 3.67, "PENDING", "ECHECK")
    with pytest.raises(payment.UnfundedCaptureError):
        payment.capture_and_store_order("ORD_E", job_id="jobE")

    calls = _stub_capture(monkeypatch, "ORD_C", 3.67, "COMPLETED")
    res = payment.capture_and_store_order("ORD_C", job_id="jobE")
    assert calls["n"] == 1
    assert res["already_captured"] is False
    assert res["order_id"] == "ORD_C"
    assert payment.consume_payment_token("ORD_C", 3.67, "jobE") == "paypal"


# ------------------------ reti di sicurezza (rimborsi) ----------------------

def test_unfunded_capture_is_not_refundable_nor_settleable(isolated_store,
                                                           monkeypatch):
    """Denaro mai ricevuto: niente voucher di rimborso, niente incasso "dovuto"."""
    _stub_capture(monkeypatch, "ORD_E", 5.01, "PENDING", "ECHECK")
    with pytest.raises(payment.UnfundedCaptureError):
        payment.capture_and_store_order("ORD_E", job_id="jobE")
    # Invecchia il record: senza il guard finirebbe fra i capture orfani
    payment._payments["ORD_E"]["captured_at"] = time.time() - 86400

    assert payment.iter_unused_captures() == []
    assert payment.refund_unused_capture("ORD_E", reason="test") is None
    assert payment.refund_unused_captures_for_job("jobE", reason="test") == []
    assert payment.settle_capture_consumed("ORD_E", job_id="jobE") is None
    assert payment.settle_delivered_captures_for_job("jobE") == []
    assert payment._vouchers == {}
    assert payment._payments["ORD_E"]["used"] is False


# ---------------------- PENDING accettati / regressione ---------------------

def test_pending_review_is_still_accepted(isolated_store, monkeypatch):
    """PENDING non in blocklist (revisione antifrode): accettato e spendibile."""
    _stub_capture(monkeypatch, "ORD_R", 4.20, "PENDING", "PENDING_REVIEW")
    res = payment.capture_and_store_order("ORD_R", job_id="jobR")

    assert res["already_captured"] is False
    rec = payment._payments["ORD_R"]
    assert rec["pending_reason"] == "PENDING_REVIEW"
    assert "pending_unfunded" not in rec
    assert payment.consume_payment_token("ORD_R", 4.20, "jobR") == "paypal"


def test_completed_capture_unchanged(isolated_store, monkeypatch):
    """Nessuna regressione sul flusso normale."""
    _stub_capture(monkeypatch, "ORD_C", 3.72, "COMPLETED")
    res = payment.capture_and_store_order("ORD_C", job_id="jobC")

    assert res["amount_eur"] == pytest.approx(3.72)
    assert res["email"] == "buyer@x.it"
    rec = payment._payments["ORD_C"]
    assert "pending_unfunded" not in rec
    assert "pending_reason" not in rec
    assert payment.consume_payment_token("ORD_C", 3.72, "jobC") == "paypal"


def test_blocklist_reasons_cover_unfunded_families(isolated_store, monkeypatch):
    """Tutti i reason "fondi non trasferiti" bloccano l'erogazione."""
    for i, reason in enumerate(sorted(payment.UNFUNDED_PENDING_REASONS)):
        oid = f"ORD_{i}"
        _stub_capture(monkeypatch, oid, 3.05, "PENDING", reason)
        with pytest.raises(payment.UnfundedCaptureError):
            payment.capture_and_store_order(oid, job_id=f"job{i}")
        assert payment._payments[oid]["pending_unfunded"] is True
