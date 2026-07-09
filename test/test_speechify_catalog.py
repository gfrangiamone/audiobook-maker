import voice_utils


def test_is_speechify_voice_true():
    assert voice_utils.is_speechify_voice("speechify:simba-3.2:dominic_32") is True


def test_is_speechify_voice_false_on_gemini():
    assert voice_utils.is_speechify_voice("gemini:flash25:Zephyr") is False


def test_is_speechify_voice_safe_on_none_and_empty():
    assert voice_utils.is_speechify_voice(None) is False
    assert voice_utils.is_speechify_voice("") is False
    assert voice_utils.is_speechify_voice(123) is False
