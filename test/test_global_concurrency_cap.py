"""Test: tetto GLOBALE di generazioni simultanee sull'istanza.

Incidente 2026-08-21: il solo cap per-client (2) non pone alcun limite lato
server. 19 generazioni contemporanee da client diversi hanno saturato RAM+swap
fino al thrash livelock. `ABM_MAX_CONCURRENT_GLOBAL` (default 6) rifiuta le
nuove generazioni con 429/server_busy quando l'istanza e' al limite.
"""
from unittest.mock import patch

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


@pytest.fixture
def clean_jobs():
    saved = dict(audiobook_app.jobs)
    audiobook_app.jobs.clear()
    yield
    audiobook_app.jobs.clear()
    audiobook_app.jobs.update(saved)


class _Info:
    title = "T"
    author = "A"
    language = "it"
    chapters = []


def _seed_generating(n, prefix="G"):
    for i in range(n):
        audiobook_app.jobs[f"{prefix}{i}"] = {
            "status": "generating", "client_id": f"other{i}", "info": _Info(),
        }


def _seed_candidate(job_id="CAND"):
    job = {
        "status": "analyzed", "client_id": "mine", "client_ip": "1.2.3.4",
        "info": _Info(), "original_filename": "libro.epub",
    }
    audiobook_app.jobs[job_id] = job
    return job


def test_active_generating_total_counts_all_clients(clean_jobs):
    _seed_generating(3)
    audiobook_app.jobs["X"] = {"status": "analyzed", "client_id": "z"}
    with audiobook_app._jobs_lock:
        assert audiobook_app._active_generating_total_unlocked() == 3


def test_generate_rejected_when_global_cap_reached(client, clean_jobs):
    _seed_generating(audiobook_app.MAX_CONCURRENT_GLOBAL)
    job = _seed_candidate()
    with patch("audiobook_app._check_job_owner", return_value=(job, None, None)), \
         patch("audiobook_app.MAX_CONCURRENT_GLOBAL",
               audiobook_app.MAX_CONCURRENT_GLOBAL):
        r = client.post("/api/generate", json={"job_id": "CAND",
                                               "voice": "it-IT-DiegoNeural"})
    assert r.status_code == 429
    body = r.get_json()
    assert body["error_code"] == "server_busy"
    # il job NON deve aver rubato lo slot
    assert audiobook_app.jobs["CAND"]["status"] == "analyzed"


def test_generate_allowed_below_global_cap(client, clean_jobs):
    _seed_generating(max(0, audiobook_app.MAX_CONCURRENT_GLOBAL - 1))
    job = _seed_candidate()
    with patch("audiobook_app._check_job_owner", return_value=(job, None, None)), \
         patch("audiobook_app.threading.Thread"):
        r = client.post("/api/generate", json={"job_id": "CAND",
                                               "voice": "it-IT-DiegoNeural"})
    assert r.status_code == 200, r.get_json()
    assert audiobook_app.jobs["CAND"]["status"] == "generating"


def test_global_cap_zero_disables_the_limit(client, clean_jobs):
    _seed_generating(50)
    job = _seed_candidate()
    with patch("audiobook_app._check_job_owner", return_value=(job, None, None)), \
         patch("audiobook_app.MAX_CONCURRENT_GLOBAL", 0), \
         patch("audiobook_app.threading.Thread"):
        r = client.post("/api/generate", json={"job_id": "CAND",
                                               "voice": "it-IT-DiegoNeural"})
    assert r.status_code == 200, r.get_json()


# --- gate ANTICIPATO: avvisa prima di chiedere il pagamento -----------------
# Il controllo dentro il blocco atomico arriva dopo il preflight premium: un
# utente poteva pagare e solo dopo vedersi rifiutare il job (con rimborso del
# capture orfano). Il gate anticipato risponde 429/server_busy prima che il
# preflight di pagamento venga anche solo raggiunto.

_GEMINI_VOICE = "gemini:gemini-2.5-flash-preview-tts:Zephyr"


def test_server_busy_before_payment_preflight(client, clean_jobs):
    """Server saturo + voce PREMIUM: 429 server_busy, preflight mai eseguito."""
    _seed_generating(audiobook_app.MAX_CONCURRENT_GLOBAL)
    job = _seed_candidate()
    gem = type("G", (), {"is_available": staticmethod(lambda: True)})
    with patch("audiobook_app._check_job_owner", return_value=(job, None, None)), \
         patch("audiobook_app.gemini_tts", gem), \
         patch("audiobook_app._effective_max_text_chars") as preflight, \
         patch("audiobook_app.threading.Thread"):
        r = client.post("/api/generate", json={"job_id": "CAND",
                                               "voice": _GEMINI_VOICE})
    assert r.status_code == 429, r.get_json()
    assert r.get_json()["error_code"] == "server_busy"
    # nessun passaggio dal preflight premium -> nessun pagamento richiesto
    assert preflight.call_count == 0
    assert audiobook_app.jobs["CAND"]["status"] == "analyzed"


def test_payment_preflight_runs_when_server_has_capacity(client, clean_jobs):
    """Sotto il tetto il preflight premium viene raggiunto normalmente."""
    _seed_generating(max(0, audiobook_app.MAX_CONCURRENT_GLOBAL - 1))
    job = _seed_candidate()
    gem = type("G", (), {"is_available": staticmethod(lambda: True)})
    with patch("audiobook_app._check_job_owner", return_value=(job, None, None)), \
         patch("audiobook_app.gemini_tts", gem), \
         patch("audiobook_app._effective_max_text_chars",
               return_value=10 ** 9) as preflight, \
         patch("audiobook_app.threading.Thread"):
        client.post("/api/generate", json={"job_id": "CAND",
                                           "voice": _GEMINI_VOICE})
    assert preflight.call_count >= 1


def test_paypal_create_order_gemini_rejected_when_server_busy(client, clean_jobs):
    """Server saturo: nessun ordine PayPal viene nemmeno creato."""
    _seed_generating(audiobook_app.MAX_CONCURRENT_GLOBAL)
    _seed_candidate()
    r = client.post("/api/paypal_create_order_gemini",
                    json={"job_id": "CAND", "voice_id": _GEMINI_VOICE,
                          "amount_eur": 1.0})
    assert r.status_code == 429, r.get_json()
    assert r.get_json()["error_code"] == "server_busy"
