import re
from pathlib import Path

APP_JS = Path("static/js/app.js").read_text(encoding="utf-8")


def test_has_switch_audio_tab_function():
    assert "function switchAudioTab" in APP_JS


def test_has_updVoicesPremium_function():
    assert "function updVoicesPremium" in APP_JS


def test_updVoices_excludes_gemini():
    assert "// SKIP gemini in Standard tab" in APP_JS


def test_wizardState_has_audioTab():
    assert "audioTab:" in APP_JS or "audioTab =" in APP_JS


def test_lang_sync_between_tabs_present():
    assert "syncLanguage" in APP_JS or "vlPremium.value = " in APP_JS


# ── Issue 1: _updateSummary is tab-aware for voice display ──
def test_updateSummary_uses_vvPremium_when_premium():
    assert "audioTab" in APP_JS
    assert "vvPremium" in APP_JS
    assert "summaryVoice" in APP_JS
    # The fix: inside _updateSummary's body, wizardState.audioTab==='premium' branches to vvPremium
    m = re.search(r"function _updateSummary\(\)\{(.+?)^}", APP_JS, re.DOTALL | re.MULTILINE)
    assert m, "_updateSummary function not found"
    body = m.group(1)
    assert "audioTab" in body, "audioTab branch missing in _updateSummary"
    assert "vvPremium" in body, "vvPremium read missing in _updateSummary"


# ── Issue 2: voiceLang is tab-aware (ternary with vlPremium) ──
def test_validateLanguage_uses_vlPremium():
    # _validateLanguage must contain a ternary that reads vlPremium based on audioTab
    m = re.search(r"async function _validateLanguage\(\)(.+?)^}", APP_JS, re.DOTALL | re.MULTILINE)
    assert m, "_validateLanguage function not found"
    body = m.group(1)
    assert "vlPremium" in body, "vlPremium not used in _validateLanguage"
    assert "audioTab" in body, "audioTab check missing in _validateLanguage"


def test_startCombinedGeneration_estimate_uses_vlPremium():
    # The optimize_estimate URL in startCombinedGeneration must be tab-aware
    m = re.search(
        r"async function startCombinedGeneration\([^)]*\)(.+?)^(?:async function|function)\s",
        APP_JS, re.DOTALL | re.MULTILINE
    )
    assert m, "startCombinedGeneration function not found"
    body = m.group(1)
    # Should contain vlPremium near the optimize_estimate block
    assert "vlPremium" in body, "vlPremium not used in startCombinedGeneration estimate"


# ── Issue 3: switchAudioTab re-valuta l'anteprima al cambio tab ──
# Il reset/invalidazione anteprima è ora centralizzato in _onPreviewParamsChanged()
# (basato su firma): se la combinazione voce/parametri non è già nota, nasconde il
# player e forza la rigenerazione (cfr. commento app.js "Sostituisce _resetPreviewState()").
def test_switchAudioTab_resets_preview_on_change():
    m = re.search(r"function switchAudioTab\(tab\)\{(.+?)^}", APP_JS, re.DOTALL | re.MULTILINE)
    assert m, "switchAudioTab function not found"
    body = m.group(1)
    assert "_onPreviewParamsChanged" in body or "_resetPreviewState" in body or "previewStop" in body, \
        "preview re-evaluation/reset call missing in switchAudioTab"


# ── Issue 4: updVoicesPremium aggancia onchange per re-valutare l'anteprima ──
def test_updVoicesPremium_attaches_onchange_reset():
    m = re.search(r"function updVoicesPremium\(\)\{(.+?)^}", APP_JS, re.DOTALL | re.MULTILINE)
    assert m, "updVoicesPremium function not found"
    body = m.group(1)
    assert "onchange" in body, "onchange handler missing in updVoicesPremium"
    assert "_onPreviewParamsChanged" in body or "_resetPreviewState" in body or "previewStop" in body, \
        "preview re-evaluation/reset missing in updVoicesPremium onchange"
