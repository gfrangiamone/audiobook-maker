"""Motore Pocket TTS (worker abm-pocket-worker su VPS): client, chunk diretto,
pre-sintesi con i chunk riusati, audit, tag, gate di configurazione."""
import pathlib
import types

import pytest
import requests

import generation_engine as ge
import pocket_tts
import premium_chunk
import tts_engines
import voice_utils

VOICE = "pocket:v1:it-IT/Chiara"


@pytest.fixture
def worker_env(monkeypatch):
    monkeypatch.setenv("ABM_POCKET_URL", "https://pocket.example/")
    monkeypatch.setenv("ABM_POCKET_TOKEN", "tok")


class _Resp:
    def __init__(self, status, content=b"", text="", body=None):
        self.status_code = status
        self.content = content
        self.text = text
        self.body = body

    def json(self):
        if self.body is None:
            raise ValueError("no json")
        return self.body


class _Session:
    """Risposte in coda; registra le chiamate."""

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append((url, json, headers))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


# --- voci e registro ----------------------------------------------------------

def test_voice_id_and_registry():
    assert voice_utils.engine_for_voice(VOICE) == "pocket"
    assert voice_utils.is_premium_voice(VOICE) and voice_utils.voice_id_shape_ok(VOICE)
    assert pocket_tts.parse_voice_id("pocket:v1:es-AR/Agustín") == ("v1", "es-AR", "Agustín")
    for bad in ("pocket:v2:it-IT/Chiara", "pocket:v1:it/Chiara", "pocket:v1:it-IT/", "voxcpm:v2:it-IT/Chiara"):
        with pytest.raises(ValueError):
            pocket_tts.parse_voice_id(bad)
    eng = tts_engines.ENGINES["pocket"]
    assert eng.direct and eng.sample_rate({}) == 24000 and "pocket" in tts_engines.DIRECT
    assert ge._friendly_voice_name(VOICE) == "Chiara"


def test_available_only_with_url_and_token(monkeypatch):
    monkeypatch.delenv("ABM_POCKET_URL", raising=False)
    monkeypatch.setenv("ABM_POCKET_TOKEN", "tok")
    assert not pocket_tts.is_available() and not tts_engines.ENGINES["pocket"].is_available()
    monkeypatch.setenv("ABM_POCKET_URL", "https://pocket.example")
    assert pocket_tts.is_available()


def test_price_flat_rate_with_book_minimum(monkeypatch):
    monkeypatch.delenv("ABM_POCKET_RATE_EUR_PER_MCHAR", raising=False)
    monkeypatch.delenv("ABM_POCKET_MIN_PRICE_EUR", raising=False)
    big = pocket_tts.compute_user_price_eur(1_000_000, "de")
    assert big["list_price_eur"] == big["user_price_eur"] == 11.0 and not big["is_free"]
    assert big["cost_usd"] == 0.0 and big["free_threshold_eur"] == 0.0
    small = pocket_tts.compute_user_price_eur(10_000, "it")
    assert small["list_price_eur"] == 0.11 and small["user_price_eur"] == 0.5   # minimo per libro
    assert pocket_tts.compute_user_price_eur(0)["user_price_eur"] == 0.5        # mai gratis
    monkeypatch.setenv("ABM_POCKET_RATE_EUR_PER_MCHAR", "20")
    monkeypatch.setenv("ABM_POCKET_MIN_PRICE_EUR", "1.5")
    assert pocket_tts.compute_user_price_eur(1_000_000)["user_price_eur"] == 20.0
    assert pocket_tts.compute_user_price_eur(10_000)["user_price_eur"] == 1.5


def test_catalog_mode_is_free_and_not_offered(worker_env, monkeypatch):
    assert pocket_tts.is_paid() and pocket_tts.is_offered()
    monkeypatch.setenv("ABM_POCKET_RATE_EUR_PER_MCHAR", "0")
    price = pocket_tts.compute_user_price_eur(1_000_000, "it")
    assert price["user_price_eur"] == price["list_price_eur"] == 0.0 and price["is_free"]
    assert not pocket_tts.is_paid() and not pocket_tts.is_offered()
    assert pocket_tts.free_threshold_eur() == pocket_tts.FREE_THRESHOLD_EUR


