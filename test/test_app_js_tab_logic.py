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
