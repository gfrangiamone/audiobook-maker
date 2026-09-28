"""Fix #1 (v3.35.0): quando Gemini rifiuta un chunk in modo definitivo, invece
di scrivere silenzio si tenta una voce edge-tts standard per la lingua di
lettura. Incidente kd8XQj6WWdrZJt1_z0VMPQ (5 chunk silenziati su libro es per
safety filter). Qui si testa il dispatch del fallback, non la sintesi reale
(edge-tts + ffmpeg sono mockati)."""
import os
import pytest
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
        "Texto sensible que Gemini rechaza.", "gemini:flash31:Enceladus", out,
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
        "Sensitive text.", "gemini:flash31:Algenib", out,
        fallback_lang="en", accent_code="gb", rate="+10%")

    assert isinstance(result, dict)
    assert calls["gender"] == "Male"
    assert calls["accent_code"] == "gb"



# --- flash38: ripiego sullo stesso nome voce di flash31, poi edge-tts ---

def _no_edge(*a, **k):
    raise AssertionError("edge non doveva essere chiamato")


def _fake_edge_ok(text, fallback_lang, rate, output_path, gender=None, accent_code=None):
    with open(output_path, "wb") as f:
        f.write(b"\x00\x01" * 100)
    return {"success": True, "bytes_written": 200, "fallback_engine": "edge"}


def _fallback_ready(monkeypatch, ok=True):
    """flash31 risolto e disponibile; synthesize fallisce su flash38 e, se
    ok, riesce su flash31. Ritorna la lista delle voci chiamate."""
    calls = []

    def _synth(text, voice_id, output_path="x.pcm", **kw):
        calls.append((voice_id, kw.get("debug_prompt_path")))
        if voice_id.startswith("gemini:flash38:") or not ok:
            raise RuntimeError("Gemini TTS failed after 3 attempts: no audio parts")
        with open(output_path, "wb") as f:
            f.write(b"\x01\x00" * 50)
        return {"success": True, "bytes_written": 100, "input_tokens": 7,
                "output_tokens": 30, "model_key": "flash31", "backend": "vertex",
                "tokens_measured": True}

    monkeypatch.setattr(gemini_tts, "synthesize", _synth)
    monkeypatch.setattr(gemini_tts, "_resolve_backend", lambda mk=None: "vertex")
    monkeypatch.setattr(gemini_tts, "model_unavailable", lambda mk: False)
    return calls


def test_flash38_retry_esauriti_ripiega_su_flash31_stessa_voce(tmp_path, monkeypatch):
    calls = _fallback_ready(monkeypatch)
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", _no_edge)
    fi = {}
    result = tts_split.generate_chunk_pcm_gemini(
        "Testo di prova.", "gemini:flash38:Zephyr", str(tmp_path / "c.pcm"),
        failure_info=fi, fallback_lang="it",
        debug_prompt_path=str(tmp_path / "prompt5.txt"))
    assert [c[0] for c in calls] == ["gemini:flash38:Zephyr", "gemini:flash31:Zephyr"]
    assert calls[1][1].endswith("prompt5.fallback.txt")
    assert result["fallback_model"] == "flash31"
    assert result["model_key"] == "flash31"  # contabilizzato sul ripiego
    assert fi["fallback_engine"] == "gemini:flash31"
    assert fi["reason"] == "gemini_failed_model_fallback"


def test_flash38_ripiego_fallito_passa_a_edge(tmp_path, monkeypatch):
    calls = _fallback_ready(monkeypatch, ok=False)
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", _fake_edge_ok)
    fi = {}
    result = tts_split.generate_chunk_pcm_gemini(
        "Testo di prova.", "gemini:flash38:Zephyr", str(tmp_path / "c.pcm"),
        failure_info=fi, fallback_lang="it")
    assert [c[0] for c in calls] == ["gemini:flash38:Zephyr", "gemini:flash31:Zephyr"]
    assert result["fallback_engine"] == "edge"
    assert fi["fallback_engine"] == "edge"


