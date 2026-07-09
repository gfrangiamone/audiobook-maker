import generation_engine


def test_engine_for_speechify_voice():
    assert generation_engine._engine_for_voice("speechify:simba-3.2:harper_32") == "speechify"


def test_engine_for_gemini_still_gemini():
    assert generation_engine._engine_for_voice("gemini:flash25:Zephyr") == "gemini"


def test_engine_for_edge_default():
    assert generation_engine._engine_for_voice("en-US-GuyNeural") == "edge"