def test_estimate_counts_chars_and_consumed_uses_list_price():
    chs = [types.SimpleNamespace(title="", text="Uno due tre."), types.SimpleNamespace(title="", text="Quattro.")]
    est = tts_engines.estimate("pocket", chs, language="it")
    assert est["chars_total"] == len("Uno due tre.") + len("Quattro.")
    assert est["user_price_eur"] == pocket_tts.min_price_eur() and est["model_label"] == pocket_tts.MODEL_LABEL
    consumed = tts_engines.ENGINES["pocket"].consumed_list_price_eur({"pocket_actual": {"chars": 500_000}})
    assert consumed == pocket_tts.compute_user_price_eur(500_000)["list_price_eur"] == 5.5


def test_free_quota_never_free_for_paid_pocket(monkeypatch, tmp_path):
    import free_quota
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ABM_POCKET_RATE_EUR_PER_MCHAR", raising=False)
    assert free_quota.never_free(VOICE) and not free_quota.never_free("voxcpm:v2:it-IT/Chiara")
    d = free_quota.decision("cid-x", VOICE, 0.11, job_id="J1", book_chars=10_000, language="it")
    assert d["due_eur"] == 0.5 and not d["is_free"] and d["threshold_eur"] == 0.0
    assert free_quota.decision("cid-x", VOICE, 3.2)["due_eur"] == 3.2
    monkeypatch.setenv("ABM_POCKET_RATE_EUR_PER_MCHAR", "0")
    assert not free_quota.never_free(VOICE)


def test_voice_language():
    assert pocket_tts.voice_language("pocket:v1:de-DE/Franziska") == "de"
    with pytest.raises(ValueError):
        pocket_tts.voice_language("voxcpm:v2:de-DE/Franziska")


# --- client HTTP ---------------------------------------------------------------

def test_synthesize_writes_pcm_and_sends_worker_voice(worker_env, tmp_path):
    out = tmp_path / "c.pcm"
    sess = _Session(_Resp(200, b"\x01\x00" * 24000))
    res = pocket_tts.synthesize("Ciao a tutti.", VOICE, str(out), rate="+0%", session=sess)
    assert out.read_bytes() == b"\x01\x00" * 24000
    assert res["success"] and res["sample_rate"] == 24000 and res["bytes_written"] == 48000
    url, payload, headers = sess.calls[0]
    assert url == "https://pocket.example/v1/synthesize"
    assert payload == {"text": "Ciao a tutti.", "voice": "it-IT/Chiara", "lang": "it", "normalize": True}
    assert headers == {"Authorization": "Bearer tok"}


def test_synthesize_applica_la_velocita_al_pcm(worker_env, tmp_path):
    # Il worker legge al ritmo della voce: +30% lo stira ABM con ffmpeg vero,
    # e i byte scritti (durata dei marker e dell'audit) sono quelli nuovi.
    out = tmp_path / "c.pcm"
    sess = _Session(_Resp(200, b"\x00\x00" * 24000))     # 1 s a 24 kHz
    res = pocket_tts.synthesize("Ciao a tutti.", VOICE, str(out), rate="+30%", session=sess)
    assert 30000 < out.stat().st_size < 42000              # ~1/1,3 di 48000 byte
    assert res["bytes_written"] == out.stat().st_size
    assert sess.calls[0][1]["text"] == "Ciao a tutti."     # niente velocita' al worker


def test_synthesize_velocita_fallita_tiene_l_audio(worker_env, tmp_path, monkeypatch):
    # ffmpeg mancante: il chunk arriva a velocita' normale invece di perdersi.
    import subprocess

    def fallisce(cmd, **kw):
        raise FileNotFoundError("ffmpeg non trovato")

    monkeypatch.setattr(subprocess, "run", fallisce)
    out = tmp_path / "c.pcm"
    sess = _Session(_Resp(200, b"\x01\x02" * 24000))
    res = pocket_tts.synthesize("Ciao.", VOICE, str(out), rate="-20%", session=sess)
    assert res["success"] and out.read_bytes() == b"\x01\x02" * 24000
    assert res["bytes_written"] == 48000 and not (tmp_path / "c.pcm.rate").exists()


def test_synthesize_retries_restart_and_network_then_succeeds(worker_env, tmp_path):
    waits = []
    sess = _Session(_Resp(503, text="worker in riavvio"), requests.ConnectionError("giu'"),
                    _Resp(200, b"\x00\x00"))
    res = pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                                sleep=waits.append)
    assert res["success"] and len(sess.calls) == 3 and waits == [5.0, 10.0]


