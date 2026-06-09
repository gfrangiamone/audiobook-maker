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
