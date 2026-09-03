"""Enforcement anti-abuso: ramo cancel, 403 pre-claim, kill in corsa, progress,
cleanup e ripristino admin."""
import time

import pytest

import abuse_watch as aw
import audiobook_app
import free_tts_quota as ftq
import generation_engine
import payment
from epub_to_tts import BookInfo, Chapter

CID = "cid_abuse_enf_test"
OTHER = "cid_abuse_enf_other"
IP = "7.7.7.7"
VOICE = "en-US-AriaNeural"


class _SyncThread:
    def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
        self._t, self._a, self._k = target, args, kwargs or {}

    def start(self):
        self._t(*self._a, **self._k)


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "1000")
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
    yield {"run": run_calls, "log": log_calls, "dir": tmp_path}
    with audiobook_app._jobs_lock:
        for jid in [j for j in audiobook_app.jobs if j.startswith("abz-")]:
            audiobook_app.jobs.pop(jid, None)


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        yield c


def _mk_job(job_id, n_chars=100, client_id=CID, status="analyzed"):
    ch = Chapter(index=0, title="Cap0", text="A" * n_chars)
    info = BookInfo(title="T", author="A", language="en", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": status, "client_id": client_id,
                                      "client_ip": IP, "original_filename": "book.epub"}
    return audiobook_app.jobs[job_id]


def _ops(env):
    return [a[2] for a, _k in env["log"]]


def _abuse_verdict(cids, scope="cids", confidence=0.95):
    g = aw.group_key(IP, CID)
    for c in cids:
        aw.record_event(g, c, "generate", {"chars": 10})
    aw.set_verdict(g, {"verdict": "abuse", "confidence": confidence, "scope": scope,
                       "cids": cids, "reason": "test"})
    return g


# ---------------------------------------------------------------------------
# Ramo cancel (generation_engine._cancel_cleanup_workdir)
# ---------------------------------------------------------------------------

def _work_dir(tmp_path):
    wd = tmp_path / "job-wd"
    wd.mkdir()
    (wd / "chunk_0001.pcm").write_bytes(b"x" * 10)
    (wd / "prompt_1.txt").write_text("p", encoding="utf-8")
    (wd / "_silence.pcm").write_bytes(b"s")
    return wd


def test_cancel_cleanup_removes_workdir_on_user_cancel(env, tmp_path):
    wd = _work_dir(tmp_path)
    job = {}
    generation_engine._cancel_cleanup_workdir(job, "j1", wd, partial_audio_delivered=False)
    assert not wd.exists() and "abuse_kept_until" not in job


def test_cancel_cleanup_keeps_pcm_only_with_partial_audio(env, tmp_path):
    wd = _work_dir(tmp_path)
    generation_engine._cancel_cleanup_workdir({}, "j1", wd, partial_audio_delivered=True)
    assert wd.exists() and not list(wd.glob("chunk_*.pcm")) and not (wd / "_silence.pcm").exists()


def test_cancel_cleanup_keeps_everything_on_abuse_kill(env, tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_ABUSE_KEEP_HOURS", "2")
    wd = _work_dir(tmp_path)
    job = {"abuse_terminated": True}
    t0 = time.time()
    generation_engine._cancel_cleanup_workdir(job, "j1", wd, partial_audio_delivered=False)
    assert (wd / "chunk_0001.pcm").exists() and (wd / "prompt_1.txt").exists()
    assert 2 * 3600 - 5 <= job["abuse_kept_until"] - t0 <= 2 * 3600 + 5


def test_cancel_cleanup_missing_workdir_sets_no_marker(env, tmp_path):
    job = {"abuse_terminated": True}
    generation_engine._cancel_cleanup_workdir(job, "j1", tmp_path / "nope", partial_audio_delivered=False)
    assert "abuse_kept_until" not in job


def test_analyzed_status_does_not_refund_quota(env):
    """La kill chiude su `analyzed` + cancelled: la quota resta addebitata.
    Solo `error` storna (_set_job_status)."""
    ftq.consume(CID, 400, "abz-q:1")
    job = {"status": "generating", "_free_tts_quota_ref": (CID, "abz-q:1"),
           "cancelled": True, "abuse_terminated": True}
    generation_engine._set_job_status(job, "analyzed")
    assert ftq.month_table().get(CID, {}).get("chars") == 400
