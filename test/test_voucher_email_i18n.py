"""Email del buono di rimborso: lingua UI, operazione fallita, bonus."""
import pytest

import email_service as es


@pytest.fixture
def sent(monkeypatch):
    out = {}
    monkeypatch.setattr(es, "_smtp_available", lambda: True)
    monkeypatch.setattr(es, "_send_email",
                        lambda to, subj, html, reply_to=None: out.update(to=to, subject=subj, html=html))
    return out


def test_translation_refund_in_english(sent):
    es._send_voucher_email("ABCD-EFGH-IJKL", "u@x.com", 7.52, "Earthsea",
                           kind="translation", lang="en")
    assert sent["subject"] == "Audiobook Maker — Refund voucher EUR 7.52"
    assert "The translation of <strong>Earthsea</strong>" in sent["html"]
    assert "ottimizzazione" not in sent["html"].lower()
    assert f"increased by {es.VOUCHER_BONUS_PERCENT}%" in sent["html"]
    assert "ABCD-EFGH-IJKL" in sent["html"]


@pytest.mark.parametrize("lang", sorted(es._VOUCHER_I18N))
@pytest.mark.parametrize("kind", ["optimization", "translation"])
def test_every_language_renders(sent, lang, kind):
    es._send_voucher_email("C0DE", "u@x.com", 3.0, "Libro", kind=kind, lang=lang)
    assert "3.00" in sent["subject"]
    assert es._VOUCHER_WHAT[lang][kind] in sent["html"]
    assert "{" not in sent["html"]


def test_unknown_lang_falls_back_to_english_and_region_is_stripped(sent):
    es._send_voucher_email("C", "u@x.com", 1.0, "T", lang="pt-BR")
    assert "Refund voucher" in sent["subject"]
    es._send_voucher_email("C", "u@x.com", 1.0, "T", lang="fr-FR")
    assert "Bon de remboursement" in sent["subject"]


def test_no_bonus_on_cancel_and_title_escaped(sent):
    es._send_voucher_email("C", "u@x.com", 1.0, "<b>x</b>", lang="it", bonus_applied=False)
    assert "maggiorato" not in sent["html"]
    assert "<b>x</b>" not in sent["html"] and "&lt;b&gt;x&lt;/b&gt;" in sent["html"]


def test_no_smtp_no_send(monkeypatch):
    calls = []
    monkeypatch.setattr(es, "_smtp_available", lambda: False)
    monkeypatch.setattr(es, "_send_email", lambda *a, **k: calls.append(a))
    es._send_voucher_email("C", "u@x.com", 1.0, "T")
    assert calls == []


# --- Ricevuta di pagamento ---------------------------------------------------

def test_receipt_translation_in_english_names_the_service(sent):
    es._send_payment_receipt_email("ORD-1", "u@x.com", 7.16, kind="translation",
                                   lang="en", book_title="Earthsea", job={"notify_email": ""})
    assert sent["subject"] == "Audiobook Maker payment receipt — EUR 7.16"
    assert "Service: <strong>Book translation</strong>" in sent["html"]
    assert "Project: <strong>Earthsea</strong>" in sent["html"]
    assert "speech synthesis" not in sent["html"] and "optimization" not in sent["html"]
    assert "<strong>u@x.com</strong>" in sent["html"]


@pytest.mark.parametrize("lang", sorted(es._RECEIPT_I18N))
@pytest.mark.parametrize("kind", sorted(es._RECEIPT_SERVICE["en"]))
def test_receipt_every_language_and_kind(sent, lang, kind):
    es._send_payment_receipt_email("ORD", "u@x.com", 2.5, kind=kind, lang=lang,
                                   book_title="T", job={})
    assert "2.50" in sent["subject"]
    assert es._RECEIPT_SERVICE[lang][kind] in sent["html"]
    assert "{" not in sent["html"]


def test_receipt_voice_clone_has_no_delivery_block_and_falls_back(sent):
    es._send_payment_receipt_email("ORD", "u@x.com", 5.0, kind="voice_clone", lang="pt-BR")
    assert "Sampling of your voice" in sent["html"]
    assert "download link" not in sent["html"]
    assert "Project:" not in sent["html"]


def test_receipt_delivery_prefers_registered_email_and_escapes_title(sent):
    es._send_payment_receipt_email("ORD", "pay@x.com", 1.0, lang="it",
                                   book_title="<i>x</i>", job={"notify_email": "me@y.com"})
    assert "<strong>me@y.com</strong>" in sent["html"]
    assert "<i>x</i>" not in sent["html"] and "&lt;i&gt;x&lt;/i&gt;" in sent["html"]
