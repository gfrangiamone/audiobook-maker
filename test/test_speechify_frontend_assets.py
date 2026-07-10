from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_html_has_speechify_emotion_combo():
    html = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
    assert 'id="speechifyEmotion"' in html
    # Accento deve precedere la voce nel markup del tab Premium.
    i_accent = html.find('id="geminiAccentRow"')
    i_voice = html.find('id="vvPremium"')
    assert i_accent != -1 and i_voice != -1
    assert i_accent < i_voice, "accent row must come before the voice select"


def test_appjs_has_model_population():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "updModelsPremium" in js
    assert "simba-3.2" in js


def test_appjs_toggle_and_payload():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "_onPremiumModelChanged" in js
    assert "speechifyEmotionRow" in js
    assert "speechify_emotion" in js  # payload key
    assert "_isSpeechifyVoiceId" in js


def test_i18n_has_emotion_keys():
    # NOTE: i18n/en.json et al. were intentionally dropped in commit 86c4594
    # ("chore: remove dead code and unused i18n keys" - orphan files, never
    # loaded). The single source of truth for UI translations is the inline
    # `const L={...}` dict in templates/_fragments/i18n_data.js.
    js = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    assert "lbl_emotion" in js
    assert "lbl_model_simba" in js
    assert "emotion_none" in js
    # Present in it/en/fr/es/de/zh (same 6-language set as the existing
    # accent_* Object.assign(L.xx,...) blocks; 'hi' relies on the built-in
    # t() fallback to L.en for untranslated keys).
    assert js.count("lbl_model_simba") >= 6
