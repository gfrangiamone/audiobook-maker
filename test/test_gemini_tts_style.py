import inspect
import gemini_tts


def test_synthesize_has_style_instruction_param():
    sig = inspect.signature(gemini_tts.synthesize)
    assert "style_instruction" in sig.parameters
    assert sig.parameters["style_instruction"].default is None


def _make_fake_client(captured):
    class _FakeModels:
        @staticmethod
        def generate_content(*, model, contents, config):
            captured["contents"] = contents
            class _Inline:
                data = b"\x00" * 200
            class _Part:
                inline_data = _Inline()
            class _Content:
                parts = [_Part()]
            class _Cand:
                content = _Content()
            class _Usage:
                prompt_token_count = 10
                candidates_token_count = 50
            class _R:
                candidates = [_Cand()]
                usage_metadata = _Usage()
            return _R()
    class _FakeClient:
        models = _FakeModels()
    return _FakeClient()


def test_style_instruction_prepended_to_text(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize(
        "Ciao mondo",
        "gemini:flash25:Zephyr",
        style_instruction="tono calmo e narrativo",
        output_path=str(out),
    )
    assert "tono calmo e narrativo" in captured["contents"]
    assert "Ciao mondo" in captured["contents"]
    assert "[style:" in captured["contents"]


def test_style_instruction_none_does_not_prepend(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize("Ciao", "gemini:flash25:Zephyr", style_instruction=None, output_path=str(out))
    assert captured["contents"] == "Ciao"


def test_style_instruction_truncated_at_300_chars(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    long_style = "a" * 500
    gemini_tts.synthesize("Testo", "gemini:flash25:Zephyr", style_instruction=long_style, output_path=str(out))
    # The style payload (between [style: and ]) must be capped at 300 chars
    assert "a" * 300 in captured["contents"]
    assert "a" * 301 not in captured["contents"]


def test_style_instruction_coexists_with_rate(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setenv("ABM_GEMINI_RATE_MODE", "prompt")
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize("Frase", "gemini:flash25:Zephyr", rate="+10%",
                          style_instruction="vivace", output_path=str(out))
    c = captured["contents"]
    # Both [fast] and [style: vivace] should be present
    assert "[fast]" in c and "[style:" in c
    assert "vivace" in c
    assert "Frase" in c


def test_style_instruction_whitespace_only_does_not_prepend(monkeypatch, tmp_path):
    """A whitespace-only style_instruction must not crash and must not add a prefix."""
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize("Solo testo", "gemini:flash25:Zephyr",
                          style_instruction="   \t  \n  ", output_path=str(out))
    assert captured["contents"] == "Solo testo"
    assert "[style:" not in captured["contents"]


def test_style_instruction_overflow_raises_value_error(monkeypatch, tmp_path):
    """If prefix + text exceeds MAX_BYTES_PER_CALL, raise ValueError."""
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    # Build text just under the cap, so prefix pushes it over
    near_cap_text = "x" * (gemini_tts.MAX_BYTES_PER_CALL - 50)
    style = "y" * 300  # 300 + "[style: ] " overhead = ~310 chars
    import pytest
    with pytest.raises(ValueError):
        gemini_tts.synthesize(near_cap_text, "gemini:flash25:Zephyr",
                              style_instruction=style, output_path="/tmp/x.pcm")
