"""Incidente tUV3YzoYMcde_euhIU6QCg: il descrittore batch di /api/generate
veniva registrato (subito dopo la capture PayPal, ramo auto-batch) PRIMA che
job["voice"] fosse valorizzato. Al riavvio la guardia anti-audio-muto leggeva
voice="" e dichiarava irrecuperabile un job PREMIUM al 89%, rimborsandolo e
buttando via 3465 chunk gia' sintetizzati.

L'invariante da difendere e' d'ordine: lo snapshot dei parametri di generazione
deve precedere ogni pending_jobs.register() dentro api_generate."""
import inspect

import audiobook_app


def _src():
    return inspect.getsource(audiobook_app.api_generate)


def _first_index(src, needle):
    i = src.find(needle)
    assert i >= 0, f"atteso {needle!r} in api_generate"
    return i


def test_generation_params_snapshot_precedes_register():
    src = _src()
    register_at = _first_index(src, "pending_jobs.register(job_id")
    for assignment in ('job["voice"] = voice',
                       'job["rate"] = rate',
                       'job["single_file"] = single_file',
                       'job["selected_chapters"] = selected_chapters',
                       'job["read_round_parens"]',
                       'job["read_square_brackets"]',
                       'job["gemini_style_instruction"] = style_instruction',
                       'job["gemini_accent"] = accent_variant',
                       'job["speechify_emotion"] = speechify_emotion'):
        assert _first_index(src, assignment) < register_at, (
            f"{assignment} deve precedere pending_jobs.register()")


def test_descriptor_carries_generation_params():
    job = {
        "original_filename": "book.epub",
        "voice": "gemini:flash25:Enceladus",
        "rate": "+10%",
        "single_file": True,
        "output_format": "m4b",
        "selected_chapters": [0, 1, 2],
        "gemini_style_instruction": "tono calmo",
        "gemini_accent": "it-IT",
        "speechify_emotion": "warm",
    }
    d = audiobook_app._build_job_descriptor(job, "generate")
    assert d["voice"] == "gemini:flash25:Enceladus"
    assert d["rate"] == "+10%"
    assert d["selected_chapters"] == [0, 1, 2]
    assert d["gemini_style_instruction"] == "tono calmo"
    assert d["gemini_accent"] == "it-IT"
    assert d["speechify_emotion"] == "warm"


def test_reenqueue_reports_whether_it_actually_started(tmp_path, monkeypatch):
    """Il log '[recover] ...: re-enqueued' era incondizionato: in fase forense
    faceva credere che un job dirottato su _orphan_fallback stesse ripartendo."""
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"fake-epub")
    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: object())
    monkeypatch.setattr(audiobook_app, "_orphan_fallback", lambda *a, **k: None)

    class _FakeThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            pass

    monkeypatch.setattr(audiobook_app.threading, "Thread", _FakeThread)

    mute = {"id": "Jmute", "phase": "generate", "voice": "",
            "input_path": str(epub)}
    assert audiobook_app._reenqueue_orphan("Jmute", mute) is False

    ok = {"id": "Jok", "phase": "generate", "voice": "gemini:flash25:Enceladus",
          "input_path": str(epub)}
    try:
        assert audiobook_app._reenqueue_orphan("Jok", ok) is True
    finally:
        audiobook_app.jobs.pop("Jok", None)
        audiobook_app.jobs.pop("Jmute", None)
