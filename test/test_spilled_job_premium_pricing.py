"""Prezzo delle voci PREMIUM su job con testi SPILLATI (contenimento RAM).

Incidente Q9lQN3RrapCvGLSonVnzmA: un job gia' terminale (done/error/cancelled)
ha i testi capitolo serializzati su disco e `ch.text == ""` in RAM (vedi
`generation_engine.spill_job_texts`). Tutti i path di PREZZO leggevano
`ch.text` direttamente: su un job spillato la stima collassava a ~0 €, la
decisione quota lo dichiarava sotto soglia -> "gratis", e /api/generate faceva
partire il job SENZA pagamento. Subito dopo `run_generation` reidratava i testi
dallo spill e sintetizzava il libro INTERO (costo reale a doppia cifra).

`char_count` sopravvive allo spill (calcolato in `Chapter.__post_init__` e mai
riazzerato): il cap `selection_too_large` continuava quindi a vedere il libro
vero, mentre il prezzo vedeva un libro vuoto. E' l'asimmetria che rende il
difetto silenzioso.

Invariante verificata qui: il prezzo di un job spillato deve essere IDENTICO a
quello dello stesso job non spillato, su ogni endpoint che quota o incassa.
"""
import pytest

import audiobook_app
import free_quota
import gemini_tts
import generation_engine
import payment
import speechify_tts
import tts_engines
import voxcpm_tts
from epub_to_tts import BookInfo, Chapter

CID = "cid_spill_pricing_test"
GEMINI_VOICE = "gemini:flash31:Zephyr"
SPEECHIFY_VOICE = "speechify:simba-3.2:harper_32"
VOXCPM_VOICE = "voxcpm:v2:it-IT/Stefano"
# ~50k char: listino ben sopra la soglia gratuita (0.50 €) e sopra la quota
# mensile di test, quindi il job DEVE richiedere pagamento in ogni caso.
BOOK_CHARS = 50000


