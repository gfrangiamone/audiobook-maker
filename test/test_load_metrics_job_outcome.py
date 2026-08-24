"""Esito e durata dei job registrati in load_metrics da _set_job_status."""
import time

import pytest

import generation_engine as ge
import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def test_is_premium_job_recognises_paid_voice():
    assert ge.is_premium_job({"voice": "it-IT-Chirp3-HD-Charon"}) is False
    assert ge.is_premium_job({"voice": "gemini:gemini-2.5-flash-preview-tts:Kore"}) is True


def test_is_premium_job_recognises_consumed_payment():
    assert ge.is_premium_job({"voice": "it-IT-ElsaNeural", "payment_token": "t-1"}) is True
    assert ge.is_premium_job({"voice": "it-IT-ElsaNeural",
                              "payment_amount_eur": 1.5}) is True
    assert ge.is_premium_job({"voice": "it-IT-ElsaNeural"}) is False


def test_assembly_priority_agrees_with_is_premium_job():
    import assembly_queue as aq
    job = {"voice": "it-IT-ElsaNeural", "payment_token": "t-1"}
    assert ge._assembly_priority(job) == aq.PRIORITY_PREMIUM
    assert ge._assembly_priority({"voice": "it-IT-ElsaNeural"}) == aq.PRIORITY_NORMAL


def test_terminal_status_records_outcome_and_duration(monkeypatch):
    seen = {"obs": [], "inc": []}
    monkeypatch.setattr(lm, "observe",
                        lambda h, s, premium=False, now=None: seen["obs"].append((h, s, premium)))
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen["inc"].append((c, n)))
    job = {"job_id": "j1", "voice": "it-IT-ElsaNeural", "_texts_spilled": True,
           "_lm_gen_t0": time.time() - 45}
    ge._set_job_status(job, "done")
    assert ("job", pytest.approx(45, abs=2), False) in [
        (h, s, p) for h, s, p in seen["obs"]]
    assert ("done", 1) in seen["inc"]
    assert "_lm_gen_t0" not in job


def test_outcome_is_recorded_once_per_generation(monkeypatch):
    calls = []
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: calls.append(c))
    monkeypatch.setattr(lm, "observe", lambda *a, **k: None)
    job = {"job_id": "j2", "voice": "it-IT-ElsaNeural", "_texts_spilled": True,
           "_lm_gen_t0": time.time()}
    ge._set_job_status(job, "error")
    ge._set_job_status(job, "cancelled")
    assert calls.count("err") == 1
    assert "cancel" not in calls


def test_non_generation_status_records_nothing(monkeypatch):
    calls = []
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: calls.append(c))
    monkeypatch.setattr(lm, "observe", lambda *a, **k: None)
    ge._set_job_status({"job_id": "j3", "_texts_spilled": True}, "done")
    assert calls == []


def test_premium_job_counts_in_the_premium_branch(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "observe",
                        lambda h, s, premium=False, now=None: seen.append((h, premium)))
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append((c, None)))
    job = {"job_id": "j4", "voice": "gemini:gemini-2.5-flash-preview-tts:Kore",
           "_texts_spilled": True, "_lm_gen_t0": time.time()}
    ge._set_job_status(job, "done")
    assert ("job", True) in seen
    assert ("done_p", None) in seen
