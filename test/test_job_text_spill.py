"""Test: contenimento RAM — spill su disco dei testi capitolo ai terminali.

Incidente 2026-08-21 (freeze prod da saturazione RAM+swap): `jobs[job_id]["info"]`
tiene in memoria il testo di ogni capitolo per l'intera finestra di retention
(24/48/96h). Con `ABM_MAX_TEXT_CHARS=3.1M` e decine di job vivi la RSS cresce
monotona fino al thrash livelock.

Invariante testata: quando un job entra in stato terminale i testi escono dalla
RAM ma restano recuperabili on-demand dalla job dir.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import generation_engine


class _Chapter:
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text
        self.word_count = len(text.split())
        self.char_count = len(text)


class _Info:
    def __init__(self, chapters):
        self.title = "Titolo"
        self.author = "Autore"
        self.language = "it"
        self.chapters = chapters


@pytest.fixture
def job_env(tmp_path, monkeypatch):
    chapters = [
        _Chapter(1, "Cap 1", "Testo del primo capitolo. " * 50),
        _Chapter(2, "Cap 2", "Testo del secondo capitolo. " * 50),
    ]
    job = {"status": "generating", "info": _Info(chapters)}
    (tmp_path / "j1").mkdir()
    monkeypatch.setattr(generation_engine, "_jobs", {"j1": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)
    return job, chapters, tmp_path


def test_spill_releases_texts_and_keeps_them_recoverable(job_env):
    job, chapters, tmp_path = job_env
    originals = [c.text for c in chapters]

    assert generation_engine.spill_job_texts("j1") is True

    # RAM liberata
    assert all(c.text == "" for c in chapters)
    # File di spill nella job dir (fuori da output*/ → non tocca hot-evict)
    spill = tmp_path / "j1" / generation_engine._SPILL_FILENAME
    assert spill.exists()

    # Recuperabile on-demand senza reidratare il job
    texts = generation_engine.chapter_texts("j1", job)
    assert texts[1] == originals[0]
    assert texts[2] == originals[1]
    assert all(c.text == "" for c in chapters), "chapter_texts non deve reidratare"


def test_rehydrate_restores_texts_in_memory(job_env):
    job, chapters, _ = job_env
    originals = [c.text for c in chapters]

    generation_engine.spill_job_texts("j1")
    assert generation_engine.rehydrate_job_texts("j1") is True

    assert [c.text for c in chapters] == originals
    assert job.get("_texts_spilled") is not True


def test_terminal_status_triggers_spill(job_env):
    job, chapters, tmp_path = job_env

    generation_engine._set_job_status(job, "done")

    assert job["status"] == "done"
    assert all(c.text == "" for c in chapters)
    assert (tmp_path / "j1" / generation_engine._SPILL_FILENAME).exists()


@pytest.mark.parametrize("status", ["error", "cancelled", "partial"])
def test_other_terminal_statuses_trigger_spill(job_env, status):
    job, chapters, _ = job_env
    generation_engine._set_job_status(job, status)
    assert all(c.text == "" for c in chapters)


@pytest.mark.parametrize("status", ["analyzed", "optimized", "generating", "translated"])
def test_non_terminal_status_keeps_texts(job_env, status):
    job, chapters, _ = job_env
    generation_engine._set_job_status(job, status)
    assert all(c.text for c in chapters)


def test_chapter_texts_without_spill_reads_memory(job_env):
    job, chapters, _ = job_env
    texts = generation_engine.chapter_texts("j1", job)
    assert texts[1] == chapters[0].text


def test_generate_optimized_abm_works_after_spill(job_env, monkeypatch):
    """Lo snapshot .abm scaricabile non deve contenere capitoli vuoti."""
    import io
    import zipfile

    job, chapters, _ = job_env
    originals = [c.text for c in chapters]
    job["ai_optimized"] = True
    monkeypatch.setattr(generation_engine, "_get_llm_prompt", lambda lang: "")

    generation_engine.spill_job_texts("j1")
    abm_path, _fname = generation_engine._generate_optimized_abm("j1")

    assert abm_path and Path(abm_path).exists()
    with zipfile.ZipFile(abm_path) as zf:
        names = [n for n in zf.namelist() if n.startswith("chapters/")]
        assert len(names) == 2
        contents = sorted(zf.read(n).decode("utf-8") for n in names)
    assert contents == sorted(originals)


def test_spill_is_idempotent(job_env):
    job, chapters, _ = job_env
    assert generation_engine.spill_job_texts("j1") is True
    assert generation_engine.spill_job_texts("j1") is False
    # il secondo giro non deve sovrascrivere lo spill con testi vuoti
    texts = generation_engine.chapter_texts("j1", job)
    assert texts[1].strip()


def test_spill_noop_without_job_dir(tmp_path, monkeypatch):
    chapters = [_Chapter(1, "Cap 1", "abc")]
    job = {"status": "generating", "info": _Info(chapters)}
    monkeypatch.setattr(generation_engine, "_jobs", {"j2": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)

    # job dir inesistente → nessuna perdita di testo
    assert generation_engine.spill_job_texts("j2") is False
    assert chapters[0].text == "abc"


def test_abm_not_overwritten_when_spill_unreadable(job_env, monkeypatch, tmp_path):
    """Spill corrotto/mancante → mai riscrivere lo snapshot .abm con testi vuoti."""
    job, chapters, _ = job_env
    monkeypatch.setattr(generation_engine, "_get_llm_prompt", lambda lang: "")

    generation_engine.spill_job_texts("j1")
    (tmp_path / "j1" / generation_engine._SPILL_FILENAME).unlink()

    good = tmp_path / "j1" / "good.abm"
    good.write_bytes(b"snapshot-integro")
    job["optimized_abm_path"] = str(good)

    path, name = generation_engine._generate_optimized_abm("j1")
    assert path == str(good)
    assert name == "good.abm"
    assert good.read_bytes() == b"snapshot-integro"


def test_abm_generation_aborted_without_snapshot(job_env, monkeypatch, tmp_path):
    job, chapters, _ = job_env
    monkeypatch.setattr(generation_engine, "_get_llm_prompt", lambda lang: "")
    generation_engine.spill_job_texts("j1")
    (tmp_path / "j1" / generation_engine._SPILL_FILENAME).unlink()

    assert generation_engine._generate_optimized_abm("j1") == (None, None)
