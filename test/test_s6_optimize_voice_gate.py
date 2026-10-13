"""S6 (2026-10-12): /api/optimize con auto_generate e voce campionata faceva
partire la generazione da run_optimization senza `voice_clone.check_use`,
il gate di proprieta'/lingua che /api/generate e il recovery applicano: un
dispositivo revocato poteva usare la voce di un altro. Ora lo stesso gate
sta anche qui, prima del claim del job."""
import pytest

import audiobook_app
import voice_clone

CID = "cid_s6_test"
VOICE = voice_clone.VOICE_ID_PREFIX + "abc123"


@pytest.fixture
def job(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(audiobook_app, "_premium_model_gate", lambda v: None)
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    j = {"status": "analyzed", "client_id": CID, "original_filename": "x.epub", "created_at": 0, "last_poll": 0}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["s6-job"] = j
    yield j
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("s6-job", None)


def _post(c, **body):
    c.set_cookie("abm_cid", CID)
    return c.post("/api/optimize", json={"job_id": "s6-job", "voice": VOICE, "lang": "it-IT", **body})


def test_auto_generate_with_a_revoked_cloned_voice_is_refused_before_the_claim(job, monkeypatch):
    seen = []
    monkeypatch.setattr(voice_clone, "check_use", lambda v, cid, lang, locale: seen.append((v, cid, lang, locale)) or "voice_not_authorized")
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        r = _post(c, auto_generate=True, locale="it-IT")
    assert r.status_code == 403 and r.get_json()["error_code"] == "voice_not_authorized"
    assert seen == [(VOICE, CID, "it", "it-IT")]
    assert job["status"] == "analyzed"                     # nessun claim lasciato a meta'


@pytest.mark.parametrize("code,status", [("voice_gone", 410), ("voice_lang_mismatch", 400)])
def test_other_gate_outcomes_map_like_api_generate(job, monkeypatch, code, status):
    monkeypatch.setattr(voice_clone, "check_use", lambda *a: code)
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        r = _post(c, auto_generate=True)
    assert r.status_code == status and r.get_json()["error_code"] == code


def test_without_auto_generate_the_gate_is_not_consulted(job, monkeypatch):
    called = []
    monkeypatch.setattr(voice_clone, "check_use", lambda *a: called.append(a) or "voice_gone")
    # dopo il gate la richiesta prosegue: la fermiamo al primo passo successivo
    monkeypatch.setattr(audiobook_app, "_suspend_new_jobs", True)
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        r = _post(c, auto_generate=False)
    assert r.status_code == 503 and called == []
