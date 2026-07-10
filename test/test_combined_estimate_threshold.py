"""Regressione: /api/combined_estimate deve restituire la soglia gratuita
coerente con l'engine premium ATTIVO.

Difetto (job Speechify bloccato a 0%): la stima calcolava is_free/threshold_eur
sempre su ABM_GEMINI_FREE_THRESHOLD_EUR. Per una voce Speechify, con soglia
Speechify < Gemini, un totale compreso tra le due soglie risultava is_free lato
UI (nessun payment token inviato) ma veniva respinto con 402 dal ramo Speechify
di /api/generate (che usa ABM_SPEECHIFY_FREE_THRESHOLD_EUR). Il frontend saltava
il modale di pagamento e l'UI restava sulla schermata di avanzamento.

Fix: la soglia (e quindi is_free) deve dipendere dalla voce -> Speechify usa
ABM_SPEECHIFY_FREE_THRESHOLD_EUR, tutto il resto ABM_GEMINI_FREE_THRESHOLD_EUR.
"""
import pytest


class _Ch:
    def __init__(self, index, text):
        self.index = index
        self.text = text
        self.char_count = len(text)


class _Info:
    def __init__(self, chapters):
        self.chapters = chapters
        self.title = "Test Book"
        self.language = "en"


def _setup_job(audiobook_app, job_id="CE1"):
    info = _Info([_Ch(1, "Hello world. " * 50)])
    job = {"job_id": job_id, "status": "analyzed", "info": info}
    audiobook_app.jobs = {job_id: job}
    return job_id


def test_combined_estimate_uses_speechify_threshold_for_speechify_voice(monkeypatch):
    import audiobook_app
    if not hasattr(audiobook_app, "jobs"):
        pytest.skip("audiobook_app.jobs non trovato")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.40")
    job_id = _setup_job(audiobook_app)

    client = audiobook_app.app.test_client()
    resp = client.post("/api/combined_estimate", json={
        "job_id": job_id,
        "voice_id": "speechify:simba-3.2:harper_32",
        "lang": "en",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    # La soglia riportata deve essere quella Speechify, non quella Gemini.
    assert abs(data["threshold_eur"] - 0.40) < 1e-9, \
        f"threshold_eur={data['threshold_eur']} (atteso 0.40 = soglia Speechify)"
    # is_free deve essere calcolato su quella soglia.
    assert data["is_free"] == (data["total_eur"] <= 0.40)


def test_combined_estimate_uses_gemini_threshold_for_non_speechify_voice(monkeypatch):
    import audiobook_app
    if not hasattr(audiobook_app, "jobs"):
        pytest.skip("audiobook_app.jobs non trovato")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.40")
    job_id = _setup_job(audiobook_app, "CE2")

    client = audiobook_app.app.test_client()
    # Voce standard (non premium): nessuna stima premium, total 0 -> is_free True,
    # ma la soglia riportata deve restare quella Gemini.
    resp = client.post("/api/combined_estimate", json={
        "job_id": job_id,
        "voice_id": "en-US-AriaNeural",
        "lang": "en",
    })
    assert resp.status_code == 200
    data = resp.get_json()
    assert abs(data["threshold_eur"] - 0.50) < 1e-9, \
        f"threshold_eur={data['threshold_eur']} (atteso 0.50 = soglia Gemini)"
