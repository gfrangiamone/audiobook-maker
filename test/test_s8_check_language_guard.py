"""S8 (2026-10-13): /api/check_language usava `lang` libero come chiave del
memo nel job e dentro il prompt del giudice semantico: una chiamata LLM a
pagamento per ogni valore nuovo, senza limite. Ora solo codici lingua
(2-3 lettere dopo norm_lang) e rate limit per IP; in entrambi i casi la
risposta resta `{"mismatch": false}` (il wizard prosegue)."""
import pytest

import audiobook_app

CID = "cid_s8_test"


@pytest.fixture
def job():
    j = {"status": "analyzed", "client_id": CID, "original_filename": "x.epub", "created_at": 0, "last_poll": 0}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["s8-job"] = j
    yield j
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("s8-job", None)


def _post(c, lang):
    c.set_cookie("abm_cid", CID)
    return c.post("/api/check_language", json={"job_id": "s8-job", "voice": "it-IT-ElsaNeural", "lang": lang})


def test_garbage_lang_never_reaches_the_judge(job, monkeypatch):
    seen = []
    monkeypatch.setattr(audiobook_app, "_language_mismatch_hit", lambda *a: seen.append(a[3]) or None)
    monkeypatch.setattr(audiobook_app, "_ip_rl_check", lambda *a: (True, 0))
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        for bad in ("<script>", "it; drop", "x" * 40):
            assert _post(c, bad).get_json() == {"mismatch": False}
        assert seen == []
        assert _post(c, "it-IT").get_json() == {"mismatch": False}
        assert _post(c, "").get_json() == {"mismatch": False}      # vuoto: decide la voce
        assert seen == ["it", ""]


def test_rate_limited_requests_skip_the_judge(job, monkeypatch):
    seen = []
    monkeypatch.setattr(audiobook_app, "_language_mismatch_hit", lambda *a: seen.append(1) or None)
    monkeypatch.setattr(audiobook_app, "_ip_rl_check", lambda bucket, ip, m, h: (False, 30) if bucket == "check_language" else (True, 0))
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        assert _post(c, "fr").get_json() == {"mismatch": False}
    assert seen == []
