"""Enforcement pagamento nel flusso combinato (auto_generate + voce Gemini) di /api/optimize.

Bug originale: il blocco 402 "payment_required" era annidato dentro
`if _combined_token:` -> irraggiungibile. Una richiesta combinata senza token
(o con token non consumabile, ramo WARNING-and-proceed) avviava ottimizzazione
LLM + auto-generazione Gemini senza pagamento. Il path auto-gen chiama
run_generation direttamente bypassando /api/generate, quindi /api/optimize
e' l'UNICO punto di enforcement per il flusso combinato.

Bug correlato (stessa famiglia): i return 402 del branch standalone LLM non
rilasciavano lo status claim "optimizing" -> job brickato (retry respinto
con "Optimization already running").
"""
import time

import pytest

import audiobook_app
import free_quota
import payment
import voxcpm_tts
from epub_to_tts import BookInfo, Chapter

GEMINI_VOICE = "gemini:flash25:Zephyr"
VOXCPM_VOICE = "voxcpm:v2:it-IT/Stefano"

# NB: accesso a app/jobs/_jobs_lock SEMPRE via attributo a runtime, mai
# `from audiobook_app import jobs`: i test test_cold_*.py (che girano prima
# in ordine alfabetico) fanno importlib.reload(audiobook_app), che ri-esegue
# `jobs = {}` nel namespace del modulo. Un from-import a collection time
# resterebbe legato al dict pre-reload mentre le route vedono quello nuovo
# -> 404 "Session expired" solo nella suite completa.


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


def _mk_job(job_id, n_chars):
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
    # Isola la quota gratuita cumulativa (Task 6) dal file reale di
    # ABM_DATA_DIR: senza questo i test leggerebbero/scriverebbero
    # _free_quota.json nell'ambiente dev reale, con stato residuo tra run.
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    # Soglia bassa cosi' anche un libro di test modesto richiede pagamento.
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.10")
    yield calls
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("cpe-")]:
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
    }
    payload.update(extra)
    return client.post("/api/optimize", json=payload)


def test_combined_no_token_returns_402_and_releases_claim(client, env):
    job = _mk_job("cpe-notoken", 300_000)
    r = _post_optimize(client, "cpe-notoken")
    assert r.status_code == 402, r.get_data(as_text=True)
    d = r.get_json()
    assert d["error_code"] == "payment_required"
    assert d["total_eur"] > 0
    # Lo status claim deve essere rilasciato: il retry (post-pagamento) deve poter passare.
    assert job["status"] == "analyzed"
    # Nessuna ottimizzazione avviata.
    assert env == []


def test_combined_invalid_token_returns_402_and_releases_claim(client, env):
    job = _mk_job("cpe-badtoken", 300_000)
    r = _post_optimize(client, "cpe-badtoken", payment_token="BOGUS-TOKEN")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "invalid_payment"
    assert job["status"] == "analyzed"
    assert env == []


def test_combined_used_paypal_token_returns_402(client, env):
    """Token PayPal gia' usato: non consumabile -> 402, niente run gratuito."""
    job = _mk_job("cpe-usedtoken", 300_000)
    payment._payments["ORD-USED"] = {
        "order_id": "ORD-USED", "amount_eur": 99.0, "email": "x@y.it",
        "captured_at": time.time(), "used": True,
    }
    r = _post_optimize(client, "cpe-usedtoken", payment_token="ORD-USED")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "invalid_payment"
    assert job["status"] == "analyzed"
    assert env == []


def test_combined_valid_voucher_consumes_and_starts(client, env):
    job = _mk_job("cpe-voucher", 300_000)
    code, _v = payment._create_voucher("u@x.it", 100.0, kind="test", note="t")
    remaining_before = payment._voucher_remaining(payment._vouchers[code])
    r = _post_optimize(client, "cpe-voucher", payment_token=code)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"
    # Voucher consumato per l'intero combinato (gemini + llm).
    remaining_after = payment._voucher_remaining(payment._vouchers[code])
    consumed = remaining_before - remaining_after
    assert consumed == pytest.approx(job["payment_amount_eur"], abs=0.01)
    assert consumed > 0
    # Metadata pagamento per audit/refund presenti.
    assert job["payment"]["source"] == "combined_optimize_autogen"
    assert job["payment"]["method"] == "voucher"
    assert job["payment_type"] == "voucher"
    # Ottimizzazione avviata.
    assert env == [("cpe-voucher", [0])]


def test_combined_below_threshold_runs_free(client, env, monkeypatch):
    """Sotto soglia il flusso combinato resta gratuito (nessun 402 senza token)."""
    _mk_job("cpe-free", 300_000)
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "100000")
    # Il listino di questo job (~8€) supera di gran lunga la quota gratuita
    # mensile di default (2€/mese): qui si vuole isolare lo scenario "sotto
    # SOGLIA" da quello "quota esaurita" (coperto da test dedicati), quindi
    # si alza il tetto mensile cosi' la quota non interferisce.
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "1000")
    r = _post_optimize(client, "cpe-free")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"
    assert env == [("cpe-free", [0])]


