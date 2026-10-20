# test/test_account_plans.py
"""Piani v2: piano gratuito con consenso, piani regalati sub_5/sub_10, migrazione
dei vecchi archivi archive_10/20/50."""
import threading
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
    """Piano regalato con UPDATE diretto: ammette anche la scadenza assente (regali migrati), che gift_plan non permette."""
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


# ------------------------------------------------------------ consenso al piano gratuito

def _consent_rows():
    with db.tx() as c:
        return [tuple(r) for r in c.execute(
            "SELECT at, action, version, source FROM plan_consents ORDER BY id").fetchall()]


def test_free_plan_actions_record_consents(env):
    a = _login("a@b.it")
    assert accounts.free_offer_pending(accounts.get(a["id"]))
    accounts.free_plan_action(a["id"], "decline", "prompt", now=T0)
    acc = accounts.get(a["id"])
    assert not accounts.free_offer_pending(acc) and acc["free_consent_at"] is None
    acc = accounts.free_plan_action(a["id"], "activate", "account", now=T0 + 5)
    assert acc["free_consent_at"] == T0 + 5 and acc["free_offer_at"] == T0
    accounts.free_plan_action(a["id"], "activate", "account", now=T0 + 6)   # idempotente
    acc = accounts.free_plan_action(a["id"], "deactivate", "account", now=T0 + 9)
    assert acc["free_consent_at"] is None
    assert _consent_rows() == [(T0, "decline", "", "prompt"),
                               (T0 + 5, "grant", accounts.FREE_TERMS_VERSION, "account"),
                               (T0 + 9, "withdraw", "", "account")]
    with pytest.raises(ValueError):
        accounts.free_plan_action(a["id"], "maybe", "account")
    with pytest.raises(ValueError):
        accounts.free_plan_action(a["id"], "activate", "migration")
    assert accounts.free_plan_action("missing", "activate", "account") is None


def test_no_offer_while_gift_active(env):
    g = _login("g@b.it")
    _gift(g, "sub_10", T0 + 86400)
    assert not accounts.free_offer_pending(accounts.get(g["id"]), now=T0)
    assert accounts.free_offer_pending(accounts.get(g["id"]), now=T0 + 86400)
    with db.tx() as c:
        assert c.execute("SELECT COUNT(*) FROM plan_consents").fetchone()[0] == 0


def test_free_plan_noop_actions_write_nothing(env):
    a = _login("a@b.it")
    # ritirare senza consenso e' un no-op
    acc = accounts.free_plan_action(a["id"], "deactivate", "account", now=T0)
    assert acc["free_consent_at"] is None and acc["free_offer_at"] is None
    assert _consent_rows() == []
    accounts.free_plan_action(a["id"], "activate", "prompt", now=T0 + 1)
    # rifiutare con il consenso gia' dato non lo toglie ne' registra nulla
    acc = accounts.free_plan_action(a["id"], "decline", "prompt", now=T0 + 2)
    assert acc["free_consent_at"] == T0 + 1
    assert _consent_rows() == [(T0 + 1, "grant", accounts.FREE_TERMS_VERSION, "prompt")]


def test_free_offer_not_shown_again_after_any_choice(env):
    a, b = _login("a@b.it"), _login("b@b.it")
    accounts.free_plan_action(a["id"], "activate", "prompt", now=T0)
    accounts.free_plan_action(a["id"], "deactivate", "account", now=T0 + 1)
    accounts.free_plan_action(b["id"], "decline", "prompt", now=T0)
    assert not accounts.free_offer_pending(accounts.get(a["id"]), now=T0 + 2)
    assert not accounts.free_offer_pending(accounts.get(b["id"]), now=T0 + 2)
    assert not accounts.free_offer_pending(None)


def test_free_plan_ignores_deleted_accounts(env):
    a = _login("a@b.it")
    accounts.delete_account(a["id"], now=T0)
    assert accounts.free_plan_action(a["id"], "activate", "account", now=T0 + 1) is None
    assert not accounts.free_offer_pending(accounts.get(a["id"]), now=T0 + 1)
    assert _consent_rows() == []