def test_flash38_ripiego_errore_quota_non_sospende_il_job(tmp_path, monkeypatch):
    def _synth(text, voice_id, output_path="x.pcm", **kw):
        if voice_id.startswith("gemini:flash38:"):
            raise RuntimeError("Gemini TTS failed after 3 attempts: 503")
        raise gemini_tts.GeminiQuotaExhausted("flash31 rpd", reason="rpd")

    monkeypatch.setattr(gemini_tts, "synthesize", _synth)
    monkeypatch.setattr(gemini_tts, "_resolve_backend", lambda mk=None: "vertex")
    monkeypatch.setattr(gemini_tts, "model_unavailable", lambda mk: False)
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", _fake_edge_ok)
    result = tts_split.generate_chunk_pcm_gemini(
        "Testo di prova.", "gemini:flash38:Zephyr", str(tmp_path / "c.pcm"),
        failure_info={}, fallback_lang="it")
    assert result["fallback_engine"] == "edge"


def test_flash38_senza_ripiego_disponibile_va_diretto_a_edge(tmp_path, monkeypatch):
    calls = _fallback_ready(monkeypatch)
    monkeypatch.setattr(gemini_tts, "model_unavailable", lambda mk: mk == "flash31")
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", _fake_edge_ok)
    result = tts_split.generate_chunk_pcm_gemini(
        "Testo di prova.", "gemini:flash38:Zephyr", str(tmp_path / "c.pcm"),
        failure_info={}, fallback_lang="it")
    assert [c[0] for c in calls] == ["gemini:flash38:Zephyr"]
    assert result["fallback_engine"] == "edge"


def test_flash38_tutto_fallito_chunk_fallito_non_job_fatale(tmp_path, monkeypatch):
    _fallback_ready(monkeypatch, ok=False)
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", lambda *a, **k: False)
    fi = {}
    result = tts_split.generate_chunk_pcm_gemini(
        "Testo di prova.", "gemini:flash38:Zephyr", str(tmp_path / "c.pcm"),
        failure_info=fi, fallback_lang="it")
    assert result is False
    assert fi["reason"] == "synthesize_failed"


def test_flash38_errore_fatale_resta_job_fatale(tmp_path, monkeypatch):
    def _fatal(*a, **k):
        raise gemini_tts.GeminiUnavailable("billing: credito esaurito")

    monkeypatch.setattr(gemini_tts, "synthesize", _fatal)
    monkeypatch.setattr(tts_split, "_edge_fallback_to_pcm", _no_edge)
    with pytest.raises(gemini_tts.GeminiUnavailable):
        tts_split.generate_chunk_pcm_gemini(
            "Testo di prova.", "gemini:flash38:Zephyr", str(tmp_path / "c.pcm"),
            failure_info={}, fallback_lang="it")


def test_flash38_byte_split_rifatto_intero_su_flash31(tmp_path, monkeypatch):
    calls = _fallback_ready(monkeypatch)
    agg_calls = []
    real = tts_split._synthesize_pcm_pieces_and_concat

    def _spy(pieces, voice_id, *a, **k):
        agg_calls.append(voice_id)
        return real(pieces, voice_id, *a, **k)

    monkeypatch.setattr(tts_split, "_synthesize_pcm_pieces_and_concat", _spy)
    monkeypatch.setattr(tts_split, "_pick_chunk_max_bytes", lambda v: 40)
    fi = {}
    result = tts_split.generate_chunk_pcm_gemini(
        "Prima frase di prova. Seconda frase di prova. Terza frase.",
        "gemini:flash38:Zephyr", str(tmp_path / "c.pcm"), failure_info=fi)
    assert agg_calls == ["gemini:flash38:Zephyr", "gemini:flash31:Zephyr"]
    assert result["fallback_model"] == "flash31"
    assert result["model_key"] == "flash31"
    assert fi["fallback_engine"] == "gemini:flash31"
    assert all(v.startswith("gemini:flash31:") for v, _ in calls[1:])


def test_flash31_byte_split_retry_esauriti_resta_chunk_fallito(tmp_path, monkeypatch):
    def _exhausted(*a, **k):
        raise RuntimeError("Gemini TTS failed after 3 attempts: timeout")

    monkeypatch.setattr(gemini_tts, "synthesize", _exhausted)
    assert tts_split._synthesize_pcm_pieces_and_concat(
        ["Prima parte.", "Seconda parte."], "gemini:flash31:Zephyr",
        str(tmp_path / "c.pcm"), None, 1) is False