class _SyncThread:
    """Rende sincrono threading.Thread (cfr. test_free_quota_generate_enforcement)."""

    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_PREMIUM_MIN_COST_EUR", "0.50")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "reserve_budget", lambda *a, **k: None)
    monkeypatch.setattr(gemini_tts, "release_reservation", lambda *a, **k: None)
    audiobook_app._invalidate_voices_cache()

    # Lo spill scrive nella job dir sotto _upload_dir: puntala su tmp_path.
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)

    run_calls = []
    monkeypatch.setattr(audiobook_app, "run_generation",
                        lambda job_id, info, voice, *a, **k: run_calls.append((job_id, voice)))
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)

    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")

    yield {"run_calls": run_calls, "tmp": tmp_path}

    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("spill-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(tmp_path, job_id, n_chars=BOOK_CHARS, language="it"):
    ch = Chapter(index=0, title="Cap0", text="Bla bla bla. " * (n_chars // 13))
    info = BookInfo(
        title="T", author="A", language=language, chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=10.0,
    )
    (tmp_path / job_id).mkdir(parents=True, exist_ok=True)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {
            "info": info, "status": "analyzed", "client_id": CID,
        }
    return audiobook_app.jobs[job_id]


def _spill(job_id, job):
    """Porta il job nello stato reale post-terminale: testi su disco, RAM vuota."""
    assert generation_engine.spill_job_texts(job_id, job) is True
    assert job["_texts_spilled"] is True
    assert all(ch.text == "" for ch in job["info"].chapters), \
        "precondizione: dopo lo spill i testi in RAM sono vuoti"
    # char_count sopravvive: e' quello che rende il difetto asimmetrico.
    assert sum(ch.char_count for ch in job["info"].chapters) > 0
    job["status"] = "analyzed"  # l'utente rilancia la generazione sullo stesso job


def _post_generate(client, job_id, **extra):
    payload = {"job_id": job_id, "voice": GEMINI_VOICE, "rate": "+0%",
               "output_format": "mp3", "lang": "it"}
    payload.update(extra)
    return client.post("/api/generate", json=payload)


# ---------------------------------------------------------------------------
# Precondizione: senza spill il gate funziona (402).
# ---------------------------------------------------------------------------

def test_generate_premium_richiede_pagamento_senza_spill(client, env):
    _mk_job(env["tmp"], "spill-baseline")
    r = _post_generate(client, "spill-baseline")
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error"] == "payment_required"
    assert env["run_calls"] == []


# ---------------------------------------------------------------------------
# Il difetto: stesso job, testi spillati -> deve restare a pagamento.
# ---------------------------------------------------------------------------

def test_generate_premium_su_job_spillato_richiede_pagamento(client, env):
    job = _mk_job(env["tmp"], "spill-generate")
    _spill("spill-generate", job)

    r = _post_generate(client, "spill-generate")
    assert r.status_code == 402, (
        "job spillato quotato a ~0 € -> voce PREMIUM partita gratis: "
        + r.get_data(as_text=True)
    )
    assert r.get_json()["error"] == "payment_required"
    assert env["run_calls"] == [], "nessuna generazione senza incasso"
    assert free_quota.used_eur(CID) == pytest.approx(0.0)


def test_stima_gemini_identica_con_e_senza_spill(client, env):
    job = _mk_job(env["tmp"], "spill-estimate")
    r_full = client.post("/api/gemini_estimate",
                         json={"job_id": "spill-estimate", "voice_id": GEMINI_VOICE,
                               "rate": "+0%", "lang": "it"})
    assert r_full.status_code == 200, r_full.get_data(as_text=True)
    full = r_full.get_json()
    assert full["user_price_eur"] > 0.50, "precondizione: libro a pagamento"

    _spill("spill-estimate", job)
    r_spilled = client.post("/api/gemini_estimate",
                            json={"job_id": "spill-estimate", "voice_id": GEMINI_VOICE,
                                  "rate": "+0%", "lang": "it"})
    assert r_spilled.status_code == 200, r_spilled.get_data(as_text=True)
    assert r_spilled.get_json()["user_price_eur"] == pytest.approx(
        full["user_price_eur"]), "lo spill non deve cambiare il prezzo mostrato"


def test_combined_estimate_identico_con_e_senza_spill(client, env):
    job = _mk_job(env["tmp"], "spill-combined")
    body = {"job_id": "spill-combined", "voice_id": GEMINI_VOICE, "rate": "+0%",
            "lang": "it", "ai_opt_enabled": True}
    r_full = client.post("/api/combined_estimate", json=body)
    assert r_full.status_code == 200, r_full.get_data(as_text=True)
    full = r_full.get_json()
    assert full["total_eur"] > 0.50

    _spill("spill-combined", job)
    r_spilled = client.post("/api/combined_estimate", json=body)
    assert r_spilled.status_code == 200, r_spilled.get_data(as_text=True)
    assert r_spilled.get_json()["total_eur"] == pytest.approx(full["total_eur"])


# ---------------------------------------------------------------------------
# /api/optimize con auto-generazione (wizard combinato): stesso invariante.
# Il ramo VoxCPM stimava sui capitoli in RAM senza `_pricing_chapters`: un job
# tornato "analyzed" dopo la generazione (/api/reset_to_chapters) pagava la
# sola quota AI, e un buono scalava solo quella, mentre la generazione
# reidratava i testi e leggeva il libro intero.
# ---------------------------------------------------------------------------

# voce, lingua del libro e della UI (Speechify legge solo inglese).
COMBINED_VOICES = [(GEMINI_VOICE, "it"), (SPEECHIFY_VOICE, "en"), (VOXCPM_VOICE, "it")]


@pytest.fixture
def opt_env(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "run_optimization",
                        lambda job_id, chapters: env["run_calls"].append((job_id, "optimize")))
    monkeypatch.setattr(speechify_tts, "is_available", lambda: True)
    monkeypatch.setattr(voxcpm_tts, "is_available", lambda: True)
    monkeypatch.setenv("ABM_SPEECHIFY_COST_USD_PER_MCHAR", "11.18")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.50")
    monkeypatch.setenv("ABM_VOXCPM_RATE_EUR_PER_MCHAR", "60")
    monkeypatch.setenv("ABM_VOXCPM_FREE_THRESHOLD_EUR", "0.50")
    # Quota mensile minima: ogni libro di test e' a pagamento su tutti i motori.
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "0.10")
    return env


def _post_optimize(client, job_id, voice, lang, **extra):
    payload = {"job_id": job_id, "batch": False, "lang": lang, "auto_generate": True,
               "voice": voice, "rate": "+0%", "single_file": True, "output_format": "m4b"}
    payload.update(extra)
    return client.post("/api/optimize", json=payload)


def _list_price_unspilled(client, env, voice, lang):
    """Dovuto (402) dello stesso libro con i testi ancora in RAM."""
    _mk_job(env["tmp"], "spill-opt-ref", language=lang)
    r = _post_optimize(client, "spill-opt-ref", voice, lang)
    assert r.status_code == 402, r.get_data(as_text=True)
    total = r.get_json()["total_eur"]
    assert total > 0.50, "precondizione: libro a pagamento"
    return total


@pytest.mark.parametrize("voice,lang", COMBINED_VOICES)
def test_optimize_su_job_spillato_chiede_lo_stesso_prezzo(client, opt_env, voice, lang):
    total = _list_price_unspilled(client, opt_env, voice, lang)
    job = _mk_job(opt_env["tmp"], "spill-opt", language=lang)
    _spill("spill-opt", job)

    r = _post_optimize(client, "spill-opt", voice, lang)
    assert r.status_code == 402, (
        "job spillato quotato sulla sola quota AI -> voce PREMIUM gratis: "
        + r.get_data(as_text=True))
    assert r.get_json()["total_eur"] == pytest.approx(total)
    assert job["status"] == "analyzed"
    assert opt_env["run_calls"] == []
    assert free_quota.used_eur(CID) == pytest.approx(0.0)


def test_optimize_voxcpm_su_job_spillato_il_buono_scala_il_prezzo_intero(client, opt_env):
    total = _list_price_unspilled(client, opt_env, VOXCPM_VOICE, "it")
    job = _mk_job(opt_env["tmp"], "spill-opt-vou")
    _spill("spill-opt-vou", job)
    code, _v = payment._create_voucher("u@x.it", 50.0, kind="test", note="t")
    before = payment._voucher_remaining(payment._vouchers[code])

    r = _post_optimize(client, "spill-opt-vou", VOXCPM_VOICE, "it", payment_token=code)
    assert r.status_code == 200, r.get_data(as_text=True)
    consumed = before - payment._voucher_remaining(payment._vouchers[code])
    assert consumed == pytest.approx(total, abs=0.005)
    assert job["payment_amount_eur"] == pytest.approx(total)
    assert job["payment"]["voxcpm_est"]["chars_total"] > 0


@pytest.mark.parametrize("voice,lang", COMBINED_VOICES)
def test_optimize_rifiuta_un_prezzo_su_testo_vuoto(client, opt_env, monkeypatch, voice, lang):
    # Spill illeggibile: `_pricing_chapters` ripiega sui capitoli vuoti in RAM.
    job = _mk_job(opt_env["tmp"], "spill-opt-empty", language=lang)
    _spill("spill-opt-empty", job)

    def _illeggibile(*a, **k):
        raise OSError("spill illeggibile")
    monkeypatch.setattr(generation_engine, "chapter_texts", _illeggibile)

    r = _post_optimize(client, "spill-opt-empty", voice, lang)
    assert r.status_code == 500, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "estimate_failed"
    assert job["status"] == "analyzed"
    assert opt_env["run_calls"] == []
    assert free_quota.used_eur(CID) == pytest.approx(0.0)


@pytest.mark.parametrize("voice,lang", COMBINED_VOICES)
def test_optimize_stima_fallita_non_parte_gratis(client, opt_env, monkeypatch, voice, lang):
    # Il ramo VoxCPM azzerava la stima e proseguiva col solo prezzo AI.
    job = _mk_job(opt_env["tmp"], "spill-opt-err", language=lang)

    def _giu(*a, **k):
        raise RuntimeError("stima giu'")
    monkeypatch.setattr(tts_engines, "estimate", _giu)

    r = _post_optimize(client, "spill-opt-err", voice, lang)
    assert r.status_code == 500, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "estimate_failed"
    assert job["status"] == "analyzed"
    assert opt_env["run_calls"] == []
    assert free_quota.used_eur(CID) == pytest.approx(0.0)