def test_free_plan_activate_is_atomic_under_concurrency(env):
    a = _login("a@b.it")
    n = 8
    gate = threading.Barrier(n)
    errors = []

    def click():
        try:
            gate.wait(timeout=5)
            accounts.free_plan_action(a["id"], "activate", "prompt", now=T0)
        except Exception as e:  # noqa: BLE001  l'errore deve far fallire il test
            errors.append(e)

    threads = [threading.Thread(target=click) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    assert not errors
    assert _consent_rows() == [(T0, "grant", accounts.FREE_TERMS_VERSION, "prompt")]


# ------------------------------------------------------------ piani regalati

def _set(acct, **cols):
    sets = ", ".join(f"{k}=?" for k in cols)
    with db.tx() as c:
        c.execute(f"UPDATE accounts SET {sets} WHERE id=?", (*cols.values(), acct["id"]))


def test_gift_and_revoke(env):
    a = _login("a@b.it")
    with pytest.raises(ValueError):
        accounts.gift_plan(a["id"], "sub_99", T0 + 10, now=T0)
    with pytest.raises(ValueError):
        accounts.gift_plan(a["id"], "sub_5", T0 - 1, now=T0)
    st, acc = accounts.gift_plan(a["id"], "sub_5", T0 + 86400, now=T0)
    assert st == "ok" and (acc["plan"], acc["plan_source"], acc["plan_until"]) == ("sub_5", "gift", T0 + 86400)
    assert acc["free_consent_at"] is None
    assert accounts.gift_plan("nope", "sub_5", T0 + 10, now=T0)[0] == "not_found"
    with db.tx() as c:
        c.execute("UPDATE accounts SET plan_source='paid' WHERE id=?", (a["id"],))
    assert accounts.gift_plan(a["id"], "sub_10", T0 + 10, now=T0)[0] == "paid"
    assert accounts.revoke_gift(a["id"], now=T0)[0] == "not_gift"
    with db.tx() as c:
        c.execute("UPDATE accounts SET plan_source='gift' WHERE id=?", (a["id"],))
    st, acc = accounts.revoke_gift(a["id"], now=T0)
    assert st == "ok" and (acc["plan"], acc["plan_source"], acc["plan_until"]) == ("free", "", None)


def test_gift_requires_a_future_integer_epoch(env):
    a = _login("a@b.it")
    for bad in (T0, T0 - 1, None, "4073587200", float(T0 + 10), True):
        with pytest.raises(ValueError):
            accounts.gift_plan(a["id"], "sub_5", bad, now=T0)
    assert accounts.get(a["id"])["plan"] == "free"
    assert accounts.gift_plan(a["id"], "sub_5", T0 + 1, now=T0)[0] == "ok"


def test_gift_overwrites_gift_and_expired_paid_but_not_active_paid(env):
    a = _login("a@b.it")
    assert accounts.gift_plan(a["id"], "sub_5", T0 + 100, now=T0)[0] == "ok"
    st, acc = accounts.gift_plan(a["id"], "sub_10", T0 + 500, now=T0)       # regalo su regalo
    assert st == "ok" and (acc["plan"], acc["plan_until"]) == ("sub_10", T0 + 500)
    _set(a, plan_source="paid", plan_until=T0 + 100)
    assert accounts.gift_plan(a["id"], "sub_5", T0 + 500, now=T0 + 100)[0] == "ok"   # pagato scaduto
    _set(a, plan_source="paid", plan_until=None)                            # pagato senza scadenza
    st, acc = accounts.gift_plan(a["id"], "sub_5", T0 + 500, now=T0)
    assert st == "paid" and (acc["plan"], acc["plan_source"], acc["plan_until"]) == ("sub_5", "paid", None)


def test_gift_ignores_deleted_accounts_and_never_writes_consents(env):
    gone, live = _login("d@b.it"), _login("l@b.it")
    accounts.delete_account(gone["id"])
    assert accounts.gift_plan(gone["id"], "sub_5", T0 + 10, now=T0) == ("not_found", None)
    assert accounts.revoke_gift(gone["id"]) == ("not_found", None)
    assert accounts.revoke_gift("nope") == ("not_found", None)
    accounts.gift_plan(live["id"], "sub_10", T0 + 10, now=T0)
    accounts.revoke_gift(live["id"])
    accounts.gift_plan(live["id"], "sub_10", T0 + 10, now=T0)
    accounts.expire_gifts(now=T0 + 10)
    assert accounts.get(live["id"])["free_consent_at"] is None
    assert accounts.get(live["id"])["free_offer_at"] is None
    assert _consent_rows() == []


def test_gift_and_revoke_clear_archive_cache(env):
    a = _login("a@b.it")
    accounts._archive_cache["at"] = 123.0
    accounts.gift_plan(a["id"], "sub_5", T0 + 10, now=T0)
    assert accounts._archive_cache["at"] == 0.0
    accounts._archive_cache["at"] = 123.0
    accounts.gift_plan("nope", "sub_5", T0 + 10, now=T0)                    # nessun cambiamento
    assert accounts._archive_cache["at"] == 123.0
    accounts.revoke_gift(a["id"])
    assert accounts._archive_cache["at"] == 0.0


def test_expire_gifts(env):
    a = _login("a@b.it")
    accounts.gift_plan(a["id"], "sub_10", T0 + 100, now=T0)
    assert accounts.expire_gifts(now=T0 + 99) == 0
    assert accounts.expire_gifts(now=T0 + 100) == 1
    assert accounts.get(a["id"])["plan"] == "free"


def test_expire_gifts_scope_and_cache(env):
    due, later, forever, paid, plain = (_login(f"{n}@b.it") for n in "dlfpx")
    accounts.gift_plan(due["id"], "sub_10", T0 + 100, now=T0)
    accounts.gift_plan(later["id"], "sub_5", T0 + 200, now=T0)
    _gift(forever, "sub_10", None)
    _set(paid, plan="sub_5", plan_source="paid", plan_until=T0 + 50)
    accounts._archive_cache["at"] = 123.0
    assert accounts.expire_gifts(now=T0 + 150) == 1
    assert accounts._archive_cache["at"] == 0.0
    accounts._archive_cache["at"] = 123.0
    assert accounts.expire_gifts(now=T0 + 150) == 0                         # niente da fare: cache intatta
    assert accounts._archive_cache["at"] == 123.0
    assert accounts.expire_gifts(now=T0 + 10 ** 9) == 1                     # il senza-scadenza resta
    got = {k: accounts.get(v["id"]) for k, v in (
        ("due", due), ("later", later), ("forever", forever), ("paid", paid), ("plain", plain))}
    assert {k: (a["plan"], a["plan_source"], a["plan_until"]) for k, a in got.items()} == {
        "due": ("free", "", None), "later": ("free", "", None),
        "forever": ("sub_10", "gift", None), "paid": ("sub_5", "paid", T0 + 50),
        "plain": ("free", "", None)}


def test_admin_list_filters_by_plan_and_origin(env):
    g, f, n = _login("g@x.it"), _login("f@x.it"), _login("n@x.it")
    accounts.gift_plan(g["id"], "sub_10", T0 + 86400, now=T0)
    accounts.free_plan_action(f["id"], "activate", "account", now=T0)
    ids = lambda **kw: {r["id"] for r in accounts.admin_list(now=T0 + 1, **kw)["records"]}
    assert ids(origin="gift") == {g["id"]} and ids(origin="free") == {f["id"]}
    assert ids(origin="none") == {n["id"]} and ids(plan="sub_10") == {g["id"]}
    assert ids(plan="free") == {f["id"], n["id"]}
    agg = accounts.admin_list(now=T0 + 1)["aggregates"]
    assert (agg["gift"], agg["free_active"], agg["paid"], agg["in_tolerance"]) == (1, 1, 0, 0)
    rec = {r["id"]: r for r in accounts.admin_list(now=T0 + 1)["records"]}
    assert rec[g["id"]]["origin"] == "gift" and rec[g["id"]]["archive_quota_bytes"] == 10 * GIB


def test_admin_list_origin_paid_expired_gift_and_combined_filters(env):
    p, g, e, c = (_login(f"{n}@x.it") for n in "pgec")
    _set(p, plan="sub_5", plan_source="paid", plan_until=T0 + 1000)
    accounts.gift_plan(g["id"], "sub_5", T0 + 1000, now=T0)
    accounts.gift_plan(e["id"], "sub_10", T0 + 5, now=T0)       # scaduto ma non ancora ritirato
    _consent(c)
    out = accounts.admin_list(now=T0 + 10)
    rec = {r["id"]: r for r in out["records"]}
    assert out["origins"] == ["paid", "gift", "free", "none"]
    assert [rec[x["id"]]["origin"] for x in (p, g, e, c)] == ["paid", "gift", "none", "free"]
    assert [rec[x["id"]]["plan_effective"] for x in (p, g, e, c)] == ["sub_5", "sub_5", "free", "free"]
    assert rec[e["id"]]["plan"] == "sub_10"                     # il dato grezzo resta quello del DB
    ids = lambda **kw: {r["id"] for r in accounts.admin_list(now=T0 + 10, **kw)["records"]}
    assert ids(origin="paid") == {p["id"]} and ids(origin="gift") == {g["id"]}
    assert ids(origin="none") == {e["id"]} and ids(origin="free") == {c["id"]}
    assert ids(plan="sub_5") == {p["id"], g["id"]} and ids(plan="sub_10") == set()
    assert ids(plan="free") == {e["id"], c["id"]}
    assert ids(plan="sub_5", origin="gift") == {g["id"]} and ids(plan="sub_10", origin="gift") == set()
    assert ids(plan="free", origin="free") == {c["id"]}
    assert ids(plan="bogus") == ids(origin="bogus") == {p["id"], g["id"], e["id"], c["id"]}
    assert ids(origin="gift", q="g@x") == {g["id"]} and ids(origin="gift", q="p@x") == set()
    agg = accounts.admin_list(now=T0 + 10)["aggregates"]
    assert (agg["paid"], agg["gift"], agg["free_active"]) == (1, 1, 1)
    assert accounts.admin_list(now=T0 + 10, origin="gift")["count"] == 1


def test_space_plan_sql_follows_space_plan_active(env):
    """Il filtro SQL e il predicato Python concordano sul confine di scadenza,
    sul senza-scadenza, sul piano gratuito e sulle origini."""
    rows = {"future": ("sub_5", "gift", T0 + 100), "edge": ("sub_5", "gift", T0),
            "past": ("sub_5", "gift", T0 - 1), "forever": ("sub_10", "gift", None),
            "paid": ("sub_10", "paid", T0 + 100), "free": ("free", "", None)}
    accts = {}
    for k, (plan, source, until) in rows.items():
        accts[k] = _login(f"{k}@x.it")
        _set(accts[k], plan=plan, plan_source=source, plan_until=until)
    for source in (None, "gift", "paid"):
        sql, args = accounts._space_plan_sql(T0, source)
        with db.tx() as c:
            got = {r[0] for r in c.execute(
                "SELECT a.id FROM accounts a WHERE " + sql, tuple(args))}
        want = {a["id"] for a in accts.values()
                if accounts.space_plan_active(accounts.get(a["id"]), T0)
                and (source is None or accounts.get(a["id"])["plan_source"] == source)}
        assert got == want, source
    sql, args = accounts._space_plan_sql(T0, ("gift", "paid"), alias="x")
    assert sql.startswith("x.plan_source IN (?,?) AND x.plan IN (?,?)") and args[:2] == ["gift", "paid"]
    expected = {"future": "gift", "edge": "none", "past": "none", "forever": "gift",
                "paid": "paid", "free": "none"}
    for k, a in accts.items():
        assert accounts.plan_origin(accounts.get(a["id"]), T0) == expected[k], k


def test_admin_list_record_fields_and_tolerance(env):
    a, b = _login("a@x.it"), _login("b@x.it")
    accounts.gift_plan(a["id"], "sub_5", T0 + 500, now=T0)
    _consent(b)
    _set(b, archive_over_since=T0 + 100)
    out = accounts.admin_list(now=T0 + 200)
    rec = {r["id"]: r for r in out["records"]}
    ra, rb = rec[a["id"]], rec[b["id"]]
    assert (ra["plan_source"], ra["plan_effective"], ra["origin"]) == ("gift", "sub_5", "gift")
    assert ra["free_consent_at"] is None and ra["archive_over_since"] is None
    assert ra["archive_grace_until"] is None
    assert (rb["origin"], rb["plan_effective"], rb["free_consent_at"]) == ("free", "free", T0)
    assert rb["archive_over_since"] == T0 + 100
    assert rb["archive_grace_until"] == T0 + 100 + accounts.archive_tolerance_days() * 86400
    assert out["aggregates"]["in_tolerance"] == 1
    assert "subscribed" not in out["aggregates"]


def test_admin_list_aggregates_skip_deleted_accounts(env):
    g, f = _login("g@x.it"), _login("f@x.it")
    accounts.gift_plan(g["id"], "sub_5", T0 + 500, now=T0)
    accounts.free_plan_action(f["id"], "activate", "account", now=T0)
    _set(g, archive_over_since=T0)
    _set(f, archive_over_since=T0)
    agg = accounts.admin_list(now=T0 + 1)["aggregates"]
    assert (agg["gift"], agg["free_active"], agg["in_tolerance"]) == (1, 1, 2)
    accounts.delete_account(g["id"])
    accounts.delete_account(f["id"])
    # dati sporchi su account gia' cancellati: gli aggregati contano solo i vivi
    _set(g, plan="sub_5", plan_source="gift", archive_over_since=T0)
    _set(f, free_consent_at=T0, archive_over_since=T0)
    agg = accounts.admin_list(now=T0 + 1)["aggregates"]
    assert (agg["gift"], agg["free_active"], agg["in_tolerance"], agg["deleted"]) == (0, 0, 0, 2)