def test_synthesize_fatal_on_4xx_and_gives_up_after_attempts(worker_env, tmp_path):
    sess = _Session(_Resp(404, text="voce it-IT/Chiara non presente"))
    with pytest.raises(pocket_tts.PocketFatalError):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess)
    assert len(sess.calls) == 1
    # 502 del worker (chunk fallito: JSON con detail, come FastAPI).
    sess = _Session(*[_Resp(502, text='{"detail":"chunk fallito"}', body={"detail": "chunk fallito"})] * 2)
    with pytest.raises(RuntimeError, match="after 2 attempts"):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                              max_attempts=2, sleep=lambda s: None)


def test_synthesize_rete_giu_oltre_i_tentativi_non_ammutolisce_il_chunk(worker_env, tmp_path):
    # Michael Kohlhaas (catalogo, 18/11/2026): un ConnectTimeout di qualche
    # minuto esauriva i 5 tentativi e il chunk diventava silenzio. Il worker
    # irraggiungibile non consuma tentativi: il chunk aspetta che torni.
    waits = []
    down = [requests.ConnectTimeout("VPS irraggiungibile")] * 8
    sess = _Session(*down, _Resp(200, b"\x00\x00"))
    res = pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                                sleep=waits.append)
    assert res["success"] and len(sess.calls) == 9
    assert waits == [5.0, 10.0, 20.0, 40.0, 60.0, 60.0, 60.0, 60.0]


def test_synthesize_worker_giu_troppo_a_lungo_e_motore_spento(worker_env, tmp_path, monkeypatch):
    # Oltre ABM_POCKET_OUTAGE_WAIT_S il motore e' spento: il job fallisce col
    # rimborso (PocketUnavailable risale dal wrapper), mai chunk muti.
    monkeypatch.setenv("ABM_POCKET_OUTAGE_WAIT_S", "60")
    clock = _Clock()
    sess = _Session(*[requests.ConnectionError("giu'")] * 5)
    with pytest.raises(pocket_tts.PocketWorkerDown, match="unreachable for 75 s"):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                              sleep=clock.sleep, clock=clock)
    assert len(sess.calls) == 5 and clock.t == 75          # pause 5+10+20+40
    assert issubclass(pocket_tts.PocketWorkerDown, pocket_tts.PocketUnavailable)

    def _giu(*a, **k):
        raise pocket_tts.PocketWorkerDown("unreachable")
    monkeypatch.setattr(pocket_tts, "synthesize", _giu)
    out = tmp_path / "w.pcm"
    with pytest.raises(pocket_tts.PocketWorkerDown):
        premium_chunk.generate_chunk_pcm_pocket("Un testo.", VOICE, str(out))
    assert not out.exists()                                 # niente silenzio scritto


def test_synthesize_502_del_proxy_e_worker_giu_non_errore_del_chunk(worker_env, tmp_path):
    # Il proxy davanti al VPS risponde 502/504 senza JSON quando il worker e'
    # spento o riparte: non consuma l'unico tentativo, il 502 del worker si'.
    sess = _Session(_Resp(502, text="<html>Bad Gateway</html>"), _Resp(504, text=""),
                    _Resp(200, b"\x00\x00"))
    res = pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                                max_attempts=1, sleep=lambda s: None)
    assert res["success"] and len(sess.calls) == 3
    sess = _Session(_Resp(504, text='{"detail":"chunk non pronto"}', body={"detail": "chunk non pronto"}))
    with pytest.raises(RuntimeError, match="after 1 attempts"):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                              max_attempts=1, sleep=lambda s: None)


def test_synthesize_annullato_mentre_il_worker_e_giu(worker_env, tmp_path):
    ticket = pocket_tts.BookTicket("J1", 100, "it", check_cancelled=lambda: True,
                                   session=_QSession(), sleep=lambda s: None)
    sess = _Session(requests.ConnectionError("giu'"))
    with pytest.raises(pocket_tts.PocketFatalError, match="cancelled while worker unreachable"):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess, book=ticket,
                              sleep=lambda s: None)
    assert len(sess.calls) == 1


def test_synthesize_unavailable_without_config(monkeypatch, tmp_path):
    monkeypatch.delenv("ABM_POCKET_URL", raising=False)
    with pytest.raises(pocket_tts.PocketUnavailable):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"))


# --- wrapper di chunk -----------------------------------------------------------

