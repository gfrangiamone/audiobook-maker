"""Correzione 4: la riserva di budget preflight in /api/generate si fa sul
caso PEGGIORE fra i backend abilitati (worst_case_cost_breakdown), non sul
listino mostrato/addebitato all'utente (D1 tiene il prezzo fisso, il costo
reale no). Se il modello e' configurato su Cloudflare e il circuit breaker
devia a meta' job su Vertex, il costo reale puo' superare il listino misto:
una riserva sul listino sforerebbe il cap interno in silenzio.

flash31 e' l'unico modello con `id_cloudflare` configurato (flash25 resta
sempre su Vertex): serve a far divergere listino e caso-peggiore.
"""
import time
from unittest.mock import patch

import pytest

import audiobook_app
import gemini_tts
import payment
from epub_to_tts import BookInfo, Chapter

VOICE = "gemini:flash31:Kore"


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


def _mk_job(job_id, n_chars=300_000):
    ch = Chapter(index=0, title="Cap0", text="A" * n_chars)
    info = BookInfo(
        title="T", author="A", language="it", chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": "analyzed"}
    return audiobook_app.jobs[job_id]


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "run_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.10")
    yield
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("pfw-")]:
            audiobook_app.jobs.pop(jid, None)


def _generate(client, job_id, **extra):
    payload = {
        "job_id": job_id, "voice": VOICE, "rate": "+0%", "lang": "it",
        "selected_chapters": [0], "single_file": True, "output_format": "m4b",
    }
    payload.update(extra)
    return client.post("/api/generate", json=payload)


def _pay(client, job_id, amount_eur, order_id):
    """Crea e cattura un ordine PayPal fittizio per superare la soglia
    gratuita, cosi' /api/generate arriva davvero al blocco di preflight
    invece di fermarsi prima a payment_required."""
    with patch("payment._paypal_create_order") as mock:
        mock.return_value = {"id": order_id, "status": "CREATED"}
        r = client.post("/api/paypal_create_order_gemini", json={
            "job_id": job_id, "voice_id": VOICE, "selected_chapters": [0],
            "ai_opt_enabled": False, "rate": "+0%", "lang": "it",
            "amount_eur": amount_eur,
        })
    assert r.status_code == 200, r.get_data(as_text=True)
    payment._payments[order_id] = {
        "order_id": order_id, "amount_eur": amount_eur,
        "email": "buyer@example.com", "job_id": job_id,
        "captured_at": time.time(), "used": False, "used_at": None,
        "capture_id": "CAP-" + order_id,
    }


def test_reservation_equals_listino_when_cloudflare_not_configured(client, env, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    _mk_job("pfw-vertex")
    amount = client.post("/api/combined_estimate", json={
        "job_id": "pfw-vertex", "voice_id": VOICE,
        "selected_chapters": [0], "ai_opt_enabled": False,
    }).get_json()["total_eur"]
    _pay(client, "pfw-vertex", amount, "ORD-VERTEX")
    captured = {}
    monkeypatch.setattr(gemini_tts, "reserve_budget",
                        lambda job_id, eur: captured.setdefault("eur", eur))

    r = _generate(client, "pfw-vertex", payment_token="ORD-VERTEX")

    assert r.status_code == 200, r.get_data(as_text=True)
    job = audiobook_app.jobs["pfw-vertex"]
    listino = float(job["gemini_estimate"]["google_cost_eur"])
    assert captured["eur"] == pytest.approx(listino, rel=1e-6)


def test_reservation_exceeds_listino_when_cloudflare_is_configured(client, env, monkeypatch):
    """Il caso del rilievo Correzione 4: con Cloudflare abilitato il listino e'
    piu' economico della tariffa Vertex pura (share del risparmio ceduto al
    cliente), quindi la riserva sul caso peggiore deve essere strettamente
    superiore al listino - mai uguale, mai inferiore."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    _mk_job("pfw-cf")
    amount = client.post("/api/combined_estimate", json={
        "job_id": "pfw-cf", "voice_id": VOICE,
        "selected_chapters": [0], "ai_opt_enabled": False,
    }).get_json()["total_eur"]
    _pay(client, "pfw-cf", amount, "ORD-CF")
    captured = {}
    monkeypatch.setattr(gemini_tts, "reserve_budget",
                        lambda job_id, eur: captured.setdefault("eur", eur))

    r = _generate(client, "pfw-cf", payment_token="ORD-CF")

    assert r.status_code == 200, r.get_data(as_text=True)
    job = audiobook_app.jobs["pfw-cf"]
    est = job["gemini_estimate"]
    cost_listino = float(est["google_cost_eur"])
    assert captured["eur"] > cost_listino
    # E deve combaciare esattamente col caso peggiore calcolato sugli stessi
    # token stimati (nessuna euristica separata/duplicata nel call site).
    worst = gemini_tts.worst_case_cost_breakdown(
        est.get("input_tokens_est", 0), est.get("output_tokens_est", 0),
        est.get("model_key"))
    assert captured["eur"] == pytest.approx(worst["total_eur"], rel=1e-6)
    # Il prezzo addebitato all'utente resta quello di LISTINO (est_pre/
    # gemini_estimate["user_price_eur"], invariato da questa correzione): la
    # riserva piu' alta e' interna, non si riversa mai sull'importo pagato.
    price_charged = float(job["payment"]["total_eur"])
    price_listino = round(float(est["user_price_eur"]), 2)
    assert price_charged == pytest.approx(price_listino, rel=1e-6)
