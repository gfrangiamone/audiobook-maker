"""Restart con testo del piano cambiato (06/11/2026, deploy delle 15:12: 18 job
ripartiti da zero per differenze di pochi caratteri). I chunk il cui testo e'
rimasto uguale si riusano anche se il loro indice e' cambiato, e un crash a
meta' scrittura di un chunk ricollocato fuori ordine non lascia audio
troncato al restart successivo."""
import os

import pytest

import generation_engine


def _plan(*chapters):
    return [{"chapter_index": ch, "chapter_title": f"Cap {ch}", "chunk_index": k,
             "chunks_in_chapter": len(texts), "text": t, "chars": len(t)}
            for ch, texts in enumerate(chapters, start=1) for k, t in enumerate(texts)]


@pytest.fixture
def engine(monkeypatch, tmp_path):
    """Edge finto: il file del chunk contiene il suo testo; `die_on` simula
    il processo ucciso a meta' scrittura di quel chunk."""
    st = {"plan": None, "die_on": None, "calls": [], "books": []}

    async def fake_chunk_edge(text, voice, rate, output_path, max_retries=3, **kwargs):
        if text == st["die_on"]:
            st["die_on"] = None
            with open(output_path, "wb") as f:
                f.write(b"tronc")
            raise KeyboardInterrupt
        st["calls"].append(text)
        with open(output_path, "wb") as f:
            f.write(text.encode())
        return True
    monkeypatch.setattr(generation_engine, "generate_chunk_mp3", fake_chunk_edge)
    monkeypatch.setattr(generation_engine, "_plan_chunks",
                        lambda info, max_chars, max_bytes=None, **kw: st["plan"])
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "edge")
    monkeypatch.setattr(generation_engine, "_generate_silence_mp3",
                        lambda p, duration_sec=1: open(p, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)

    def fake_concat(parts, out, **kw):
        st["books"].append([open(p, "rb").read().decode() for p in parts
                            if os.path.basename(p).startswith("chunk_")])
        open(out, "wb").write(b"\x01")
        return True
    monkeypatch.setattr(generation_engine, "_concatenate_mp3", fake_concat)
    monkeypatch.setattr(generation_engine, "_include_cover_in_dir", lambda *a, **k: None)

    class _Info:
        title = "T"
        author = "A"
        language = "en"
        chapters = [type("C", (), {"index": 1, "title": "Cap 1", "text": "..."})(),
                    type("C", (), {"index": 2, "title": "Cap 2", "text": "..."})()]
    st["info"] = _Info
    monkeypatch.setattr(generation_engine, "_jobs", {})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)
    return st


def _run(st):
    job = {"gen_epoch": 0, "info": st["info"](), "status": "queued", "recovered": True,
           "last_poll": 9e18, "email_registered": True}
    generation_engine._jobs["jr"] = job
    st["calls"].clear()
    generation_engine.run_generation("jr", st["info"](), "en-US-AndrewMultilingualNeural",
                                     "+0%", single_file=True, output_format="mp3")
    return job


def test_changed_text_reuses_matching_chunks_at_new_indices(engine):
    engine["plan"] = _plan(["a0", "a1", "a2"], ["b0", "b1", "b2", "b3"])
    engine["die_on"] = "b3"
    with pytest.raises(KeyboardInterrupt):
        _run(engine)

    # Deploy: un chunk riscritto e uno nuovo in testa al capitolo 2, che
    # sposta di un indice tutti i chunk dopo.
    nuovo = _plan(["a0", "A1", "a2"], ["intro", "b0", "b1", "b2", "b3"])
    engine["plan"] = nuovo
    engine["die_on"] = "intro"  # muore a meta' di un chunk scritto fuori ordine
    with pytest.raises(KeyboardInterrupt):
        _run(engine)
    # a0, a2, b0, b1 riusati (b0 e b1 a indice spostato); b2 e' l'indice
    # massimo ricollocato e si rifa', b3 era l'ultimo scritto (troncato).
    assert engine["calls"] == ["A1"]

    job = _run(engine)
    # "intro" troncato non si riusa anche se non e' l'indice massimo presente.
    assert engine["calls"] == ["intro", "b2", "b3"]
    assert job["chunks_reused"] == 5
    assert engine["books"][-1] == [b["text"] for b in nuovo]
    assert job["status"] == "done" and job["failed_chunks"] == 0
