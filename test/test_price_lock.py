"""Price lock (D1): il prezzo quotato al create dell'ordine PayPal e' il dovuto
alla conferma, anche se la stima empirica si e' mossa nel frattempo.

Incidente 21/08/2026 (job N-RUN2qrc2blK82lRX_NdA): ordine creato per 5,86€,
capture riuscita, conferma 40 secondi dopo con dovuto ricalcolato a 6,00€
(+2,4% per la deriva della media mobile in gemini_tts_rate_log.json). Il token
e' stato rifiutato con 402 `invalid_payment`, il job non e' partito e la capture
e' rimasta orfana fino al purge "stale analyzed" -> rimborso manuale.

Il lock e' registrato per order_id insieme alla firma degli input di prezzo:
se l'utente cambia voce/capitoli/velocita'/lingua/AI fra pagamento e conferma
la firma non combacia e il ricalcolo vivo torna a comandare.
"""
import time
from unittest.mock import patch

import pytest

import audiobook_app
import gemini_tts
import payment
from epub_to_tts import BookInfo, Chapter

GEMINI_VOICE = "gemini:flash25:Zephyr"

# NB: accesso a app/jobs/_jobs_lock SEMPRE via attributo a runtime, mai
# from-import: i test test_cold_*.py fanno importlib.reload(audiobook_app).


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
    """LLM 'disponibile', nessun thread reale, stato payment isolato su tmp."""
    # gemini_tts._available e' una cache di modulo risolta una sola volta a
    # processo (gia' all'import di audiobook_app, in base alle credenziali
    # reali della macchina) e mai piu' ricalcolata per il resto della sessione
    # pytest: senza questo monkeypatch il gate is_available() di
    # /api/generate su GEMINI_VOICE dipenderebbe da uno stato globale fuori
    # dal controllo di questo test. Auto-ripristinato da monkeypatch.
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    calls = []
    monkeypatch.setattr(
        audiobook_app, "run_optimization",
        lambda job_id, chapters: calls.append((job_id, chapters)),
    )
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    # Soglia bassa: anche un libro di test modesto richiede pagamento.
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.10")
    yield calls
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("plk-")]:
            audiobook_app.jobs.pop(jid, None)


def _post_optimize(client, job_id, **extra):
    payload = {
        "job_id": job_id,
        "batch": False,
        "lang": "it",
        "auto_generate": True,
        "voice": GEMINI_VOICE,
        "rate": "+0%",
        "single_file": True,
        "output_format": "m4b",
        "selected_chapters": [0],
    }
    payload.update(extra)
    return client.post("/api/optimize", json=payload)


def _capture(order_id, amount, job_id):
    payment._payments[order_id] = {
        "order_id": order_id, "amount_eur": amount, "email": "buyer@example.com",
        "job_id": job_id, "captured_at": time.time(), "used": False, "used_at": None,
        "capture_id": "CAP-" + order_id,
    }


# --------------------------------------------------------------------------
# Helper puri
# --------------------------------------------------------------------------

def test_signature_ignores_selection_shape():
    """Nessuna selezione e selezione esplicita di tutti i capitoli devono dare
    la stessa firma: e' il caso piu' comune, se divergesse il lock non si
    applicherebbe mai."""
    a = audiobook_app._pricing_signature(GEMINI_VOICE, [2, 0, 1], "+0%", "it", True)
    b = audiobook_app._pricing_signature(GEMINI_VOICE, [0, 1, 2], "+0%", "IT", True)
    assert a == b
    assert a != audiobook_app._pricing_signature(GEMINI_VOICE, [0, 1], "+0%", "it", True)
    assert a != audiobook_app._pricing_signature(GEMINI_VOICE, [0, 1, 2], "+10%", "it", True)
    assert a != audiobook_app._pricing_signature(GEMINI_VOICE, [0, 1, 2], "+0%", "it", False)


def test_lock_expires_after_ttl(monkeypatch):
    job = {}
    sig = audiobook_app._pricing_signature(GEMINI_VOICE, [0], "+0%", "it", True)
    audiobook_app._price_lock_store(job, "ORD-TTL", sig, 5.86)
    assert audiobook_app._price_lock_lookup(job, "ORD-TTL", sig) == 5.86
    job["price_locks"]["ORD-TTL"]["ts"] = time.time() - audiobook_app._PRICE_LOCK_TTL_SEC - 1
    assert audiobook_app._price_lock_lookup(job, "ORD-TTL", sig) is None


