import shutil

import pytest

import generation_engine


def test_engine_for_speechify_voice():
    assert generation_engine._engine_for_voice("speechify:simba-3.2:harper_32") == "speechify"


def test_engine_for_gemini_still_gemini():
    assert generation_engine._engine_for_voice("gemini:flash25:Zephyr") == "gemini"


def test_engine_for_edge_default():
    assert generation_engine._engine_for_voice("en-US-GuyNeural") == "edge"


# ---------------------------------------------------------------------------
# run_generation integration smoke (Task 9): pool per-job + assemblaggio PCM
# ---------------------------------------------------------------------------

ffmpeg_missing = shutil.which("ffmpeg") is None


def _make_speechify_job(ge, tmp_path, monkeypatch, text="Hello world."):
    """Harness minimale per run_generation su voce Speechify, ricalcato sul
    pattern usato da test_pending_failed_on_refund.py / test_generation_engine_accumulation.py:
    registra un job in ge._jobs, punta ge._upload_dir su una dir isolata, e
    costruisce un _SimpleBookInfo a 1 capitolo (real _plan_chunks path).
    """
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(ge, "_upload_dir", upload_dir)

    info = ge._SimpleBookInfo("Test Book", "Test Author", text)

    job_id = "spx_smoke_1"
    job = {
        "gen_epoch": 0,
        "info": info,
        "status": "queued",
        "last_poll": 9e18,
        "email_registered": True,
    }
    jobs = {job_id: job}
    monkeypatch.setattr(ge, "_jobs", jobs)
    monkeypatch.setattr(ge, "_jobs_lock", None, raising=False)
    # Cover fallback (Pillow-dependent) fuori scope per lo smoke: rendila no-op.
    monkeypatch.setattr(ge, "_prepare_m4b_cover_path", lambda *a, **kw: None)

    return job_id, info


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_run_generation_speechify_smoke(monkeypatch, tmp_path):
    """Smoke: run_generation con voce speechify sintetizza tutti i chunk via
    generate_chunk_pcm_speechify (mockata) e assembla un output PCM->MP3 senza
    toccare l'API reale."""
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    import generation_engine as ge
    import speechify_tts
    speechify_tts._reset_gate_for_test()

    synth_calls = []

    def _fake_chunk(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        synth_calls.append({"text": text, "emotion": emotion})
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00" * 4800)  # 0.1s @ 48kHz mono 16-bit
        return {"success": True, "bytes_written": 9600, "sample_rate": 48000,
                "channels": 1, "billable_chars": len(text), "voice_name": "harper_32"}

    monkeypatch.setattr(ge, "generate_chunk_pcm_speechify", _fake_chunk, raising=False)

    # Job minimale + info a 1 capitolo.
    job_id, info = _make_speechify_job(ge, tmp_path, monkeypatch,
                                       text="Hello world. Second sentence.")
    ge.run_generation(job_id, info, "speechify:simba-3.2:harper_32", "+0%",
                      single_file=True, output_format="mp3",
                      speechify_emotion="cheerful")

    job = ge._jobs.get(job_id)
    assert job["status"] in ("done", "completed")
    assert len(synth_calls) >= 1
    assert all(c["emotion"] == "cheerful" for c in synth_calls)
    # Sample rate reale (48kHz) propagato sul job dalla pre-sintesi.
    assert job.get("speechify_sample_rate") == 48000
