"""Tests for /api/voices Gemini merge."""
import os
import pytest
import audiobook_app


@pytest.fixture(autouse=True)
def reset_voices_cache():
    audiobook_app._invalidate_voices_cache()
    yield
    audiobook_app._invalidate_voices_cache()


def test_get_voices_includes_gemini_when_module_present(monkeypatch):
    """If gemini_tts is loaded, voices catalog should include 'gemini' engine entries."""
    if audiobook_app.gemini_tts is None:
        pytest.skip("gemini_tts module not importable")

    voices = audiobook_app.get_voices()
    found_gemini = False
    for lang_code, lang_data in voices.items():
        if lang_code.startswith("_"):
            continue
        for v in lang_data.get("voices", []):
            if v.get("engine") == "gemini":
                found_gemini = True
                assert "gender" in v
                assert "gender_icon" in v
                assert v["id"].startswith("gemini:")
                break
        if found_gemini:
            break
    assert found_gemini, "No Gemini voices found in catalog"


def test_get_voices_gemini_entry_shape(monkeypatch):
    if audiobook_app.gemini_tts is None:
        pytest.skip("gemini_tts module not importable")

    voices = audiobook_app.get_voices()
    it_voices = voices.get("it", {}).get("voices", [])
    gemini_it = [v for v in it_voices if v.get("engine") == "gemini"]
    assert len(gemini_it) >= 30  # at least one model × 30 voices
    sample = gemini_it[0]
    for key in ("id", "name", "gender", "gender_icon", "locale", "engine"):
        assert key in sample, f"Missing key: {key}"
