"""Incidente LxRrADnUul50aFbWLM0rAg (06/10/2026).

Traduzione EN->EL adottata (/api/translate_adopt) e generazione avviata con
voce greca: i capitoli tradotti vivevano solo in RAM e il descrittore di
recovery puntava all'EPUB inglese caricato. Dopo un restart il recovery
avrebbe ri-parsato l'originale: voce greca sul testo inglese, chunk scartati
(plan_sha diverso) e libro sbagliato consegnato come completo.

Invarianti:
- l'adopt scrive nella job dir un .abm con i capitoli tradotti;
- il descrittore porta quel path e il recovery lo usa al posto di input_path,
  senza marcare il job come ottimizzato;
- se lo snapshot manca il recovery non ripiega sull'originale.
"""
import time
from unittest.mock import patch

import pytest

import audiobook_app
import community_store
import pending_jobs


class _Ch:
    def __init__(self, index, title, text):
        self.index, self.title, self.text = index, title, text
        self.char_count = len(text)
        self.word_count = len(text.split())


class _Info:
    title = "Notes"
    author = "A"
    language = "en"

    def __init__(self):
        self.chapters = [_Ch(1, "One", "English one."), _Ch(2, "Two", "English two.")]


@pytest.fixture
def env(tmp_path, monkeypatch):
    community_store.init(str(tmp_path))
    pending_jobs._store = None
    pending_jobs.init()
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    audiobook_app.jobs.clear()
    yield tmp_path
    audiobook_app.jobs.clear()


@pytest.fixture
def started(monkeypatch):
    calls = []

    class _T:
        def __init__(self, *a, **k):
            self.k = k

        def start(self):
            calls.append(self.k)

    monkeypatch.setattr(audiobook_app.threading, "Thread", _T)
    return calls


def _adopt(env, job_id="JTR"):
    (env / job_id).mkdir()
    src = env / job_id / "book.epub"
    src.write_bytes(b"original english epub")
    job = {"status": "translated", "client_id": "c1", "client_ip": "127.0.0.1",
           "info": _Info(), "original_filename": "book.epub",
           "epub_path": str(src), "last_poll": time.time(),
           "translated_lang": "el", "translated_optimized": False,
           "translated_title": "Σημειώσεις",
           "translated_chapters": [
               {"index": 1, "title": "Ένα", "text": "Ελληνικό ένα."},
               {"index": 2, "title": "Δύο", "text": "Ελληνικό δύο."},
           ]}
    audiobook_app.jobs[job_id] = job
    client = audiobook_app.app.test_client()
    with patch("audiobook_app._check_job_owner", return_value=(job, None, None)):
        r = client.post(f"/api/translate_adopt/{job_id}")
    assert r.status_code == 200
    job.update({"voice": "el-GR-AthinaNeural", "rate": "+0%",
                "single_file": True, "output_format": "m4b",
                "notify_email": "a@x.gr"})
    return job


def test_adopt_writes_snapshot_and_descriptor_carries_it(env):
    job = _adopt(env)
    path = job["adopted_abm_path"]
    assert path == str(env / "JTR" / audiobook_app.ADOPTED_TRANSLATION_ABM)
    info, _cover = audiobook_app.parse_abm(path)
    assert [c.text for c in info.chapters] == ["Ελληνικό ένα.", "Ελληνικό δύο."]
    assert [c.index for c in info.chapters] == [1, 2]
    assert info.language == "el" and info.title == "Σημειώσεις"
    rec = audiobook_app._build_job_descriptor(job, "generate")
    assert rec["adopted_abm_path"] == path
    assert rec["input_path"].endswith("book.epub")


def test_recovery_regenerates_from_translated_text(env, started):
    job = _adopt(env)
    rec = audiobook_app._build_job_descriptor(job, "generate")
    rec.update({"id": "JTR", "phase": "generate"})
    audiobook_app.jobs.clear()
    pending_jobs.register("JTR", "generate", rec)
    assert audiobook_app._reenqueue_orphan("JTR", rec) is True
    info = started[0]["args"][1]
    assert [c.text for c in info.chapters] == ["Ελληνικό ένα.", "Ελληνικό δύο."]
    rebuilt = audiobook_app.jobs["JTR"]
    assert rebuilt["ai_optimized"] is False
    assert rebuilt["adopted_abm_path"] == job["adopted_abm_path"]


def test_recovery_without_snapshot_does_not_fall_back_to_original(env, monkeypatch):
    job = _adopt(env)
    rec = audiobook_app._build_job_descriptor(job, "generate")
    rec.update({"id": "JTR", "phase": "generate"})
    (env / "JTR" / audiobook_app.ADOPTED_TRANSLATION_ABM).unlink()
    monkeypatch.setattr(audiobook_app, "_parse_book",
                        lambda src: (_ for _ in ()).throw(
                            AssertionError("non deve ri-parsare l'originale")))
    with pytest.raises(FileNotFoundError):
        audiobook_app._reenqueue_orphan("JTR", rec)


def test_reset_keeps_adopted_snapshot():
    import inspect
    src = inspect.getsource(audiobook_app)
    loop = src[src.index('for abm in work_dir.glob("*.abm"):'):][:300]
    assert "ADOPTED_TRANSLATION_ABM" in loop and "continue" in loop
