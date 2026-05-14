"""Test per POST /api/paypal_create_order_gemini (server-side amount check)."""
import pytest
from unittest.mock import patch

from audiobook_app import app, jobs, _jobs_lock
from epub_to_tts import BookInfo, Chapter


@pytest.fixture
def client():
    app.config['TESTING'] = True
    with app.test_client() as c:
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
    with _jobs_lock:
        jobs["pj1"] = {"info": info, "status": "analyzed"}
    yield "pj1"
    with _jobs_lock:
        jobs.pop("pj1", None)


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
