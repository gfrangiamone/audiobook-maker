"""Regressione: l'email di completamento deve presentare le voci Speechify come
PREMIUM, con nome voce amichevole e label modello, non il frammento grezzo dell'id.

Difetto (screenshot utente): "You chose the voice 3.2:harper_32 at normal speed."
Causa: is_premium = _is_gemini_voice(voice) escludeva Speechify, quindi la voce
veniva trattata come Standard e _friendly_voice_name faceva split su '-' di
'simba-3.2' restituendo '3.2:harper_32'; nessuna riga modello/PREMIUM.

Atteso: tipo voci "PREMIUM", voce "Harper", modello "Simba (English)", e nessun
frammento grezzo dell'id.
"""
import generation_engine as ge


def test_friendly_voice_name_speechify():
    assert ge._friendly_voice_name("speechify:simba-3.2:harper_32") == "Harper"
    assert ge._friendly_voice_name("speechify:simba-3.2:hugh_32") == "Hugh"


def test_email_details_speechify_is_premium_with_friendly_voice_and_model():
    job = {
        "voice": "speechify:simba-3.2:harper_32",
        "rate": "+0%",
        "gen_lang": "en",
        "ai_optimized": True,
    }
    html = ge._email_generation_details(job, "en")
    assert "PREMIUM" in html, "voce Speechify non marcata come PREMIUM"
    assert "Harper" in html, "nome voce amichevole assente"
    assert "Simba (English)" in html, "label modello assente"
    assert "3.2:harper_32" not in html, "frammento grezzo dell'id ancora presente"
    assert "harper_32" not in html, "id voce grezzo ancora presente"


def test_email_details_gemini_still_works():
    job = {
        "voice": "gemini:flash25:Zephyr",
        "rate": "+0%",
        "gen_lang": "it",
        "ai_optimized": False,
    }
    html = ge._email_generation_details(job, "en")
    assert "PREMIUM" in html
    assert "Zephyr" in html
    assert "Gemini 2.5 Flash TTS" in html
