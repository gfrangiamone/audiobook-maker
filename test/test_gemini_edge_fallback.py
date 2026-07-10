"""Fix #1 (v3.35.0): quando Gemini rifiuta un chunk in modo definitivo, invece
di scrivere silenzio si tenta una voce edge-tts standard per la lingua di
lettura. Incidente kd8XQj6WWdrZJt1_z0VMPQ (5 chunk silenziati su libro es per
safety filter). Qui si testa il dispatch del fallback, non la sintesi reale
(edge-tts + ffmpeg sono mockati)."""
import os
import gemini_tts
import tts_split


def _boom(*a, **k):
    raise RuntimeError("simulated gemini definitive failure (SAFETY)")


def test_fallback_used_when_gemini_fails_and_lang_known(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts, "synthesize", _boom)

    calls = {}

    def _fake_edge(text, fallback_lang, rate, output_path):
        calls["text"] = text
        calls["lang"] = fallback_lang
        # simula il PCM scritto dalla voce edge
        with open(output_path, "wb") as f:
            f.write(b"\x00\x01" * 100)
        return {"success": True, "bytes_written": 200, "input_tokens": 0,
                "output_tokens": 0, "model_key": None, "voice_name": "es-ES-ElviraNeural",
                "fallback_engine": "edge"}

    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", _fake_edge)

    out = str(tmp_path / "chunk.pcm")
    fi = {}
    result = tts_split.generate_chunk_pcm_gemini(
        "Texto sensible que Gemini rechaza.", "gemini:flash31:Enceladus", out,
        failure_info=fi, fallback_lang="es", rate="-10%")

    assert isinstance(result, dict)
    assert result.get("fallback_engine") == "edge"
    assert fi.get("fallback_engine") == "edge"
    assert calls["lang"] == "es"
    # il file contiene il PCM edge, non il silenzio (tutti zero)
    assert os.path.getsize(out) == 200
    with open(out, "rb") as f:
        assert f.read() != b"\x00" * 200


def test_silence_when_no_fallback_lang(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts, "synthesize", _boom)
    # _edge_fallback_to_pcm non deve nemmeno essere chiamato senza lingua
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no lang -> no edge")))

    out = str(tmp_path / "chunk.pcm")
    fi = {}
    result = tts_split.generate_chunk_pcm_gemini(
        "Texto.", "gemini:flash31:Enceladus", out, failure_info=fi, fallback_lang=None)

    assert result is False
    assert fi.get("reason") == "synthesize_failed"
    # silenzio: file di soli zero
    with open(out, "rb") as f:
        data = f.read()
    assert data and set(data) == {0}


def test_silence_when_edge_fallback_also_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts, "synthesize", _boom)
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", lambda *a, **k: False)

    out = str(tmp_path / "chunk.pcm")
    fi = {}
    result = tts_split.generate_chunk_pcm_gemini(
        "Texto.", "gemini:flash31:Enceladus", out, failure_info=fi, fallback_lang="es")

    assert result is False
    assert fi.get("reason") == "synthesize_failed"
    with open(out, "rb") as f:
        assert set(f.read()) == {0}


def test_quota_error_not_edge_fallbacked(tmp_path, monkeypatch):
    # Quota/budget/kill-switch restano job-fatal: NON devono cadere su edge.
    def _quota(*a, **k):
        raise gemini_tts.GeminiQuotaExhausted("quota")

    monkeypatch.setattr(gemini_tts, "synthesize", _quota)
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("quota must not edge-fallback")))

    out = str(tmp_path / "chunk.pcm")
    import pytest
    with pytest.raises(gemini_tts.GeminiQuotaExhausted):
        tts_split.generate_chunk_pcm_gemini(
            "Texto.", "gemini:flash31:Enceladus", out, fallback_lang="es")


def test_edge_voice_map_defaults_to_english():
    assert tts_split._EDGE_FALLBACK_VOICES["es"] == "es-ES-ElviraNeural"
    assert tts_split._EDGE_FALLBACK_DEFAULT == "en-US-AriaNeural"
