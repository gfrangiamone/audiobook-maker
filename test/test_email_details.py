# Test del blocco "dettagli di generazione" nell'email di completamento.
import pytest

import generation_engine as ge


def _job(voice="it-IT-IsabellaNeural", rate="+0%", ai=False, **extra):
    j = {"voice": voice, "rate": rate, "ai_optimized": ai}
    j.update(extra)
    return j


def test_standard_voice_italian_email():
    html = ge._email_generation_details(_job(), "it")
    assert "Voci Standard" in html
    assert "it-IT" in html
    assert "Isabella" in html
    assert "normale" in html
    assert "Gemini" not in html
    assert "Istruzioni di stile" not in html
    # non ottimizzato (default)
    assert "non" in html


def test_standard_voice_custom_rate():
    html = ge._email_generation_details(_job(rate="+10%"), "it")
    assert "+10%" in html
    assert "normale" not in html


def test_standard_multilingual_name_spacing():
    html = ge._email_generation_details(
        _job(voice="en-US-AndrewMultilingualNeural"), "en")
    assert "Andrew Multilingual" in html
    assert "en-US" in html
    assert "Standard" in html


def test_premium_voice_full_block():
    html = ge._email_generation_details(
        _job(voice="gemini:flash25:Zephyr", gen_lang="it",
             gemini_style_instruction="tono calmo", ai=True), "it")
    assert "Voci PREMIUM" in html
    assert "Zephyr" in html
    assert "Gemini 2.5 Flash TTS" in html
    assert "tono calmo" in html
    assert ">it<" in html or ">it</strong>" in html.replace(" ", "")


def test_premium_flash31_model_label():
    html = ge._email_generation_details(
        _job(voice="gemini:flash31:Puck", gen_lang="en"), "en")
    assert "Gemini 3.1 Flash TTS" in html
    assert "PREMIUM" in html


def test_premium_without_style_omits_style_line():
    html = ge._email_generation_details(
        _job(voice="gemini:flash25:Zephyr", gen_lang="it"), "it")
    assert "Istruzioni di stile" not in html
    assert "Gemini 2.5 Flash TTS" in html


def test_style_is_html_escaped():
    html = ge._email_generation_details(
        _job(voice="gemini:flash25:Zephyr", gen_lang="it",
             gemini_style_instruction='<b>x</b>"y"'), "it")
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;" in html


def test_ai_optimized_states():
    h_yes = ge._email_generation_details(_job(ai=True), "en")
    h_no = ge._email_generation_details(_job(ai=False), "en")
    assert "has been optimized" in h_yes
    assert "was not optimized" in h_no


def test_unknown_email_lang_falls_back_to_english():
    html = ge._email_generation_details(_job(), "xx")
    assert "Standard" in html
    assert "Isabella" in html


def test_malformed_voice_never_crashes():
    html = ge._email_generation_details(_job(voice=""), "it")
    assert isinstance(html, str)  # blocco anche vuoto, mai eccezione
    html2 = ge._email_generation_details(_job(voice="weird"), "it")
    assert isinstance(html2, str)


def test_unknown_premium_model_omits_model_line():
    html = ge._email_generation_details(
        _job(voice="gemini:futurex:Nova", gen_lang="it"), "it")
    assert "Hai utilizzato il modello" not in html
    assert "Nova" in html


def test_all_seven_email_langs_have_all_keys():
    keys = set(ge._email_details_i18n["en"].keys())
    for lng in ("it", "en", "fr", "es", "de", "pt", "zh"):
        assert set(ge._email_details_i18n[lng].keys()) == keys, lng