def test_chunk_wrapper_silence_at_24k_on_fatal(worker_env, monkeypatch, tmp_path):
    def _fatal(*a, **k):
        raise pocket_tts.PocketFatalError("HTTP 404")
    monkeypatch.setattr(pocket_tts, "synthesize", _fatal)
    out, fi = tmp_path / "c.pcm", {}
    assert premium_chunk.generate_chunk_pcm_pocket("Un testo.", VOICE, str(out), failure_info=fi) is False
    assert out.stat().st_size == 24000 * 2 and fi["reason"] == "synthesize_failed"


def test_chunk_wrapper_reraises_unavailable(monkeypatch, tmp_path):
    monkeypatch.delenv("ABM_POCKET_URL", raising=False)
    with pytest.raises(pocket_tts.PocketUnavailable):
        premium_chunk.generate_chunk_pcm_pocket("Un testo.", VOICE, str(tmp_path / "c.pcm"))


# --- generazione -------------------------------------------------------------------

def test_presynth_skips_reused_chunks(monkeypatch, tmp_path):
    plan = [{"text": f"chunk {i}"} for i in range(5)]
    job, seen = {}, []

    def _fake(text, voice, path, emotion=None, rate="+0%", failure_info=None):
        seen.append(text)
        pathlib.Path(path).write_bytes(b"\x00\x00")
        return {"success": True, "bytes_written": 2, "sample_rate": 24000, "billable_chars": len(text)}

    monkeypatch.setattr(ge, "generate_chunk_pcm_pocket", _fake)
    out = ge._direct_presynth(job, "pocket", plan, tmp_path, VOICE, emotion=None, rate="+0%",
                              check_cancelled=lambda: False, start_time=0.0, skip={1, 3})
    assert sorted(out) == [0, 2, 4] and sorted(seen) == ["chunk 0", "chunk 2", "chunk 4"]
    assert job["progress_current"] == 2 + len(plan)       # i riusati contano come fatti
    assert "speechify_sample_rate" not in job


def test_actual_and_audit_record(monkeypatch):
    job = {"pocket_actual": ge._new_direct_actual()}
    ge._accumulate_direct_actual(job, "pocket", {"text": "ciao"},
                                 {"billable_chars": 4, "bytes_written": 48000, "sample_rate": 24000})
    assert job["pocket_actual"]["audio_seconds"] == 1.0 and job["pocket_actual"]["model_key"] == "v1"
    recs = []
    monkeypatch.setattr(ge.gemini_cost_audit, "append_record", recs.append)
    ge._write_pocket_audit("J", job, VOICE, "it", "completed")
    assert recs and recs[0]["provider"] == "pocket" and recs[0]["model_key"] == "v1"
    assert recs[0]["google_cost_eur_actual"] == 0.0 and recs[0]["chars_total"] == 4
    ge._write_pocket_audit("J", job, "gemini:flash31:Zephyr", "it", "completed")   # altra voce: no-op
    assert len(recs) == 1


def test_generation_tags_for_pocket_voice():
    info = types.SimpleNamespace(title="Libro", author="Autore", language="it")
    tags = ge._generation_tags({}, info, VOICE, "+0%")
    assert tags["abm_model"] == pocket_tts.MODEL_LABEL and tags["abm_voice"] == "Chiara"
    assert tags["abm_language"] == "it-IT" and tags["abm_voice_id"] == VOICE


def test_model_gate_rejects_pocket_without_worker(monkeypatch):
    import audiobook_app
    monkeypatch.delenv("ABM_POCKET_URL", raising=False)
    with audiobook_app.app.test_request_context():
        resp, status = audiobook_app._premium_model_gate(VOICE)
        assert status == 400 and resp.get_json()["error"] == "pocket_not_configured"
        monkeypatch.setenv("ABM_POCKET_URL", "https://pocket.example")
        monkeypatch.setenv("ABM_POCKET_TOKEN", "tok")
        assert audiobook_app._premium_model_gate(VOICE) is None


# --- coda per libro (BookTicket) ------------------------------------------------

QUEUED = {"state": "queued", "position": 1, "wait_s": 100, "eta_s": 400}
ACTIVE = {"state": "active", "position": 0, "wait_s": 0, "eta_s": 300}


class _QSession:
    """Risposte in coda per metodo HTTP; registra (metodo, url, json)."""

    def __init__(self, **by_method):
        self.resp = {m: list(v) for m, v in by_method.items()}
        self.calls = []

    def _take(self, method, url, json=None):
        self.calls.append((method, url, json))
        r = self.resp[method].pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def put(self, url, json=None, headers=None, timeout=None):
        return self._take("put", url, json)

    def get(self, url, headers=None, timeout=None):
        return self._take("get", url)

    def delete(self, url, headers=None, timeout=None):
        return self._take("delete", url)


