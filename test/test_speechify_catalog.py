import pytest
import voice_utils
import speechify_tts


def test_is_speechify_voice_true():
    assert voice_utils.is_speechify_voice("speechify:simba-3.2:dominic_32") is True


def test_is_speechify_voice_false_on_gemini():
    assert voice_utils.is_speechify_voice("gemini:flash25:Zephyr") is False


def test_is_speechify_voice_safe_on_none_and_empty():
    assert voice_utils.is_speechify_voice(None) is False
    assert voice_utils.is_speechify_voice("") is False
    assert voice_utils.is_speechify_voice(123) is False


def test_voices_are_eight_all_32():
    ids = [v["id"] for v in speechify_tts.VOICES]
    assert len(ids) == 8
    assert all(i.endswith("_32") for i in ids)


def test_voice_locale_mapping():
    assert speechify_tts.voice_locale("dominic_32") == "en-US"
    assert speechify_tts.voice_locale("beatrice_32") == "en-GB"
    assert speechify_tts.voice_locale("nope") is None


def test_emotions_are_thirteen():
    assert len(speechify_tts.EMOTIONS) == 13
    assert "cheerful" in speechify_tts.EMOTIONS


def test_get_voices_only_english():
    cat = speechify_tts.get_voices()
    assert set(cat.keys()) == {"en"}
    entry = cat["en"][0]
    assert entry["engine"] == "speechify"
    assert entry["model_key"] == "simba-3.2"
    assert entry["id"].startswith("speechify:simba-3.2:")


def test_parse_voice_id_ok():
    mk, vn, loc = speechify_tts.parse_voice_id("speechify:simba-3.2:harper_32")
    assert mk == "simba-3.2"
    assert vn == "harper_32"
    assert loc == "en-US"


def test_parse_voice_id_invalid():
    with pytest.raises(ValueError):
        speechify_tts.parse_voice_id("gemini:flash25:Zephyr")
    with pytest.raises(ValueError):
        speechify_tts.parse_voice_id("speechify:simba-3.2:unknown_voice")
