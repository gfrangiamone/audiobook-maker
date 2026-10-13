"""S9 (2026-10-13): /api/translate_title faceva una chiamata LLM per ogni
`target` di 2-3 lettere (circa 18 000 valori), senza rate limit. Ora solo le
lingue di translation_core.EDGE_LANGS_FALLBACK e 10 richieste al minuto per
IP; oltre, `{"title": ""}` come per ogni altro inciampo."""
import types

import pytest

import audiobook_app
import translation_core

CID = "cid_s9_test"


@pytest.fixture
def job(monkeypatch):
    monkeypatch.setattr(translation_core, "is_available", lambda: True)
    monkeypatch.setattr(translation_core, "resolve_backend", lambda: "fake")
    monkeypatch.setattr(translation_core, "make_client_provider", lambda b: (object(), "m", ""))
    j = {"status": "analyzed", "client_id": CID, "original_filename": "x.epub", "created_at": 0, "last_poll": 0,
         "info": types.SimpleNamespace(title="La città perduta", language="it")}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["s9-job"] = j
    yield j
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("s9-job", None)


def _get(c, target):
    c.set_cookie("abm_cid", CID)
    return c.get(f"/api/translate_title/s9-job?target={target}")


def test_unknown_target_and_rate_limit_never_call_the_llm(job, monkeypatch):
    calls = []
    monkeypatch.setattr(translation_core, "translate_titles", lambda *a, **k: calls.append(a[3]) or ["Titre"])
    limited = {"on": False}
    monkeypatch.setattr(audiobook_app, "_ip_rl_check",
                        lambda bucket, ip, m, h: (not limited["on"], 9) if bucket == "translate_title" else (True, 0))
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        assert _get(c, "zq").get_json() == {"title": ""} and calls == []        # non e' una lingua
        assert _get(c, "fr").get_json() == {"title": "Titre"} and calls == ["fr"]
        assert _get(c, "fr").get_json() == {"title": "Titre", "cached": True}  # cache del job
        limited["on"] = True
        assert _get(c, "de").get_json() == {"title": ""} and calls == ["fr"]      # rate limit