def test_lock_is_per_order_and_bounded():
    """Piu' ordini sullo stesso job (doppio click sul bottone): ognuno porta il
    proprio importo. Il dizionario resta limitato."""
    job = {}
    sig = audiobook_app._pricing_signature(GEMINI_VOICE, [0], "+0%", "it", True)
    audiobook_app._price_lock_store(job, "ORD-A", sig, 5.86)
    audiobook_app._price_lock_store(job, "ORD-B", sig, 5.90)
    assert audiobook_app._price_lock_lookup(job, "ORD-A", sig) == 5.86
    assert audiobook_app._price_lock_lookup(job, "ORD-B", sig) == 5.90
    for i in range(audiobook_app._PRICE_LOCK_MAX_PER_JOB + 3):
        audiobook_app._price_lock_store(job, f"ORD-{i}", sig, 1.0 + i)
    assert len(job["price_locks"]) <= audiobook_app._PRICE_LOCK_MAX_PER_JOB
    assert audiobook_app._price_lock_lookup(job, "ORD-A", sig) is None  # sfrattato


def test_lookup_ignores_unknown_token_and_changed_inputs():
    job = {}
    sig = audiobook_app._pricing_signature(GEMINI_VOICE, [0], "+0%", "it", True)
    audiobook_app._price_lock_store(job, "ORD-X", sig, 5.86)
    other = audiobook_app._pricing_signature(GEMINI_VOICE, [0, 1], "+0%", "it", True)
    assert audiobook_app._price_lock_lookup(job, "ORD-X", other) is None
    assert audiobook_app._price_lock_lookup(job, "ORD-ALTRO", sig) is None
    assert audiobook_app._price_lock_lookup(job, "", sig) is None


# --------------------------------------------------------------------------
# Create order -> lock registrato
# --------------------------------------------------------------------------

def test_create_order_registers_lock(client, env):
    job = _mk_job("plk-create")
    est = client.post("/api/combined_estimate", json={
        "job_id": "plk-create", "voice_id": GEMINI_VOICE,
        "selected_chapters": [0], "ai_opt_enabled": True,
    }).get_json()
    amount = est["total_eur"]
    assert amount > 0
    with patch("payment._paypal_create_order") as mock:
        mock.return_value = {"id": "ORD-LOCK", "status": "CREATED"}
        r = client.post("/api/paypal_create_order_gemini", json={
            "job_id": "plk-create", "voice_id": GEMINI_VOICE,
            "selected_chapters": [0], "ai_opt_enabled": True,
            "rate": "+0%", "lang": "it", "amount_eur": amount,
        })
    assert r.status_code == 200, r.get_data(as_text=True)
    sig = audiobook_app._pricing_signature(GEMINI_VOICE, [0], "+0%", "it", True)
    assert audiobook_app._price_lock_lookup(job, "ORD-LOCK", sig) == round(amount, 2)


# --------------------------------------------------------------------------
# Consume: il prezzo lockato vince sul ricalcolo derivato
# --------------------------------------------------------------------------

def _create_order(client, job_id, amount, **extra):
    payload = {
        "job_id": job_id, "voice_id": GEMINI_VOICE, "selected_chapters": [0],
        "ai_opt_enabled": True, "rate": "+0%", "lang": "it", "amount_eur": amount,
    }
    payload.update(extra)
    with patch("payment._paypal_create_order") as mock:
        mock.return_value = {"id": "ORD-PAID", "status": "CREATED"}
        return client.post("/api/paypal_create_order_gemini", json=payload)


def _estimate_total(client, job_id, ai=True):
    return client.post("/api/combined_estimate", json={
        "job_id": job_id, "voice_id": GEMINI_VOICE,
        "selected_chapters": [0], "ai_opt_enabled": ai,
    }).get_json()["total_eur"]


def _inflate_estimate(monkeypatch, factor):
    """Simula la deriva della media mobile empirica fra pagamento e conferma."""
    import gemini_tts
    _orig = gemini_tts.estimate_book_cost

    def _drifted(*a, **k):
        est = dict(_orig(*a, **k))
        for _k in ("user_price_eur", "list_price_eur"):
            if _k in est:
                est[_k] = round(float(est[_k]) * factor, 2)
        return est

    monkeypatch.setattr(gemini_tts, "estimate_book_cost", _drifted)


def test_drifted_price_does_not_reject_paid_token(client, env, monkeypatch):
    """Il caso dell'incidente: si paga l'importo quotato, il prezzo sale del
    2,4% prima della conferma. Senza lock -> 402 e capture orfana."""
    job = _mk_job("plk-drift")
    paid = _estimate_total(client, "plk-drift")
    assert _create_order(client, "plk-drift", paid).status_code == 200
    _capture("ORD-PAID", paid, "plk-drift")

    _inflate_estimate(monkeypatch, 1.024)
    # Il test non deve poter diventare vacuo: la deriva dev'essere davvero
    # oltre la tolleranza di 0,05€ del consumo token.
    assert _estimate_total(client, "plk-drift") - paid > 0.05
    r = _post_optimize(client, "plk-drift", payment_token="ORD-PAID")

    assert r.status_code == 200, r.get_data(as_text=True)
    assert payment._payments["ORD-PAID"]["used"] is True
    assert payment._payments["ORD-PAID"]["used_job_id"] == "plk-drift"
    # Addebito registrato = importo pagato, non il ricalcolo derivato.
    assert job["payment_amount_eur"] == pytest.approx(paid, abs=0.01)
    assert env and env[0][0] == "plk-drift"