class _Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


def _ticket(sess, clock, **kw):
    return pocket_tts.BookTicket("J1", 5000, "de-DE", session=sess, sleep=clock.sleep, clock=clock, **kw)


def test_ticket_join_waits_for_turn(worker_env):
    sess, clock, seen = _QSession(put=[_Resp(200, body=QUEUED)],
                                  get=[_Resp(200, body=QUEUED), _Resp(200, body=ACTIVE)]), _Clock(), []
    t = _ticket(sess, clock, on_state=seen.append)
    assert t.join() is True
    assert sess.calls[0] == ("put", "https://pocket.example/v1/books/J1",
                             {"lang": "de", "chars": 5000, "priority": 10})
    assert [s["state"] for s in seen] == ["queued", "queued", "active"]
    assert clock.t == 50                    # due pause da wait_s/4 = 25 s
    assert t.chunk_fields() == {"book": "J1", "book_chars": 5000, "priority": 10}


def test_ticket_join_cancelled_while_waiting(worker_env):
    sess, clock = _QSession(put=[_Resp(200, body=QUEUED)]), _Clock()
    t = _ticket(sess, clock, check_cancelled=lambda: clock.t >= 10)
    assert t.join() is False
    assert [c[0] for c in sess.calls] == ["put"]          # nessun controllo dopo l'annullo


def test_ticket_times_out(worker_env, monkeypatch):
    monkeypatch.setenv("ABM_POCKET_MAX_QUEUE_WAIT_S", "60")
    far = {**QUEUED, "wait_s": 10_000}
    sess, clock = _QSession(put=[_Resp(200, body=far)], get=[_Resp(200, body=far)] * 3), _Clock()
    with pytest.raises(pocket_tts.PocketQueueTimeout):
        _ticket(sess, clock).join()
    assert issubclass(pocket_tts.PocketQueueTimeout, pocket_tts.PocketUnavailable)


def test_ticket_redeclares_book_lost_by_worker(worker_env):
    # Worker in riavvio alla dichiarazione, poi 404 (coda persa): il libro si
    # ridichiara e riprende il turno.
    sess, clock = _QSession(put=[requests.ConnectionError("giu'"), _Resp(200, body=ACTIVE)],
                            get=[_Resp(404)]), _Clock()
    assert _ticket(sess, clock).join() is True
    assert [c[0] for c in sess.calls] == ["put", "get", "put"]


def test_ticket_rejected_book_is_fatal_and_close_is_best_effort(worker_env):
    sess, clock = _QSession(put=[_Resp(422, text="lingua")], delete=[requests.ConnectionError("x")]), _Clock()
    t = _ticket(sess, clock)
    with pytest.raises(pocket_tts.PocketFatalError):
        t.join()
    t.close()                                             # non solleva


def test_synthesize_waits_turn_on_423_within_same_attempt(worker_env, tmp_path):
    qs, clock = _QSession(get=[_Resp(200, body=ACTIVE)]), _Clock()
    ticket = pocket_tts.BookTicket("J1", 100, "it", session=qs, sleep=clock.sleep, clock=clock)
    sess = _Session(_Resp(423, body=QUEUED), _Resp(200, b"\x00\x00"))
    res = pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess,
                                book=ticket, max_attempts=1)
    assert res["success"] and len(sess.calls) == 2 and ticket.state["state"] == "active"
    payload = sess.calls[0][1]
    assert (payload["book"], payload["book_chars"], payload["priority"]) == ("J1", 100, 10)


def test_synthesize_cancelled_while_queued_is_fatal(worker_env, tmp_path):
    ticket = pocket_tts.BookTicket("J1", 100, "it", check_cancelled=lambda: True,
                                   session=_QSession(), sleep=lambda s: None)
    sess = _Session(_Resp(423, body=QUEUED))
    with pytest.raises(pocket_tts.PocketFatalError, match="cancelled"):
        pocket_tts.synthesize("Testo.", VOICE, str(tmp_path / "c.pcm"), session=sess, book=ticket)
    assert len(sess.calls) == 1


