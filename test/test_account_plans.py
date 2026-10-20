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


def _consent(acct, at=T0):
    """Consenso al piano gratuito con UPDATE diretto (la funzione di dominio arriva nel Task 3)."""
    with db.tx() as c:
        c.execute("UPDATE accounts SET free_consent_at=?, free_consent_version=? WHERE id=?",
                  (at, accounts.FREE_TERMS_VERSION, acct["id"]))


def _gift(acct, plan, until):
    """Piano regalato con UPDATE diretto (la funzione di dominio arriva nel Task 4)."""
    with db.tx() as c:
        c.execute("UPDATE accounts SET plan=?, plan_source='gift', plan_until=? WHERE id=?",
                  (plan, until, acct["id"]))


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


# ------------------------------------------------------------ quota, candidati, protezione

def test_quota_follows_consent_and_plan(env, monkeypatch):
    a = _login("a@b.it")
    assert accounts.archive_quota_for(accounts.get(a["id"]), T0) == 0
    _gift(a, "sub_10", T0 + 86400)
    assert accounts.archive_quota_for(accounts.get(a["id"]), T0) == 10 * GIB   # regalo senza consenso
    assert accounts.archive_quota_for(accounts.get(a["id"]), T0 + 86400) == 0  # scaduto, senza consenso
    _consent(a)
    assert accounts.archive_quota_for(accounts.get(a["id"]), T0) == 10 * GIB
    assert accounts.archive_quota_for(accounts.get(a["id"]), T0 + 86400) == 512 * accounts.MIB
    monkeypatch.setenv("ABM_PLAN_FREE_MB", "100")
    assert accounts.archive_quota_for(accounts.get(a["id"]), T0 + 86400) == 100 * accounts.MIB
    assert accounts.effective_plan(accounts.get(a["id"]), T0 + 86400) == "free"


def test_plan_quota_bytes_reads_env_each_call(env, monkeypatch):
    assert [accounts.plan_quota_bytes(p) for p in ("free", "sub_5", "sub_10")] == [
        512 * accounts.MIB, 5 * GIB, 10 * GIB]
    assert accounts.plan_quota_bytes("archive_10") == 0 and accounts.plan_quota_bytes("") == 0
    monkeypatch.setenv("ABM_PLAN_SUB5_GB", "7")
    monkeypatch.setenv("ABM_PLAN_SUB10_GB", "12")
    assert accounts.plan_quota_bytes("sub_5") == 7 * GIB
    assert accounts.plan_quota_bytes("sub_10") == 12 * GIB


def test_plan_predicates_and_expiry_boundary(env):
    a = _login("a@b.it")
    assert not accounts.space_plan_active(accounts.get(a["id"]), T0)
    assert accounts.effective_plan(accounts.get(a["id"]), T0) == "free"
    _gift(a, "sub_5", T0 + 100)
    acct = accounts.get(a["id"])
    assert accounts.space_plan_active(acct, T0 + 99) and accounts.gift_active(acct, T0 + 99)
    assert accounts.effective_plan(acct, T0 + 99) == "sub_5"
    # "futuro" = strettamente maggiore di adesso: a plan_until il regalo e' scaduto
    assert not accounts.space_plan_active(acct, T0 + 100) and not accounts.gift_active(acct, T0 + 100)
    assert accounts.effective_plan(acct, T0 + 100) == "free"
    with db.tx() as c:
        c.execute("UPDATE accounts SET plan_until=NULL WHERE id=?", (a["id"],))
    assert accounts.gift_active(accounts.get(a["id"]), T0 + 10 ** 9)   # senza scadenza
    with db.tx() as c:
        c.execute("UPDATE accounts SET plan_source='paid' WHERE id=?", (a["id"],))
    paid = accounts.get(a["id"])
    assert accounts.space_plan_active(paid, T0) and not accounts.gift_active(paid, T0)
    assert accounts.archive_quota_for(paid, T0) == 0                    # pagato senza consenso: fase 2
    assert accounts.archive_quota_for(None, T0) == 0


def test_quota_zero_for_deleted_account(env):
    a = _login("a@b.it"); _consent(a)
    _gift(a, "sub_10", None)
    acct = accounts.get(a["id"])
    assert accounts.archive_quota_for(acct, T0) == 10 * GIB
    with db.tx() as c:   # riga cancellata ma con i campi del piano ancora presenti
        c.execute("UPDATE accounts SET deleted_at=? WHERE id=?", (T0, a["id"]))
    assert accounts.archive_quota_for(accounts.get(a["id"]), T0) == 0