def test_unquoted_price_still_rejects(client, env, monkeypatch):
    """Controprova: un importo mai quotato per questo job — ne' al create
    dell'ordine ne' dalla stima — resta rifiutato. I lock non aprono un buco."""
    _mk_job("plk-nolock")
    paid = _estimate_total(client, "plk-nolock")
    # Capture "dal nulla" per un importo che nessuna quotazione ha mai emesso.
    _capture("ORD-PAID", round(paid * 0.4, 2), "plk-nolock")
    _inflate_estimate(monkeypatch, 1.30)
    r = _post_optimize(client, "plk-nolock", payment_token="ORD-PAID")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "invalid_payment"
    assert payment._payments["ORD-PAID"]["used"] is False


def test_quote_lock_covers_estimate_to_payment(client, env, monkeypatch):
    """Quote lock (D2): l'importo mostrato dalla stima e' esigibile anche se il
    create dell'ordine non ha registrato nulla (path voucher/pagamento diretto)
    e la media mobile si e' mossa nel frattempo."""
    job = _mk_job("plk-quote")
    paid = _estimate_total(client, "plk-quote")
    _capture("ORD-PAID", paid, "plk-quote")  # nessun create: solo la stima quota
    _inflate_estimate(monkeypatch, 1.30)
    r = _post_optimize(client, "plk-quote", payment_token="ORD-PAID")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert job["payment_amount_eur"] == pytest.approx(paid, abs=0.01)


def test_quote_lock_expires(client, env, monkeypatch):
    """Oltre il TTL la quotazione non difende piu' l'importo pagato."""
    job = _mk_job("plk-quote-ttl")
    paid = _estimate_total(client, "plk-quote-ttl")
    _capture("ORD-PAID", paid, "plk-quote-ttl")
    for rec in (job.get("quote_locks") or {}).values():
        rec["ts"] -= audiobook_app._QUOTE_LOCK_TTL_SEC + 1
    _inflate_estimate(monkeypatch, 1.30)
    r = _post_optimize(client, "plk-quote-ttl", payment_token="ORD-PAID")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert payment._payments["ORD-PAID"]["used"] is False


def test_lock_not_applied_if_selection_changed(client, env, monkeypatch):
    """L'utente paga per un capitolo e poi ne seleziona due: il lock non vale,
    il dovuto torna a essere quello ricalcolato."""
    ch0 = Chapter(index=0, title="Cap0", text="A" * 300_000)
    ch1 = Chapter(index=1, title="Cap1", text="B" * 300_000)
    info = BookInfo(title="T", author="A", language="it", chapters=[ch0, ch1],
                    total_words=1, total_chars=600_000,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["plk-sel"] = {"info": info, "status": "analyzed"}
    paid = _estimate_total(client, "plk-sel")
    assert _create_order(client, "plk-sel", paid).status_code == 200
    _capture("ORD-PAID", paid, "plk-sel")
    # Conferma su DUE capitoli: prezzo molto piu' alto del pagato.
    r = _post_optimize(client, "plk-sel", payment_token="ORD-PAID",
                       selected_chapters=[0, 1])
    assert r.status_code == 402, r.get_data(as_text=True)
    assert payment._payments["ORD-PAID"]["used"] is False


def test_lock_applies_to_generate_without_ai(client, env, monkeypatch):
    """Percorso voce PREMIUM senza ottimizzazione AI: paga -> /api/generate."""
    job = _mk_job("plk-gen")
    est = client.post("/api/combined_estimate", json={
        "job_id": "plk-gen", "voice_id": GEMINI_VOICE,
        "selected_chapters": [0], "ai_opt_enabled": False,
    }).get_json()
    paid = est["total_eur"]
    assert _create_order(client, "plk-gen", paid, ai_opt_enabled=False).status_code == 200
    _capture("ORD-PAID", paid, "plk-gen")

    _inflate_estimate(monkeypatch, 1.024)
    monkeypatch.setattr(audiobook_app, "run_generation", lambda *a, **k: None)
    r = client.post("/api/generate", json={
        "job_id": "plk-gen", "voice": GEMINI_VOICE, "rate": "+0%", "lang": "it",
        "selected_chapters": [0], "single_file": True, "output_format": "m4b",
        "payment_token": "ORD-PAID",
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    assert payment._payments["ORD-PAID"]["used"] is True
    assert job["payment"]["total_eur"] == pytest.approx(paid, abs=0.01)