def test_estimate_delivery(worker_env, monkeypatch):
    seen = {}

    def _get(url, headers=None, params=None, timeout=None):
        seen.update(url=url, params=params, timeout=timeout)
        return _Resp(200, body={"position": 0, "wait_s": 0, "eta_s": 1200})

    monkeypatch.setattr(pocket_tts.requests, "get", _get)
    assert pocket_tts.estimate_delivery(48_000, "fr-FR")["eta_s"] == 1200
    assert seen["url"] == "https://pocket.example/v1/eta"
    assert seen["params"] == {"lang": "fr", "chars": 48_000, "priority": 10} and seen["timeout"] <= 5

    def _down(*a, **k):
        raise requests.ConnectionError("giu'")

    monkeypatch.setattr(pocket_tts.requests, "get", _down)
    assert pocket_tts.estimate_delivery(1, "it") is None
    monkeypatch.delenv("ABM_POCKET_URL")
    assert pocket_tts.estimate_delivery(1, "it") is None


class _FakeTicket:
    def __init__(self, book_id, chars, language, check_cancelled=None, on_state=None, joins=True):
        self.args, self.on_state, self.closed, self.joins = (book_id, chars, language), on_state, False, joins

    def join(self):
        self.on_state({"state": "queued", "position": 2, "wait_s": 60, "eta_s": 600})
        return self.joins

    def close(self):
        self.closed = True


def test_presynth_holds_book_ticket_and_closes_it(monkeypatch, tmp_path):
    plan = [{"text": f"chunk {i}"} for i in range(3)]
    job, books, made = {}, [], []

    def _fake(text, voice, path, emotion=None, rate="+0%", failure_info=None, book=None):
        books.append(book)
        pathlib.Path(path).write_bytes(b"\x00\x00")
        return {"success": True, "bytes_written": 2, "sample_rate": 24000, "billable_chars": len(text)}

    monkeypatch.setattr(ge, "generate_chunk_pcm_pocket", _fake)
    monkeypatch.setattr(pocket_tts, "BookTicket", lambda *a, **k: made.append(_FakeTicket(*a, **k)) or made[-1])
    out = ge._direct_presynth(job, "pocket", plan, tmp_path, VOICE, emotion=None, rate="+0%",
                              check_cancelled=lambda: False, start_time=0.0, skip={0}, job_id="J1")
    (ticket,) = made
    assert sorted(out) == [1, 2] and ticket.args == ("J1", len("chunk 1") + len("chunk 2"), "it")
    assert books == [ticket, ticket] and ticket.closed
    assert job["book_queue"]["position"] == 3 and job["book_queue"]["eta_s"] == 600


def test_presynth_cancelled_in_queue_closes_ticket(monkeypatch, tmp_path):
    made = []
    monkeypatch.setattr(pocket_tts, "BookTicket",
                        lambda *a, **k: made.append(_FakeTicket(*a, joins=False, **k)) or made[-1])
    with pytest.raises(ge._CancelledError):
        ge._direct_presynth({}, "pocket", [{"text": "x"}], tmp_path, VOICE, emotion=None, rate="+0%",
                            check_cancelled=lambda: False, start_time=0.0, job_id="J1")
    assert made[0].closed


def test_book_queue_note_sets_queued_message():
    job = {}
    ge._note_book_queue(job, QUEUED)
    assert job["book_queue"]["position"] == 2 and job["progress_message"] == ge.BOOK_QUEUED_MSG
    job["progress_message"] = "x"
    ge._note_book_queue(job, ACTIVE)
    assert job["book_queue"]["state"] == "active" and job["progress_message"] == "x"
    ge._note_book_queue(job, None)                         # stato illeggibile: no-op
    assert job["book_queue"]["state"] == "active"


def test_recovery_rejects_unpaid_pocket_job(monkeypatch, tmp_path):
    # Mai gratuito: un descrittore senza pagamento non riparte al boot.
    import audiobook_app  # noqa: F401 — configura recovery
    import recovery
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    text = "Testo del capitolo. " * 20
    info = types.SimpleNamespace(chapters=[types.SimpleNamespace(index=0, title="", text=text,
                                                                 char_count=len(text))],
                                 language="it")
    with pytest.raises(recovery._RecoveryRejected, match="SENZA pagamento"):
        recovery._recovery_generate_gate("J1", {"voice": VOICE, "client_id": "c"}, info)
    out = recovery._recovery_generate_gate("J1", {"voice": VOICE, "payment": {"total_eur": 0.5}}, info)
    assert out["estimate_key"] == tts_engines.ENGINES["pocket"].estimate_key
    assert out["estimate"]["chars_total"] == len(text)
