"""Tetto di generazioni contemporanee per client: perimetro e falle chiuse.

Politica implementata:
  - il tetto `ABM_MAX_CONCURRENT_PER_CLIENT` vale SOLO per la corsia gratuita;
    le generazioni PREMIUM (voce Gemini/Speechify o pagamento incassato) non
    sono limitate e non consumano slot;
  - lo slot e' imputato a `gen_owner_cid`, fissato al claim e mai riscritto:
    il transfer verso l'app mobile cambia `client_id` ma non libera il posto
    (agosto 2026: un client con 8 generazioni contemporanee, tutte trasferite
    all'app subito dopo il GENERATE);
  - il ramo auto-gen del wizard (`/api/optimize` con `auto_generate`), che
    chiama `run_generation` senza passare da `/api/generate`, e' soggetto allo
    stesso tetto: rifiuto a monte in `/api/optimize`, attesa bloccante (non
    rifiuto) al momento di far partire l'audio.
"""
import pytest

import audiobook_app
import generation_engine
from epub_to_tts import BookInfo, Chapter

CID = "cid_gen_cap_test"
OTHER_CID = "cid_gen_cap_other"
PREMIUM_VOICE = "gemini:flash25:Zephyr"
FREE_VOICE = "en-US-AriaNeural"


class _SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    run_calls = []
    monkeypatch.setattr(audiobook_app, "run_generation",
                        lambda job_id, info, voice, *a, **k: run_calls.append((job_id, voice)))
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "MAX_CONCURRENT_PER_CLIENT", 2)
    monkeypatch.setattr(audiobook_app, "MAX_CONCURRENT_GLOBAL", 0)
    yield {"run_calls": run_calls}
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("cap-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(job_id, client_id=CID):
    ch = Chapter(index=0, title="Cap0", text="A" * 500)
    info = BookInfo(title="T", author="A", language="en", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {
            "info": info, "status": "analyzed", "client_id": client_id,
        }
    return audiobook_app.jobs[job_id]


def _running(job_id, **extra):
    job = {"status": "generating", "client_id": CID, "gen_owner_cid": CID}
    job.update(extra)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = job
    return job


def _post_generate(client, job_id, voice):
    return client.post("/api/generate", json={
        "job_id": job_id, "voice": voice, "rate": "+0%",
        "output_format": "mp3", "lang": "en",
    })


# ---------------------------------------------------------------------------
# Conteggio degli slot
# ---------------------------------------------------------------------------

def test_free_voice_oltre_il_tetto_respinta(client, env):
    _running("cap-r1")
    _running("cap-r2")
    _mk_job("cap-new")

    r = _post_generate(client, "cap-new", FREE_VOICE)

    assert r.status_code == 429, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "concurrent_limit"
    assert env["run_calls"] == []


def test_job_premium_in_corso_non_occupano_slot(client, env):
    """Due generazioni PREMIUM attive non devono bloccare un job gratuito."""
    _running("cap-p1", voice=PREMIUM_VOICE)
    _running("cap-p2", payment_amount_eur=1.5)
    _mk_job("cap-new")

    r = _post_generate(client, "cap-new", FREE_VOICE)

    assert r.status_code == 200, r.get_data(as_text=True)
    assert env["run_calls"] == [("cap-new", FREE_VOICE)]


def test_richiesta_premium_ignora_il_tetto(client, env):
    """Chi paga non ha tetto, anche con la corsia gratuita gia' satura."""
    _running("cap-r1")
    _running("cap-r2")
    _mk_job("cap-new")

    r = _post_generate(client, "cap-new", PREMIUM_VOICE)

    # Il gate pagamento/quota del ramo PREMIUM puo' rispondere 402/503 secondo
    # la configurazione: cio' che conta e' che non sia il tetto a fermarlo.
    body = r.get_json() or {}
    assert body.get("error_code") != "concurrent_limit", r.get_data(as_text=True)


def test_transfer_a_mobile_non_libera_lo_slot(client, env):
    """Il transfer riassegna client_id ma non gen_owner_cid: slot ancora occupato."""
    _running("cap-r1", client_id="app-deadbeef")
    _running("cap-r2", client_id="app-deadbeef")
    _mk_job("cap-new")

    with audiobook_app._jobs_lock:
        assert audiobook_app._active_generating_for_client_unlocked(CID) == 2

    r = _post_generate(client, "cap-new", FREE_VOICE)
    assert r.status_code == 429, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "concurrent_limit"


def test_slot_imputato_ad_altro_client_non_conta(client, env):
    _running("cap-o1", gen_owner_cid=OTHER_CID, client_id=OTHER_CID)
    _running("cap-o2", gen_owner_cid=OTHER_CID, client_id=OTHER_CID)
    _mk_job("cap-new")

    r = _post_generate(client, "cap-new", FREE_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)


def test_claim_registra_gen_owner_cid(client, env):
    _mk_job("cap-new")
    r = _post_generate(client, "cap-new", FREE_VOICE)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert audiobook_app.jobs["cap-new"]["gen_owner_cid"] == CID


# ---------------------------------------------------------------------------
# Ramo auto-gen (wizard ottimizza + genera)
# ---------------------------------------------------------------------------

def test_optimize_auto_generate_respinto_oltre_il_tetto(client, env, monkeypatch):
    """Senza questo controllo il wizard aggirava del tutto il tetto: la
    generazione parte da run_optimization, non da /api/generate."""
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    _running("cap-r1")
    _running("cap-r2")
    _mk_job("cap-opt")

    r = client.post("/api/optimize", json={
        "job_id": "cap-opt", "auto_generate": True, "voice": FREE_VOICE,
        "lang": "en",
    })

    assert r.status_code == 429, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "concurrent_limit"
    # Il claim "optimizing" deve essere rilasciato, altrimenti il job resta
    # brickato e ogni retry viene respinto con "already running".
    assert audiobook_app.jobs["cap-opt"]["status"] == "analyzed"


def test_optimize_auto_generate_premium_non_respinto(client, env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    _running("cap-r1")
    _running("cap-r2")
    _mk_job("cap-opt")

    r = client.post("/api/optimize", json={
        "job_id": "cap-opt", "auto_generate": True, "voice": PREMIUM_VOICE,
        "lang": "en",
    })

    body = r.get_json() or {}
    assert body.get("error_code") != "concurrent_limit", r.get_data(as_text=True)


# ---------------------------------------------------------------------------
# Attesa slot lato engine
# ---------------------------------------------------------------------------

def test_wait_gen_slot_non_attende_per_i_premium(monkeypatch):
    calls = []
    monkeypatch.setattr(generation_engine, "_client_gen_cap_reached",
                        lambda cid, jid=None: (calls.append(cid), (True, 9, 2))[1])
    waited = generation_engine._wait_gen_slot(
        {"client_id": CID, "voice": PREMIUM_VOICE}, "cap-x")
    assert waited == 0.0
    assert calls == []


def test_wait_gen_slot_attende_e_poi_procede(monkeypatch):
    """Slot occupato: si attende, non si scarta il lavoro gia' ottimizzato."""
    sleeps = []
    states = [True, True, False]
    monkeypatch.setattr(generation_engine, "_client_gen_cap_reached",
                        lambda cid, jid=None: (states.pop(0) if states else False, 2, 2))
    monkeypatch.setattr(generation_engine.time, "sleep", sleeps.append)
    monkeypatch.setattr(generation_engine, "GEN_SLOT_WAIT_SEC", 60.0)
    monkeypatch.setattr(generation_engine, "GEN_SLOT_POLL_SEC", 5.0)

    waited = generation_engine._wait_gen_slot({"client_id": CID, "voice": FREE_VOICE},
                                              "cap-x")

    assert sleeps == [5.0, 5.0]
    assert waited == pytest.approx(10.0)


def test_wait_gen_slot_timeout_procede_comunque(monkeypatch):
    """Oltre il timeout si genera lo stesso: a valle di un'ottimizzazione
    (spesso pagata) rifiutare significherebbe distruggere lavoro dell'utente."""
    monkeypatch.setattr(generation_engine, "_client_gen_cap_reached",
                        lambda cid, jid=None: (True, 3, 2))
    monkeypatch.setattr(generation_engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(generation_engine, "GEN_SLOT_WAIT_SEC", 10.0)
    monkeypatch.setattr(generation_engine, "GEN_SLOT_POLL_SEC", 5.0)

    waited = generation_engine._wait_gen_slot({"client_id": CID, "voice": FREE_VOICE},
                                              "cap-x")

    assert waited >= 10.0


def test_wait_gen_slot_interrotto_da_cancellazione(monkeypatch):
    monkeypatch.setattr(generation_engine, "_client_gen_cap_reached",
                        lambda cid, jid=None: (True, 3, 2))
    monkeypatch.setattr(generation_engine.time, "sleep", lambda s: None)
    monkeypatch.setattr(generation_engine, "GEN_SLOT_WAIT_SEC", 600.0)

    waited = generation_engine._wait_gen_slot(
        {"client_id": CID, "voice": FREE_VOICE, "opt_cancelled": True}, "cap-x")

    assert waited == 0.0
