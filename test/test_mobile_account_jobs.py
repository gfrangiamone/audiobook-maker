# test/test_mobile_account_jobs.py
"""/api/my_jobs?account=1 con sessione account: la tab Attivita' dell'app
segue anche i job dell'account partiti dal sito o da altri dispositivi,
marcati `account_job` (l'app non offre Annulla: il cancel e' del cid)."""
import time

import pytest

import accounts
import audiobook_app
import db
import email_service
import token_store

APP_CID = "mobile-cid-12345"
WEB_CID = "web-cid-777777"
HDR = {"X-ABM-Cid": APP_CID}


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(token_store, "download_tokens", {})
    codes = []
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: codes.append(kw["code"]) or True)
    audiobook_app._ip_rl_buckets.pop("auth_request", None)
    audiobook_app.app.config["TESTING"] = True
    env.codes = codes
    seeded = []

    def seed_job(jid, **fields):
        with audiobook_app._jobs_lock:
            audiobook_app.jobs[jid] = fields
        seeded.append(jid)

    env.seed_job = seed_job
    yield env
    with audiobook_app._jobs_lock:
        for jid in seeded:
            audiobook_app.jobs.pop(jid, None)
    db.close()


@pytest.fixture
def client(env):
    return audiobook_app.app.test_client()


def _account(client, email="a@b.it"):
    client.post("/api/auth/request", json={"email": email, "lang": "it"}, headers=HDR)
    r = client.post("/api/auth/verify", json={"email": email, "code": env.codes[-1]},
                    headers=HDR)
    assert r.status_code == 200
    return accounts.account_for_email(email)


def _bearer(acct):
    return {**HDR, "Authorization": "Bearer " + accounts.open_session(acct["id"])}


def _site_job(acct, jid, *, created_at=None, kind="generate", output_format="m4b"):
    accounts.record_job(acct["id"], jid, kind=kind, book_title="Dal sito",
                        output_format=output_format, created_at=created_at)


def _site_token(tok, jid, created_at=None):
    token_store.download_tokens[tok] = {
        "job_id": jid,
        "client_id": WEB_CID,
        "created_at": created_at or time.time() - 60,
        "book_title": "Dal sito",
        "output_format": "m4b",
        "output_m4b": "/x/out.m4b",
        "is_gemini": False,
    }


def _my_jobs(client, headers, query="?account=1"):
    r = client.get("/api/my_jobs" + query, headers=headers)
    assert r.status_code == 200
    return r.get_json()["jobs"]


def test_site_job_in_progress_listed_as_account_job(client, env):
    acct = _account(client)
    _site_job(acct, "aj-run")
    env.seed_job("aj-run", status="generating", client_id=WEB_CID,
                 original_filename="sito.epub", output_format="m4b",
                 progress_current=2, progress_total=8, progress_message="Capitolo 2",
                 start_time=time.time(), info=None, last_poll=time.time())
    jobs = _my_jobs(client, _bearer(acct))
    assert [j["job_id"] for j in jobs] == ["aj-run"]
    j = jobs[0]
    assert j["status"] == "generating"
    assert (j["progress_current"], j["progress_total"]) == (2, 8)
    assert j["account_job"] is True


def test_site_job_done_listed_with_its_download_token(client, env):
    acct = _account(client)
    _site_job(acct, "aj-done")
    _site_token("TOKSITE", "aj-done")
    jobs = _my_jobs(client, _bearer(acct))
    assert len(jobs) == 1
    j = jobs[0]
    assert (j["job_id"], j["status"], j["download_token"]) == ("aj-done", "done", "TOKSITE")
    assert j["formats"]["m4b"] is True
    assert j["account_job"] is True


def test_account_jobs_only_when_app_asks_for_them(client, env):
    # Le app gia' installate non mandano ?account=1: lista come prima.
    acct = _account(client)
    _site_job(acct, "aj-old-app")
    _site_token("TOKOLDAPP", "aj-old-app")
    assert _my_jobs(client, _bearer(acct), query="") == []


def test_account_jobs_need_a_session(client, env):
    acct = _account(client)
    _site_job(acct, "aj-nosess")
    _site_token("TOKNOSESS", "aj-nosess")
    # Client nuovo: quello del login ha ancora il cookie di sessione.
    assert _my_jobs(audiobook_app.app.test_client(), HDR) == []


def test_app_own_job_of_the_account_is_not_flagged(client, env):
    # Job lanciato dall'app con login: e' dell'account ma anche del cid,
    # una sola voce e resta annullabile.
    acct = _account(client)
    _site_job(acct, "aj-app")
    env.seed_job("aj-app", status="generating", client_id=APP_CID,
                 original_filename="app.epub", output_format="m4b",
                 start_time=time.time(), info=None, last_poll=time.time())
    jobs = _my_jobs(client, _bearer(acct))
    assert [j["job_id"] for j in jobs] == ["aj-app"]
    assert "account_job" not in jobs[0]


def test_hidden_old_and_foreign_account_jobs_excluded(client, env):
    acct = _account(client)
    other = _account(client, "z@b.it")
    _site_job(acct, "aj-hidden")
    accounts.update_status("aj-hidden", "done")
    accounts.hide_job(acct["id"], "aj-hidden")
    _site_token("TOKHIDDEN", "aj-hidden")
    _site_job(acct, "aj-old", created_at=time.time() - 8 * 86400)
    _site_token("TOKOLD", "aj-old")
    _site_job(other, "aj-other")
    _site_token("TOKOTHER", "aj-other")
    assert _my_jobs(client, _bearer(acct)) == []


def test_non_audiobook_account_jobs_excluded(client, env):
    # Un'ottimizzazione che produce solo il .abm non e' un audiolibro.
    acct = _account(client)
    _site_job(acct, "aj-abm", kind="optimize", output_format="abm")
    env.seed_job("aj-abm", status="optimizing", client_id=WEB_CID,
                 original_filename="sito.epub", start_time=time.time(),
                 info=None, last_poll=time.time())
    assert _my_jobs(client, _bearer(acct)) == []


def test_site_job_cancelled_back_to_analyzed_reads_cancelled(client, env):
    # Il cancel riporta il job ad "analyzed": per l'app e' annullato, non
    # sparito (sparire mentre era attivo vorrebbe dire "interrotto").
    acct = _account(client)
    _site_job(acct, "aj-cancel")
    env.seed_job("aj-cancel", status="analyzed", cancelled=True, client_id=WEB_CID,
                 original_filename="sito.epub", start_time=time.time(),
                 info=None, last_poll=time.time())
    jobs = _my_jobs(client, _bearer(acct))
    assert [(j["job_id"], j["status"]) for j in jobs] == [("aj-cancel", "cancelled")]
