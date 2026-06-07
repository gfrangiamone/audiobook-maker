# test/test_app_js_tr_title.py
"""Test statici su app.js: proposta nome file tradotto
(spec 2026-06-06-translated-title-filename)."""
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def test_has_fetch_translated_name():
    assert "function _trFetchTranslatedName" in APP


def test_uses_translate_title_endpoint():
    assert "/api/translate_title/" in APP


def test_guard_user_edits():
    # Aggiorna il campo solo se contiene ancora il valore auto-impostato
    assert "el.value===trAutoOutName" in APP


def test_state_var_reset():
    assert "trAutoOutName=''" in APP


def test_prefill_records_auto_value():
    assert "trAutoOutName=base" in APP


def test_fetch_triggered_from_panel_and_change():
    # definizione + chiamata in goToTranslate + chiamata nel listener change
    assert APP.count("_trFetchTranslatedName(") >= 3


def test_timeout_abort_present():
    assert "function _trFetchTranslatedName" in APP
    fn = APP.split("function _trFetchTranslatedName", 1)[1][:900]
    assert "AbortController" in fn
