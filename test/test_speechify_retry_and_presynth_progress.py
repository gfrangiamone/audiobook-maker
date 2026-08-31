"""Speechify: retry sugli errori di rete del chunk + progresso live in pre-sintesi.

Incidente 2026-08-31 (job 1dxCX/2Mzs): (a) durante la pre-sintesi parallela il
job restava a 0% per 35-40 minuti senza alcun aggiornamento; (b) un
`Read timed out` non veniva ritentato (max_retries=1) e il chunk PREMIUM pagato
veniva sostituito da 1 s di silenzio.
"""
import pathlib

import pytest

import generation_engine
import speechify_tts
import tts_split


# --- (b) retry sugli errori di rete -----------------------------------------

def _ok_result(text):
    return {"success": True, "bytes_written": 2, "sample_rate": 48000,
            "channels": 1, "billable_chars": len(text), "voice_name": "wyatt_32"}


def test_generate_chunk_speechify_retries_on_network_error(monkeypatch, tmp_path):
    calls = []

    def _flaky(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        calls.append(1)
        if len(calls) < 3:
            raise ConnectionError("HTTPSConnectionPool(host='api.speechify.ai'): Read timed out.")
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00")
        return _ok_result(text)

    monkeypatch.setattr("speechify_tts.synthesize", _flaky)
    monkeypatch.setattr(tts_split.time, "sleep", lambda s: None)
    out = tmp_path / "c.pcm"
    fi = {}
    res = tts_split.generate_chunk_pcm_speechify(
        "Hello world", "speechify:simba-3.2:wyatt_32", str(out), failure_info=fi)
    assert len(calls) == 3
    assert res["success"] is True
    assert fi == {}


def test_generate_chunk_speechify_silence_after_all_retries(monkeypatch, tmp_path):
    calls = []

    def _always_timeout(*a, **k):
        calls.append(1)
        raise ConnectionError("Read timed out.")

    monkeypatch.setattr("speechify_tts.synthesize", _always_timeout)
    monkeypatch.setattr(tts_split.time, "sleep", lambda s: None)
    out = tmp_path / "c.pcm"
    fi = {}
    res = tts_split.generate_chunk_pcm_speechify(
        "Hello world", "speechify:simba-3.2:wyatt_32", str(out), failure_info=fi)
    assert res is False
    assert len(calls) >= 3
    assert fi["reason"] == "synthesize_failed"
    assert out.exists()


def test_generate_chunk_speechify_no_retry_on_fatal(monkeypatch, tmp_path):
    """Un 4xx fatale (es. SSML invalido) non va ritentato: costa una chiamata
    a vuoto per tentativo e l'esito non cambia."""
    calls = []

    def _fatal(*a, **k):
        calls.append(1)
        raise speechify_tts.SpeechifyFatalError("Speechify HTTP 400 (fatal): invalid SSML")

    monkeypatch.setattr("speechify_tts.synthesize", _fatal)
    monkeypatch.setattr(tts_split.time, "sleep", lambda s: None)
    out = tmp_path / "c.pcm"
    fi = {}
    res = tts_split.generate_chunk_pcm_speechify(
        "Hello world", "speechify:simba-3.2:wyatt_32", str(out), failure_info=fi)
    assert res is False
    assert len(calls) == 1
    assert fi["reason"] == "synthesize_failed"
    assert out.exists()


def test_synthesize_fatal_raises_dedicated_error(monkeypatch, tmp_path):
    from test.test_speechify_synthesize import _Resp, _Session
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "k")
    sess = _Session([_Resp(400)])
    with pytest.raises(speechify_tts.SpeechifyFatalError):
        speechify_tts.synthesize("hi", "speechify:simba-3.2:wyatt_32",
                                 str(tmp_path / "o.pcm"), session=sess)
    assert len(sess.calls) == 1


# --- (a) progresso live durante la pre-sintesi ------------------------------

def test_presynth_updates_progress_per_chunk(monkeypatch, tmp_path):
    plan = [{"text": f"chunk {i}", "chapter_index": 1} for i in range(4)]
    job = {"progress_current": 2, "progress_total": len(plan) + 2}
    snapshots = []

    def _fake_chunk(text, voice, output_path, emotion=None, rate="+0%", failure_info=None):
        snapshots.append((job["progress_current"], job.get("progress_message", "")))
        pathlib.Path(output_path).write_bytes(b"\x00\x00")
        return _ok_result(text)

    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_speechify", _fake_chunk)
    monkeypatch.setattr(speechify_tts, "per_job_concurrency", lambda: 1)
    monkeypatch.setattr(speechify_tts, "max_concurrency", lambda: 3)

    out = generation_engine._speechify_presynth(
        job, plan, tmp_path, "speechify:simba-3.2:wyatt_32",
        emotion=None, rate="-10%", check_cancelled=lambda: False,
        start_time=0.0)

    assert sorted(out.keys()) == [0, 1, 2, 3]
    # Prima di ogni chiamata il contatore riflette i chunk gia' completati.
    assert [s[0] for s in snapshots] == [2, 3, 4, 5]
    assert job["progress_current"] == 2 + len(plan)
    assert "4/4" in snapshots[-1][1] or job["progress_message"] == "Assembling audio..."
    assert job["progress_message"] == "Assembling audio..."
    assert job["speechify_sample_rate"] == 48000
    assert job["elapsed_seconds"] >= 0


def test_presynth_propagates_cancel(monkeypatch, tmp_path):
    plan = [{"text": "a"}, {"text": "b"}]
    job = {}
    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_speechify",
                        lambda *a, **k: pytest.fail("must not synthesize after cancel"))
    monkeypatch.setattr(speechify_tts, "per_job_concurrency", lambda: 1)
    monkeypatch.setattr(speechify_tts, "max_concurrency", lambda: 3)
    with pytest.raises(generation_engine._CancelledError):
        generation_engine._speechify_presynth(
            job, plan, tmp_path, "speechify:simba-3.2:wyatt_32",
            emotion=None, rate="+0%", check_cancelled=lambda: True, start_time=0.0)
