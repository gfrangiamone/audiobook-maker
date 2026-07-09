"""Test per POST /api/paypal_create_order (ottimizzazione AI standalone).

L'importo dell'ordine deve essere allineato a /api/optimize_estimate e
/api/optimize: capitoli gia' ottimizzati esclusi dal conteggio, altrimenti
la capture PayPal supererebbe il costo reale del job.
"""
import pytest
from unittest.mock import patch

import audiobook_app
from epub_to_tts import BookInfo, Chapter

# NB: accesso a app/jobs via attributo a runtime (mai from-import): altri test
# ricaricano audiobook_app (vedi nota in test_paypal_create_gemini.py).


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


def _mk_job(job_id, optimized=None):
    # 3 x 400k = 1.2M char: sotto MAX_TEXT_CHARS (1.5M) ma sopra la soglia
    # free (1.2M x 1.10 EUR/M = ~1.32 EUR > 0.50).
    chs = [Chapter(index=i, title=f"Cap{i}", text="X" * 400000) for i in range(3)]
    info = BookInfo(
        title="T", author="A", language="it", chapters=chs,
        total_words=sum(c.word_count for c in chs),
        total_chars=sum(c.char_count for c in chs),
        estimated_duration_minutes=1.0,
    )
    job = {"info": info, "status": "analyzed"}
    if optimized is not None:
        job["optimized_chapters"] = list(optimized)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = job
    return job


def _cleanup(job_id):
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop(job_id, None)


def _create_order(client, job_id, selected=None):
    """Chiama l'endpoint con PayPal mockato; ritorna (status, body, cost_addebitato)."""
    captured = {}

    def _fake_order(cost, description, custom_id=None):
        captured["cost"] = cost
        return {"id": "ORDER-TEST", "status": "CREATED", "purchase_units": []}

    body = {"job_id": job_id}
    if selected is not None:
        body["selected_chapters"] = selected
    with patch.object(audiobook_app, "_paypal_available", return_value=True), \
         patch.object(audiobook_app, "_paypal_create_order", side_effect=_fake_order):
        r = client.post("/api/paypal_create_order", json=body)
    return r.status_code, r.get_json(), captured.get("cost")


def test_create_order_llm_amount_matches_estimate(client):
    jid = "llmord1"
    _mk_job(jid)
    try:
        est = client.get(f"/api/optimize_estimate/{jid}").get_json()
        assert est["requires_payment"]
        status, body, cost = _create_order(client, jid)
        assert status == 200, body
        assert body["order_id"] == "ORDER-TEST"
        assert cost == pytest.approx(est["cost_eur"])
        assert body["amount_eur"] == pytest.approx(est["cost_eur"])
    finally:
        _cleanup(jid)


def test_create_order_llm_excludes_already_optimized(client):
    """Capitolo 0 gia' ottimizzato: l'ordine addebita solo i capitoli 1-2,
    come /api/optimize_estimate (regressione sovra-addebito)."""
    jid = "llmord2"
    _mk_job(jid, optimized=[0])
    try:
        est = client.get(f"/api/optimize_estimate/{jid}").get_json()
        status, body, cost = _create_order(client, jid)
        assert status == 200, body
        assert cost == pytest.approx(est["cost_eur"])
        # 2 capitoli su 3: il costo deve essere ~2/3 di quello full-book
        full = audiobook_app._estimate_llm_cost_eur(3 * 400000)
        assert cost < full
    finally:
        _cleanup(jid)


def test_create_order_llm_selected_subset(client):
    jid = "llmord3"
    _mk_job(jid, optimized=[1])
    try:
        # Selezione {0,1}, con 1 gia' ottimizzato -> addebita solo il cap 0
        est = client.get(
            f"/api/optimize_estimate/{jid}?selected_chapters=0&selected_chapters=1"
        ).get_json()
        status, body, cost = _create_order(client, jid, selected=[0, 1])
        assert status == 200, body
        assert cost == pytest.approx(est["cost_eur"])
        assert cost == pytest.approx(audiobook_app._estimate_llm_cost_eur(400000))
    finally:
        _cleanup(jid)


def test_create_order_llm_free_below_threshold(client):
    jid = "llmord4"
    chs = [Chapter(index=0, title="Cap0", text="X" * 1000)]
    info = BookInfo(title="T", author="A", language="it", chapters=chs,
                    total_words=chs[0].word_count, total_chars=chs[0].char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[jid] = {"info": info, "status": "analyzed"}
    try:
        status, body, cost = _create_order(client, jid)
        assert status == 400
        assert "not required" in (body.get("error") or "").lower()
    finally:
        _cleanup(jid)
