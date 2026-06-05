# test/test_run_translation.py
import time
import types
import pytest
from pathlib import Path
from unittest.mock import patch

import generation_engine as ge
import translation_core as tc


class _Ch:
    def __init__(self, index, title, text):
        self.index, self.title, self.text = index, title, text
        self.char_count = len(text)
        self.word_count = len(text.split())


class _Info:
    title = "Libro"
    author = "Autore"
    language = "it"
    def __init__(self):
        self.chapters = [_Ch(1, "Uno", "Testo uno."), _Ch(2, "Due", "Testo due.")]


def _seed_job(tmp_path, **extra):
    job_id = "TRJOB1"
    job = {
        "status": "translating",
        "client_id": "c1",
        "info": _Info(),
        "original_filename": "libro.epub",
        "last_poll": time.time(),
        "tr_params": {
            "source_lang": "it", "target_lang": "en",
            "output_format": "txt", "output_name": "libro",
            "optimize": False, "selected_chapters": [1, 2],
        },
    }
    job.update(extra)
    ge._jobs[job_id] = job
    return job_id, job


@pytest.fixture(autouse=True)
def _jobs_dict(monkeypatch):
    """Assicura che ge._jobs sia un dict e ge._jobs_lock esista (in prod sono
    iniettati via configure(); _set_job_status li legge come globali)."""
    monkeypatch.setattr(ge, "_jobs", {}, raising=True)
    monkeypatch.setattr(ge, "_jobs_lock", None, raising=False)
    yield


@pytest.fixture
def fake_llm(monkeypatch, tmp_path):
    """Mock del layer LLM del core: traduzione = upper()."""
    # In generation_engine la dir di upload e' il module-level _upload_dir.
    monkeypatch.setattr(ge, "_upload_dir", tmp_path, raising=True)
    monkeypatch.setattr(tc, "resolve_backend", lambda: "apikey")
    monkeypatch.setattr(tc, "make_client_provider",
                        lambda b: ((lambda: None), "m", "http://x"))
    monkeypatch.setattr(
        tc, "call_llm",
        lambda provider, sys_p, user, **kw: user.upper())
    monkeypatch.setattr(
        tc, "translate_titles",
        lambda provider, titles, s, t, **kw: [x + "_EN" for x in titles])
    yield


def test_run_translation_success_writes_file(fake_llm, tmp_path):
    job_id, job = _seed_job(tmp_path)
    ge.run_translation(job_id)
    assert job["status"] == "translated"
    out = Path(job["translated_path"])
    assert out.exists() and out.suffix == ".txt"
    body = out.read_text(encoding="utf-8")
    assert "TESTO UNO." in body
    assert job["translated_name"] == "libro.txt"
    assert [c["title"] for c in job["translated_chapters"]] == ["Uno_EN", "Due_EN"]
    assert job["translated_lang"] == "en"


def test_run_translation_respects_selection(fake_llm, tmp_path):
    job_id, job = _seed_job(tmp_path)
    job["tr_params"]["selected_chapters"] = [2]
    ge.run_translation(job_id)
    assert len(job["translated_chapters"]) == 1
    assert job["translated_chapters"][0]["text"] == "TESTO DUE."


def test_run_translation_error_refunds(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path, payment_type="voucher",
                            payment_token="V1", payment_amount_eur=2.0)
    def _boom(*a, **kw):
        raise tc.TranslationError("LLM giù")
    monkeypatch.setattr(tc, "call_llm", _boom)
    refunds = []
    monkeypatch.setattr(ge, "_refund_job_payment",
                        lambda jid, j, reason: refunds.append((jid, reason)))
    ge.run_translation(job_id)
    assert job["status"] == "error"
    assert refunds == [(job_id, "error")]


def test_run_translation_cancel_refunds_and_reverts(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path, tr_cancelled=True,
                            payment_type="voucher", payment_token="V1")
    refunds = []
    monkeypatch.setattr(ge, "_refund_job_payment",
                        lambda jid, j, reason: refunds.append(reason))
    ge.run_translation(job_id)
    assert job["status"] == "analyzed"
    assert refunds == ["cancel"]


def test_run_translation_heartbeat_timeout_cancels(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path)
    def _llm_then_stale(provider, sys_p, user, **kw):
        job["last_poll"] = time.time() - 9999  # heartbeat perso durante la chiamata
        return user.upper()
    monkeypatch.setattr(tc, "call_llm", _llm_then_stale)
    refunds = []
    monkeypatch.setattr(ge, "_refund_job_payment",
                        lambda jid, j, reason: refunds.append(reason))
    ge.run_translation(job_id)
    assert job["status"] == "analyzed"
    assert refunds == ["cancel"]


def test_run_translation_email_failure_does_not_refund(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path, email_registered=True,
                            notify_email="u@x.it",
                            payment_type="voucher", payment_token="V1")
    def _mail_boom(jid):
        raise RuntimeError("SMTP giù")
    monkeypatch.setattr(ge, "_send_translation_email", _mail_boom)
    refunds = []
    monkeypatch.setattr(ge, "_refund_job_payment",
                        lambda jid, j, reason: refunds.append(reason))
    ge.run_translation(job_id)
    assert job["status"] == "translated"  # email fallita NON invalida il lavoro
    assert refunds == []                   # e NON rimborsa


def test_run_translation_batch_skips_heartbeat_and_sends_email(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path, email_registered=True,
                            notify_email="u@x.it")
    job["last_poll"] = time.time() - 9999  # ignorato in batch
    sent = []
    monkeypatch.setattr(ge, "_send_translation_email",
                        lambda jid: sent.append(jid))
    ge.run_translation(job_id)
    assert job["status"] == "translated"
    assert sent == [job_id]
