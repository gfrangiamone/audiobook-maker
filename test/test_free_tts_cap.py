"""Tetto duro mensile dei caratteri a voce standard (cap) in /api/generate.

Contratto: oltre `ABM_FREE_TTS_CAP_CHARS_PER_MONTH` /api/generate risponde 402
`free_tts_cap_reached` e nessun ack lo supera (ne' l'email registrata ne' la
push): il cap e' un soffitto, il gate email era solo un rallentamento. Il cap
e' contato sull'identita' di quota E sull'hash dell'email del gate, cosi'
cancellare il cookie non azzera il contatore. Il job resta riavviabile (stato
ripristinato, nulla consumato) e il log riporta QUOTA_CAP.
"""
import pytest

import audiobook_app
import free_tts_quota as ftq
import generation_engine
import payment
from epub_to_tts import BookInfo, Chapter

CID = "cid_tts_cap_test"
CID2 = "cid_tts_cap_test_rotated"
MAIL = "reader@example.com"
VOICE = "en-US-AriaNeural"


class _SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "1000")
    monkeypatch.setenv("ABM_FREE_TTS_CAP_CHARS_PER_MONTH", "2000")
    monkeypatch.setenv("ABM_IP_SALT", "test-salt")
    monkeypatch.delenv("ABM_OUTPUT_REUSE", raising=False)
    run_calls, log_calls = [], []

    def _fake_run(job_id, info, voice, rate, single_file, **kw):
        run_calls.append((job_id, voice, kw))

    monkeypatch.setattr(audiobook_app, "run_generation", _fake_run)
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **k: log_calls.append((a, k)))
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    yield {"run": run_calls, "log": log_calls}
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("cap-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(job_id, n_chars, client_id=CID, email=""):
    ch = Chapter(index=0, title="Cap0", text="A" * n_chars)
    info = BookInfo(title="T", author="A", language="en", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    job = {"info": info, "status": "analyzed", "client_id": client_id}
    if email:
        job["notify_email"] = email
        job["email_registered"] = True
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = job
    return audiobook_app.jobs[job_id]


def _post(client, job_id, **extra):
    payload = {"job_id": job_id, "voice": VOICE, "rate": "+0%",
               "output_format": "mp3", "lang": "en"}
    payload.update(extra)
    return client.post("/api/generate", json=payload)


def _ops(log_calls):
    return [a[2] for a, _k in log_calls]


# ---------------------------------------------------------------- modulo

def test_mail_key_stable_salted_and_case_insensitive(env):
    k = ftq.mail_key(MAIL)
    assert k.startswith("mail:") and len(k) == len("mail:") + 16
    assert ftq.mail_key("  Reader@Example.COM ") == k
    assert ftq.mail_key("other@example.com") != k
    assert MAIL.split("@")[0] not in k
    assert ftq.mail_key("") == "" and ftq.mail_key("non-una-email") == ""


def test_mail_key_depends_on_salt(env, monkeypatch):
    k = ftq.mail_key(MAIL)
    monkeypatch.setenv("ABM_IP_SALT", "altro-salt")
    assert ftq.mail_key(MAIL) != k


def test_consume_with_email_fills_both_keys_and_hides_mail_from_digest(env):
    ftq.consume(CID, 700, "j1", gated=True, email=MAIL)
    assert ftq.used_chars(CID) == 700
    assert ftq._used_key(ftq.mail_key(MAIL)) == 700
    assert list(ftq.month_table().keys()) == [CID], "le chiavi mail: non sono client"


def test_refund_frees_both_keys(env):
    ftq.consume(CID, 700, "j1", email=MAIL)
    assert ftq.refund(CID, "j1", email=MAIL) == 700
    assert ftq.used_chars(CID) == 0
    assert ftq._used_key(ftq.mail_key(MAIL)) == 0


def test_cap_decision_blocks_on_email_key_alone(env):
    ftq.consume(CID, 1900, "j1", email=MAIL)  # cid "vecchio"
    dec = ftq.cap_decision(CID2, 500, "j2", email=MAIL)
    assert dec["allowed"] is False and dec["cap_reached"] is True
    assert dec["key"] == "mail" and dec["used_chars"] == 1900
    assert ftq.cap_decision(CID2, 500, "j2")["allowed"] is True, "senza email: cid nuovo pulito"


def test_cap_decision_allows_retry_of_charged_generation(env):
    ftq.consume(CID, 2500, "j1", email=MAIL)  # gia' oltre cap (job storico)
    assert ftq.cap_decision(CID, 500, "j1", email=MAIL)["allowed"] is True
    assert ftq.cap_decision(CID, 500, "j2", email=MAIL)["allowed"] is False


def test_cap_off_never_blocks(env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_CAP_CHARS_PER_MONTH", "0")
    ftq.consume(CID, 10_000_000, "j1")
    assert ftq.cap_decision(CID, 500, "j2")["allowed"] is True


def test_cap_default_is_25_mchars(env, monkeypatch):
    monkeypatch.delenv("ABM_FREE_TTS_CAP_CHARS_PER_MONTH", raising=False)
    assert ftq.cap_chars() == 25_000_000
    monkeypatch.setenv("ABM_FREE_TTS_CAP_CHARS_PER_MONTH", "non-un-numero")
    assert ftq.cap_chars() == 25_000_000


# ---------------------------------------------------------------- endpoint

def test_registered_email_does_not_pass_the_cap(client, env):
    ftq.consume(CID, 1800, "preload")
    job = _mk_job("cap-blocked", 500, email=MAIL)
    r = _post(client, "cap-blocked", quota_ack=True)
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "free_tts_cap_reached"
    assert body["quota_used_chars"] == 1800 and body["quota_cap_chars"] == 2000
    assert body["chars_selected"] == 500
    assert "email_required" not in body, "nessuna via d'uscita da offrire"
    assert job["status"] == "analyzed", "stato ripristinato: il job resta riavviabile"
    assert env["run"] == []
    assert ftq.used_chars(CID) == 1800, "nulla consumato"
    assert "QUOTA_CAP" in _ops(env["log"])
    assert "_free_tts_quota_charge" not in job


def test_push_ack_does_not_pass_the_cap(client, env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_push_ack_possible", lambda job: True)
    ftq.consume(CID, 1800, "preload")
    _mk_job("cap-push", 500)
    assert _post(client, "cap-push", quota_ack=True).status_code == 402
    assert env["run"] == []


def test_below_cap_still_passes_through_the_email_gate(client, env):
    ftq.consume(CID, 1200, "preload")  # oltre quota (1000), sotto cap (2000)
    _mk_job("cap-gated", 500, email=MAIL)
    r = _post(client, "cap-gated", quota_ack=True)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [c[0] for c in env["run"]] == ["cap-gated"]
    assert ftq.used_chars(CID) == 1700
    assert ftq._used_key(ftq.mail_key(MAIL)) == 500, "il contatore email parte dal gate"
    assert "QUOTA_GATE" in _ops(env["log"])


def test_cookie_rotation_does_not_reset_the_cap(client, env):
    """Il caso reale: cookie cancellato, stessa email del gate -> stesso tetto."""
    ftq.consume(CID, 1800, "old", email=MAIL)
    _mk_job("cap-rotated", 500, client_id=CID2, email=MAIL)
    client.set_cookie("abm_cid", CID2)  # cookie rigenerato: nuovo proprietario
    r = _post(client, "cap-rotated", quota_ack=True)
    assert r.status_code == 402, r.get_data(as_text=True)
    assert r.get_json()["error_code"] == "free_tts_cap_reached"
    assert ftq.used_chars(CID2) == 0
    assert env["run"] == []


def test_premium_voice_is_not_capped(client, env, monkeypatch):
    """Il cap vale solo sulle voci standard: le premium sono pagate."""
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    ftq.consume(CID, 5000, "preload")
    job = _mk_job("cap-premium", 500)
    dec = ftq.cap_decision(CID, 500, "cap-premium:1")
    assert dec["allowed"] is False, "la stessa richiesta a voce standard sarebbe bloccata"
    assert job["status"] == "analyzed"


def test_cap_active_with_quota_off_consumes_and_blocks(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "0")
    _mk_job("cap-q0-a", 1500, email=MAIL)
    assert _post(client, "cap-q0-a").status_code == 200
    assert ftq.used_chars(CID) == 1500, "col cap acceso il contatore si riempie comunque"
    assert "QUOTA_GATE" not in _ops(env["log"]), "senza quota non c'e' gate"
    _mk_job("cap-q0-b", 600, email=MAIL)
    assert _post(client, "cap-q0-b").status_code == 402


def test_both_off_never_consumes(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "0")
    monkeypatch.setenv("ABM_FREE_TTS_CAP_CHARS_PER_MONTH", "0")
    _mk_job("cap-off", 50_000)
    assert _post(client, "cap-off").status_code == 200
    assert ftq.used_chars(CID) == 0


def test_server_error_refunds_both_keys(client, env):
    ftq.consume(CID, 1200, "preload")
    job = _mk_job("cap-err", 500, email=MAIL)
    assert _post(client, "cap-err", quota_ack=True).status_code == 200
    assert ftq._used_key(ftq.mail_key(MAIL)) == 500
    generation_engine._set_job_status(job, "error")
    assert ftq.used_chars(CID) == 1200
    assert ftq._used_key(ftq.mail_key(MAIL)) == 0
    assert "_free_tts_quota_ref" not in job


def test_legacy_two_element_ref_still_refunds(env):
    """Descrittori posati prima della v3.67 (senza email): storno comunque."""
    ftq.consume(CID, 400, "legacy", email=MAIL)
    job = {"status": "error", "_free_tts_quota_ref": (CID, "legacy")}
    generation_engine._set_job_status(job, "error")
    assert ftq.used_chars(CID) == 0
