"""Regressione segnalazione utente DE (14/11/2026): traduzione EPUB consegnata
via email, poi traduzione adottata e messa in TTS sullo stesso job. L'email
"Dein Hörbuch ist fertig!" puntava alla pagina della TRADUZIONE: nessun
bottone per l'audiolibro.

Due cause, entrambe coperte:
  1. `_create_download_token` riusava QUALSIASI token del job (anche quello
     `download_type="translated"` creato da `_send_translation_email`);
  2. `notify_download_type="translated"` armato da /api/translate restava sul
     job anche dopo l'adopt (i `setdefault("notify_download_type", "audio")`
     di /api/generate non lo sovrascrivono).
"""
import time

import pytest

import audiobook_app
import generation_engine as ge

CID = "cid_tr_audio_test"


def _env(monkeypatch, jobs, tokens):
    monkeypatch.setattr(ge, "_jobs", jobs)
    monkeypatch.setattr(ge, "_download_tokens", tokens)
    monkeypatch.setattr(ge, "_save_tokens", lambda: None)
    monkeypatch.setattr(ge, "_account_notify_token", lambda *a, **k: None)


@pytest.mark.parametrize("prev_type", ["translated", "optimized_abm"])
def test_audio_token_is_not_the_previous_translation_token(monkeypatch, tmp_path, prev_type):
    jobs = {"j1": {"status": "done", "info": None, "original_filename": "x.epub",
                   "output_m4b": str(tmp_path / "a.m4b"), "output_format": "m4b",
                   "notify_download_type": "translated", "voice": "it-IT-IsabellaNeural"}}
    tokens = {"OLD": {"job_id": "j1", "created_at": time.time(),
                      "download_type": prev_type,
                      "translated_path": str(tmp_path / "x-de.epub")}}
    _env(monkeypatch, jobs, tokens)

    tok = ge._create_download_token("j1")

    assert tok != "OLD", "l'email audio riusa il token della traduzione/.abm"
    assert tokens[tok]["download_type"] == "audio"
    assert tokens[tok]["output_m4b"] == str(tmp_path / "a.m4b")
    assert tokens["OLD"]["download_type"] == prev_type      # link precedente intatto
    assert ge._create_download_token("j1") == tok          # idempotenza conservata


def test_podcast_type_recovered_from_output_format(monkeypatch):
    jobs = {"j2": {"status": "done", "info": None, "output_format": "zip_rss",
                   "notify_download_type": "translated"}}
    tokens = {}
    _env(monkeypatch, jobs, tokens)
    tok = ge._create_download_token("j2")
    assert tokens[tok]["download_type"] == "podcast"


def test_existing_audio_token_still_reused(monkeypatch):
    jobs = {"j3": {"status": "done", "info": None}}
    tokens = {"TR": {"job_id": "j3", "download_type": "translated"},
              "AU": {"job_id": "j3", "download_type": "audio"}}
    _env(monkeypatch, jobs, tokens)
    assert ge._create_download_token("j3") == "AU"


def test_api_generate_resets_translated_notify_type(monkeypatch):
    """Dopo l'adopt il job torna 'analyzed' con notify_download_type ancora
    'translated': /api/generate deve riportarlo ad 'audio'. Il blocco di
    manutenzione ferma la richiesta subito dopo l'assegnazione."""
    monkeypatch.setattr(audiobook_app, "_premium_model_gate", lambda v: None)
    monkeypatch.setattr(audiobook_app, "_suspend_new_jobs", True)
    j = {"status": "analyzed", "client_id": CID, "original_filename": "x.epub",
         "created_at": 0, "last_poll": 0, "notify_download_type": "translated",
         "email_registered": True, "notify_email": "u@example.com"}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["tr-audio-job"] = j
    try:
        audiobook_app.app.config["TESTING"] = True
        with audiobook_app.app.test_client() as c:
            c.set_cookie("abm_cid", CID)
            r = c.post("/api/generate", json={"job_id": "tr-audio-job",
                                              "voice": "de-DE-KatjaNeural", "rate": "+0%",
                                              "output_format": "m4b", "single_file": True,
                                              "selected_chapters": [1]})
        assert r.status_code == 503
        assert j["notify_download_type"] == "audio"
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("tr-audio-job", None)
