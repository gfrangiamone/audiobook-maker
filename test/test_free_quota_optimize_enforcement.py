"""Task 6: enforcement e consumo della quota gratuita nei rami combinati
(TTS premium + LLM) di /api/optimize.

Mirror di test_free_quota_generate_enforcement.py (Task 5) ma sul punto di
enforcement dei flussi wizard "ottimizza + auto-genera": qui il
payment_token, quando presente, copre LLM + TTS premium in un unico
addebito, e la quota gratuita mensile si applica sul LISTINO combinato
(TTS + LLM), non sulla sola quota TTS. Entrambi i rami (_is_combined_gemini,
_is_combined_speechify) devono passare da _premium_quota_decision, la
stessa funzione usata da /api/combined_estimate e
/api/paypal_create_order_gemini (Task 4), e rispondere 402 con
error_code "free_quota_exhausted" quando la quota mensile e' esaurita
(distinto dal generico "payment_required" quando il job supera la soglia
a prescindere dalla quota).
"""
import pytest

import audiobook_app
import free_quota
import gemini_tts
import payment
import speechify_tts
from epub_to_tts import BookInfo, Chapter

# NB: accesso a app/jobs/_jobs_lock via attributo a runtime, mai from-import
# (altri test della suite completa fanno importlib.reload(audiobook_app), che
# ri-bind gli oggetti modulo: un from-import a collection time resterebbe
# legato al dict jobs pre-reload).

