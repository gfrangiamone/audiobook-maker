"""Anti doppio-addebito PayPal (incidente K1Rpn-x0fmaylsjKYGdftg, 2026-07).

Un utente ha ri-cliccato il bottone PayPal prima di confermare: due ordini
distinti, entrambi catturati per lo stesso job, ma solo il secondo consumato da
/api/generate. Il primo capture è rimasto orfano (incassato, servizio erogato
una sola volta) e la rete di sicurezza `settle_delivered_captures_for_job` lo ha
INCASSATO (assumeva max un capture per job) invece di rimborsarlo.

Copre:
  - Layer A: `capture_and_store_order` con guard a livello job — non cattura un
    secondo ordine se il job ne ha gia' uno incassato.
  - Layer B: `settle_delivered_captures_for_job` rimborsa i capture in eccesso
    (duplicati reali) quando un capture del job risulta gia' consumato.
"""
import time
import pytest
import payment


@pytest.fixture
def isolated_store(monkeypatch, tmp_path):
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "AUTO_REFUND_UNUSED_CAPTURES", True)
    yield


def _capture(order_id, *, amount=26.17, email="buyer@x.it", job_id="job-1",
             used=False, captured_at=None):
    if captured_at is None:
        captured_at = time.time()
    payment._payments[order_id] = {
        "order_id": order_id, "amount_eur": amount,
        "amount_requested_eur": amount, "email": email,
        "job_id": job_id, "captured_at": captured_at, "used": used,
        "used_at": None, "capture_id": "CAP" + order_id,
    }


def _fake_captured(order_id, amount):
    return {
        "payer": {"email_address": "buyer@x.it"},
        "purchase_units": [{
            "payments": {"captures": [{
                "id": "CAP" + order_id, "status": "COMPLETED",
                "amount": {"value": f"{amount:.2f}"},
            }]},
        }],
    }


# ------------------------------- Layer A -----------------------------------

def test_second_capture_same_job_reuses_unused(isolated_store, monkeypatch):
    """Job con capture non consumato: un SECONDO ordine non viene catturato,
    viene riusato il primo (nessun secondo addebito)."""
    _capture("ORD1", job_id="jobK", used=False)
    called = {"n": 0}
    monkeypatch.setattr(payment, "_paypal_capture_order",
                        lambda oid: called.__setitem__("n", called["n"] + 1))

    res = payment.capture_and_store_order("ORD2", job_id="jobK")
    # L'API di capture NON deve essere chiamata per ORD2
    assert called["n"] == 0
    assert res["already_captured"] is True
    assert res["order_id"] == "ORD1"                 # token effettivo = capture esistente
    assert res.get("duplicate_skipped_order_id") == "ORD2"
    # ORD2 non è entrato nello store
    assert "ORD2" not in payment._payments


def test_second_capture_same_job_consumed_raises(isolated_store, monkeypatch):
    """Job con capture GIA' consumato: un secondo ordine è un doppio addebito →
    DuplicateJobCaptureError, senza chiamare l'API di capture."""
    _capture("ORD1", job_id="jobK", used=True)
    called = {"n": 0}
    monkeypatch.setattr(payment, "_paypal_capture_order",
                        lambda oid: called.__setitem__("n", called["n"] + 1))

    with pytest.raises(payment.DuplicateJobCaptureError):
        payment.capture_and_store_order("ORD2", job_id="jobK")
    assert called["n"] == 0
    assert "ORD2" not in payment._payments


def test_capture_other_job_proceeds(isolated_store, monkeypatch):
    """Un capture per un job DIVERSO non è bloccato dal guard."""
    _capture("ORD1", job_id="jobK", used=False)
    monkeypatch.setattr(payment, "_paypal_capture_order",
                        lambda oid: _fake_captured(oid, 26.17))
    monkeypatch.setattr(payment, "_get_pending_amount", lambda oid: 26.17)
    monkeypatch.setattr(payment, "_consume_pending_order", lambda oid: None)

    res = payment.capture_and_store_order("ORD_OTHER", job_id="jobZ")
    assert res["already_captured"] is False
    assert res["order_id"] == "ORD_OTHER"
    assert payment._payments["ORD_OTHER"]["job_id"] == "jobZ"


def test_same_order_idempotent_returns_order_id(isolated_store, monkeypatch):
    """Re-capture dello STESSO order_id resta idempotente e ora espone order_id."""
    _capture("ORD1", job_id="jobK", used=False)
    called = {"n": 0}
    monkeypatch.setattr(payment, "_paypal_capture_order",
                        lambda oid: called.__setitem__("n", called["n"] + 1))
    res = payment.capture_and_store_order("ORD1", job_id="jobK")
    assert called["n"] == 0
    assert res["already_captured"] is True
    assert res["order_id"] == "ORD1"


# ------------------------------- Layer B -----------------------------------

def test_settle_delivered_refunds_duplicate_when_consumed_exists(isolated_store):
    """Job consegnato con un capture consumato + uno non consumato: il non
    consumato è un DUPLICATO reale → rimborso (voucher), non incasso."""
    _capture("ORD_USED", job_id="jobK", used=True)
    _capture("ORD_DUP", job_id="jobK", used=False)

    out = payment.settle_delivered_captures_for_job("jobK", reason="cleanup")
    assert len(out) == 1
    r = out[0]
    assert r["order_id"] == "ORD_DUP"
    assert r.get("refunded_duplicate") is True
    assert r["voucher_code"]                          # rimborsato via voucher
    # Il capture duplicato è ora used (consumato dal refund), non un settle
    pay_dup = payment._payments["ORD_DUP"]
    assert pay_dup["used"] is True
    assert pay_dup.get("used_for") == "auto_refund_unused"
    # Il capture consegnato NON viene toccato
    assert payment._payments["ORD_USED"]["used"] is True
    assert "refund_voucher" not in payment._payments["ORD_USED"]


def test_settle_delivered_settles_when_no_consumed(isolated_store):
    """Job consegnato ma nessun capture consumato (mark-consume mai avvenuto):
    vero falso positivo → settle senza rimborso (denaro dovuto)."""
    _capture("ORD_ONLY", job_id="jobK", used=False)

    out = payment.settle_delivered_captures_for_job("jobK", reason="delivered")
    assert len(out) == 1
    assert out[0].get("refunded_duplicate") is not True
    pay = payment._payments["ORD_ONLY"]
    assert pay["used"] is True
    assert pay.get("used_for") == "delivered_settle"   # settle, non refund
    assert "refund_voucher" not in pay
