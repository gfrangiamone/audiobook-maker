"""Email della voce campione in sette lingue (spec §8)."""
import json
import os

import pytest

import email_service as es

LANGS = ("it", "en", "fr", "es", "de", "zh", "hi")
KEYS = ("brand", "paid_subject", "paid_body", "confirm_subject", "confirm_body",
        "device_subject", "device_body", "ready_subject", "ready_body",
        "expiring_subject", "expiring_body", "reminder_subject", "reminder_body_1",
        "reminder_body_2", "refund_subject", "refund_body_paypal", "refund_body_voucher",
        "refund_reason_user_rejected", "refund_reason_sample_unusable",
        "refund_reason_demo_failed_timeout", "refund_reason_no_approval", "footer")
PROVIDERS = ("runpod", "voxcpm", "deepseek", "gemini", "speechify")


@pytest.fixture
def inviate(monkeypatch):
    out = []
    monkeypatch.setattr(es, "_send_email", lambda to, subj, body, **kw: out.append((to, subj, body)) or True)
    return out


def test_il_json_ha_tutte_le_lingue_e_le_chiavi():
    path = os.path.join(os.path.dirname(es.__file__), "i18n", "voice_clone_emails.json")
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    for lang in LANGS:
        assert set(data[lang]) == set(KEYS), lang
        for k in KEYS:
            assert data[lang][k].strip(), (lang, k)
            assert not any(p in data[lang][k].lower() for p in PROVIDERS), (lang, k)


@pytest.mark.parametrize("lang", LANGS + ("xx",))
def test_paid_in_ogni_lingua_e_fallback(inviate, lang):
    assert es.send_voice_clone_paid("u@x.it", lang, voice_code="ABCD-EFGH-JKMN", amount_eur=5.0,
                                    resume_url="https://a/vc/r/resume", manage_url="https://a/vc/m/devices",
                                    delete_url="https://a/vc/m/delete") is True
    to, subj, body = inviate[-1]
    assert to == "u@x.it" and "ABCD-EFGH-JKMN" in body and "5.00" in body
    assert "https://a/vc/r/resume" in body and "https://a/vc/m/delete" in body
    if lang == "it":
        assert subj == "La tua voce campione: codice e ricevuta"
    if lang == "xx":
        assert subj == "Your voice sample: code and receipt"


def test_confirm_e_device(inviate):
    assert es.send_voice_clone_confirm("u@x.it", "it", confirm_code="123456")
    assert "123456" in inviate[-1][2] and "15" in inviate[-1][2]
    assert es.send_voice_clone_device_added("u@x.it", "en", devices_url="https://a/vc/m/devices")
    assert inviate[-1][1] == "New device authorized" and "https://a/vc/m/devices" in inviate[-1][2]


def test_ready_expiring_reminder(inviate):
    assert es.send_voice_clone_ready("u@x.it", "it", voice_code="AAAA-BBBB-CCCC", manage_url="https://m",
                                     delete_url="https://d", retention_days=180)
    assert inviate[-1][1] == "La tua voce campione è pronta" and "180" in inviate[-1][2]
    assert es.send_voice_clone_expiring("u@x.it", "it", days=30, manage_url="https://m")
    assert inviate[-1][1] == "La tua voce campione scade fra 30 giorni"
    assert es.send_voice_clone_reminder("u@x.it", "en", resume_url="https://r", stage=2)
    assert "https://r" in inviate[-1][2]


def test_refund_paypal_voucher_free(inviate):
    assert es.send_voice_clone_refunded("u@x.it", "it", amount_eur=5.0, method="paypal",
                                        reason="user_rejected", voucher_code="V-1", voucher_amount=5.0,
                                        expiry_days=180)
    assert "V-1" in inviate[-1][2] and "180" in inviate[-1][2]
    assert es.send_voice_clone_refunded("u@x.it", "en", amount_eur=5.0, method="voucher",
                                        reason="sample_unusable")
    assert "V-1" not in inviate[-1][2] and "5.00" in inviate[-1][2]
    n = len(inviate)
    assert es.send_voice_clone_refunded("u@x.it", "en", amount_eur=0.0, method="free",
                                        reason="user_rejected") is False
    assert len(inviate) == n


def test_i_valori_vengono_escapati(inviate):
    es.send_voice_clone_paid("u@x.it", "en", voice_code="<b>x</b>", amount_eur=5.0,
                             resume_url="https://r", manage_url="https://m", delete_url="https://d")
    assert "<b>x</b>" not in inviate[-1][2] and "&lt;b&gt;x&lt;/b&gt;" in inviate[-1][2]


def test_send_email_che_fallisce_non_solleva(monkeypatch):
    def esplode(*a, **k):
        raise RuntimeError("smtp giu")
    monkeypatch.setattr(es, "_send_email", esplode)
    assert es.send_voice_clone_confirm("u@x.it", "it", confirm_code="1") is False


def test_blocco_digest():
    assert es._voice_clone_block_html({}) == ""
    assert es._voice_clone_block_html({"window_hours": 24, "rows": [], "active_ready": 3}) == ""
    html = es._voice_clone_block_html({"window_hours": 24, "active_ready": 3,
                                       "rows": [{"label": "paid", "count": 2},
                                                {"label": "refunded:user_rejected", "count": 1}]})
    assert "paid" in html and "2" in html and "refunded:user_rejected" in html and "3" in html
    es.set_voice_clone_provider(lambda: {"window_hours": 24, "rows": [{"label": "ready", "count": 1}],
                                         "active_ready": 1})
    try:
        assert "ready" in es._voice_clone_block_html()
    finally:
        es.set_voice_clone_provider(None)
