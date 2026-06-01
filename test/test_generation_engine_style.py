import inspect
import generation_engine
import tts_split


def test_tts_split_chunk_gemini_accepts_style_instruction():
    sig = inspect.signature(tts_split.generate_chunk_pcm_gemini)
    assert "style_instruction" in sig.parameters
    assert sig.parameters["style_instruction"].default is None


def test_run_generation_accepts_gemini_style_instruction():
    sig = inspect.signature(generation_engine.run_generation)
    assert "gemini_style_instruction" in sig.parameters


def test_chunk_gemini_passes_style_to_synthesize(monkeypatch, tmp_path):
    captured = {}
    def fake_synthesize(text, voice_id, *, output_path, style_instruction=None, **kw):
        captured["style_instruction"] = style_instruction
        captured["text"] = text
        # Write a minimal valid PCM
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        return {
            "success": True, "bytes_written": 1000,
            "input_tokens": 10, "output_tokens": 50,
            "model_key": "flash25", "voice_name": "Zephyr", "attempts_used": 1,
        }
    import gemini_tts
    monkeypatch.setattr(gemini_tts, "synthesize", fake_synthesize)
    out = tmp_path / "x.pcm"
    res = tts_split.generate_chunk_pcm_gemini(
        "Ciao mondo", "gemini:flash25:Zephyr", str(out),
        style_instruction="vivace e narrativo",
    )
    assert res is not False
    assert captured["style_instruction"] == "vivace e narrativo"


def test_chunk_gemini_default_style_is_none(monkeypatch, tmp_path):
    captured = {}
    def fake_synthesize(text, voice_id, *, output_path, style_instruction=None, **kw):
        captured["style_instruction"] = style_instruction
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 100)
        return {"success": True, "bytes_written": 100, "input_tokens": 1,
                "output_tokens": 1, "model_key": "flash25", "voice_name": "Zephyr", "attempts_used": 1}
    import gemini_tts
    monkeypatch.setattr(gemini_tts, "synthesize", fake_synthesize)
    out = tmp_path / "x.pcm"
    tts_split.generate_chunk_pcm_gemini("Test", "gemini:flash25:Zephyr", str(out))
    assert captured["style_instruction"] is None


def test_run_generation_applies_style_to_every_chunk(monkeypatch, tmp_path):
    """End-to-end (mocked): 2 chapters x 3 chunks each = 6 calls.
    Expect style="calmo" su tutti i chunk -- limitarlo al primo chunk di ogni
    capitolo faceva percepire all'utente uno stile incoerente tra preview
    (sempre con stile) e job finale (stile solo nel ~5% dell'audio)."""
    # Capture calls to generate_chunk_pcm_gemini through patch
    captured_calls = []
    def fake_chunk_gemini(text, voice_id, output_path, max_retries=3, style_instruction=None,
                          debug_prompt_path=None, rate="+0%", **kwargs):
        captured_calls.append({
            "text": text, "style_instruction": style_instruction, "voice_id": voice_id,
        })
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        return {
            "success": True, "bytes_written": 1000,
            "input_tokens": 1, "output_tokens": 1,
            "model_key": "flash25", "voice_name": "Zephyr", "attempts_used": 1,
        }
    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_gemini", fake_chunk_gemini)

    # Build a minimal plan: 2 chapters, 3 chunks each
    plan = []
    for ch_idx in range(2):
        for c_idx in range(3):
            plan.append({
                "chapter_index": ch_idx + 1,
                "chapter_title": f"Cap {ch_idx + 1}",
                "chunk_index": c_idx,
                "chunks_in_chapter": 3,
                "text": f"Cap{ch_idx+1}-Chunk{c_idx}",
                "chars": 20,
            })
    monkeypatch.setattr(generation_engine, "_plan_chunks", lambda info, max_chars, max_bytes=None: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "gemini")
    monkeypatch.setattr(generation_engine, "_generate_silence_pcm", lambda p, s=1: open(p, "wb").write(b"\x00"))

    # Avoid heavy post-processing (mp3 encoding etc.)
    monkeypatch.setattr(generation_engine, "pcm_to_mp3", lambda parts, out, **kw: open(out, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_aac_m4b", lambda *a, **k: True)
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)
    monkeypatch.setattr(generation_engine, "pcm_size_to_seconds", lambda b: 1.0)
    monkeypatch.setattr(generation_engine, "_prepare_m4b_cover_path", lambda *a, **k: None)

    # Build a fake info + job
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
    # Module-level _jobs_lock is only assigned in configure(); set it here
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)
    # Avoid gemini_tts.record_usage trying real work if module is None vs not None
    monkeypatch.setattr(generation_engine, "gemini_tts", None, raising=False)

    try:
        generation_engine.run_generation("j1", _Info(), "gemini:flash25:Zephyr", "+0%",
                                         single_file=True, output_format="mp3",
                                         gemini_style_instruction="calmo")
    except Exception:
        pass  # OK if final mp3 assembly fails — we only care about TTS calls

    # Verify: lo stile deve essere applicato a TUTTI i 6 chunk.
    styles = [c["style_instruction"] for c in captured_calls]
    assert len(captured_calls) == 6, f"expected 6 calls, got {len(captured_calls)}"
    assert all(s == "calmo" for s in styles), f"style non applicato a tutti i chunk: {styles}"


