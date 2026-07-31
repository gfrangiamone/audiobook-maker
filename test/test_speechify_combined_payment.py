"""Regressione: enforcement del pagamento TTS Speechify (Simba) nel flusso
combinato "ottimizza AI + auto_generate" (wizard).

Difetto (job gApjBiIPFSKocjpdD0ar1g, marigolds): /api/optimize applicava
l'enforcement del pagamento premium SOLO alle voci Gemini (`_is_combined_gemini`).
Per una voce Speechify il flusso auto_generate chiama run_generation diretto,
bypassando il preflight pagamento di /api/generate; senza un enforcement in
/api/optimize il TTS Simba veniva erogato GRATIS ogni volta che la sola quota
LLM cadeva sotto soglia -> margine economico negativo (costo provider non
incassato).

Fix: ramo `_is_combined_speechify` speculare a quello Gemini, che calcola la
quota Simba (speechify_tts.estimate_book_cost) e impone il 402 payment_required
se manca un token che copra LLM + TTS.
"""
import pytest


class _Ch:
    def __init__(self, index, text):
        self.index = index
        self.text = text
        self.char_count = len(text)
        self.word_count = max(1, len(text.split()))


class _Info:
    def __init__(self, chapters):
        self.chapters = chapters
        self.title = "Test Book"
        self.language = "en"


def _setup(monkeypatch, audiobook_app, job_id, chars, tmp_path):
    # ~`chars` caratteri: quota Speechify sopra soglia, quota LLM sotto soglia.
    info = _Info([_Ch(1, "a" * chars)])
    # Job legacy senza client_id -> _check_job_owner passa senza cookie.
    audiobook_app.jobs = {job_id: {"job_id": job_id, "status": "analyzed",
                                   "info": info}}
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    monkeypatch.setattr(audiobook_app.speechify_tts, "is_available", lambda: True)
    # Nessun avvio reale dell'ottimizzazione (i path che partono lo fanno solo
    # DOPO il pagamento andato a buon fine; qui ci fermiamo sul 402).
    monkeypatch.setattr(audiobook_app, "run_optimization", lambda *a, **k: None)
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_SPEECHIFY_COST_USD_PER_MCHAR", "11.18")
    monkeypatch.setenv("ABM_SPEECHIFY_MARGIN_PERCENT", "60")
    # Isola la quota gratuita cumulativa (Task 6) dal file reale di
    # ABM_DATA_DIR: senza questo i test leggerebbero/scriverebbero
    # _free_quota.json nell'ambiente dev reale, con stato residuo tra run.
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))


def test_speechify_autogen_requires_payment_when_llm_below_threshold(monkeypatch, tmp_path):
    import audiobook_app
    if not hasattr(audiobook_app, "jobs"):
        pytest.skip("audiobook_app.jobs non trovato")
    # 40k caratteri: quota Simba ~1.4€ (> 0.50), quota LLM << 0.50 (free).
    _setup(monkeypatch, audiobook_app, "SPX1", 40_000, tmp_path)

    # Sanity: la quota Simba supera la soglia, la quota LLM no.
    spx_eur = audiobook_app.speechify_tts.compute_user_price_eur(40_000)["user_price_eur"]
    assert spx_eur > 0.50
    assert audiobook_app._estimate_llm_cost_eur(40_000) <= 0.50

    client = audiobook_app.app.test_client()
    resp = client.post("/api/optimize", json={
        "job_id": "SPX1",
        "voice": "speechify:simba-3.2:harper_32",
        "auto_generate": True,
        "batch": False,
        "lang": "en",
        # NESSUN payment_token: prima del fix il job partiva gratis (200/started).
    })
    assert resp.status_code == 402, \
        f"atteso 402 payment_required, ottenuto {resp.status_code}: {resp.get_json()}"
    data = resp.get_json()
    assert data.get("error_code") == "payment_required"
    assert data.get("speechify_eur", 0) > 0.50
    assert data.get("total_eur", 0) >= data.get("speechify_eur", 0)
    # Il claim "optimizing" deve essere stato rilasciato (retry possibile).
    assert audiobook_app.jobs["SPX1"]["status"] == "analyzed"


def test_speechify_autogen_bad_token_rejected(monkeypatch, tmp_path):
    import audiobook_app
    if not hasattr(audiobook_app, "jobs"):
        pytest.skip("audiobook_app.jobs non trovato")
    _setup(monkeypatch, audiobook_app, "SPX2", 40_000, tmp_path)

    client = audiobook_app.app.test_client()
    resp = client.post("/api/optimize", json={
        "job_id": "SPX2",
        "voice": "speechify:simba-3.2:harper_32",
        "auto_generate": True,
        "batch": False,
        "lang": "en",
        "payment_token": "does-not-exist-token",
    })
    # Token sconosciuto/non consumabile -> non deve partire gratis.
    assert resp.status_code == 402
    assert resp.get_json().get("error_code") == "invalid_payment"
    assert audiobook_app.jobs["SPX2"]["status"] == "analyzed"


def test_speechify_autogen_free_when_below_threshold(monkeypatch, tmp_path):
    import audiobook_app
    if not hasattr(audiobook_app, "jobs"):
        pytest.skip("audiobook_app.jobs non trovato")
    # 2k caratteri: quota Simba < 0.50, totale sotto soglia -> job free, parte.
    _setup(monkeypatch, audiobook_app, "SPX3", 2_000, tmp_path)
    assert audiobook_app.speechify_tts.compute_user_price_eur(2_000)["user_price_eur"] <= 0.50

    client = audiobook_app.app.test_client()
    resp = client.post("/api/optimize", json={
        "job_id": "SPX3",
        "voice": "speechify:simba-3.2:harper_32",
        "auto_generate": True,
        "batch": False,
        "lang": "en",
    })
    assert resp.status_code == 200, resp.get_json()
    assert resp.get_json().get("status") == "started"
