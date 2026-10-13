"""M2 (2026-10-13), correzioni puntuali sullo stato del job:
- il wrapper di crash di audiobook_app.run_generation passa da
  generation_engine._set_job_status (spill, storno quota, notifica, metriche)
  invece di scrivere status="error" a mano;
- _log_m4b_progress legge client_ip/browser_lang (le chiavi vere del job),
  non "ip"/"lang" che nessuno scriveva: le righe M4B_* restavano senza IP;
- run_translation salva tr_backend/tr_model sul job: l'audit admin delle
  traduzioni li mostrava sempre vuoti."""
import inspect
import re

import audiobook_app
import generation_engine as ge


def test_wrapper_crash_goes_through_set_job_status(monkeypatch):
    calls = []
    real = ge._set_job_status
    monkeypatch.setattr(ge, "_set_job_status", lambda job, status: calls.append(status) or real(job, status))
    monkeypatch.setattr(ge, "run_generation", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    job = {"status": "generating", "client_id": "c", "_texts_spilled": True}
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["m2-job"] = job
    try:
        audiobook_app.run_generation("m2-job", None, "it-IT-ElsaNeural", "+0%", True)
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("m2-job", None)
    assert calls == ["error"] and job["status"] == "error"
    assert job["progress_message"].startswith("Internal error: boom")


def test_m4b_log_carries_the_job_ip_and_lang(monkeypatch):
    seen = {}
    monkeypatch.setattr(ge, "_log_activity", lambda *a, **k: seen.update(k))
    job = {"client_ip": "203.0.113.9", "browser_lang": "de", "original_filename": "x.epub",
           "client_id": "c", "voice": "it-IT-ElsaNeural"}
    ge._log_m4b_progress("m2-job", job, "START", size_mb=1)
    assert seen.get("client_ip") == "203.0.113.9" and seen.get("browser_lang") == "de"


def test_no_reads_of_keys_nobody_writes():
    src = inspect.getsource(ge)
    assert not re.search(r'job\.get\("(ip|lang)"', src)
    assert 'job["tr_backend"] = backend' in src and 'job["tr_model"] = model' in src