def test_candidates_need_consent_and_start_at_consent(env):
    a, b = _login("a@b.it"), _login("b@b.it")
    _done_job(a, "old", created=T0 - 10); _done_job(a, "new", created=T0 + 10)
    _done_job(b, "nb", created=T0 + 10)
    _consent(a, at=T0)
    assert [c["job_id"] for c in accounts.archive_candidates(T0 + 20)] == ["new"]
    assert accounts.archive_candidates(T0 + 20)[0]["quota_bytes"] == 512 * accounts.MIB


def test_active_gift_makes_whole_history_candidate_without_consent(env):
    g = _login("g@b.it")
    _done_job(g, "g_old", created=T0 - 10); _done_job(g, "g_new", created=T0 + 10)
    _gift(g, "sub_5", T0 + 86400)
    got = accounts.archive_candidates(T0 + 20)
    assert sorted(c["job_id"] for c in got) == ["g_new", "g_old"]
    assert {c["quota_bytes"] for c in got} == {5 * GIB}
    assert accounts.archive_candidates(T0 + 86400) == []                 # regalo scaduto
    accounts.mark_archived("g_old", 10, now=T0 + 30)
    st = accounts.archive_status(accounts.get(g["id"]), T0 + 30)
    assert (st["plan"], st["plan_source"], st["free_active"]) == ("sub_5", "gift", False)
    st = accounts.archive_status(accounts.get(g["id"]), T0 + 86400)       # expire_gifts non ancora passato
    assert (st["plan"], st["plan_source"], st["plan_until"], st["quota_bytes"]) == ("free", "", None, 0)


def test_candidates_blocked_during_tolerance_and_after_eviction(env):
    a = _login("a@b.it"); _consent(a)
    _done_job(a, "j1", created=T0 + 1)
    with db.tx() as c:
        c.execute("UPDATE accounts SET archive_over_since=? WHERE id=?", (T0, a["id"]))
    assert accounts.archive_candidates(T0 + 2) == []
    with db.tx() as c:
        c.execute("UPDATE accounts SET archive_over_since=NULL WHERE id=?", (a["id"],))
        c.execute("UPDATE account_jobs SET archive_evicted_at=? WHERE job_id='j1'", (T0,))
    assert accounts.archive_candidates(T0 + 2) == []


def test_candidates_skip_running_hidden_archived_and_deleted(env):
    a, d = _login("a@b.it"), _login("d@b.it")
    _consent(a); _consent(d)
    _done_job(a, "ok", created=T0 + 5); _done_job(a, "hid", created=T0 + 4)
    _done_job(a, "arc", created=T0 + 3); _done_job(d, "dj", created=T0 + 2)
    accounts.record_job(a["id"], "run", kind="generate", status="running", created_at=T0 + 6)
    accounts.hide_job(a["id"], "hid")
    accounts.mark_archived("arc", 10)
    assert [c["job_id"] for c in accounts.archive_candidates(T0 + 10)] == ["ok", "dj"]
    with db.tx() as c:   # riga cancellata ma con il consenso ancora presente
        c.execute("UPDATE accounts SET deleted_at=? WHERE id=?", (T0, d["id"]))
    assert [c["job_id"] for c in accounts.archive_candidates(T0 + 10)] == ["ok"]


def test_protection_ignores_plan_and_consent(env):
    a = _login("a@b.it"); _consent(a)
    _done_job(a, "j1", created=T0 + 1); accounts.mark_archived("j1", 10)
    with db.tx() as c:
        c.execute("UPDATE accounts SET free_consent_at=NULL WHERE id=?", (a["id"],))
    accounts._archive_cache_clear()
    assert accounts.archive_protects("j1")
    accounts.delete_account(a["id"])
    assert not accounts.archive_protects("j1")


def test_delete_account_clears_plan_and_consent_state(env):
    a = _login("a@b.it"); _consent(a); _gift(a, "sub_5", None)
    with db.tx() as c:
        c.execute("UPDATE accounts SET archive_over_since=?, archive_notice_stage=2 WHERE id=?",
                  (T0, a["id"]))
    accounts.delete_account(a["id"])
    row = accounts.get(a["id"])
    assert (row["plan"], row["plan_source"], row["plan_until"], row["free_consent_at"],
            row["archive_over_since"], row["archive_notice_stage"]) == ("free", "", None, None, None, 0)


