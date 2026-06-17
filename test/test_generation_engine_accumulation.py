import generation_engine
import gemini_tts


def test_run_generation_accumulates_gemini_actuals(monkeypatch, tmp_path):
    """2 chapters x 3 chunks; each fake synth returns 100 in_tok, 500 out_tok, 1000 bytes.
    Expect job['gemini_actual'] sums to: in=600, out=3000, chars=sum(len(text)), audio=6*1000/(24000*2)."""
    def fake_chunk_gemini(text, voice_id, output_path, max_retries=3, style_instruction=None,
                          debug_prompt_path=None, rate="+0%", **kwargs):
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        return {
            "success": True, "bytes_written": 1000,
            "input_tokens": 100, "output_tokens": 500,
            "model_key": "flash25", "voice_name": "Zephyr", "attempts_used": 1,
        }
    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_gemini", fake_chunk_gemini)

    # google_cost_breakdown fake — 0.001 € per 1k input + 0.005 € per 1k output
    def fake_breakdown(in_t, out_t, model_key):
        return {"total_eur": (in_t / 1000.0) * 0.001 + (out_t / 1000.0) * 0.005}
    monkeypatch.setattr(generation_engine.gemini_tts, "google_cost_breakdown", fake_breakdown, raising=False)

    plan = []
    for ch_idx in range(2):
        for c_idx in range(3):
            plan.append({
                "chapter_index": ch_idx + 1,
                "chapter_title": f"Cap {ch_idx + 1}",
                "chunk_index": c_idx,
                "chunks_in_chapter": 3,
                "text": "Hello world",  # 11 chars each
                "chars": 11,
            })
    monkeypatch.setattr(generation_engine, "_plan_chunks", lambda info, max_chars, max_bytes=None: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "gemini")
    monkeypatch.setattr(generation_engine, "_generate_silence_pcm", lambda p, s=1: open(p, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_mp3", lambda parts, out, **kw: open(out, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_aac_m4b", lambda *a, **k: True)
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)
    monkeypatch.setattr(generation_engine, "pcm_size_to_seconds", lambda b: 1.0)
    monkeypatch.setattr(generation_engine, "_prepare_m4b_cover_path", lambda *a, **k: None)

    class _Info:
        title = "T"
        author = "A"
        language = "it"
        chapters = [type("C", (), {"title": "Cap 1", "text": "..."})(),
                    type("C", (), {"title": "Cap 2", "text": "..."})()]
    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True}
    monkeypatch.setattr(generation_engine, "_jobs", {"j1": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)

    try:
        generation_engine.run_generation("j1", _Info(), "gemini:flash25:Zephyr", "+0%",
                                         single_file=True, output_format="mp3")
    except Exception:
        pass

    ga = job["gemini_actual"]
    assert ga["input_tokens"] == 600
    assert ga["output_tokens"] == 3000
    assert ga["chars"] == 6 * len("Hello world")
    expected_audio = 6 * 1000 / (24000.0 * 2)
    assert abs(ga["audio_seconds"] - expected_audio) < 1e-6
    # google cost = 6 * ((100/1000)*0.001 + (500/1000)*0.005) = 6 * (0.0001 + 0.0025) = 0.0156
    assert abs(ga["google_cost_eur"] - 6 * (0.0001 + 0.0025)) < 1e-6
    assert ga["model_key"] == "flash25"


def test_run_generation_accumulates_gemini_actuals_multifile(monkeypatch, tmp_path):
    """Stessa contabilita' del test single-file ma sul ramo MULTI-FILE
    (single_file=False, output_format='zip'). Caratterizza l'accumulo Gemini
    del secondo ramo di run_generation, cosi' l'estrazione di un helper di
    dispatch condiviso e' provabile come behavior-preserving su ENTRAMBI i rami.
    2 capitoli x 3 chunk, ognuno 100 in / 500 out / 1000 byte."""
    def fake_chunk_gemini(text, voice_id, output_path, max_retries=3, style_instruction=None,
                          debug_prompt_path=None, rate="+0%", **kwargs):
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        return {
            "success": True, "bytes_written": 1000,
            "input_tokens": 100, "output_tokens": 500,
            "model_key": "flash25", "voice_name": "Zephyr", "attempts_used": 1,
        }
    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_gemini", fake_chunk_gemini)

    def fake_breakdown(in_t, out_t, model_key):
        return {"total_eur": (in_t / 1000.0) * 0.001 + (out_t / 1000.0) * 0.005}
    monkeypatch.setattr(generation_engine.gemini_tts, "google_cost_breakdown", fake_breakdown, raising=False)

    plan = []
    for ch_idx in range(2):
        for c_idx in range(3):
            plan.append({
                "chapter_index": ch_idx + 1,
                "chapter_title": f"Cap {ch_idx + 1}",
                "chunk_index": c_idx,
                "chunks_in_chapter": 3,
                "text": "Hello world",
                "chars": 11,
            })
    monkeypatch.setattr(generation_engine, "_plan_chunks", lambda info, max_chars, max_bytes=None: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "gemini")
    monkeypatch.setattr(generation_engine, "_generate_silence_pcm", lambda p, s=1: open(p, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_mp3", lambda parts, out, **kw: open(out, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)
    monkeypatch.setattr(generation_engine, "pcm_size_to_seconds", lambda b: 1.0)
    monkeypatch.setattr(generation_engine, "_include_cover_in_dir", lambda *a, **k: None)

    class _Info:
        title = "T"
        author = "A"
        language = "it"
        chapters = [type("C", (), {"index": 1, "title": "Cap 1", "text": "..."})(),
                    type("C", (), {"index": 2, "title": "Cap 2", "text": "..."})()]
    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True}
    monkeypatch.setattr(generation_engine, "_jobs", {"jm": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)

    try:
        generation_engine.run_generation("jm", _Info(), "gemini:flash25:Zephyr", "+0%",
                                         single_file=False, output_format="zip")
    except Exception:
        pass

    ga = job["gemini_actual"]
    assert ga["input_tokens"] == 600
    assert ga["output_tokens"] == 3000
    assert ga["chars"] == 6 * len("Hello world")
    expected_audio = 6 * 1000 / (24000.0 * 2)
    assert abs(ga["audio_seconds"] - expected_audio) < 1e-6
    assert abs(ga["google_cost_eur"] - 6 * (0.0001 + 0.0025)) < 1e-6
    assert ga["model_key"] == "flash25"


def test_run_generation_actuals_zero_when_no_gemini(monkeypatch, tmp_path):
    """If engine is google/edge, gemini_actual stays at zeros (initialised but never accumulated)."""
    def fake_chunk_google(text, voice, rate, output_path, max_retries=3, **kwargs):
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        return {"success": True}
    monkeypatch.setattr(generation_engine, "generate_chunk_mp3_google", fake_chunk_google)

    plan = [{
        "chapter_index": 1, "chapter_title": "C", "chunk_index": 0, "chunks_in_chapter": 1,
        "text": "x", "chars": 1,
    }]
    monkeypatch.setattr(generation_engine, "_plan_chunks", lambda info, max_chars, max_bytes=None: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "google")
    monkeypatch.setattr(generation_engine, "_generate_silence_mp3", lambda p, s=1: True)
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)

    class _Info:
        title = "T"
        author = "A"
        language = "it"
        chapters = [type("C", (), {"title": "C", "text": "..."})()]
    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True}
    monkeypatch.setattr(generation_engine, "_jobs", {"j2": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)

    try:
        generation_engine.run_generation("j2", _Info(), "google:it-IT-Standard-A", "+0%",
                                         single_file=True, output_format="mp3")
    except Exception:
        pass

    ga = job.get("gemini_actual", {})
    assert ga.get("input_tokens", 0) == 0
    assert ga.get("output_tokens", 0) == 0
    assert ga.get("audio_seconds", 0.0) == 0.0
