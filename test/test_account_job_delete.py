# test/test_account_job_delete.py
"""Eliminazione di un job dall'area personale (web e app): la riga di storico
viene nascosta, non cancellata; file e token di download non si toccano."""
import json

import pytest

import account_page
import accounts
import audiobook_app
import db


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "jobs", {})
    tok, _ = accounts.request_code("a@b.it", "login")
    acct = accounts.verify(token=tok)[1]
    tok2, _ = accounts.request_code("c@d.it", "login")
    other = accounts.verify(token=tok2)[1]
    yield acct, other
    db.close()


def _ids(acct):
    rows, total = accounts.list_jobs(acct["id"])
    return [r["job_id"] for r in rows], total


def test_hide_job_outcomes(env):
    acct, other = env
    accounts.record_job(acct["id"], "d", kind="generate", status="done", paid_eur=3.0)
    accounts.record_job(acct["id"], "r", kind="generate", status="running")
    accounts.record_job(other["id"], "o", kind="generate", status="done")
    assert accounts.hide_job(acct["id"], "r") == "running"
    assert accounts.hide_job(acct["id"], "o") == "not_found"
    assert accounts.hide_job(acct["id"], "nope") == "not_found"
    assert accounts.hide_job(acct["id"], "d") == "ok"
    assert accounts.hide_job(acct["id"], "d") == "not_found"
    assert _ids(acct) == (["r"], 1)
    # La riga resta per l'audit admin (conteggi e incassi).
    row = db.conn().execute("SELECT paid_eur, hidden_at FROM account_jobs WHERE job_id='d'").fetchone()
    assert row["paid_eur"] == 3.0 and row["hidden_at"]


def test_relaunch_makes_job_visible_again(env):
    acct, _ = env
    accounts.record_job(acct["id"], "j", kind="generate", status="done")
    accounts.hide_job(acct["id"], "j")
    accounts.record_job(acct["id"], "j", kind="generate", status="done")
    assert _ids(acct) == ([], 0)
    accounts.record_job(acct["id"], "j", kind="generate", status="running")
    assert _ids(acct) == (["j"], 1)


def test_adopt_history_does_not_resurrect(env):
    acct, _ = env
    accounts.record_job(acct["id"], "p", kind="generate", status="done")
    accounts.hide_job(acct["id"], "p")
    with db.tx() as c:
        c.execute("INSERT OR IGNORE INTO account_jobs(job_id, account_id, created_at, kind, "
                  "updated_at) VALUES ('p', ?, 1, 'generate', 1)", (acct["id"],))
    assert _ids(acct) == ([], 0)


def test_endpoint(env, monkeypatch):
    acct, _ = env
    client = audiobook_app.app.test_client()
    url = "/api/account/jobs/delete"
    assert client.post(url, json={"job_id": "d"}).status_code == 401
    monkeypatch.setattr(audiobook_app, "_current_account", lambda: acct)
    accounts.record_job(acct["id"], "d", kind="generate", status="done", paid_eur=1.0)
    accounts.record_job(acct["id"], "r", kind="generate", status="running")
    assert client.post(url, json={}).status_code == 400
    r = client.post(url, json={"job_id": "r"})
    assert r.status_code == 409 and r.get_json()["error_code"] == "job_running"
    assert client.post(url, json={"job_id": "x"}).status_code == 404
    r = client.post(url, json={"job_id": "d"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert [j["job_id"] for j in client.get("/api/account/jobs").get_json()["jobs"]] == ["r"]


def test_endpoint_does_not_touch_files_or_tokens(env, monkeypatch):
    acct, _ = env
    monkeypatch.setattr(audiobook_app, "_current_account", lambda: acct)
    called = []
    monkeypatch.setattr(audiobook_app, "_cleanup_job", lambda *a, **k: called.append(a))
    monkeypatch.setattr(audiobook_app, "_delete_cold_for_job", lambda *a, **k: called.append(a))
    tokens = {"tok": {"job_id": "d"}}
    monkeypatch.setattr(audiobook_app, "_download_tokens", tokens)
    accounts.record_job(acct["id"], "d", kind="generate", status="done")
    accounts.set_download_token("d", "tok")
    audiobook_app.app.test_client().post("/api/account/jobs/delete", json={"job_id": "d"})
    assert called == [] and tokens == {"tok": {"job_id": "d"}}


def _render(rows):
    t = audiobook_app._acct_txt("it")
    return account_page.render_history(
        t, lang="it", account={"email": "a@b.it"}, rows=rows, page=1, per_page=50,
        total=len(rows), voices_count=0)


def test_page_delete_buttons():
    html = _render([
        {"job_id": "live", "status": "done", "downloads": [
            {"kind": "m4b", "url": "https://x/dl/t/m4b", "expires_at": 2_000_000_000}]},
        {"job_id": "old", "status": "done", "downloads": []},
        {"job_id": "busy", "status": "running", "downloads": []},
    ])
    assert 'data-del="live" data-dl="1"' in html
    assert 'data-del="old" data-dl="0"' in html
    assert 'data-del="busy"' not in html
    assert 'id="acctJobDelDlg"' in html and "Eliminare questo lavoro" in html
    assert "/api/account/jobs/delete" in html


def test_texts_in_every_language():
    data = json.load(open("i18n/account_pages.json", encoding="utf-8"))
    for lang, t in data.items():
        for k in ("job_delete", "job_delete_title", "job_delete_p"):
            assert t.get(k), (lang, k)