def test_status_shape_and_tolerance(env):
    a = _login("a@b.it")
    assert accounts.archive_status(accounts.get(a["id"]), T0) is None
    _consent(a)
    st = accounts.archive_status(accounts.get(a["id"]), T0)
    assert st["plan"] == "free" and st["state"] == "active" and st["free_active"] is True
    assert st["quota_bytes"] == 512 * accounts.MIB and st["grace_until"] is None
    assert set(st) >= {"plan", "quota_bytes", "used_bytes", "jobs", "items", "state",
                       "grace_until", "plan_source", "plan_until", "free_active"}
    with db.tx() as c:
        c.execute("UPDATE accounts SET archive_over_since=? WHERE id=?", (T0, a["id"]))
    st = accounts.archive_status(accounts.get(a["id"]), T0)
    assert st["state"] == "grace" and st["grace_until"] == T0 + 15 * 86400


def test_tolerance_settings_and_states(env, monkeypatch):
    assert accounts.archive_tolerance_days() == 15
    assert accounts.archive_tolerance_remind_days() == 3
    monkeypatch.setenv("ABM_ARCHIVE_TOLERANCE_DAYS", "0")
    monkeypatch.setenv("ABM_ARCHIVE_TOLERANCE_REMIND_DAYS", "-2")
    assert accounts.archive_tolerance_days() == 1
    assert accounts.archive_tolerance_remind_days() == 0
    monkeypatch.setenv("ABM_ARCHIVE_TOLERANCE_DAYS", "20")
    a = _login("a@b.it")
    assert accounts.archive_state(accounts.get(a["id"]), T0) == "none"
    assert accounts.archive_grace_until(accounts.get(a["id"])) is None
    _consent(a)
    assert accounts.archive_state(accounts.get(a["id"]), T0) == "active"
    with db.tx() as c:
        c.execute("UPDATE accounts SET archive_over_since=? WHERE id=?", (T0, a["id"]))
    acct = accounts.get(a["id"])
    assert accounts.archive_state(acct, T0) == "grace"
    assert accounts.archive_grace_until(acct) == T0 + 20 * 86400
    assert accounts.archive_state(None, T0) == "none"


def test_purge_expired_keeps_archived_history(env):
    a = _login("a@b.it"); _consent(a, at=0)
    old = T0 - 30 * 31 * 86400
    _done_job(a, "keep", created=old); accounts.mark_archived("keep", 10)
    _done_job(a, "drop", created=old)
    accounts.purge_expired(now=T0)
    with db.tx() as c:
        ids = {r[0] for r in c.execute("SELECT job_id FROM account_jobs").fetchall()}
    assert ids == {"keep"}


def test_purge_expired_follows_job_in_archive_not_archived_at(env):
    a = _login("a@b.it"); _consent(a, at=0)
    old = T0 - 30 * 31 * 86400
    for jid in ("gone", "linked"):
        _done_job(a, jid, created=old); accounts.mark_archived(jid, 10)
    with db.tx() as c:   # entrambi nascosti: solo "linked" ha ancora un libro dell'app collegato
        c.execute("UPDATE account_jobs SET hidden_at=? WHERE job_id IN ('gone', 'linked')", (T0,))
        c.execute("INSERT INTO archive_items(id, account_id, fingerprint, job_id, created_at, updated_at) "
                  "VALUES ('i1', ?, ?, 'linked', ?, ?)", (a["id"], "f" * 64, T0, T0))
    accounts.purge_expired(now=T0)
    with db.tx() as c:
        ids = {r[0] for r in c.execute("SELECT job_id FROM account_jobs").fetchall()}
    assert ids == {"linked"}


def test_admin_list_quota_and_plans(env):
    a = _login("a@b.it"); _consent(a)
    g = _login("g@b.it"); _gift(g, "sub_5", None)
    out = accounts.admin_list(now=T0 + 60)
    quota = {r["id"]: r["archive_quota_bytes"] for r in out["records"]}
    assert quota == {a["id"]: 512 * accounts.MIB, g["id"]: 5 * GIB}
    assert out["plans"] == ["free", "sub_5", "sub_10"]


def test_format_bytes():
    assert accounts.format_bytes(380 * accounts.MIB) == "380 MB"
    assert accounts.format_bytes(int(1.25 * GIB)) == "1.25 GB"
    assert accounts.format_bytes(10 * GIB) == "10 GB"
    assert accounts.format_bytes(0) == "0 MB"
    assert accounts.format_bytes(GIB) == "1 GB"
    assert accounts.format_bytes(int(2.5 * GIB)) == "2.5 GB"
