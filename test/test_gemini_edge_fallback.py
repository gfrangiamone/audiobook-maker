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

    def _fake_edge(text, fallback_lang, rate, output_path, gender=None, accent_code=None):
        calls["text"] = text
        calls["lang"] = fallback_lang
        calls["gender"] = gender
        calls["accent_code"] = accent_code
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
        "Texto sensible que el sistema rechaza por completo.",
        "gemini:flash31:Enceladus", out,
        failure_info=fi, fallback_lang="es", rate="-10%")

    assert isinstance(result, dict)
    assert result.get("fallback_engine") == "edge"
    assert fi.get("fallback_engine") == "edge"
    assert calls["lang"] == "es"
    # Enceladus e' una voce Gemini maschile: il fallback deve saperlo per
    # scegliere una voce edge maschile (coerenza di genere).
    assert calls["gender"] == "Male"
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
        "Este es un texto que el sistema rechaza sin exito.",
        "gemini:flash31:Enceladus", out, failure_info=fi, fallback_lang=None)

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
        "Este es un texto que el sistema rechaza sin exito.",
        "gemini:flash31:Enceladus", out, failure_info=fi, fallback_lang="es")

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
            "Este es un texto que el sistema rechaza sin exito.",
            "gemini:flash31:Enceladus", out, fallback_lang="es")


def test_edge_voice_map_defaults_to_english():
    assert tts_split._EDGE_FALLBACK_VOICES["es"] == "es-ES-ElviraNeural"
    assert tts_split._EDGE_FALLBACK_DEFAULT == "en-US-AriaNeural"


# --- v3.xx: coerenza di genere + accento nell'edge-fallback -------------------

def test_pick_edge_fallback_gender_and_accent_en_gb_male():
    # Incidente lSuRCN...: voce Gemini maschile en-GB (Algenib) rifiutata ->
    # il fallback DEVE essere una voce edge maschile con accento British.
    v = tts_split._pick_edge_fallback_voice("en", gender="Male", accent_code="gb")
    assert v == "en-GB-RyanNeural"


def test_pick_edge_fallback_female_en_gb():
    v = tts_split._pick_edge_fallback_voice("en", gender="Female", accent_code="gb")
    assert v == "en-GB-SoniaNeural"


def test_pick_edge_fallback_male_us_default_accent():
    # en senza accento -> default US, ma il genere maschile va rispettato
    # (prima del fix restituiva sempre Aria femminile).
    v = tts_split._pick_edge_fallback_voice("en", gender="Male", accent_code="us")
    assert v == "en-US-GuyNeural"


def test_pick_edge_fallback_unknown_gender_stays_female():
    # Genere ignoto -> comportamento storico (voce femminile), nessun crash.
    v = tts_split._pick_edge_fallback_voice("en", gender=None, accent_code=None)
    assert v == "en-US-AriaNeural"


def test_pick_edge_fallback_accent_falls_back_to_lang_gender():
    # Accento non mappato per la lingua -> almeno il genere resta coerente.
    v = tts_split._pick_edge_fallback_voice("de", gender="Male", accent_code="zz")
    assert v == "de-DE-ConradNeural"


def test_pick_edge_fallback_mono_variant_language_gender():
    # Lingua senza varianti d'accento (it): coerenza di solo genere.
    assert tts_split._pick_edge_fallback_voice("it", gender="Male") == "it-IT-DiegoNeural"
    assert tts_split._pick_edge_fallback_voice("it", gender="Female") == "it-IT-ElsaNeural"


def test_pick_edge_fallback_latam_spanish_male():
    v = tts_split._pick_edge_fallback_voice("es", gender="Male", accent_code="419")
    assert v == "es-MX-JorgeNeural"


def test_generate_chunk_passes_gender_from_voice_id(tmp_path, monkeypatch):
    # generate_chunk_pcm_gemini deve estrarre il genere dal voice_id (Algenib =
    # Male) e propagarlo, insieme all'accent_code, al fallback edge.
    monkeypatch.setattr(gemini_tts, "synthesize", _boom)
    calls = {}

    def _fake_edge(text, fallback_lang, rate, output_path, gender=None, accent_code=None):
        calls["gender"] = gender
        calls["accent_code"] = accent_code
        with open(output_path, "wb") as f:
            f.write(b"\x00\x01" * 100)
        return {"success": True, "bytes_written": 200, "fallback_engine": "edge",
                "input_tokens": 0, "output_tokens": 0, "model_key": None,
                "voice_name": "en-GB-RyanNeural"}

    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", _fake_edge)
    out = str(tmp_path / "chunk.pcm")
    result = tts_split.generate_chunk_pcm_gemini(
        "This is a longer piece of sensitive text for testing.",
        "gemini:flash31:Algenib", out,
        fallback_lang="en", accent_code="gb", rate="+10%")

    assert isinstance(result, dict)
    assert calls["gender"] == "Male"
    assert calls["accent_code"] == "gb"
