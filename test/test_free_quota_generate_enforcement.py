"""Task 5: enforcement e consumo della quota gratuita in /api/generate.

Copre i due gate di pagamento (ramo Gemini e ramo Speechify): entrambi devono
passare da `_premium_quota_decision` (stessa funzione usata da
/api/combined_estimate e /api/paypal_create_order_gemini, Task 4), rispondere
402 con `error_code: "free_quota_exhausted"` quando la quota mensile e'
esaurita (distinto dal generico "payment_required" quando il libro supera la
soglia gratuita a prescindere dalla quota), e consumare la quota SOLO dopo il
claim atomico dello stato job — un job respinto dal limite di concorrenza non
deve bruciare quota (vedi audiobook_app.py, blocco `job.pop("_free_quota_charge")`
subito dopo `job["platform"] = _client_platform()`).
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

CID = "cid_quota_generate_test"
GEMINI_VOICE = "gemini:flash25:Zephyr"
SPEECHIFY_VOICE = "speechify:simba-3.2:harper_32"


class _SyncThread:
    """Rende sincrono threading.Thread: senza questo run_generation girerebbe
    in un thread daemon reale non joinato, in race con le asserzioni post-request."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch, tmp_path):
    """Stato isolato: quota/payment su tmp_path, TTS premium 'disponibili' senza
    rete, run_generation/_admin_notify_generation/_log_activity intercettati."""
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    audiobook_app._invalidate_voices_cache()

    run_calls = []

    def _fake_run(job_id, info, voice, rate, single_file, **kw):
        run_calls.append((job_id, voice))

    monkeypatch.setattr(audiobook_app, "run_generation", _fake_run)
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)

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
        for jid in [j for j in audiobook_app.jobs if j.startswith("fq-")]:
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


def _post_generate(client, job_id, voice, output_format="mp3", **extra):
    payload = {
        "job_id": job_id, "voice": voice, "rate": "+0%",
        "output_format": output_format, "lang": "en",
    }
    payload.update(extra)
    return client.post("/api/generate", json=payload)


def _log_ops(log_calls):
    return [a[2] for a, _k in log_calls]


# ---------------------------------------------------------------------------
# Ramo Speechify
# ---------------------------------------------------------------------------

