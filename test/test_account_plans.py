# test/test_account_plans.py
"""Piani v2: piano gratuito con consenso, piani regalati sub_5/sub_10, migrazione
dei vecchi archivi archive_10/20/50."""
import time

import pytest

import accounts
import db


T0 = 1_800_000_000
GIB = accounts.GIB


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(accounts, "_payments_path", None)
    monkeypatch.setattr(accounts, "_voice_ids_for_email", None)
    monkeypatch.setattr(accounts, "_link_voice", None)
    monkeypatch.setattr(accounts, "_unlink_voice", None)
    accounts._archive_cache_clear()
    yield tmp_path
    accounts._archive_cache_clear()
    db.close()


def _login(email, now=T0):
    token, code = accounts.request_code(email, "login", "it", now=now)
    status, acct = accounts.verify(token=token, code=code, purpose="login", now=now)
    assert status == "ok"
    return acct


def _done_job(acct, job_id, created=T0):
    accounts.record_job(acct["id"], job_id, kind="generate", status="done", created_at=created)


# ------------------------------------------------------------ schema e migrazione

def test_plans_v2_migration(env, monkeypatch):
    monkeypatch.setenv("ABM_ARCHIVE_GRACE_DAYS", "30")
    now = int(time.time())
    gifted, grace, gone, plain, dead = (_login(e) for e in
        ("g@x.it", "r@x.it", "o@x.it", "p@x.it", "d@x.it"))
    accounts.delete_account(dead["id"])
    with db.tx() as c:
        c.execute("UPDATE accounts SET plan='archive_20' WHERE id=?", (gifted["id"],))
        c.execute("UPDATE accounts SET plan_until=? WHERE id=?", (now - 5 * 86400, grace["id"]))
        c.execute("UPDATE accounts SET plan_until=? WHERE id=?", (now - 40 * 86400, gone["id"]))
        c.execute("UPDATE accounts SET plan='archive_10' WHERE id=?", (dead["id"],))
        c.execute("DELETE FROM schema_migrations WHERE name='accounts_plans_v2_data'")
    accounts.init_schema()
    g = accounts.get(gifted["id"])
    assert (g["plan"], g["plan_source"], g["plan_until"]) == ("sub_10", "gift", None)
    assert g["free_consent_at"] and g["free_consent_version"] == accounts.FREE_TERMS_VERSION
    assert g["free_offer_at"]
    r = accounts.get(grace["id"])
    assert (r["plan"], r["plan_until"]) == ("free", None) and r["free_consent_at"]
    o = accounts.get(gone["id"])
    assert o["free_consent_at"] is None and o["plan_until"] is None
    assert o["archive_over_since"] <= now - 15 * 86400 and o["archive_notice_stage"] == 2
    p = accounts.get(plain["id"])
    assert p["free_consent_at"] is None and p["free_offer_at"] is None
    with db.tx() as c:
        assert tuple(c.execute("SELECT plan, plan_source FROM accounts WHERE id=?",
                               (dead["id"],)).fetchone()) == ("free", "")
        rows = c.execute("SELECT account_id, action, source FROM plan_consents").fetchall()
    assert sorted(tuple(x) for x in rows) == sorted(
        [(gifted["id"], "grant", "migration"), (grace["id"], "grant", "migration")])
    # seconda esecuzione: nessun effetto
    accounts.init_schema()
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM plan_consents").fetchone()[0] == 2
