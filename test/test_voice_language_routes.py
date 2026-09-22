# -*- coding: utf-8 -*-
"""
L'avviso lingua libro/voce visto dalle route.

Il controllo vive in `voice_language_guard`; qui si verifica il contorno che
decide se e' utile o dannoso: che il 409 arrivi prima che parta qualcosa, che
`confirm_language` lo scavalchi, che la domanda non si paghi due volte, che
/api/optimize non lasci il job brickato in "optimizing", e che il pre-controllo
del wizard non fermi mai una generazione per colpa propria.
"""

import pytest

import audiobook_app
import voice_language_guard as vg
from epub_to_tts import BookInfo, Chapter

CID = "cid_voicelang_test"
IP = "9.9.9.9"
VOICE = "en-US-AriaNeural"
HIT = {"voice_language": "it", "book_language": "es", "confidence": 0.97}


class _SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None,
                 name=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "0")
    run_calls, log_calls = [], []
    monkeypatch.setattr(audiobook_app, "run_generation",
                        lambda *a, **k: run_calls.append(a))
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation",
                        lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **k: log_calls.append(a))
    yield {"run": run_calls, "log": log_calls}
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("vl-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(job_id, status="analyzed"):
    ch = Chapter(index=0, title="Cap0", text="A" * 2000)
    info = BookInfo(title="T", author="A", language="es", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {
            "info": info, "status": status, "client_id": CID,
            "client_ip": IP, "original_filename": "libro.epub"}
    return audiobook_app.jobs[job_id]


def _guard(monkeypatch, result, calls=None):
    def _check(texts, voice_lang, declared="", **kw):
        if calls is not None:
            calls.append((voice_lang, declared))
        return result
    monkeypatch.setattr(vg, "check", _check)


def _gen_body(job_id, **extra):
    body = {"job_id": job_id, "voice": VOICE, "rate": "+0%",
            "single_file": True, "lang": "it"}
    body.update(extra)
    return body


# ---------------------------------------------------------------------------
# /api/check_language — la domanda prima del pagamento
# ---------------------------------------------------------------------------

def test_check_language_reports_a_mismatch(env, client, monkeypatch):
    _mk_job("vl-1")
    _guard(monkeypatch, HIT)
    d = client.post("/api/check_language",
                    json={"job_id": "vl-1", "voice": VOICE,
                          "lang": "it"}).get_json()
    assert d["mismatch"] is True
    assert d["voice_language"] == "it" and d["book_language"] == "es"


def test_check_language_says_nothing_when_all_is_well(env, client,
                                                      monkeypatch):
    _mk_job("vl-2")
    _guard(monkeypatch, None)
    d = client.post("/api/check_language",
                    json={"job_id": "vl-2", "lang": "it"}).get_json()
    assert d == {"mismatch": False}


def test_an_unknown_job_does_not_stop_the_wizard(env, client, monkeypatch):
    """Il pre-controllo non e' un'autorizzazione: se il job non si trova, la
    risposta giusta e' «procedi», non un errore davanti al bottone Genera."""
    _guard(monkeypatch, HIT)
    r = client.post("/api/check_language", json={"job_id": "vl-nope"})
    assert r.status_code == 200 and r.get_json() == {"mismatch": False}


def test_a_broken_guard_does_not_stop_the_wizard(env, client, monkeypatch):
    _mk_job("vl-3")

    def _boom(*a, **k):
        raise RuntimeError("boom")
    monkeypatch.setattr(vg, "check", _boom)
    r = client.post("/api/check_language", json={"job_id": "vl-3"})
    assert r.status_code == 200 and r.get_json() == {"mismatch": False}


# ---------------------------------------------------------------------------
# /api/generate
# ---------------------------------------------------------------------------

def test_generate_warns_before_starting_anything(env, client, monkeypatch):
    _mk_job("vl-4")
    _guard(monkeypatch, HIT)
    r = client.post("/api/generate", json=_gen_body("vl-4"))
    assert r.status_code == 409
    d = r.get_json()
    assert d["error_code"] == "language_mismatch"
    assert d["book_language"] == "es"
    assert env["run"] == []


def test_the_warning_is_logged(env, client, monkeypatch):
    _mk_job("vl-5")
    _guard(monkeypatch, HIT)
    client.post("/api/generate", json=_gen_body("vl-5"))
    assert any(a[2] == "LANG_MISMATCH" for a in env["log"])


def test_confirm_language_skips_the_question(env, client, monkeypatch):
    """Chi ha gia' visto l'avviso non lo rivede, e soprattutto non lo ripaga:
    senza questo, un libro bilingue non sarebbe generabile affatto."""
    _mk_job("vl-6")
    calls = []
    _guard(monkeypatch, HIT, calls)
    r = client.post("/api/generate",
                    json=_gen_body("vl-6", confirm_language=True))
    assert calls == []
    assert (r.get_json() or {}).get("error_code") != "language_mismatch"


def test_the_question_is_asked_once_per_job(env, client, monkeypatch):
    """Il wizard chiede prima del pagamento e la route ricontrolla: senza memo
    lo stesso libro pagherebbe due giudizi per una sola generazione."""
    _mk_job("vl-7")
    calls = []
    _guard(monkeypatch, None, calls)
    client.post("/api/check_language", json={"job_id": "vl-7", "lang": "it"})
    client.post("/api/generate", json=_gen_body("vl-7"))
    assert len(calls) == 1


def test_another_voice_language_is_asked_again(env, client, monkeypatch):
    """Il memo vale per la lingua della voce: cambiarla e' l'unico motivo per
    cui la risposta di prima non vale piu'."""
    _mk_job("vl-8")
    calls = []
    _guard(monkeypatch, None, calls)
    client.post("/api/check_language", json={"job_id": "vl-8", "lang": "it"})
    client.post("/api/check_language", json={"job_id": "vl-8", "lang": "de"})
    assert [c[0] for c in calls] == ["it", "de"]


def test_the_declared_language_travels_with_the_text(env, client, monkeypatch):
    """Serve a proporre la lingua dei metadati come risposta possibile."""
    _mk_job("vl-9")
    calls = []
    _guard(monkeypatch, None, calls)
    client.post("/api/check_language", json={"job_id": "vl-9", "lang": "it"})
    assert calls[0][1] == "es"


def test_the_voice_id_supplies_the_language_when_the_client_does_not(
        env, client, monkeypatch):
    _mk_job("vl-10")
    calls = []
    _guard(monkeypatch, None, calls)
    client.post("/api/check_language",
                json={"job_id": "vl-10", "voice": "fr-FR-DeniseNeural"})
    assert calls[0][0] == "fr"


def test_a_voice_without_a_language_is_passed_through_empty(env, client,
                                                            monkeypatch):
    """Su Gemini, Speechify e voci campionate l'id non porta la lingua: il
    modulo la riceve vuota e non chiede niente."""
    _mk_job("vl-11")
    calls = []
    _guard(monkeypatch, None, calls)
    client.post("/api/check_language",
                json={"job_id": "vl-11", "voice": "gemini-Kore"})
    assert calls[0][0] == ""


# ---------------------------------------------------------------------------
# /api/optimize
# ---------------------------------------------------------------------------

def test_optimize_warns_and_releases_the_job(env, client, monkeypatch):
    """Il claim "optimizing" va rilasciato sul 409: lasciarlo li' brickherebbe
    il job, e ogni retry tornerebbe «already running»."""
    job = _mk_job("vl-12")
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    _guard(monkeypatch, HIT)
    r = client.post("/api/optimize", json={"job_id": "vl-12", "lang": "it",
                                           "voice": VOICE})
    assert r.status_code == 409
    assert r.get_json()["error_code"] == "language_mismatch"
    assert job["status"] == "analyzed"


def test_optimize_confirmed_does_not_ask(env, client, monkeypatch):
    _mk_job("vl-13")
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    calls = []
    _guard(monkeypatch, HIT, calls)
    r = client.post("/api/optimize", json={"job_id": "vl-13", "lang": "it",
                                           "voice": VOICE,
                                           "confirm_language": True})
    assert calls == []
    assert (r.get_json() or {}).get("error_code") != "language_mismatch"
