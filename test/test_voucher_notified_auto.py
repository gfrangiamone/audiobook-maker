"""Le email automatiche che portano il codice del buono lo annotano in
`notified`, come il bottone della console admin (buono PQNP, 21/10/2026:
email di annullamento col codice partita, colonna "inviata" vuota)."""
import os

os.environ.setdefault("ABM_BASE_URL", "http://localhost:5601")

import pytest

import email_service as es
import generation_engine as ge
import payment

CODE = "REF-AAAA-BBBB-CCCC"


@pytest.fixture(autouse=True)
def _store(monkeypatch):
    monkeypatch.setattr(payment, "_vouchers", {CODE: {
        "email": "u@x.it", "amount_eur": 7.95, "created_at": 1.0, "expires_at": 2e9}})
    monkeypatch.setattr(payment, "_save_vouchers", lambda: None)
    monkeypatch.setattr(es, "_smtp_available", lambda: True)
    monkeypatch.setattr(es, "BASE_URL", "https://x")
    monkeypatch.setattr(ge, "_send_push", None)
    monkeypatch.setattr(ge, "_log_activity", lambda *a, **k: None)


def _notified():
    return [n["email"] for n in payment.voucher_info(CODE).get("notified", [])]


SENDERS = {
    "voucher": lambda: es._send_voucher_email(CODE, "u@x.it", 7.95, "Libro"),
    "overload": lambda: es._send_gemini_overload_email("u@x.it", 7.95, "Libro", voucher_code=CODE),
    "cancel": lambda: es._send_gemini_cancelled_partial_email(
        "u@x.it", 7.95, 0.0, 7.95, CODE, "Libro", ""),
    "failed": lambda: es._send_gemini_failed_refund_email(
        "u@x.it", 7.95, "Libro", "quota", voucher_code=CODE),
    "voice_clone": lambda: es.send_voice_clone_refunded(
        "u@x.it", "en", amount_eur=7.95, method="paypal", reason="user_rejected",
        voucher_code=CODE),
    "premium_failed": lambda: ge._notify_user_premium_job_failed("J1", {"notify_lang": "en"}, {
        "method": "paypal", "amount_eur": 7.95, "email": "u@x.it", "voucher_code": CODE}),
}


@pytest.mark.parametrize("name", sorted(SENDERS))
def test_email_inviata_annota_il_buono(monkeypatch, name):
    monkeypatch.setattr(es, "_send_email", lambda *a, **k: True)
    SENDERS[name]()
    assert _notified() == ["u@x.it"]


@pytest.mark.parametrize("name", sorted(SENDERS))
def test_invio_fallito_non_annota(monkeypatch, name):
    monkeypatch.setattr(es, "_send_email", lambda *a, **k: False)
    SENDERS[name]()
    assert _notified() == []


def test_email_senza_codice_nel_testo_non_annota(monkeypatch):
    """Rimborso con importo zero: il codice non compare nell'email."""
    monkeypatch.setattr(es, "_send_email", lambda *a, **k: True)
    payment._vouchers[CODE]["amount_eur"] = 0.0
    ge._notify_user_premium_job_failed("J1", {"notify_lang": "en"}, {
        "method": "paypal", "amount_eur": 0.0, "email": "u@x.it", "voucher_code": CODE})
    es._send_gemini_cancelled_partial_email("u@x.it", 7.95, 7.95, 0.0, CODE, "Libro", "")
    assert _notified() == []
