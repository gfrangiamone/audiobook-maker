"""Test del template email _send_gemini_cancelled_partial_email."""
from unittest.mock import patch

import email_service


def test_email_paypal_includes_voucher_code_and_link():
    captured = {}

    def fake_send(to_addr, subject, html_body):
        captured["to"] = to_addr
        captured["subject"] = subject
        captured["html"] = html_body

    with patch.object(email_service, "_send_email", side_effect=fake_send), \
         patch.object(email_service, "_smtp_available", return_value=True):
        email_service._send_gemini_cancelled_partial_email(
            email="u@x.it",
            paid_eur=2.00,
            retained_eur=0.71,
            refund_eur=1.29,
            voucher_code="REF-ABC",
            book_title="Il mio libro",
            download_url="https://example.com/dl/TOK",
        )
    assert captured["to"] == "u@x.it"
    assert "1.29" in captured["html"]
    assert "REF-ABC" in captured["html"]
    assert "https://example.com/dl/TOK" in captured["html"]
    # Importi paid/retained presenti
    assert "2.00" in captured["html"]
    assert "0.71" in captured["html"]
    # Non deve nominare il provider TTS
    assert "Gemini" not in captured["html"]
    assert "Gemini" not in captured["subject"]


def test_email_voucher_no_code_silent_credit():
    """Pagamento via voucher: voucher_code=None, refund silente sull'originale."""
    captured = {}

    def fake_send(to_addr, subject, html_body):
        captured["html"] = html_body

    with patch.object(email_service, "_send_email", side_effect=fake_send), \
         patch.object(email_service, "_smtp_available", return_value=True):
        email_service._send_gemini_cancelled_partial_email(
            email="u@x.it",
            paid_eur=2.00,
            retained_eur=0.71,
            refund_eur=1.29,
            voucher_code=None,
            book_title="Libro",
            download_url="https://example.com/dl/TOK",
        )
    # Nessun codice voucher nel template, ma il refund 1.29 deve esserci
    assert "1.29" in captured["html"]
    assert "https://example.com/dl/TOK" in captured["html"]
