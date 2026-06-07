# test/test_app_js_last_lang.py
"""Test statici su app.js: preselezione lingua target da ultima usata
(spec 2026-06-07-last-lang-target-preselect)."""
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def test_helper_present_with_storage_key():
    assert "function _rememberLastLang" in APP
    assert "abm_last_lang" in APP


def test_helper_normalizes_and_validates():
    fn = APP.split("function _rememberLastLang", 1)[1][:400]
    assert "toLowerCase" in fn
    assert "split('-')" in fn
    assert "[a-z]{2,3}" in fn


def test_recorded_on_translation_start():
    fn = APP.split("async function startTranslation", 1)[1][:1500]
    assert "_rememberLastLang(dst)" in fn


def test_recorded_on_audio_starts():
    # ramo combined optimize+autogen, ramo TTS diretto, startGen
    assert "_rememberLastLang(selLang)" in APP
    assert "_rememberLastLang(_genLang)" in APP
    assert "_rememberLastLang(_genLang2)" in APP


def test_estimate_block_does_not_record():
    # Il selLang del blocco stima (optimize_estimate) NON deve registrare:
    # la registrazione avviene una sola volta nel ramo optimize, dopo il
    # calcolo del selLang del payload.
    assert APP.count("_rememberLastLang(selLang)") == 1


def test_preselect_in_fill_lang_selects():
    fn = APP.split("function _trFillLangSelects", 1)[1]
    fn = fn.split("function _trPrefillOutName", 1)[0]
    assert "abm_last_lang" in fn
    assert "_trRestored" in fn
    assert "[saved,cl]" in fn  # catena di fallback: ultima usata, poi lingua UI


def test_preselect_skips_source_lang():
    fn = APP.split("function _trFillLangSelects", 1)[1]
    fn = fn.split("function _trPrefillOutName", 1)[0]
    assert "cand!==srcLang" in fn
