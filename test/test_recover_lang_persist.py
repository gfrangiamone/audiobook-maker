"""Fix #2 (v3.35.0): il recovery post-restart deve preservare la lingua di
lettura. Prima, _build_job_descriptor non salvava opt_lang/gen_lang/lang e
_reenqueue_orphan non li ripristinava: run_optimization cadeva sul default
hardcoded "it" (prompt LLM italiano su libro di altra lingua). Incidente
kd8XQj6WWdrZJt1_z0VMPQ: prompt it su libro es dopo restart alle 12:15."""
import audiobook_app


def test_build_descriptor_includes_lang_fields():
    job = {
        "original_filename": "book.epub",
        "lang": "es",
        "opt_lang": "es",
        "gen_lang": "es",
        "browser_lang": "es-ES",
        "platform": "android",
        "gemini_accent": "es-ES",
    }
    d = audiobook_app._build_job_descriptor(job, "optimize")
    assert d["lang"] == "es"
    assert d["opt_lang"] == "es"
    assert d["gen_lang"] == "es"
    assert d["browser_lang"] == "es-ES"
    assert d["platform"] == "android"
    assert d["gemini_accent"] == "es-ES"


def test_reenqueue_restores_lang(tmp_path, monkeypatch):
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"fake-epub")

    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: object())

    class _FakeThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(audiobook_app.threading, "Thread", _FakeThread)

    rec = {
        "id": "Jlang",
        "phase": "optimize",
        "voice": "gemini:flash31:Enceladus",
        "input_path": str(epub),
        "lang": "es",
        "opt_lang": "es",
        "gen_lang": "",
        "opt_auto_generate": True,
    }
    try:
        audiobook_app._reenqueue_orphan("Jlang", rec)
        job = audiobook_app.jobs["Jlang"]
        assert job["opt_lang"] == "es"
        assert job["lang"] == "es"
    finally:
        audiobook_app.jobs.pop("Jlang", None)


def test_descriptor_roundtrip_preserves_lang(tmp_path, monkeypatch):
    # build -> (simula persistenza) -> reenqueue: opt_lang sopravvive al giro.
    epub = tmp_path / "b.epub"
    epub.write_bytes(b"x")
    src_job = {
        "original_filename": "b.epub",
        "epub_path": str(epub),
        "opt_lang": "fr",
        "lang": "fr",
        "voice": "gemini:flash31:Enceladus",
    }
    rec = audiobook_app._build_job_descriptor(src_job, "optimize")
    rec["id"] = "Jrt"
    rec["phase"] = "optimize"
    rec["input_path"] = str(epub)  # register normalmente usa input_path

    monkeypatch.setattr(audiobook_app, "_parse_book", lambda s: object())

    class _FakeThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(audiobook_app.threading, "Thread", _FakeThread)
    try:
        audiobook_app._reenqueue_orphan("Jrt", rec)
        assert audiobook_app.jobs["Jrt"]["opt_lang"] == "fr"
    finally:
        audiobook_app.jobs.pop("Jrt", None)
