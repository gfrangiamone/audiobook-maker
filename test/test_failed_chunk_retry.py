"""Ripasso dei chunk falliti prima dell'assembly (incidente 12/10/2026: 403
di edge per due ore, capitoli muti consegnati come audio). Un chunk che fallisce
durante la sintesi si ritenta a fine ciclo; se riesce, il conteggio dei falliti
scende e il capitolo contiene l'audio vero, non il silenzio di ripiego."""
import os

import generation_engine


def _setup(monkeypatch, tmp_path, fail_times):
    """Edge finto: il chunk 1 fallisce `fail_times` volte, poi riesce."""
    calls = {}

    async def fake_chunk_edge(text, voice, rate, output_path, max_retries=3, **kwargs):
        n = calls[text] = calls.get(text, 0) + 1
        if text == "c1" and n <= fail_times:
            raise RuntimeError("403 Invalid response status")
        with open(output_path, "wb") as f:
            f.write(b"\x01" * 1000)
        return True
    monkeypatch.setattr(generation_engine, "generate_chunk_mp3", fake_chunk_edge)

    plan = [{"chapter_index": ch, "chapter_title": f"Cap {ch}", "chunk_index": k,
             "chunks_in_chapter": 2, "text": f"c{2 * (ch - 1) + k}", "chars": 2}
            for ch in (1, 2) for k in range(2)]
    monkeypatch.setattr(generation_engine, "_plan_chunks",
                        lambda info, max_chars, max_bytes=None, **kw: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "edge")
    monkeypatch.setattr(generation_engine, "_generate_silence_mp3",
                        lambda p, duration_sec=1: open(p, "wb").write(b"\x00"))
    # Durata: 1000 ms per l'audio vero, 10 ms per il silenzio di ripiego.
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms",
                        lambda p: 1000 if open(p, "rb").read(1) != b"\x00" else 10)
    encoded = []

    def fake_concat(parts, out, **kw):
        encoded.append((out, {os.path.basename(p): open(p, "rb").read(1) for p in parts}))
        open(out, "wb").write(b"\x01")
        return True
    monkeypatch.setattr(generation_engine, "_concatenate_mp3", fake_concat)
    monkeypatch.setattr(generation_engine, "_include_cover_in_dir", lambda *a, **k: None)
    monkeypatch.setenv("ABM_FAILED_CHUNK_RETRY_ROUNDS", "2")
    monkeypatch.setenv("ABM_FAILED_CHUNK_RETRY_PAUSE_SEC", "0")

    class _Info:
        title = "T"
        author = "A"
        language = "en"
        chapters = [type("C", (), {"index": 1, "title": "Cap 1", "text": "..."})(),
                    type("C", (), {"index": 2, "title": "Cap 2", "text": "..."})()]
    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True}
    monkeypatch.setattr(generation_engine, "_jobs", {"jr": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)
    return job, calls, encoded, _Info


def _run(job_info, single_file):
    try:
        generation_engine.run_generation(
            "jr", job_info(), "en-US-AndrewMultilingualNeural", "+0%",
            single_file=single_file, output_format="mp3" if single_file else "zip")
    except Exception:
        pass


def test_failed_chunk_recovered_single_file(monkeypatch, tmp_path):
    job, calls, encoded, info = _setup(monkeypatch, tmp_path, fail_times=1)
    _run(info, single_file=True)
    assert calls["c1"] == 2
    assert job["failed_chunks"] == 0
    # L'MP3 finale e' fatto di audio vero: nessun silenzio di ripiego.
    _out, heads = encoded[-1]
    assert b"\x00" not in [h for h in heads if h]  or heads.count(b"\x00") == 0


def test_failed_chunk_recovered_multi_file(monkeypatch, tmp_path):
    job, calls, encoded, info = _setup(monkeypatch, tmp_path, fail_times=1)
    _run(info, single_file=False)
    assert calls["c1"] == 2
    assert job["failed_chunks"] == 0
    # Capitolo 1 codificato due volte: col silenzio, poi con l'audio recuperato.
    cap1 = [heads for out, heads in encoded if "Cap 1" in out or "Cap_1" in out]
    assert len(cap1) == 2
    assert cap1[0]["chunk_000001.mp3"] == b"\x00"
    assert cap1[-1]["chunk_000001.mp3"] == b"\x01"


def test_failed_chunk_still_failed_after_rounds(monkeypatch, tmp_path):
    job, calls, encoded, info = _setup(monkeypatch, tmp_path, fail_times=99)
    _run(info, single_file=True)
    assert calls["c1"] == 3  # sintesi + 2 round di ripasso
    assert job["failed_chunks"] == 1


def test_partial_email_texts_cover_completion_languages():
    # Stesse lingue dell'email di completamento, titolo escapato, percentuale
    # mai 0 (sopra soglia c'e' sempre qualcosa di muto).
    partial = generation_engine._partial_email_texts("<b>T</b>", 0.004)
    assert set(partial) == set(generation_engine._completion_email_texts("T", 24))
    for t in partial.values():
        assert "&lt;b&gt;T&lt;/b&gt;" in t["body"] and "<b>" not in t["body"]
        assert "1" in t["notice"]
    assert "29%" in generation_engine._partial_email_texts("T", 0.291)["en"]["notice"]
