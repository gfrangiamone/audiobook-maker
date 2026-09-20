# test/test_account_engine_hooks.py
"""Gli esiti dei job e i token di download arrivano allo storico account
tramite due callback iniettate con configure(); mai fatali."""
import pytest

import accounts
import audiobook_app  # noqa: F401  (configura generation_engine all'import)
import generation_engine as ge


@pytest.fixture
def hooks(monkeypatch):
    calls = {"status": [], "token": []}
    monkeypatch.setattr(ge, "_account_job_status", lambda jid, st: calls["status"].append((jid, st)))
    monkeypatch.setattr(ge, "_account_token", lambda jid, tok: calls["token"].append((jid, tok)))
    return calls


def test_configure_wires_accounts_functions():
    assert ge._account_job_status is accounts.update_status
    assert ge._account_token is accounts.set_download_token


@pytest.mark.parametrize("status,expected", [
    ("done", "done"), ("partial", "done"), ("error", "error"),
    ("cancelled", "cancelled"), ("canceled", "cancelled"),
])
def test_terminal_status_reaches_hook(hooks, status, expected):
    job = {"job_id": "jh-1"}
    ge._set_job_status(job, status)
    assert hooks["status"] == [("jh-1", expected)]


def test_non_terminal_status_does_not_call_hook(hooks):
    ge._set_job_status({"job_id": "jh-2"}, "generating")
    assert hooks["status"] == []


def test_hook_exception_is_swallowed(monkeypatch):
    def boom(jid, st):
        raise RuntimeError("db down")
    monkeypatch.setattr(ge, "_account_job_status", boom)
    job = {"job_id": "jh-3"}
    ge._set_job_status(job, "done")
    assert job["status"] == "done"


def test_hook_none_is_fine(monkeypatch):
    monkeypatch.setattr(ge, "_account_job_status", None)
    monkeypatch.setattr(ge, "_account_token", None)
    ge._set_job_status({"job_id": "jh-4"}, "done")
    ge._account_notify_token("jh-4", "tok")


def test_create_download_token_notifies(hooks, monkeypatch, tmp_path):
    jobs = {"jh-5": {"status": "done", "info": None, "original_filename": "x.epub",
                     "output_files": [str(tmp_path / "a.mp3")], "voice": "it-IT-IsabellaNeural"}}
    tokens = {}
    monkeypatch.setattr(ge, "_jobs", jobs)
    monkeypatch.setattr(ge, "_download_tokens", tokens)
    monkeypatch.setattr(ge, "_save_tokens", lambda: None)
    tok = ge._create_download_token("jh-5")
    assert tok and tokens[tok]["job_id"] == "jh-5"
    assert hooks["token"] == [("jh-5", tok)]
    assert ge._create_download_token("jh-5") == tok
    assert hooks["token"] == [("jh-5", tok)]  # il riuso idempotente non rinotifica


def test_token_sites_in_source_notify():
    src = open("generation_engine.py", encoding="utf-8").read()
    for marker in ('"download_type": "optimized_abm"', '"download_type": "translated"',
                   '"partial_cancel": True'):
        i = src.index(marker)
        window = src[i:i + 1500]
        assert "_account_notify_token(job_id, token)" in window, marker