def test_standalone_402_releases_claim(client, env):
    """Branch standalone LLM (no auto_generate): il 402 payment_required deve
    rilasciare lo status claim, altrimenti il retry post-pagamento e' respinto."""
    # 600k chars -> ~0.66 EUR > soglia free LLM 0.50
    job = _mk_job("cpe-standalone", 600_000)
    r = _post_optimize(client, "cpe-standalone",
                       auto_generate=False, voice="it-IT-IsabellaNeural")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "payment_required"
    assert job["status"] == "analyzed"
    assert env == []


def test_standalone_invalid_token_releases_claim(client, env):
    job = _mk_job("cpe-standalone-bad", 600_000)
    r = _post_optimize(client, "cpe-standalone-bad",
                       auto_generate=False, voice="it-IT-IsabellaNeural",
                       payment_token="BOGUS")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "invalid_payment"
    assert job["status"] == "analyzed"
    assert env == []


def test_already_optimized_releases_claim(client, env):
    """Nulla da ottimizzare (gia' tutto fatto): risponde already_optimized
    MA rilascia il claim 'optimizing', altrimenti il job resta brickato."""
    job = _mk_job("cpe-allopt", 300_000)
    job["optimized_chapters"] = [0]  # l'unico capitolo e' gia' ottimizzato
    r = _post_optimize(client, "cpe-allopt", auto_generate=False,
                       voice="it-IT-IsabellaNeural")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "already_optimized"
    assert job["status"] == "analyzed"
    assert env == []


# ---------------------------------------------------------------------------
# Ramo combinato VoxCPM (Fix round 1, task-10-report.md).
#
# Bug: _is_combined_voxcpm sopprimeva il gate standalone-LLM ma nessun blocco
# a valle addebitava davvero la quota VoxCPM (a differenza di Gemini/Speechify
# sopra): auto_generate + voce VoxCPM + LLM sotto soglia -> job VoxCPM gratis,
# ne' TTS ne' LLM incassati, quota gratuita mai toccata.
# ---------------------------------------------------------------------------

def test_voxcpm_combined_no_token_returns_402_with_matching_total(client, env, monkeypatch):
    """VoxCPM, testo grande, nessun pagamento -> 402 con total_eur = listino
    (TTS + LLM), identico a quanto gia' verificato per Gemini/Speechify."""
    monkeypatch.setattr(voxcpm_tts, "is_available", lambda: True)
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.10")
    job = _mk_job("cpe-vox-notoken", 300_000)
    est = voxcpm_tts.estimate_book_cost(job["info"].chapters, language="it")
    llm_eur = audiobook_app._estimate_llm_cost_eur(300_000)
    expected_total = round(est["list_price_eur"] + llm_eur, 2)
    assert expected_total > 0

    r = _post_optimize(client, "cpe-vox-notoken", voice=VOXCPM_VOICE)
    assert r.status_code == 402, r.get_data(as_text=True)
    d = r.get_json()
    assert d["error_code"] == "payment_required"
    assert d["total_eur"] == pytest.approx(expected_total, abs=0.01)
    assert d["voxcpm_eur"] > 0
    # Il claim "optimizing" deve essere rilasciato (retry post-pagamento possibile).
    assert job["status"] == "analyzed"
    # Nessuna ottimizzazione avviata: ne' LLM ne' TTS regalati.
    assert env == []


def test_voxcpm_combined_below_threshold_runs_free_and_debits_quota(client, env, monkeypatch):
    """VoxCPM, testo sotto soglia -> parte senza token E la quota gratuita
    cumulativa viene debitata (non semplicemente ignorata)."""
    monkeypatch.setattr(voxcpm_tts, "is_available", lambda: True)
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "4.00")
    # Soglia motore alta abbastanza da coprire l'intero libro di test.
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "1000")
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "1000")
    job = _mk_job("cpe-vox-free", 5_000)
    cid = "cpe-vox-free-cid"
    job["client_id"] = cid
    # Il job ora ha client_id: _check_job_owner richiede che il cookie della
    # richiesta corrisponda, altrimenti 403 Forbidden.
    client.set_cookie("abm_cid", cid)
    est = voxcpm_tts.estimate_book_cost(job["info"].chapters, language="it")
    llm_eur = audiobook_app._estimate_llm_cost_eur(5_000)
    expected_combined_list = round(est["list_price_eur"] + llm_eur, 2)
    assert free_quota.used_eur(cid) == pytest.approx(0.0)

    r = _post_optimize(client, "cpe-vox-free", voice=VOXCPM_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"
    assert env == [("cpe-vox-free", [0])]
    # La quota gratuita cumulativa si e' davvero mossa, sul listino combinato.
    assert free_quota.used_eur(cid) == pytest.approx(expected_combined_list, abs=0.01)
    # Nessun pagamento: il job resta senza job["payment"] (come per Gemini free).
    assert "payment" not in job
