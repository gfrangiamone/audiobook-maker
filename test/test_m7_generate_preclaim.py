"""M7 (2026-10-13): /api/generate scriveva voce, formato, capitoli e flag di
lettura sul job PRIMA del claim sotto lock. Un secondo POST durante una
generazione in corso modificava il job attivo e veniva rifiutato solo dopo:
email, download e retention leggevano la richiesta rifiutata. Ora il rifiuto
avviene sotto lock prima di qualunque scrittura."""
import pytest

import audiobook_app

CID = "cid_m7_test"


@pytest.fixture
def running_job(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_premium_model_gate", lambda v: None)
    j = {"status": "generating", "client_id": CID, "original_filename": "x.epub", "created_at": 0,
         "last_poll": 0, "voice": "it-IT-A", "rate": "+5%", "output_format": "zip",
         "selected_chapters": [1, 2], "single_file": False, "read_round_parens": True}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["m7-job"] = j
    yield j
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("m7-job", None)


def test_second_post_during_generation_does_not_touch_the_job(running_job):
    before = dict(running_job)
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        r = c.post("/api/generate", json={"job_id": "m7-job", "voice": "it-IT-ElsaNeural", "rate": "+0%",
                                          "output_format": "m4b", "single_file": True,
                                          "selected_chapters": [3], "read_round_parens": False})
    assert r.status_code == 400 and "already running" in r.get_json()["error"]
    assert running_job == before            # nessuna chiave riscritta dalla richiesta rifiutata
