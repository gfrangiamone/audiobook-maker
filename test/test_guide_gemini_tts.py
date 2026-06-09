"""Guida Gemini TTS: registrazione route + build HTML per lingua."""
import guide_content

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]


def test_guide_id_registered():
    import audiobook_app
    assert "gemini-tts" in audiobook_app._VALID_GUIDES


def test_build_html_all_langs_no_fallback_text():
    for lang in LANGS:
        html = guide_content.build_guide_html("gemini-tts", lang, base_url="https://x.test")
        assert "Guide content not available" not in html
        assert 'id="voices"' in html
        assert 'id="languages"' in html
        assert 'id="prompting"' in html
        assert "Zephyr" in html
        assert "(cmn)" in html
        assert "<title>" in html and "Gemini" in html


def test_published_date_present():
    assert guide_content._GUIDE_PUBLISHED.get("gemini-tts") == "2026-06-09"


def test_it_body_localized():
    import guide_content
    html = guide_content.build_guide_html("gemini-tts", "it", base_url="https://x.test")
    assert "Opzioni voce" in html
    assert "Lingue supportate" in html
    assert "Guida al prompting" in html
    assert "Brillante" in html
    assert ".ABM" in html


def test_ui_link_and_i18n_key_present():
    from pathlib import Path
    head = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
    assert "/guide/gemini-tts/?lang=__LANG_CODE__" in head
    assert 'data-t="guide_gemini_tts"' in head
    i18n = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    assert i18n.count("guide_gemini_tts:") + i18n.count('"guide_gemini_tts":') >= 7
