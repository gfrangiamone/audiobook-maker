"""Job premium fallito con pagamento combinato: il rimborso copre anche la
quota dell'ottimizzazione AI, e chi ha pagato riceve l'email con il codice
del buono (job 5hxSn_-I0LgKV0D9i9Nvjg, 04/10/2026: rimborsata la sola quota
voci, nessuna email)."""
import time
from unittest.mock import patch

import pytest

import generation_engine as ge


@pytest.fixture
def combined_voucher_job():
    return {
        "payment": {"token": "VCR-ABC", "total_eur": 4.31, "llm_eur": 0.72,
                    "method": "voucher"},
    }


@pytest.fixture
def combined_paypal_job():
    return {
        "payment": {"token": "PAY-XYZ", "total_eur": 4.31, "llm_eur": 0.72,
                    "method": "paypal"},
    }


def test_fallimento_rimborsa_anche_la_quota_llm(combined_voucher_job):
    with patch.object(ge.payment, "_voucher_refund") as mock_refund, \
         patch.object(ge.payment, "_vouchers", {"VCR-ABC": {"email": "u@x.it"}}):
        out = ge._refund_gemini_payment("job1", combined_voucher_job,
                                        "failed: boom")
    assert mock_refund.call_args[0][1] == pytest.approx(5.03)
    assert out["amount_eur"] == pytest.approx(5.03)
    assert combined_voucher_job["refund_llm_eur"] == pytest.approx(0.72)


def test_cancel_non_rimborsa_la_quota_llm(combined_voucher_job):
    with patch.object(ge.payment, "_voucher_refund") as mock_refund, \
         patch.object(ge.payment, "_vouchers", {"VCR-ABC": {"email": "u@x.it"}}):
        ge._refund_gemini_payment("job1", combined_voucher_job, "cancelled")
    assert mock_refund.call_args[0][1] == pytest.approx(4.31)
    assert "refund_llm_eur" not in combined_voucher_job


def test_include_llm_esplicito_vince_sul_default(combined_voucher_job):
    with patch.object(ge.payment, "_voucher_refund") as mock_refund, \
         patch.object(ge.payment, "_vouchers", {"VCR-ABC": {"email": "u@x.it"}}):
        ge._refund_gemini_payment("job1", combined_voucher_job,
                                  "failed: boom", include_llm=False)
    assert mock_refund.call_args[0][1] == pytest.approx(4.31)


def test_paypal_buono_sull_intero_importo(combined_paypal_job):
    with patch.object(ge.payment, "_payments", {"PAY-XYZ": {"email": "p@x.it"}}), \
         patch.object(ge.payment, "_create_voucher",
                      return_value=("JPCM-TEST", 0.2)) as mock_create:
        out = ge._refund_gemini_payment("job1", combined_paypal_job,
                                        "failed: boom")
    assert mock_create.call_args[0][1] == pytest.approx(5.03)
    assert out["voucher_code"] == "JPCM-TEST"


def _invia(job, refund, vouchers=None):
    inviate = []
    with patch.object(ge.email_service, "_send_email",
                      side_effect=lambda to, subj, html: inviate.append(
                          (to, subj, html)) or True), \
         patch.object(ge.payment, "_vouchers", vouchers or {}), \
         patch.object(ge, "_send_push", None):
        esito = ge._notify_user_premium_job_failed("job1", job, refund)
    return esito, inviate


def test_email_paypal_porta_codice_importo_e_scadenza():
    scade = time.mktime((2026, 12, 3, 12, 0, 0, 0, 0, -1))
    job = {"notify_lang": "it-IT"}
    refund = {"method": "paypal", "amount_eur": 5.03, "email": "p@x.it",
              "voucher_code": "JPCM-TEST"}
    esito, inviate = _invia(job, refund, {
        "JPCM-TEST": {"amount_eur": 5.28, "expires_at": scade}})
    assert esito is True
    to, subj, html = inviate[0]
    assert to == "p@x.it"
    assert "JPCM-TEST" in html
    assert "5.28 EUR" in html
    assert "03/12/2026" in html
    assert job["premium_fail_email_sent"] is True
    # Mai il nome del motore nel testo per l'utente.
    for nome in ("VoxCPM", "Speechify", "Gemini", "RunPod"):
        assert nome.lower() not in html.lower()
        assert nome.lower() not in subj.lower()


def test_email_voucher_riaccredito_senza_codice():
    job = {"notify_lang": "en"}
    refund = {"method": "voucher", "amount_eur": 5.03, "email": "u@x.it",
              "voucher_code": None}
    _, inviate = _invia(job, refund)
    html = inviate[0][2]
    assert "credited the full amount" in html
    assert "5.03 EUR" in html


def test_email_senza_rimborso_non_promette_nulla():
    job = {"notify_email": "n@x.it", "notify_lang": "xx"}
    _, inviate = _invia(job, None)
    to, _, html = inviate[0]
    assert to == "n@x.it"
    assert "did not go through" in html


def test_email_una_sola_volta():
    job = {"notify_lang": "en", "premium_fail_email_sent": True}
    esito, inviate = _invia(job, {"method": "voucher", "amount_eur": 1.0,
                                  "email": "u@x.it"})
    assert esito is False
    assert inviate == []


def test_testi_in_tutte_le_lingue_con_le_stesse_chiavi():
    texts = ge._premium_failed_email_texts("Libro", 5.03, "C0DE", "03/12/2026")
    attese = set(texts["en"])
    for lang in ("it", "en", "fr", "es", "de", "zh", "hi"):
        assert set(texts[lang]) == attese, lang
        assert "C0DE" in texts[lang]["refund_paypal"], lang
        assert "03/12/2026" in texts[lang]["refund_paypal"], lang
