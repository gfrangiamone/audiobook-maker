"""Incidente yKsP1JQaXgYY2RzxsBKjEw (2026-10-01): ottimizzazione AI fallita
e rimborsata con voucher, ma il descrittore in _pending_jobs.json restava
"running"; al riavvio successivo il recovery rilanciava ottimizzazione e
generazione di un job gia' rimborsato. I path di errore/annullamento di
run_optimization devono marcare `failed` il descrittore."""
import pytest

import generation_engine as ge
import pending_jobs


class _Ch:
    def __init__(self, index, text):
        self.index = index
        self.title = f"Cap {index}"
        self.text = text
        self.char_count = len(text)
        self.word_count = len(text.split())


class _Info:
    def __init__(self):
        self.title = "Libro"
        self.chapters = [_Ch(1, "Testo del capitolo uno.")]


@pytest.fixture
def harness(monkeypatch):
    jobs = {}
    monkeypatch.setattr(ge, "_jobs", jobs)
    monkeypatch.setattr(ge, "_set_job_status", lambda j, s: j.update({"status": s}))
    monkeypatch.setattr(ge, "rehydrate_job_texts", lambda *a, **k: None)
    monkeypatch.setattr(ge, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(ge, "_write_optimization_audit", lambda *a, **k: None)
    monkeypatch.setattr(ge, "_send_optimization_failed_email", lambda *a, **k: None)
    refunds, failed = [], []
    monkeypatch.setattr(ge, "_refund_job_payment",
                        lambda jid, job, reason: refunds.append((jid, reason)))
    monkeypatch.setattr(pending_jobs, "mark_failed", lambda jid: failed.append(jid))
    return jobs, refunds, failed


def _job():
    return {"info": _Info(), "email_registered": True, "opt_lang": "pl",
            "opt_auto_generate": True}


def test_optimization_error_marks_pending_failed(harness, monkeypatch):
    jobs, refunds, failed = harness
    jobs["e1"] = _job()

    def boom(*a, **k):
        raise RuntimeError("SSL DECRYPTION_FAILED_OR_BAD_RECORD_MAC")

    monkeypatch.setattr(ge, "_optimize_chapter_text", boom)
    ge.run_optimization("e1")
    assert jobs["e1"]["status"] == "error"
    assert refunds == [("e1", "error")]
    assert failed == ["e1"]


def test_optimization_cancel_marks_pending_failed(harness, monkeypatch):
    jobs, refunds, failed = harness
    jobs["c1"] = _job()

    def cancel(*a, **k):
        jobs["c1"]["opt_cancelled"] = True
        raise ge._CancelledError("Optimization cancelled")

    monkeypatch.setattr(ge, "_optimize_chapter_text", cancel)
    ge.run_optimization("c1")
    assert jobs["c1"]["status"] == "analyzed"
    assert refunds == [("c1", "cancel")]
    assert failed == ["c1"]