CID = "cid_quota_optimize_test"
GEMINI_VOICE = "gemini:flash25:Zephyr"
SPEECHIFY_VOICE = "speechify:simba-3.2:harper_32"


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Stato isolato: quota/payment su tmp_path, LLM+TTS premium 'disponibili'
    senza rete, run_optimization/_log_activity intercettati."""
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(speechify_tts, "is_available", lambda: True)

    run_calls = []
    monkeypatch.setattr(
        audiobook_app, "run_optimization",
        lambda job_id, chapters: run_calls.append((job_id, chapters)),
    )

    log_calls = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                         lambda *a, **k: log_calls.append((a, k)))

    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setenv("ABM_PREMIUM_MIN_COST_EUR", "0.50")

    yield {"run_calls": run_calls, "log_calls": log_calls}

    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("fqo-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(job_id, n_chars, client_id=CID, language="en"):
    ch = Chapter(index=0, title="Cap0", text="A" * n_chars)
    info = BookInfo(
        title="T", author="A", language=language, chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {
            "info": info, "status": "analyzed", "client_id": client_id,
        }
    return audiobook_app.jobs[job_id]


def _post_optimize(client, job_id, voice, **extra):
    payload = {
        "job_id": job_id, "voice": voice, "rate": "+0%",
        "batch": False, "lang": "en", "auto_generate": True,
        "single_file": True, "output_format": "m4b",
    }
    payload.update(extra)
    return client.post("/api/optimize", json=payload)


def _log_ops(log_calls):
    return [a[2] for a, _k in log_calls]


def _gemini_list_and_llm(chapters, n_chars):
    est = gemini_tts.estimate_book_cost(chapters, GEMINI_VOICE,
                                         language="en", rate_pct="+0%")
    list_price = round(est["list_price_eur"], 2)
    llm_eur = payment._estimate_llm_cost_eur(n_chars)
    return list_price, llm_eur


def _speechify_list_and_llm(chapters, n_chars):
    est = speechify_tts.estimate_book_cost(chapters, language="en")
    list_price = round(est["list_price_eur"], 2)
    llm_eur = payment._estimate_llm_cost_eur(n_chars)
    return list_price, llm_eur


# ---------------------------------------------------------------------------
# Ramo combinato Gemini
# ---------------------------------------------------------------------------

def test_gemini_combined_quota_exhausted_returns_402_contract_and_logs(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fqo-gem-exhausted", 5000)

    list_price, llm_eur = _gemini_list_and_llm(job["info"].chapters, 5000)
    combined_list = round(list_price + llm_eur, 2)
    assert 0 < combined_list < 2.00, "precondizione: listino combinato positivo e sotto il limite quota"

    # Consuma la quota lasciando meno del necessario per questo job -> floor.
    free_quota.consume(CID, round(2.00 - combined_list + 0.01, 2), "preload_gem_opt")
    expected = free_quota.decision(CID, GEMINI_VOICE, combined_list)
    assert expected["quota_exhausted"] is True
    assert expected["is_free"] is False

    r = _post_optimize(client, "fqo-gem-exhausted", GEMINI_VOICE)
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "free_quota_exhausted"
    assert body["total_eur"] == pytest.approx(expected["due_eur"])
    assert body["threshold_eur"] == pytest.approx(5.00)
    assert body["quota_used_eur"] == pytest.approx(expected["quota_used_eur"])
    assert body["quota_limit_eur"] == pytest.approx(2.00)

    # Nessuna ottimizzazione avviata, claim "optimizing" rilasciato.
    assert env["run_calls"] == []
    assert audiobook_app.jobs["fqo-gem-exhausted"]["status"] == "analyzed"
    assert free_quota.used_eur(CID) == pytest.approx(expected["quota_used_eur"])
    assert "FREE_QUOTA_EXCEEDED" in _log_ops(env["log_calls"])


def test_gemini_combined_quota_available_starts_without_payment_and_consumes(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fqo-gem-free", 5000)
    list_price, llm_eur = _gemini_list_and_llm(job["info"].chapters, 5000)
    combined_list = round(list_price + llm_eur, 2)
    assert combined_list > 0
    assert free_quota.used_eur(CID) == pytest.approx(0.0)

    r = _post_optimize(client, "fqo-gem-free", GEMINI_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"

    # Ottimizzazione realmente avviata (claim riuscito, run_optimization
    # chiamato) e quota consumata SOLO ora, per l'importo combinato di listino
    # (TTS + LLM), non per la sola quota TTS.
    assert env["run_calls"] == [("fqo-gem-free", [0])]
    assert free_quota.used_eur(CID) == pytest.approx(combined_list)
    assert "payment" not in audiobook_app.jobs["fqo-gem-free"]
    assert "FREE_QUOTA_EXCEEDED" not in _log_ops(env["log_calls"])


def test_gemini_combined_above_free_threshold_uses_generic_payment_required(client, env, monkeypatch):
    """Libro sopra soglia (indipendentemente dalla quota, ancora piena): 402
    generico, non 'free_quota_exhausted'."""
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.10")
    _mk_job("fqo-gem-paid", 5000)

    r = _post_optimize(client, "fqo-gem-paid", GEMINI_VOICE)
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "payment_required"
    assert "FREE_QUOTA_EXCEEDED" not in _log_ops(env["log_calls"])
    assert free_quota.used_eur(CID) == pytest.approx(0.0)
    assert audiobook_app.jobs["fqo-gem-paid"]["status"] == "analyzed"


def test_gemini_combined_quota_disabled_zero_limit_no_402(client, env, monkeypatch):
    """ABM_FREE_QUOTA_EUR_PER_MONTH=0 -> feature disattivata: nessun 402 nuovo
    per un job sotto soglia (comportamento pre-esistente preservato)."""
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "0")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "5.00")
    _mk_job("fqo-gem-disabled", 5000)

    r = _post_optimize(client, "fqo-gem-disabled", GEMINI_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"


# ---------------------------------------------------------------------------
# Ramo combinato Speechify (parita' col ramo Gemini sopra)
# ---------------------------------------------------------------------------

def test_speechify_combined_quota_exhausted_returns_402_contract_and_logs(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fqo-spx-exhausted", 5000)

    list_price, llm_eur = _speechify_list_and_llm(job["info"].chapters, 5000)
    combined_list = round(list_price + llm_eur, 2)
    assert 0 < combined_list < 2.00, "precondizione: listino combinato positivo e sotto il limite quota"

    free_quota.consume(CID, round(2.00 - combined_list + 0.01, 2), "preload_spx_opt")
    expected = free_quota.decision(CID, SPEECHIFY_VOICE, combined_list)
    assert expected["quota_exhausted"] is True

    r = _post_optimize(client, "fqo-spx-exhausted", SPEECHIFY_VOICE)
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "free_quota_exhausted"
    assert body["total_eur"] == pytest.approx(expected["due_eur"])
    assert body["quota_used_eur"] == pytest.approx(expected["quota_used_eur"])
    assert body["quota_limit_eur"] == pytest.approx(2.00)
    assert env["run_calls"] == []
    assert audiobook_app.jobs["fqo-spx-exhausted"]["status"] == "analyzed"
    assert "FREE_QUOTA_EXCEEDED" in _log_ops(env["log_calls"])


def test_speechify_combined_quota_available_starts_and_consumes(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fqo-spx-free", 5000)
    list_price, llm_eur = _speechify_list_and_llm(job["info"].chapters, 5000)
    combined_list = round(list_price + llm_eur, 2)
    assert combined_list > 0

    r = _post_optimize(client, "fqo-spx-free", SPEECHIFY_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert env["run_calls"] == [("fqo-spx-free", [0])]
    assert free_quota.used_eur(CID) == pytest.approx(combined_list)
    assert "payment" not in audiobook_app.jobs["fqo-spx-free"]


def test_speechify_combined_above_free_threshold_uses_generic_payment_required(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.10")
    _mk_job("fqo-spx-paid", 5000)

    r = _post_optimize(client, "fqo-spx-paid", SPEECHIFY_VOICE)
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "payment_required"
    assert "FREE_QUOTA_EXCEEDED" not in _log_ops(env["log_calls"])
    assert free_quota.used_eur(CID) == pytest.approx(0.0)


def test_speechify_combined_quota_disabled_zero_limit_no_402(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "0")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    _mk_job("fqo-spx-disabled", 5000)

    r = _post_optimize(client, "fqo-spx-disabled", SPEECHIFY_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"
