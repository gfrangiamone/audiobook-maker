"""Errori del gate modelli PREMIUM mostrati localizzati (review finale M5).

Il server risponde `error: "voice_model_unavailable"` (503) o
`"voice_model_disabled"` (400) col codice nudo: il frontend deve mostrarlo
come messaggio tradotto, mai come codice grezzo, e senza nominare provider.
"""
import re
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")

LANGS = ("it", "en", "fr", "es", "de", "zh", "hi")
KEYS = ("err_voice_model_unavailable", "err_voice_model_disabled")
PROVIDERS = ("Gemini", "Google", "DeepSeek", "Speechify", "VoxCPM", "Cloudflare", "Vertex")


def test_chiavi_tradotte_in_tutte_le_lingue_senza_provider():
    for key in KEYS:
        found = re.findall(key + r':"([^"]+)"', I18N)
        assert len(found) == len(LANGS), (key, found)
        assert len(set(found)) == len(LANGS), "traduzioni duplicate: %r" % (found,)
        for txt in found:
            assert not any(p in txt for p in PROVIDERS), txt


def test_mappa_codici_con_fallback_inglese():
    for code in ("voice_model_unavailable", "voice_model_disabled"):
        assert re.search(code + r":\['err_" + code + r"','[A-Z][^']+'\]", APP), code


def test_show_perr_e_show_err_localizzano_il_codice():
    # Guardia typeof: test_app_js_progress_resilience esegue showPErr isolata.
    assert ("function showPErr(m){\n  if(typeof _localizeErrCode==='function')"
            "m=_localizeErrCode(m);") in APP.replace("\r\n", "\n")
    assert "function showErr(id,m){m=_localizeErrCode(m);" in APP


def test_ordine_paypal_gestisce_il_codice():
    assert "if(d&&_VOICE_MODEL_ERR[d.error_code]){" in APP
    assert "_payPaypalErr(_localizeErrCode(d.error_code));" in APP
