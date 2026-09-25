# test/test_account_stale_jobs.py
"""Righe di storico rimaste "running" per un job che non gira piu': la lista
dell'area personale (web e app) le riconcilia, il cancel e la cleanup le
chiudono. Incidente uLTdBu1Pwz6NkxjMejBrPA (24/09/2026): cancel riportato ad
"analyzed", cleanup "stale analyzed", riga "running" per sempre."""
import time

import pytest

import accounts
import audiobook_app
import db
import generation_engine as ge
import pending_jobs


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    tok, _ = accounts.request_code("a@b.it", "login")
    acct = accounts.verify(token=tok)[1]
    fake_jobs = {}
    monkeypatch.setattr(audiobook_app, "jobs", fake_jobs)
    active = set()
    monkeypatch.setattr(pending_jobs, "is_active", lambda jid: jid in active)
    yield acct, fake_jobs, active
    db.close()


def _age(job_id, seconds):
    with db.tx() as c:
        c.execute("UPDATE account_jobs SET updated_at=? WHERE job_id=?",
                  (int(time.time()) - seconds, job_id))


def _status(job_id):
    return db.conn().execute(
        "SELECT status FROM account_jobs WHERE job_id=?", (job_id,)).fetchone()["status"]


def _rows(acct):
    return {r["job_id"]: r["status"] for r in audiobook_app._account_rows_for(acct, 1)[0]}


def test_settle_running_never_overwrites_an_outcome(env):
    acct, _, _ = env
    accounts.record_job(acct["id"], "j1", kind="generate", status="running")
    accounts.record_job(acct["id"], "j2", kind="generate", status="done")
    assert accounts.settle_running("j1", "error") is True
    assert accounts.settle_running("j2", "error") is False
    assert accounts.settle_running("j1", "running") is False
    assert (_status("j1"), _status("j2")) == ("error", "done")


def test_vanished_job_is_settled_as_error_after_grace(env):
    acct, _, _ = env
    accounts.record_job(acct["id"], "gone", kind="generate", status="running")
    accounts.record_job(acct["id"], "fresh", kind="generate", status="running")
    _age("gone", audiobook_app._ACCT_STALE_RUNNING_SEC + 60)
    assert _rows(acct) == {"gone": "error", "fresh": "running"}
    assert _status("gone") == "error"


def test_recoverable_job_is_left_running(env):
    acct, _, active = env
    accounts.record_job(acct["id"], "rec", kind="generate", status="running")
    _age("rec", audiobook_app._ACCT_STALE_RUNNING_SEC + 60)
    active.add("rec")
    assert _rows(acct) == {"rec": "running"}


def test_unreadable_pending_store_leaves_row_running(env, monkeypatch):
    acct, _, _ = env
    accounts.record_job(acct["id"], "x", kind="generate", status="running")
    _age("x", audiobook_app._ACCT_STALE_RUNNING_SEC + 60)

    def boom(jid):
        raise RuntimeError("store down")
    monkeypatch.setattr(pending_jobs, "is_active", boom)
    assert _rows(acct) == {"x": "running"}


@pytest.mark.parametrize("job,expected", [
    ({"status": "generating"}, "running"),
    ({"status": "done"}, "done"),
    ({"status": "partial"}, "done"),
    ({"status": "error"}, "error"),
    ({"status": "analyzed", "cancelled": True}, "cancelled"),
    ({"status": "analyzed", "cancelled": True, "server_interrupted": True}, "error"),
])
def test_in_memory_job_status_is_mirrored(env, job, expected):
    acct, fake_jobs, _ = env
    accounts.record_job(acct["id"], "m", kind="generate", status="running")
    fake_jobs["m"] = job
    assert _rows(acct) == {"m": expected}


def test_cleanup_of_non_terminal_job_settles_row(env, monkeypatch, tmp_path):
    acct, fake_jobs, _ = env
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path / "up")
    monkeypatch.setattr(audiobook_app, "_reconcile_unused_capture_for_job", lambda *a: None)
    monkeypatch.setattr(audiobook_app, "_delete_cold_for_job", lambda *a: None)
    monkeypatch.setattr(audiobook_app, "_has_active_download_tokens", lambda *a: False)
    monkeypatch.setattr(pending_jobs, "mark_failed", lambda jid: None)
    for jid, job in (("c1", {"status": "analyzed", "cancelled": True}),
                     ("c2", {"status": "generating"}),
                     ("c3", {"status": "done"})):
        accounts.record_job(acct["id"], jid, kind="generate",
                            status="done" if jid == "c3" else "running")
        fake_jobs[jid] = job
        audiobook_app._cleanup_job(jid, "test")
    assert (_status("c1"), _status("c2"), _status("c3")) == ("cancelled", "error", "done")


def test_engine_cancel_path_notifies_account():
    src = open("generation_engine.py", encoding="utf-8").read()
    i = src.index('_mark_pending_failed(job_id, "cancelled")\n            _set_job_status(job, "analyzed")')
    assert "_account_notify_status(" in src[i:i + 800]


def test_progress_reports_cancelled_for_cancelled_analyzed(env, monkeypatch):
    acct, fake_jobs, _ = env
    monkeypatch.setattr(audiobook_app, "_acct_gate", lambda: None)
    monkeypatch.setattr(audiobook_app, "_current_account", lambda: acct)
    accounts.record_job(acct["id"], "p", kind="generate", status="running")
    fake_jobs["p"] = {"status": "analyzed", "cancelled": True}
    with audiobook_app.app.test_request_context("/api/account/progress?ids=p"):
        d = audiobook_app.api_account_progress().get_json()
    assert d["jobs"]["p"]["status"] == "cancelled"