def test_speechify_quota_exhausted_returns_402_contract_and_logs(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fq-spx-exhausted", 5000)

    est = speechify_tts.estimate_book_cost(job["info"].chapters, language="en")
    list_price = round(est["list_price_eur"], 2)
    assert 0 < list_price < 2.00, "precondizione: listino positivo e sotto il limite quota"

    # Consuma la quota lasciando meno del necessario per questo job -> floor.
    free_quota.consume(CID, round(2.00 - list_price + 0.01, 2), "preload_spx")
    expected = free_quota.decision(CID, SPEECHIFY_VOICE, list_price)
    assert expected["quota_exhausted"] is True
    assert expected["is_free"] is False

    r = _post_generate(client, "fq-spx-exhausted", SPEECHIFY_VOICE)
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error"] == "payment_required"
    assert body["error_code"] == "free_quota_exhausted"
    assert body["total_eur"] == pytest.approx(expected["due_eur"])
    assert body["threshold_eur"] == pytest.approx(5.00)
    assert body["quota_used_eur"] == pytest.approx(expected["quota_used_eur"])
    assert body["quota_limit_eur"] == pytest.approx(2.00)

    # Nessun job avviato, nessuna consumazione ulteriore (il claim atomico non
    # e' mai stato raggiunto: il gate risponde 402 prima).
    assert env["run_calls"] == []
    assert audiobook_app.jobs["fq-spx-exhausted"]["status"] == "analyzed"
    assert free_quota.used_eur(CID) == pytest.approx(expected["quota_used_eur"])

    # Activity log dedicato all'esaurimento quota.
    assert "FREE_QUOTA_EXCEEDED" in _log_ops(env["log_calls"])


def test_speechify_quota_available_starts_without_payment_and_consumes(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fq-spx-free", 5000)
    est = speechify_tts.estimate_book_cost(job["info"].chapters, language="en")
    list_price = round(est["list_price_eur"], 2)
    assert list_price > 0
    assert free_quota.used_eur(CID) == pytest.approx(0.0)

    r = _post_generate(client, "fq-spx-free", SPEECHIFY_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"

    # Job realmente avviato (claim riuscito, thread spawnato) e quota
    # consumata SOLO ora, per l'importo di listino.
    assert env["run_calls"] == [("fq-spx-free", SPEECHIFY_VOICE)]
    assert free_quota.used_eur(CID) == pytest.approx(list_price)
    assert "payment" not in audiobook_app.jobs["fq-spx-free"]
    assert "FREE_QUOTA_EXCEEDED" not in _log_ops(env["log_calls"])


def test_speechify_above_free_threshold_uses_generic_payment_required(client, env, monkeypatch):
    """Libro sopra soglia (indipendentemente dalla quota, ancora piena): 402
    generico, non 'free_quota_exhausted'. Il frontend (Task 7) distingue i due
    casi solo se il backend non li confonde."""
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.10")
    _mk_job("fq-spx-paid", 5000)

    r = _post_generate(client, "fq-spx-paid", SPEECHIFY_VOICE)
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "payment_required"
    assert "FREE_QUOTA_EXCEEDED" not in _log_ops(env["log_calls"])
    assert free_quota.used_eur(CID) == pytest.approx(0.0)


def test_speechify_quota_not_consumed_when_concurrency_limit_denies(client, env, monkeypatch):
    """Un job quota-free respinto dal limite di concorrenza (dopo il gate, prima
    del claim atomico) non deve bruciare quota: il consumo e' differito al
    claim riuscito, non al gate."""
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    monkeypatch.setattr(audiobook_app, "MAX_CONCURRENT_PER_CLIENT", 1)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["fq-spx-blocker"] = {"status": "generating", "client_id": CID}
    _mk_job("fq-spx-blocked", 5000)
    try:
        r = _post_generate(client, "fq-spx-blocked", SPEECHIFY_VOICE)
        assert r.status_code == 429, r.get_data(as_text=True)
        assert r.get_json()["error_code"] == "concurrent_limit"
        assert env["run_calls"] == []
        assert free_quota.used_eur(CID) == pytest.approx(0.0)
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("fq-spx-blocker", None)


def test_speechify_quota_disabled_zero_limit_no_402(client, env, monkeypatch):
    """ABM_FREE_QUOTA_EUR_PER_MONTH=0 -> feature disattivata: nessun 402 nuovo
    per un job sotto soglia (comportamento pre-esistente preservato)."""
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "0")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    _mk_job("fq-spx-disabled", 5000)

    r = _post_generate(client, "fq-spx-disabled", SPEECHIFY_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json()["status"] == "started"


# ---------------------------------------------------------------------------
# Ramo Gemini (parita' con il ramo Speechify sopra)
# ---------------------------------------------------------------------------

def test_gemini_quota_exhausted_returns_402_contract(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fq-gem-exhausted", 5000)

    est = gemini_tts.estimate_book_cost(job["info"].chapters, GEMINI_VOICE,
                                         language="en", rate_pct="+0%")
    list_price = round(est["list_price_eur"], 2)
    assert 0 < list_price < 2.00, "precondizione: listino positivo e sotto il limite quota"

    free_quota.consume(CID, round(2.00 - list_price + 0.01, 2), "preload_gem")
    expected = free_quota.decision(CID, GEMINI_VOICE, list_price)
    assert expected["quota_exhausted"] is True

    r = _post_generate(client, "fq-gem-exhausted", GEMINI_VOICE)
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "free_quota_exhausted"
    assert body["total_eur"] == pytest.approx(expected["due_eur"])
    assert body["quota_used_eur"] == pytest.approx(expected["quota_used_eur"])
    assert body["quota_limit_eur"] == pytest.approx(2.00)
    assert env["run_calls"] == []
    assert audiobook_app.jobs["fq-gem-exhausted"]["status"] == "analyzed"
    assert "FREE_QUOTA_EXCEEDED" in _log_ops(env["log_calls"])


def test_gemini_quota_available_starts_and_consumes(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fq-gem-free", 5000)
    est = gemini_tts.estimate_book_cost(job["info"].chapters, GEMINI_VOICE,
                                         language="en", rate_pct="+0%")
    list_price = round(est["list_price_eur"], 2)
    assert list_price > 0

    r = _post_generate(client, "fq-gem-free", GEMINI_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert env["run_calls"] == [("fq-gem-free", GEMINI_VOICE)]
    assert free_quota.used_eur(CID) == pytest.approx(list_price)
    assert "payment" not in audiobook_app.jobs["fq-gem-free"]
