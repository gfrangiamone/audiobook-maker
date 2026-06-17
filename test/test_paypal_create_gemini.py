"""Test per POST /api/paypal_create_order_gemini (server-side amount check)."""
import pytest
from unittest.mock import patch

import audiobook_app
from epub_to_tts import BookInfo, Chapter

# NB: accesso a app/jobs/_jobs_lock via attributo a runtime, mai from-import:
# i test test_cold_*.py (alfabeticamente precedenti) fanno
# importlib.reload(audiobook_app) e test_m4b_progress.py ri-binda
# audiobook_app.jobs; un from-import a collection time resterebbe legato
# agli oggetti pre-reload -> fallimenti solo nella suite completa.


@pytest.fixture
def client():
    audiobook_app.app.config['TESTING'] = True
    with audiobook_app.app.test_client() as c:
        yield c


def _make_chapter(idx, text):
    return Chapter(index=idx, title=f"Cap{idx}", text=text)


@pytest.fixture
def jb():
    # Big enough text so the gemini estimate yields a non-trivial price.
    txt = "X" * 60000
    ch = _make_chapter(0, txt)
    info = BookInfo(
        title="T",
        author="A",
        language="it",
        chapters=[ch],
        total_words=ch.word_count,
        total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["pj1"] = {"info": info, "status": "analyzed"}
    yield "pj1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("pj1", None)


def _server_total(client, job_id, voice_id, selected, ai_opt):
    est = client.post("/api/combined_estimate", json={
        "job_id": job_id,
        "voice_id": voice_id,
        "selected_chapters": selected,
        "ai_opt_enabled": ai_opt,
    }).get_json()
    return est["total_eur"]


def test_create_order_amount_mismatch_400(client, jb):
    r = client.post("/api/paypal_create_order_gemini", json={
        "job_id": "pj1",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
        "ai_opt_enabled": False,
        "amount_eur": 99.99,
    })
    assert r.status_code == 400, r.get_data(as_text=True)
    body = r.get_json()
    assert "mismatch" in (body.get("error") or "").lower()


def test_create_order_job_not_found(client):
    r = client.post("/api/paypal_create_order_gemini", json={
        "job_id": "nonexistent",
        "voice_id": "gemini:flash25:Zephyr",
        "selected_chapters": [0],
        "ai_opt_enabled": False,
        "amount_eur": 1.20,
    })
    assert r.status_code == 404


def test_create_order_success(client, jb):
    amount = _server_total(client, "pj1", "gemini:flash25:Zephyr", [0], False)
    assert amount > 0
    with patch("payment._paypal_create_order") as mock:
        mock.return_value = {"id": "ORDER123", "status": "CREATED"}
        r = client.post("/api/paypal_create_order_gemini", json={
            "job_id": "pj1",
            "voice_id": "gemini:flash25:Zephyr",
            "selected_chapters": [0],
            "ai_opt_enabled": False,
            "amount_eur": amount,
        })
    assert r.status_code == 200, r.get_data(as_text=True)
    body = r.get_json()
    assert body["order_id"] == "ORDER123"
    assert body["amount"] == amount
    assert body["status"] == "CREATED"


def test_llm_rate_respects_module_constant(client, jb, monkeypatch):
    """/api/paypal_create_order_gemini must use the canonical
    LLM_RATE_EUR_PER_MCHAR module constant when computing the
    server-side amount, so production deployments can tune the rate
    via ABM_LLM_RATE_EUR_PER_MCHAR.

    Strategy: patch the constant to a known value, recompute the
    server-side amount via /api/combined_estimate (which must also
    honour the same constant), then submit that amount to
    paypal_create_order_gemini and assert it is accepted (no mismatch).
    A control test with a deliberately stale amount must 400.
    """
    import audiobook_app

    monkeypatch.setattr(audiobook_app, "LLM_RATE_EUR_PER_MCHAR", 5.50)

    payload_est = {
        "job_id": "pj1",
        "voice_id": "edge:it-IT-DiegoNeural",  # non-gemini => only LLM cost
        "selected_chapters": [0],
        "ai_opt_enabled": True,
    }
    est = client.post("/api/combined_estimate", json=payload_est).get_json()
    amount = est["total_eur"]
    assert amount > 0
    # Sanity: with patched rate 5.50 and 60_000 chars => 0.33 EUR.
    chars = est["llm_breakdown"]["chars"]
    assert amount == round((chars / 1_000_000.0) * 5.50, 2)

    # Submitting the matching amount must pass the server-side check.
    with patch("payment._paypal_create_order") as mock:
        mock.return_value = {"id": "ORDER_RATE", "status": "CREATED"}
        r = client.post("/api/paypal_create_order_gemini", json={
            "job_id": "pj1",
            "voice_id": "edge:it-IT-DiegoNeural",
            "selected_chapters": [0],
            "ai_opt_enabled": True,
            "amount_eur": amount,
        })
    assert r.status_code == 200, r.get_data(as_text=True)

    # Control: with the rate still patched to 5.50, sending the amount
    # that would be correct at the default 1.10 must be rejected.
    stale_amount = round((chars / 1_000_000.0) * 1.10, 2)
    assert stale_amount != amount
    r2 = client.post("/api/paypal_create_order_gemini", json={
        "job_id": "pj1",
        "voice_id": "edge:it-IT-DiegoNeural",
        "selected_chapters": [0],
        "ai_opt_enabled": True,
        "amount_eur": stale_amount,
    })
    assert r2.status_code == 400, r2.get_data(as_text=True)


def test_create_order_paypal_exception_500(client, jb):
    amount = _server_total(client, "pj1", "gemini:flash25:Zephyr", [0], False)
    with patch("payment._paypal_create_order", side_effect=RuntimeError("PayPal not configured")):
        r = client.post("/api/paypal_create_order_gemini", json={
            "job_id": "pj1",
            "voice_id": "gemini:flash25:Zephyr",
            "selected_chapters": [0],
            "ai_opt_enabled": False,
            "amount_eur": amount,
        })
    assert r.status_code == 500
    assert "paypal" in (r.get_json().get("error") or "").lower()
