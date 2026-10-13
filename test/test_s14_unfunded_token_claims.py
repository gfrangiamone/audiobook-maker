"""S14 (trovato durante M4, 2026-10-13): un capture PayPal `pending_unfunded`
(eCheck: denaro non incassato) resta in `_payments` per tracciabilita' ma non
e' spendibile. `consume_payment_token` lo rifiutava; i cinque claim
check-and-set di audiobook_app (ottimizzazione standalone e combinata Gemini/
Speechify/VoxCPM, traduzione) no: l'order_id passava come payment_token.
"""
import inspect
import re
import time

import pytest

import audiobook_app
import payment
from epub_to_tts import BookInfo, Chapter

GEMINI_VOICE = "gemini:flash31:Zephyr"


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    calls = []
    monkeypatch.setattr(audiobook_app, "run_optimization",
                        lambda job_id, chapters: calls.append((job_id, chapters)))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.10")
    yield calls
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("s14-")]:
            audiobook_app.jobs.pop(jid, None)


def _mk_job(job_id, n_chars):
    ch = Chapter(index=0, title="Cap0", text="A" * n_chars)
    info = BookInfo(title="T", author="A", language="it", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": "analyzed"}
    return audiobook_app.jobs[job_id]


def _unfunded(order_id):
    payment._payments[order_id] = {
        "order_id": order_id, "amount_eur": 99.0, "email": "x@y.it",
        "captured_at": time.time(), "used": False, "pending_unfunded": True,
        "capture_status": "PENDING", "pending_reason": "ECHECK",
    }


def _post_optimize(client, job_id, **extra):
    payload = {"job_id": job_id, "batch": False, "lang": "it", "auto_generate": True,
               "voice": GEMINI_VOICE, "rate": "+0%", "single_file": True, "output_format": "m4b"}
    payload.update(extra)
    return client.post("/api/optimize", json=payload)


def test_combinato_gemini_rifiuta_il_capture_non_finanziato(client, env):
    job = _mk_job("s14-comb", 300_000)
    _unfunded("ORD-ECHECK")
    r = _post_optimize(client, "s14-comb", payment_token="ORD-ECHECK")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "invalid_payment"
    assert payment._payments["ORD-ECHECK"]["used"] is False     # non consumato
    assert job["status"] == "analyzed" and env == []


def test_standalone_llm_rifiuta_il_capture_non_finanziato(client, env):
    job = _mk_job("s14-llm", 600_000)
    _unfunded("ORD-ECHECK2")
    r = _post_optimize(client, "s14-llm", auto_generate=False,
                       voice="it-IT-IsabellaNeural", payment_token="ORD-ECHECK2")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "invalid_payment"
    assert payment._payments["ORD-ECHECK2"]["used"] is False
    assert job["status"] == "analyzed" and env == []


def test_lo_stesso_capture_finanziato_viene_accettato(client, env):
    """Controprova: senza il flag il claim passa come prima."""
    _mk_job("s14-ok", 600_000)
    _unfunded("ORD-OK")
    del payment._payments["ORD-OK"]["pending_unfunded"]
    r = _post_optimize(client, "s14-ok", auto_generate=False,
                       voice="it-IT-IsabellaNeural", payment_token="ORD-OK")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert payment._payments["ORD-OK"]["used"] is True


def test_tutti_i_claim_sotto_lock_controllano_pending_unfunded():
    src = inspect.getsource(audiobook_app)
    claims = re.findall(r'not (\w+)\.get\("used"\)([^\n]*)', src)
    assert len(claims) == 5, claims
    for var, rest in claims:
        assert f'not {var}.get("pending_unfunded")' in rest, (var, rest)
