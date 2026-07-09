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
