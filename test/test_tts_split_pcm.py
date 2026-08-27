"""Tests for PCM helpers in tts_split.py."""
import os
import sys
from unittest.mock import patch
import tts_split


def test_generate_silence_pcm_creates_file(tmp_path):
    out = tmp_path / "silence.pcm"
    tts_split._generate_silence_pcm(str(out), duration_sec=1)
    assert out.exists()
    # 24000 Hz x 1 ch x 2 bytes = 48000 bytes per second
    assert out.stat().st_size == 48000


def test_generate_silence_pcm_two_seconds(tmp_path):
    out = tmp_path / "silence.pcm"
    tts_split._generate_silence_pcm(str(out), duration_sec=2)
    assert out.stat().st_size == 96000


def test_generate_silence_pcm_zero_duration(tmp_path):
    out = tmp_path / "silence.pcm"
    tts_split._generate_silence_pcm(str(out), duration_sec=0)
    assert out.exists()
    assert out.stat().st_size == 0


def test_generate_silence_pcm_content_is_zeros(tmp_path):
    out = tmp_path / "silence.pcm"
    tts_split._generate_silence_pcm(str(out), duration_sec=1)
    data = out.read_bytes()
    assert all(b == 0 for b in data)


def test_generate_chunk_pcm_gemini_success(tmp_path, monkeypatch):
    """Success path: writes PCM, returns dict with usage."""
    out = tmp_path / "chunk.pcm"

    def fake_synth(text, voice_id, rate="+0%", output_path=None, **kw):
        with open(output_path, "wb") as f:
            f.write(b"\x01\x02" * 1000)
        return {
            "bytes_written": 2000,
            "input_tokens": 10,
            "output_tokens": 25,
            "model_key": "flash25",
        }

    monkeypatch.setattr("gemini_tts.synthesize", fake_synth)
    result = tts_split.generate_chunk_pcm_gemini(
        "Ciao mondo, oggi il cielo e' sereno e faremo una lunga passeggiata.",
        "gemini:flash25:Zephyr", str(out)
    )
    assert result is not False
    assert isinstance(result, dict)
    assert result["input_tokens"] == 10
    assert result["output_tokens"] == 25
    assert result["model_key"] == "flash25"
    assert out.exists()
    assert out.stat().st_size == 2000


def test_generate_chunk_pcm_gemini_retries_then_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    def flaky_synth(text, voice_id, rate="+0%", output_path=None, **kw):
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 100)
        return {"bytes_written": 100, "input_tokens": 1, "output_tokens": 2, "model_key": "flash25"}

    monkeypatch.setattr("gemini_tts.synthesize", flaky_synth)
    monkeypatch.setattr("time.sleep", lambda s: None)  # no real backoff in tests
    out = tmp_path / "chunk.pcm"
    result = tts_split.generate_chunk_pcm_gemini(
        "Il mattino dopo la nave lascio' il porto con il vento a favore.",
        "gemini:flash25:Zephyr", str(out), max_retries=3
    )
    assert result is not False
    assert calls["n"] == 3


def test_generate_chunk_pcm_gemini_total_failure_writes_silence(tmp_path, monkeypatch):
    def always_fail(*a, **kw):
        raise RuntimeError("permanent")

    monkeypatch.setattr("gemini_tts.synthesize", always_fail)
    monkeypatch.setattr("time.sleep", lambda s: None)
    out = tmp_path / "chunk.pcm"
    result = tts_split.generate_chunk_pcm_gemini(
        "Questo capitolo racconta un lungo viaggio attraverso montagne innevate.",
        "gemini:flash25:Zephyr", str(out), max_retries=2
    )
    assert result is False
    assert out.exists()
    assert out.stat().st_size == 48000  # 1 second of silence


def test_generate_chunk_pcm_gemini_empty_text(tmp_path):
    """Empty/blank text writes silence and returns False (no API call)."""
    out = tmp_path / "chunk.pcm"
    result = tts_split.generate_chunk_pcm_gemini(
        "   ", "gemini:flash25:Zephyr", str(out)
    )
    assert result is False
    assert out.exists()
    assert out.stat().st_size == 48000


def test_pick_chunk_max_chars_edge_voice():
    assert tts_split._pick_chunk_max_chars("it-IT-IsabellaNeural", "it") == 2000


def test_pick_chunk_max_chars_google_voice():
    assert tts_split._pick_chunk_max_chars("gcloud:it-IT-Chirp3-HD-Charon", "it") == 2000


# Gemini: limite caratteri/chunk delegato a gemini_tts.get_max_chunk_chars(lang),
# default 700 char per stabilità acustica (indipendente dalla lingua salvo override
# env). Edge/Google restano a 2000. Cfr. tts_split._pick_chunk_max_chars.
def test_pick_chunk_max_chars_gemini_italian():
    import gemini_tts
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "it") == gemini_tts.get_max_chunk_chars("it")


def test_pick_chunk_max_chars_gemini_chinese():
    import gemini_tts
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "zh") == gemini_tts.get_max_chunk_chars("zh")


def test_pick_chunk_max_chars_gemini_japanese():
    import gemini_tts
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "ja") == gemini_tts.get_max_chunk_chars("ja")


def test_pick_chunk_max_chars_gemini_hindi():
    import gemini_tts
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "hi") == gemini_tts.get_max_chunk_chars("hi")


def test_pick_chunk_max_chars_gemini_arabic():
    import gemini_tts
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "ar") == gemini_tts.get_max_chunk_chars("ar")


def test_pick_chunk_max_chars_gemini_default_700():
    # Default per Gemini: 700 char (stabilità acustica), salvo override env.
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "xx") == 700


class _FakeCh:
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text


class _FakeInfo:
    def __init__(self, chapters):
        self.chapters = chapters


def test_plan_chunks_respects_max_chars_param():
    long_text = ". ".join([f"Frase numero {i}" for i in range(200)]) + "."
    info = _FakeInfo([_FakeCh(0, "Cap 1", long_text)])
    plan_2000 = tts_split._plan_chunks(info, max_chars=2000)
    plan_500 = tts_split._plan_chunks(info, max_chars=500)
    # Smaller limit => more chunks.
    assert len(plan_500) > len(plan_2000)
    for block in plan_500:
        assert block["chars"] <= 500 + 50  # tolerance for full-sentence fit


def test_plan_chunks_default_is_2000():
    long_text = ". ".join([f"Frase numero {i}" for i in range(100)]) + "."
    info = _FakeInfo([_FakeCh(0, "Cap 1", long_text)])
    plan_default = tts_split._plan_chunks(info)
    plan_explicit = tts_split._plan_chunks(info, max_chars=2000)
    assert len(plan_default) == len(plan_explicit)
