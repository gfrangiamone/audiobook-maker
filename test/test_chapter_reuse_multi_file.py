"""Restart di un job multi-file (zip): i capitoli gia' codificati in output_N/
non si risintetizzano. Il 26/10/2026 due job zip con piano identico sono
ripartiti dal capitolo 1 dopo il deploy: il ramo cancella le parti dopo l'encode
del capitolo e il riuso guardava solo i file `chunk_*`."""
import os
import zipfile

import pytest

import generation_engine
from test.test_failed_chunk_retry import _setup

VOICE = "en-US-AndrewMultilingualNeural"


def _generate(info):
    generation_engine.run_generation("jr", info(), VOICE, "+0%",
                                     single_file=False, output_format="zip")


def test_restart_skips_chapters_already_encoded(monkeypatch, tmp_path):
    _job, calls, encoded, info = _setup(monkeypatch, tmp_path, fail_times=0)
    sintesi = generation_engine.generate_chunk_mp3
    ucciso = []

    async def muore_al_capitolo_2(text, *a, **kw):
        # Il processo muore sul primo chunk del capitolo 2 (restart del
        # deploy): il capitolo 1 e' gia' codificato e le sue parti cancellate.
        if text == "c2" and not ucciso:
            ucciso.append(text)
            raise KeyboardInterrupt
        return await sintesi(text, *a, **kw)
    monkeypatch.setattr(generation_engine, "generate_chunk_mp3", muore_al_capitolo_2)

    with pytest.raises(KeyboardInterrupt):
        _generate(info)
    assert calls == {"c0": 1, "c1": 1}

    # Recovery: stesso job, stessa epoch, processo nuovo.
    job2 = {"gen_epoch": 0, "info": info(), "status": "queued", "recovered": True,
            "last_poll": 9e18, "email_registered": True}
    generation_engine._jobs["jr"] = job2
    _generate(info)

    assert calls == {"c0": 1, "c1": 1, "c2": 1, "c3": 1}
    assert [os.path.basename(out)[:4] for out, _ in encoded] == ["001_", "002_"]
    assert job2["status"] == "done" and job2["failed_chunks"] == 0
    names = [os.path.basename(p) for p in job2["output_files"]]
    assert [n[:4] for n in names] == ["001_", "002_"]
    with zipfile.ZipFile(job2["output_zip"]) as z:
        assert sorted(n for n in z.namelist() if n.endswith(".mp3")) == names
    assert job2["processed_chars"] == 8 and job2["chunks_reused"] == 2


def test_restart_with_other_epoch_reuses_chapters_of_previous_output_dir(monkeypatch, tmp_path):
    # 07/11/2026, C-IucY4: rilancio dell'utente (epoch 2, capitoli in
    # output_2/), poi il recovery riparte da epoch 1 e rifaceva i capitoli
    # gia' codificati.
    job, calls, encoded, info = _setup(monkeypatch, tmp_path, fail_times=0)
    job["gen_epoch"] = 2
    sintesi = generation_engine.generate_chunk_mp3
    ucciso = []

    async def muore_al_capitolo_2(text, *a, **kw):
        if text == "c2" and not ucciso:
            ucciso.append(text)
            raise KeyboardInterrupt
        return await sintesi(text, *a, **kw)
    monkeypatch.setattr(generation_engine, "generate_chunk_mp3", muore_al_capitolo_2)

    with pytest.raises(KeyboardInterrupt):
        _generate(info)
    assert calls == {"c0": 1, "c1": 1}

    job2 = {"gen_epoch": 1, "info": info(), "status": "queued", "recovered": True,
            "last_poll": 9e18, "email_registered": True}
    generation_engine._jobs["jr"] = job2
    _generate(info)

    assert calls == {"c0": 1, "c1": 1, "c2": 1, "c3": 1}
    assert job2["status"] == "done" and job2["chunks_reused"] == 2
    names = [os.path.basename(p) for p in job2["output_files"]]
    assert [n[:4] for n in names] == ["001_", "002_"]
    assert all(os.path.dirname(p).endswith("output_1") for p in job2["output_files"])
    with zipfile.ZipFile(job2["output_zip"]) as z:
        assert sorted(n for n in z.namelist() if n.endswith(".mp3")) == names
    # L'MP3 della epoch precedente resta al suo posto.
    assert (tmp_path / "jr" / "output_2" / names[0]).exists()
