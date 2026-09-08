"""Tests for _engine_for_voice dispatcher in generation_engine.py."""
import generation_engine


def test_engine_for_voice_gemini():
    assert generation_engine._engine_for_voice("gemini:flash25:Zephyr") == "gemini"
    assert generation_engine._engine_for_voice("gemini:flash31:Achernar") == "gemini"


def test_engine_for_voice_edge_default():
    assert generation_engine._engine_for_voice("it-IT-IsabellaNeural") == "edge"
    assert generation_engine._engine_for_voice("en-US-GuyNeural") == "edge"


def test_engine_for_voice_empty_returns_edge():
    assert generation_engine._engine_for_voice("") == "edge"
    assert generation_engine._engine_for_voice(None) == "edge"
