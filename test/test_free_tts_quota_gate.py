"""Gate email della quota mensile voci STANDARD in /api/generate + riuso output.

Contratto: oltre quota /api/generate risponde 402 `free_tts_quota_exhausted`
(stato job ripristinato, nulla consumato, QUOTA_BLOCK nel log) finche' il
client non registra un'email e rimanda `quota_ack`; allora il job parte,
la quota viene addebitata come `gated` e il log riporta QUOTA_GATE. Senza
SMTP il gate e' impraticabile e il job passa. Una generazione identica di
un job gia' consegnato allo stesso client parte come run_reuse senza toccare
la quota. Errore server -> storno via _set_job_status.
"""
import pytest

import audiobook_app
import free_tts_quota as ftq
import generation_engine
import output_reuse
import payment
from epub_to_tts import BookInfo, Chapter

CID = "cid_tts_quota_gate_test"
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
    monkeypatch.delenv("ABM_OUTPUT_REUSE", raising=False)
    run_calls, reuse_calls, log_calls = [], [], []

    def _fake_run(job_id, info, voice, rate, single_file, **kw):
        run_calls.append((job_id, voice, kw))

    def _fake_reuse(job_id, info, voice, rate, single_file, **kw):
        reuse_calls.append((job_id, voice, kw))

    monkeypatch.setattr(audiobook_app, "run_generation", _fake_run)
    monkeypatch.setattr(generation_engine, "run_reuse", _fake_reuse)
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)
    monkeypatch.setattr(audiobook_app, "_log_activity",
                         lambda *a, **k: log_calls.append((a, k)))
    monkeypatch.setattr(payment, "_payments", {})
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    yield {"run": run_calls, "reuse": reuse_calls, "log": log_calls}
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("ftq-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(job_id, n_chars, client_id=CID, text=None):
    ch = Chapter(index=0, title="Cap0", text=text if text is not None else "A" * n_chars)
    info = BookInfo(title="T", author="A", language="en", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": "analyzed", "client_id": client_id}
    return audiobook_app.jobs[job_id]


def _post(client, job_id, **extra):
    payload = {"job_id": job_id, "voice": VOICE, "rate": "+0%", "output_format": "mp3", "lang": "en"}
    payload.update(extra)
    return client.post("/api/generate", json=payload)


def _ops(log_calls):
    return [a[2] for a, _k in log_calls]


def test_within_quota_starts_and_consumes(client, env):
    job = _mk_job("ftq-ok", 600)
    r = _post(client, "ftq-ok")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [c[0] for c in env["run"]] == ["ftq-ok"]
    assert ftq.used_chars(CID) == 600
    assert job["_free_tts_quota_ref"][0] == CID
    assert "QUOTA_GATE" not in _ops(env["log"]) and "QUOTA_BLOCK" not in _ops(env["log"])


def test_beyond_quota_without_email_returns_402_and_consumes_nothing(client, env):
    ftq.consume(CID, 900, "preload")
    job = _mk_job("ftq-block", 500)
    r = _post(client, "ftq-block")
    assert r.status_code == 402, r.get_data(as_text=True)
    body = r.get_json()
    assert body["error_code"] == "free_tts_quota_exhausted"
    assert body["email_required"] is True
    assert body["quota_used_chars"] == 900 and body["quota_limit_chars"] == 1000
    assert body["chars_selected"] == 500
    assert job["status"] == "analyzed", "stato ripristinato: il job resta riavviabile"
    assert env["run"] == []
    assert ftq.used_chars(CID) == 900
    assert "QUOTA_BLOCK" in _ops(env["log"])
    assert "_free_tts_quota_charge" not in job


def test_quota_ack_without_registered_email_is_ignored(client, env):
    ftq.consume(CID, 900, "preload")
    _mk_job("ftq-ack-noemail", 500)
    r = _post(client, "ftq-ack-noemail", quota_ack=True)
    assert r.status_code == 402
    assert env["run"] == []


def test_beyond_quota_with_registered_email_and_ack_starts_gated(client, env):
    ftq.consume(CID, 900, "preload")
    job = _mk_job("ftq-gate", 500)
    job["notify_email"] = "u@example.com"
    job["email_registered"] = True
    r = _post(client, "ftq-gate", quota_ack=True)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [c[0] for c in env["run"]] == ["ftq-gate"]
    assert ftq.used_chars(CID) == 1400, "oltre quota si addebita comunque (totale veritiero)"
    assert ftq.month_table()[CID]["gated"] == 1
    assert "QUOTA_GATE" in _ops(env["log"])


def test_gate_applies_to_every_book_beyond_quota(client, env):
    """Nessuno sblocco mensile: il secondo libro oltre quota richiede di nuovo l'ack."""
    ftq.consume(CID, 900, "preload")
    j1 = _mk_job("ftq-g1", 500)
    j1["notify_email"] = "u@example.com"
    j1["email_registered"] = True
    assert _post(client, "ftq-g1", quota_ack=True).status_code == 200
    _mk_job("ftq-g2", 500)  # nuovo job: email non registrata, niente ack
    assert _post(client, "ftq-g2").status_code == 402


def test_smtp_unavailable_lets_job_through_ungated(client, env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: False)
    ftq.consume(CID, 900, "preload")
    _mk_job("ftq-nosmtp", 500)
    r = _post(client, "ftq-nosmtp")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [c[0] for c in env["run"]] == ["ftq-nosmtp"]
    assert ftq.month_table()[CID]["gated"] == 0


def test_feature_off_never_gates_or_consumes(client, env, monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "0")
    _mk_job("ftq-off", 50_000)
    assert _post(client, "ftq-off").status_code == 200
    assert ftq.used_chars(CID) == 0


def test_regeneration_of_same_job_counts_again(client, env, monkeypatch):
    """La chiave di quota include l'epoch: rigenerare lo stesso job_id con altra
    voce/formato conta come nuovo libro (chiude la scappatoia stesso job)."""
    job = _mk_job("ftq-epoch", 400)
    assert _post(client, "ftq-epoch").status_code == 200
    assert ftq.used_chars(CID) == 400
    job["status"] = "done"
    generation_engine._set_job_status(job, "done")
    with audiobook_app._jobs_lock:
        job["status"] = "analyzed"
    assert _post(client, "ftq-epoch", output_format="zip", single_file=False).status_code == 200
    assert ftq.used_chars(CID) == 800


def test_server_error_refunds_quota(client, env):
    job = _mk_job("ftq-err", 300)
    assert _post(client, "ftq-err").status_code == 200
    assert ftq.used_chars(CID) == 300
    generation_engine._set_job_status(job, "error")
    assert ftq.used_chars(CID) == 0
    assert "_free_tts_quota_ref" not in job


def test_user_cancel_keeps_quota_charged(client, env):
    job = _mk_job("ftq-cancel", 300)
    assert _post(client, "ftq-cancel").status_code == 200
    generation_engine._set_job_status(job, "cancelled")
    assert ftq.used_chars(CID) == 300
    assert "_free_tts_quota_ref" not in job


def test_identical_regeneration_reuses_output_without_quota(client, env, tmp_path):
    text = "Testo identico del libro. " * 20
    src = _mk_job("ftq-src", 0, text=text)
    assert _post(client, "ftq-src").status_code == 200
    used_after_src = ftq.used_chars(CID)
    assert used_after_src == len(text)
    # Simula la consegna del job sorgente (run_generation e' finta: indicizziamo a mano).
    out = tmp_path / "ftq-src" / "output_0"
    out.mkdir(parents=True)
    f = out / "book.mp3"
    f.write_bytes(b"ID3xxx")
    src.update({"status": "done", "output_dir": str(out), "output_files": [str(f)],
                "failed_chunks": 0, "output_name": "book", "bytes_generated": 6,
                "total_chunks": 1, "total_chars": len(text)})
    assert src.get("reuse_key")
    output_reuse.record(src["reuse_key"], CID, "ftq-src", str(out))

    _mk_job("ftq-dup", 0, text=text)
    r = _post(client, "ftq-dup")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert [c[0] for c in env["reuse"]] == ["ftq-dup"]
    assert env["reuse"][0][2]["reuse_from"] == "ftq-src"
    assert [c[0] for c in env["run"]] == ["ftq-src"], "il duplicato non passa da run_generation"
    assert ftq.used_chars(CID) == used_after_src, "il riuso non consuma quota"
    assert "REUSE" not in _ops(env["log"]), "REUSE lo logga run_reuse, non l'endpoint"


def test_reuse_bypasses_quota_gate_even_when_exhausted(client, env, tmp_path):
    text = "Altro libro identico. " * 10
    src = _mk_job("ftq-src2", 0, text=text)
    assert _post(client, "ftq-src2").status_code == 200
    out = tmp_path / "ftq-src2" / "output_0"
    out.mkdir(parents=True)
    f = out / "book.mp3"
    f.write_bytes(b"ID3")
    src.update({"status": "done", "output_dir": str(out), "output_files": [str(f)],
                "failed_chunks": 0, "output_name": "book", "total_chunks": 1})
    output_reuse.record(src["reuse_key"], CID, "ftq-src2", str(out))
    ftq.consume(CID, 5000, "preload")  # quota esaurita
    _mk_job("ftq-dup2", 0, text=text)
    assert _post(client, "ftq-dup2").status_code == 200
    assert [c[0] for c in env["reuse"]] == ["ftq-dup2"]


def test_reuse_never_crosses_clients(client, env, tmp_path):
    text = "Libro di un altro utente. " * 10
    src = _mk_job("ftq-src3", 0, text=text, client_id="altro-cid")
    out = tmp_path / "ftq-src3" / "output_0"
    out.mkdir(parents=True)
    f = out / "book.mp3"
    f.write_bytes(b"ID3")
    key = output_reuse.compute_key(src["info"].chapters, VOICE, "+0%", "mp3", True)
    src.update({"status": "done", "output_dir": str(out), "output_files": [str(f)],
                "failed_chunks": 0, "reuse_key": key})
    output_reuse.record(key, "altro-cid", "ftq-src3", str(out))
    _mk_job("ftq-dup3", 0, text=text)
    assert _post(client, "ftq-dup3").status_code == 200
    assert env["reuse"] == []
    assert [c[0] for c in env["run"]] == ["ftq-dup3"]


def test_reuse_disabled_by_env(client, env, tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_OUTPUT_REUSE", "0")
    text = "Riuso spento. " * 10
    src = _mk_job("ftq-src4", 0, text=text)
    out = tmp_path / "ftq-src4" / "output_0"
    out.mkdir(parents=True)
    f = out / "book.mp3"
    f.write_bytes(b"ID3")
    key = output_reuse.compute_key(src["info"].chapters, VOICE, "+0%", "mp3", True)
    src.update({"status": "done", "output_dir": str(out), "output_files": [str(f)],
                "failed_chunks": 0, "reuse_key": key})
    output_reuse.record(key, CID, "ftq-src4", str(out))
    _mk_job("ftq-dup4", 0, text=text)
    assert _post(client, "ftq-dup4").status_code == 200
    assert env["reuse"] == []
    assert [c[0] for c in env["run"]] == ["ftq-dup4"]