def test_run_generation_multi_file_branch_also_applies_style_to_every_chunk(monkeypatch, tmp_path):
    """Stesso comportamento atteso nel branch single_file=False (multi-file)."""
    captured_calls = []
    def fake_chunk_gemini(text, voice_id, output_path, max_retries=3, style_instruction=None,
                          debug_prompt_path=None, rate="+0%", **kwargs):
        captured_calls.append({"style_instruction": style_instruction})
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        return {
            "success": True, "bytes_written": 1000,
            "input_tokens": 1, "output_tokens": 1,
            "model_key": "flash25", "voice_name": "Zephyr", "attempts_used": 1,
        }
    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_gemini", fake_chunk_gemini)

    plan = []
    for ch_idx in range(2):
        for c_idx in range(3):
            plan.append({
                "chapter_index": ch_idx + 1,
                "chapter_title": f"Cap {ch_idx + 1}",
                "chunk_index": c_idx,
                "chunks_in_chapter": 3,
                "text": f"Cap{ch_idx+1}-Chunk{c_idx}",
                "chars": 20,
            })
    monkeypatch.setattr(generation_engine, "_plan_chunks", lambda info, max_chars, max_bytes=None: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "gemini")
    monkeypatch.setattr(generation_engine, "_generate_silence_pcm", lambda p, s=1: open(p, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_mp3", lambda parts, out, **kw: open(out, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)
    monkeypatch.setattr(generation_engine, "pcm_size_to_seconds", lambda b: 1.0)

    class _Ch:
        def __init__(self, title, index):
            self.title = title
            self.text = "..."
            self.index = index
    class _Info:
        title = "T"
        author = "A"
        language = "it"
        chapters = [_Ch("Cap 1", 1), _Ch("Cap 2", 2)]
    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True}
    monkeypatch.setattr(generation_engine, "_jobs", {"j2": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)
    monkeypatch.setattr(generation_engine, "gemini_tts", None, raising=False)

    try:
        generation_engine.run_generation("j2", _Info(), "gemini:flash25:Zephyr", "+0%",
                                         single_file=False, output_format="zip",
                                         gemini_style_instruction="vivace")
    except Exception:
        pass  # OK if zip assembly fails — only TTS calls matter

    styles = [c["style_instruction"] for c in captured_calls]
    assert len(captured_calls) == 6, f"expected 6 calls, got {len(captured_calls)}"
    assert all(s == "vivace" for s in styles), f"style non applicato a tutti i chunk: {styles}"
