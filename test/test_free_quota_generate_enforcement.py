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
    claim riuscito, non al gate.

    Il blocco usato qui e' il tetto GLOBALE d'istanza: il tetto per-client non
    si applica piu' alle voci PREMIUM (vedi test_gen_concurrency_policy.py).
    """
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    monkeypatch.setattr(audiobook_app, "MAX_CONCURRENT_GLOBAL", 1)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["fq-spx-blocker"] = {"status": "generating", "client_id": "other"}
    _mk_job("fq-spx-blocked", 5000)
    try:
        r = _post_generate(client, "fq-spx-blocked", SPEECHIFY_VOICE)
        assert r.status_code == 429, r.get_data(as_text=True)
        assert r.get_json()["error_code"] == "server_busy"
        assert env["run_calls"] == []
        assert free_quota.used_eur(CID) == pytest.approx(0.0)
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("fq-spx-blocker", None)


def test_speechify_stash_quota_non_sopravvive_alla_richiesta(client, env, monkeypatch):
    """C1: lo stash `_free_quota_charge` vale solo per la richiesta corrente.

    Un job quota-free respinto dal 429 concurrent_limit lascia(va) il residuo
    sul job in memoria: la richiesta successiva sullo stesso job_id — qui con
    voce STANDARD, che non attraversa alcun gate premium — arrivava comunque
    alla pop incondizionata e consumava quota per un job che non usa premium.
    """
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    monkeypatch.setattr(audiobook_app, "MAX_CONCURRENT_GLOBAL", 1)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["fq-spx-blocker2"] = {"status": "generating", "client_id": "other"}
    _mk_job("fq-residuo", 5000)
    try:
        r = _post_generate(client, "fq-residuo", SPEECHIFY_VOICE)
        assert r.status_code == 429, r.get_data(as_text=True)
        assert free_quota.used_eur(CID) == pytest.approx(0.0)
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop("fq-spx-blocker2", None)

    # Seconda richiesta sullo stesso job con voce STANDARD: nessun gate premium,
    # quindi nessuna quota deve essere consumata. Lo stash della richiesta
    # precedente non deve poter arrivare alla pop che consuma.
    r2 = _post_generate(client, "fq-residuo", "en-US-AriaNeural")
    assert r2.status_code == 200, r2.get_data(as_text=True)
    assert env["run_calls"] == [("fq-residuo", "en-US-AriaNeural")]
    assert free_quota.used_eur(CID) == pytest.approx(0.0)
    assert "_free_quota_charge" not in audiobook_app.jobs["fq-residuo"]


def test_speechify_retry_stesso_job_resta_gratis(client, env, monkeypatch):
    """I1: `decision()` e' idempotente per job.

    Al retry della stessa generazione (btnRetryWiz, reload di pagina, app
    mobile) `used_eur` contiene gia' il contributo di quel job: senza
    idempotenza il confronto `used + list` lo conta due volte e produce un 402
    che chiede il floor per un credito gia' speso.
    """
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fq-retry", 5000)
    est = speechify_tts.estimate_book_cost(job["info"].chapters, language="en")
    list_price = round(est["list_price_eur"], 2)
    assert 0 < list_price < 2.00

    # Preload tale che il job entri per un soffio: dopo il primo run la quota
    # residua e' < list_price, quindi il retry cadrebbe nel ramo floor.
    preload = round(2.00 - list_price - 0.01, 2)
    assert preload > 0
    free_quota.consume(CID, preload, "preload_retry")

    r1 = _post_generate(client, "fq-retry", SPEECHIFY_VOICE)
    assert r1.status_code == 200, r1.get_data(as_text=True)
    used_after_first = free_quota.used_eur(CID)
    assert used_after_first == pytest.approx(round(preload + list_price, 2))
    assert free_quota.decision(CID, SPEECHIFY_VOICE, list_price)["quota_exhausted"] is True, (
        "precondizione: senza job_id la quota residua non basterebbe piu'"
    )

    # Retry: il job torna in uno stato rigenerabile (come dopo un errore o un
    # reload di pagina) e viene ripresentato con gli stessi parametri.
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["fq-retry"]["status"] = "analyzed"
    r2 = _post_generate(client, "fq-retry", SPEECHIFY_VOICE)
    assert r2.status_code == 200, r2.get_data(as_text=True)
    # Nessun doppio addebito: consume e' idempotente per job_id.
    assert free_quota.used_eur(CID) == pytest.approx(used_after_first)
    assert "payment" not in audiobook_app.jobs["fq-retry"]


def test_speechify_client_id_source_agrees_between_estimate_and_generate(client, env, monkeypatch):
    """I2: stima e gate devono leggere lo STESSO bucket quota.

    Un job nato da una prima richiesta diretta a /api/analyze (nessun cookie
    ancora emesso dall'after_request) ha client_id="" e cadeva nel bucket
    condiviso `_anon`, presto esaurito, mentre /api/combined_estimate leggeva
    il cookie e vedeva quota piena: UI "Gratis", backend 402 (incidente
    "402 Speechify").
    """
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fq-anon", 5000, client_id="")
    est = speechify_tts.estimate_book_cost(job["info"].chapters, language="en")
    list_price = round(est["list_price_eur"], 2)
    assert 0 < list_price < 2.00

    # Bucket anonimo condiviso gia' esaurito da altri client senza cookie.
    free_quota.consume("", 1.99, "preload_anon")
    assert free_quota.used_eur("") == pytest.approx(1.99)

    r_est = client.post("/api/combined_estimate", json={
        "job_id": "fq-anon", "voice_id": SPEECHIFY_VOICE,
        "selected_chapters": [0], "ai_opt_enabled": False, "lang": "en",
    })
    assert r_est.status_code == 200, r_est.get_data(as_text=True)
    assert r_est.get_json()["is_free"] is True, "la stima legge il cookie: quota piena"

    # Il gate deve concordare: stesso client_id, stesso verdetto.
    r = _post_generate(client, "fq-anon", SPEECHIFY_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert env["run_calls"] == [("fq-anon", SPEECHIFY_VOICE)]
    # Consumo sul bucket del cookie, non su quello anonimo condiviso.
    assert free_quota.used_eur(CID) == pytest.approx(list_price)
    assert free_quota.used_eur("") == pytest.approx(1.99)


def test_speechify_quota_disabled_does_not_fill_counter(client, env, monkeypatch):
    """Minor: con quota disattivata non si consuma nulla.

    Riempire il contatore in silenzio significherebbe che, alzando il limite a
    mese in corso, molti client risulterebbero gia' esauriti e verrebbero
    addebitati subito.
    """
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "0")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "5.00")
    _mk_job("fq-spx-nocount", 5000)

    r = _post_generate(client, "fq-spx-nocount", SPEECHIFY_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert env["run_calls"] == [("fq-spx-nocount", SPEECHIFY_VOICE)]
    assert free_quota.used_eur(CID) == pytest.approx(0.0)


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


def test_gemini_selection_too_large_after_claim_does_not_consume_quota(client, env, monkeypatch):
    """Finestra fra il claim atomico e thread.start(): il cap safety-net
    selected_chars > max_text_chars (righe ~9190-9211) puo' scattare DOPO il
    claim (nel mondo reale: testo espanso da un'ottimizzazione LLM conclusa
    dopo la stima pre-claim a riga ~8728). Quel path rimborsa il pagamento
    (_refund_payment_on_orphan) ma NON prevede alcun rimborso quota — quindi
    la quota non deve MAI essere stata consumata per un job che non parte:
    il consumo deve restare a valle di questo cap, non a monte.

    Per riprodurre deterministicamente il "si e' allargato dopo il primo
    check" senza dipendere dalla pipeline LLM reale, si monkeypatcha
    _effective_max_text_chars con un cap che passa alla prima invocazione
    (check pre-claim, riga ~8728) e fallisce alla seconda (check post-claim,
    riga ~9190) — le uniche due chiamate attraversate da una singola request
    /api/generate per una voce Gemini."""
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "5.00")
    job = _mk_job("fq-gem-toolarge", 5000)
    est = gemini_tts.estimate_book_cost(job["info"].chapters, GEMINI_VOICE,
                                         language="en", rate_pct="+0%")
    list_price = round(est["list_price_eur"], 2)
    assert 0 < list_price < 2.00, "precondizione: sotto soglia e quota disponibile"
    assert free_quota.used_eur(CID) == pytest.approx(0.0)

    real_cap_fn = audiobook_app._effective_max_text_chars
    calls = []

    def _flaky_cap(voice, job=None):
        calls.append(1)
        # 1a chiamata (pre-claim, riga ~8728): cap ampio -> passa.
        # 2a chiamata e succ. (post-claim, riga ~9190): cap minuscolo -> 413.
        if len(calls) <= 1:
            return real_cap_fn(voice, job)
        return 100

    monkeypatch.setattr(audiobook_app, "_effective_max_text_chars", _flaky_cap)

    r = _post_generate(client, "fq-gem-toolarge", GEMINI_VOICE)
    assert r.status_code == 413, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "selection_too_large"

    # Il job non e' mai partito: nessun thread, quota mai bruciata, e lo
    # status torna a uno stato non-generating (nessuna consumazione residua).
    assert env["run_calls"] == []
    assert free_quota.used_eur(CID) == pytest.approx(0.0)
    assert audiobook_app.jobs["fq-gem-toolarge"]["status"] != "generating"
