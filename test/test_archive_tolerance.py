# test/test_archive_tolerance.py
"""Tolleranza sull'eccedenza dell'archivio: avviso email, promemoria, poi
cancellazione dei libri piu' vecchi (job tolti dalla protezione, upload tolti
da R2 e dal DB)."""
import hashlib
import time

import pytest

import accounts
import archive_tolerance
import db
import email_service
import user_archive
from test.test_account_plans import GIB, T0, _consent, _done_job, _gift, _login
from test.test_user_archive import FakeR2

MIB = accounts.MIB
DAY = 86400
ZERO = {"gifts_expired": 0, "started": 0, "reminded": 0, "evicted": 0, "cleared": 0, "errors": 0}


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(accounts, "_payments_path", None)
    monkeypatch.setattr(accounts, "_voice_ids_for_email", None)
    monkeypatch.setattr(accounts, "_link_voice", None)
    monkeypatch.setattr(accounts, "_unlink_voice", None)
    monkeypatch.delenv("ABM_ARCHIVE_TOLERANCE_DAYS", raising=False)
    monkeypatch.delenv("ABM_ARCHIVE_TOLERANCE_REMIND_DAYS", raising=False)
    accounts._archive_cache_clear()
    archive_tolerance._sweep_state["at"] = 0.0
    user_archive._sweep_state["at"] = 0.0
    r2 = FakeR2()
    r2.install(monkeypatch)
    yield r2
    accounts._archive_cache_clear()
    db.close()


class _Mails:
    def __init__(self):
        self.over = []
        self.remind = []
        self.ok = True


@pytest.fixture
def mails(monkeypatch):
    box = _Mails()

    def over(email, lang, **kw):
        box.over.append({"email": email, "lang": lang, **kw})
        return box.ok

    def remind(email, lang, **kw):
        box.remind.append({"email": email, "lang": lang, **kw})
        return box.ok

    monkeypatch.setattr(email_service, "send_archive_over", over)
    monkeypatch.setattr(email_service, "send_archive_remind", remind)
    return box


def _archived(acct, job_id, nbytes, at, created=T0):
    _done_job(acct, job_id, created=created)
    assert accounts.mark_archived(job_id, nbytes, now=at)


def _upload(acct, item_id, nbytes, at, job_id="", state="ready", r2_key=None, orphan_key="",
            title="", filename=""):
    """Riga di archive_items con INSERT diretto; ritorna la chiave R2."""
    key = f"archive/{acct['id']}/{item_id}.m4b" if r2_key is None else r2_key
    fp = hashlib.sha256(item_id.encode()).hexdigest()
    with db.tx() as c:
        c.execute(
            "INSERT INTO archive_items (id, account_id, fingerprint, state, filename, title, "
            "size_bytes, r2_key, orphan_key, job_id, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (item_id, acct["id"], fp, state, filename, title, nbytes, key, orphan_key, job_id, at, at))
    return key


def _item_ids(acct):
    with db.tx() as c:
        return sorted(r[0] for r in c.execute(
            "SELECT id FROM archive_items WHERE account_id=?", (acct["id"],)))


def _day(ts):
    return time.strftime("%Y-%m-%d", time.gmtime(ts))


def _small_quota(monkeypatch, nbytes=100):
    monkeypatch.setattr(accounts, "plan_quota_bytes", lambda p: nbytes)


# ------------------------------------------------------------ accounts: elenchi

def test_entries_order_and_filters(env):
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_b", 10, at=T0 + 5)
    _archived(a, "j_a", 20, at=T0 + 5)                     # stesso istante: ordina per id
    _upload(a, "i_first", 30, at=T0 + 1, title="Primo", filename="primo.m4b")
    _upload(a, "i_zero", 0, at=T0)                         # 0 byte: mai in elenco
    _upload(a, "i_pending", 40, at=T0, state="pending")    # upload non chiuso: non e' scegliibile
    _archived(a, "j_zero", 0, at=T0)                       # 0 byte: mai in elenco
    _archived(a, "j_linked", 50, at=T0 + 2)
    _upload(a, "i_link", 50, at=T0 + 3, job_id="j_linked")  # collegamento: conta con il job
    _done_job(a, "j_plain")                                # mai archiviato
    _archived(a, "j_hidden", 60, at=T0 + 4)
    with db.tx() as c:                                     # nascosto e senza collegamenti: fuori dall'archivio
        c.execute("UPDATE account_jobs SET hidden_at=? WHERE job_id='j_hidden'", (T0 + 6,))
    got = accounts.archive_entries(a["id"])
    keys = [(e["kind"], e["id"]) for e in got]
    assert ("item", "i_zero") not in keys and ("item", "i_pending") not in keys
    assert ("job", "j_zero") not in keys and ("item", "i_link") not in keys
    assert ("job", "j_plain") not in keys and ("job", "j_hidden") not in keys
    ordered = [e for e in got if e["id"] in ("i_first", "j_linked", "j_a", "j_b")]
    assert [e["id"] for e in ordered] == ["i_first", "j_linked", "j_a", "j_b"]
    first = got[0]
    assert first == {"kind": "item", "id": "i_first", "title": "Primo", "bytes": 30,
                     "entered_at": T0 + 1}
    assert {e["id"]: e["entered_at"] for e in got if e["kind"] == "job"}["j_a"] == T0 + 5


def test_entries_exclude_evicted_and_deleted_accounts(env):
    a = _login("a@b.it"); _consent(a)
    b = _login("c@d.it"); _consent(b)
    _archived(a, "j1", 10, at=T0)
    _archived(b, "j2", 10, at=T0)
    assert accounts.evict_archived_job("j1", now=T0 + 1) is True
    assert accounts.archive_entries(a["id"]) == []
    with db.tx() as c:
        c.execute("UPDATE accounts SET deleted_at=? WHERE id=?", (T0, b["id"]))
    assert accounts.archive_entries(b["id"]) == []
    assert accounts.archive_accounts_to_check() == []


def test_entries_fall_back_to_id_and_filename(env):
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_notitle", 10, at=T0)
    _upload(a, "i_notitle", 10, at=T0 + 1, filename="libro.m4b")
    _upload(a, "i_bare", 10, at=T0 + 2)
    with db.tx() as c:
        c.execute("UPDATE account_jobs SET book_title='Il Titolo' WHERE job_id='j_notitle'")
    assert accounts.archive_entries(a["id"])[0]["title"] == "Il Titolo"
    with db.tx() as c:
        c.execute("UPDATE account_jobs SET book_title='' WHERE job_id='j_notitle'")
    titles = {e["id"]: e["title"] for e in accounts.archive_entries(a["id"])}
    assert titles == {"j_notitle": "j_notitle", "i_notitle": "libro.m4b", "i_bare": "i_bare"}


def test_accounts_to_check(env):
    a = _login("a@b.it"); _consent(a)
    with_job = _login("j@b.it")
    with_item = _login("i@b.it")
    in_tol = _login("t@b.it")
    empty = _login("e@b.it")
    only_linked = _login("l@b.it")
    _archived(with_job, "j1", 10, at=T0)
    _upload(with_item, "i1", 10, at=T0)
    accounts.set_archive_tolerance(in_tol["id"], T0, 1)
    _archived(only_linked, "j2", 10, at=T0)
    with db.tx() as c:
        c.execute("UPDATE account_jobs SET archived_at=NULL WHERE job_id='j2'")
    ids = {x["id"] for x in accounts.archive_accounts_to_check()}
    assert ids == {with_job["id"], with_item["id"], in_tol["id"]}
    assert empty["id"] not in ids and a["id"] not in ids


def test_set_archive_tolerance_and_evict_job(env):
    a = _login("a@b.it")
    _archived(a, "j1", 10, at=T0)
    accounts.set_archive_tolerance(a["id"], T0 + 7, 1)
    acc = accounts.get(a["id"])
    assert (acc["archive_over_since"], acc["archive_notice_stage"]) == (T0 + 7, 1)
    accounts.set_archive_tolerance(a["id"], None, 0)
    acc = accounts.get(a["id"])
    assert (acc["archive_over_since"], acc["archive_notice_stage"]) == (None, 0)
    assert accounts.archive_protects("j1")
    assert accounts.evict_archived_job("j1", now=T0 + 9) is True
    assert not accounts.archive_protects("j1")
    with db.tx() as c:
        row = c.execute("SELECT archived_at, archived_bytes, archive_evicted_at "
                        "FROM account_jobs WHERE job_id='j1'").fetchone()
    assert tuple(row) == (None, 0, T0 + 9)
    assert accounts.evict_archived_job("j1", now=T0 + 10) is False      # gia' tolto: nulla da fare
    assert accounts.evict_archived_job("nope", now=T0 + 10) is False
    with db.tx() as c:
        c.execute("UPDATE accounts SET deleted_at=? WHERE id=?", (T0, a["id"]))
    accounts.set_archive_tolerance(a["id"], T0 + 7, 1)                  # account cancellato: non si tocca
    acc = accounts.get(a["id"])
    assert (acc["archive_over_since"], acc["archive_notice_stage"]) == (None, 0)


def test_purge_job_links(env):
    a = _login("a@b.it")
    _archived(a, "j1", 10, at=T0)
    _archived(a, "j2", 10, at=T0)
    assert user_archive.purge_job_links(a["id"], "j1") is True            # nessun collegamento
    _upload(a, "l1", 1, at=T0, job_id="j1", r2_key="")
    _upload(a, "l1b", 1, at=T0, job_id="j1", r2_key="", orphan_key="archive/orph/l1b")
    _upload(a, "l2", 1, at=T0, job_id="j2", orphan_key="archive/orph/l2")
    env.fail_delete = True
    assert user_archive.purge_job_links(a["id"], "j1") is False
    assert "l1b" in _item_ids(a)
    env.fail_delete = False
    assert user_archive.purge_job_links(a["id"], "j1") is True
    assert _item_ids(a) == ["l2"] and env.deleted == ["archive/orph/l1b"]


# ------------------------------------------------------------ sweep

def test_tolerance_full_cycle(env, mails, monkeypatch):
    monkeypatch.setattr(accounts, "plan_quota_bytes", lambda p: 100)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_old", 60, at=T0 + 1)
    _upload(a, "i_mid", 50, at=T0 + 2)
    _archived(a, "j_new", 40, at=T0 + 3)
    _upload(a, "i_zero", 0, at=T0)                       # 0 byte: mai scelto
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out["started"] == 1
    assert [b[0] for b in mails.over[0]["books"]] == ["j_old"]     # eccedenza 50, j_old ne libera 60
    mail = mails.over[0]
    assert mail["email"] == "a@b.it" and mail["lang"] == accounts.get(a["id"])["lang"]
    assert mail["off"] is False and mail["deadline"] == "2027-01-30"
    assert mail["used"] == accounts.format_bytes(150) and mail["quota"] == accounts.format_bytes(100)
    assert mail["manage_url"] == email_service.BASE_URL + "/account"
    assert mail["books"] == [("j_old", accounts.format_bytes(60))]
    assert accounts.get(a["id"])["archive_notice_stage"] == 1
    deadline = T0 + 10 + 15 * DAY
    archive_tolerance.sweep(now=deadline - 3 * DAY, force=True)
    archive_tolerance.sweep(now=deadline - 2 * DAY, force=True)
    assert len(mails.remind) == 1 and accounts.get(a["id"])["archive_notice_stage"] == 2
    assert mails.remind[0]["deadline"] == "2027-01-30"
    assert [b[0] for b in mails.remind[0]["books"]] == ["j_old"]
    archive_tolerance.sweep(now=deadline - 1, force=True)
    assert accounts.archive_protects("j_old")                     # un secondo prima: niente
    out = archive_tolerance.sweep(now=deadline, force=True)
    assert out["evicted"] == 1 and not accounts.archive_protects("j_old")
    assert accounts.archive_protects("j_new")
    with db.tx() as c:
        row = c.execute("SELECT archive_evicted_at FROM account_jobs WHERE job_id='j_old'").fetchone()
        assert row[0] == deadline
        assert c.execute("SELECT COUNT(*) FROM archive_items").fetchone()[0] == 2
    acc = accounts.get(a["id"])
    assert acc["archive_over_since"] is None and acc["archive_notice_stage"] == 0
    assert len(mails.over) == 1 and len(mails.remind) == 1


def test_no_tolerance_without_email(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j1", 150, at=T0)
    mails.ok = False
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out["started"] == 0 and out["errors"] == 1
    assert accounts.get(a["id"])["archive_over_since"] is None
    out = archive_tolerance.sweep(now=T0 + 30 * DAY, force=True)
    assert out["evicted"] == 0 and out["errors"] == 1
    assert accounts.get(a["id"])["archive_over_since"] is None
    assert accounts.archive_protects("j1")
    mails.ok = True
    later = T0 + 31 * DAY
    out = archive_tolerance.sweep(now=later, force=True)
    assert out["started"] == 1 and out["errors"] == 0
    acc = accounts.get(a["id"])
    assert acc["archive_over_since"] == later and acc["archive_notice_stage"] == 1
    assert accounts.archive_protects("j1")


def test_eviction_stops_on_storage_error(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    k1 = _upload(a, "i1", 30, at=T0 + 1)
    k2 = _upload(a, "i2", 30, at=T0 + 2)
    _upload(a, "i3", 80, at=T0 + 3)                       # eccedenza 40: servono i1 e i2
    archive_tolerance.sweep(now=T0 + 10, force=True)
    assert [b[0] for b in mails.over[0]["books"]] == ["i1", "i2"]
    deadline = T0 + 10 + 15 * DAY
    env.fail_delete = True
    out = archive_tolerance.sweep(now=deadline, force=True)
    assert out["evicted"] == 0 and out["errors"] == 1
    assert _item_ids(a) == ["i1", "i2", "i3"]
    acc = accounts.get(a["id"])
    assert acc["archive_over_since"] == T0 + 10
    env.fail_delete = False
    out = archive_tolerance.sweep(now=deadline + 3600, force=True)
    assert out["evicted"] == 2 and out["errors"] == 0
    assert _item_ids(a) == ["i3"] and env.deleted == [k1, k2]
    acc = accounts.get(a["id"])
    assert acc["archive_over_since"] is None and acc["archive_notice_stage"] == 0


def test_job_links_purged_before_eviction(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j1", 150, at=T0)
    _upload(a, "lnk", 5, at=T0 + 1, job_id="j1", r2_key="", orphan_key="archive/orph/lnk")
    archive_tolerance.sweep(now=T0 + 10, force=True)
    deadline = T0 + 10 + 15 * DAY
    env.fail_delete = True
    out = archive_tolerance.sweep(now=deadline, force=True)
    assert out["evicted"] == 0 and out["errors"] == 1
    assert accounts.archive_protects("j1") and _item_ids(a) == ["lnk"]
    env.fail_delete = False
    out = archive_tolerance.sweep(now=deadline + 3600, force=True)
    assert out["evicted"] == 1 and out["errors"] == 0
    assert _item_ids(a) == [] and env.deleted == ["archive/orph/lnk"]
    assert not accounts.archive_protects("j1")


def test_expired_gift_opens_tolerance_not_eviction(env, mails):
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_old", 300 * MIB, at=T0 + 1)
    _archived(a, "j_new", 300 * MIB, at=T0 + 2)
    _gift(a, "sub_10", T0 + 5)
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out["gifts_expired"] == 1 and out["started"] == 1 and out["evicted"] == 0
    assert accounts.get(a["id"])["plan"] == "free"
    assert len(mails.over) == 1 and mails.over[0]["off"] is False
    assert [b[0] for b in mails.over[0]["books"]] == ["j_old"]
    assert accounts.archive_protects("j_old") and accounts.archive_protects("j_new")
    acc = accounts.get(a["id"])
    assert (acc["archive_over_since"], acc["archive_notice_stage"]) == (T0 + 10, 1)


def test_expired_gift_without_consent_sends_off_notice(env, mails):
    a = _login("a@b.it")
    _archived(a, "j_before", 10 * MIB, at=T0 + 1, created=T0 - 100 * DAY)   # creato prima del regalo
    _archived(a, "j_gift", 20 * MIB, at=T0 + 2)
    _gift(a, "sub_5", T0 + 5)
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out["gifts_expired"] == 1 and out["started"] == 1 and out["evicted"] == 0
    assert accounts.get(a["id"])["plan"] == "free"
    assert len(mails.over) == 1 and mails.over[0]["off"] is True
    assert [b[0] for b in mails.over[0]["books"]] == ["j_before", "j_gift"]
    assert mails.over[0]["quota"] == accounts.format_bytes(0)
    assert accounts.get(a["id"])["archive_notice_stage"] == 1
    assert accounts.archive_protects("j_before") and accounts.archive_protects("j_gift")
    deadline = T0 + 10 + 15 * DAY
    out = archive_tolerance.sweep(now=deadline, force=True)
    assert out["evicted"] == 2
    assert not accounts.archive_protects("j_before") and not accounts.archive_protects("j_gift")
    assert len(mails.over) == 1


def test_tolerance_cleared_when_back_under_quota(env, mails):
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j1", 300 * MIB, at=T0 + 1)
    accounts.free_plan_action(a["id"], "deactivate", "account", now=T0 + 5)
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out["started"] == 1 and mails.over[0]["off"] is True
    accounts.free_plan_action(a["id"], "activate", "account", now=T0 + DAY)
    out = archive_tolerance.sweep(now=T0 + 2 * DAY, force=True)
    assert out["cleared"] == 1 and out["evicted"] == 0 and out["reminded"] == 0
    acc = accounts.get(a["id"])
    assert acc["archive_over_since"] is None and acc["archive_notice_stage"] == 0
    assert accounts.archive_protects("j1") and mails.remind == []
    out = archive_tolerance.sweep(now=T0 + 20 * DAY, force=True)
    assert out == ZERO and accounts.archive_protects("j1")


def test_tolerance_skips_deleted_accounts(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    gone = _login("g@b.it"); _consent(gone)
    live = _login("l@b.it"); _consent(live)
    _archived(gone, "j_gone", 150, at=T0)
    _archived(live, "j_live", 10, at=T0)
    accounts.set_archive_tolerance(gone["id"], T0, 1)
    with db.tx() as c:                                    # cancellato, tolleranza e righe ancora li'
        c.execute("UPDATE accounts SET deleted_at=? WHERE id=?", (T0 + 1, gone["id"]))
    ids = [x["id"] for x in accounts.archive_accounts_to_check()]
    assert ids == [live["id"]]
    out = archive_tolerance.sweep(now=T0 + 30 * DAY, force=True)
    assert out == ZERO and mails.over == [] and mails.remind == []
    with db.tx() as c:
        row = c.execute("SELECT archived_at FROM account_jobs WHERE job_id='j_gone'").fetchone()
    assert row[0] is not None


def test_sweep_rechecks_account_state(env, mails, monkeypatch):
    """L'elenco degli account si legge a inizio giro: ogni account si rilegge prima di agire."""
    _small_quota(monkeypatch)
    gone = _login("g@b.it"); _consent(gone)
    back = _login("b@b.it")                                # senza consenso: quota 0 allo scatto dell'istantanea
    _archived(gone, "j_gone", 150, at=T0)
    _archived(back, "j_back", 50, at=T0)
    empty = _login("e@b.it")                               # nessun libro, tolleranza ancora aperta
    accounts.set_archive_tolerance(empty["id"], T0, 1)
    snapshot = accounts.archive_accounts_to_check()
    assert {x["id"] for x in snapshot} == {gone["id"], back["id"], empty["id"]}
    with db.tx() as c:
        c.execute("UPDATE accounts SET deleted_at=? WHERE id IN (?, ?)", (T0 + 1, gone["id"], empty["id"]))
    _consent(back)                                         # consenso dato dopo l'istantanea: 100 byte, ne usa 50
    monkeypatch.setattr(accounts, "archive_accounts_to_check", lambda: snapshot)
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out == ZERO and mails.over == []
    assert accounts.get(gone["id"])["archive_over_since"] is None
    assert accounts.get(back["id"])["archive_over_since"] is None


def test_migrated_expired_grace_evicted_without_email(env, mails):
    a = _login("a@b.it")
    _archived(a, "j1", 10, at=T0 + 1)
    _archived(a, "j2", 20, at=T0 + 2)
    accounts.set_archive_tolerance(a["id"], T0 - 16 * DAY, 2)      # stato della migrazione, caso 4
    out = archive_tolerance.sweep(now=T0, force=True)
    assert out["evicted"] == 2 and out["started"] == 0 and out["errors"] == 0
    assert mails.over == [] and mails.remind == []
    assert not accounts.archive_protects("j1") and not accounts.archive_protects("j2")
    acc = accounts.get(a["id"])
    assert acc["archive_over_since"] is None and acc["archive_notice_stage"] == 0


def test_remind_failure_is_retried(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j1", 150, at=T0)
    archive_tolerance.sweep(now=T0 + 10, force=True)
    deadline = T0 + 10 + 15 * DAY
    mails.ok = False
    out = archive_tolerance.sweep(now=deadline - 3 * DAY, force=True)
    assert out["reminded"] == 0 and out["errors"] == 1
    assert accounts.get(a["id"])["archive_notice_stage"] == 1
    mails.ok = True
    out = archive_tolerance.sweep(now=deadline - 3 * DAY + 3600, force=True)
    assert out["reminded"] == 1 and accounts.get(a["id"])["archive_notice_stage"] == 2
    assert accounts.archive_protects("j1")


def test_no_email_when_only_pending_uploads_exceed(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _upload(a, "i_pending", 150, at=T0, state="pending")
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out == ZERO and mails.over == []
    assert accounts.get(a["id"])["archive_over_since"] is None


def test_account_error_does_not_stop_other_accounts(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    first = _login("a@b.it"); _consent(first)
    second = _login("c@d.it"); _consent(second)
    _archived(first, "j1", 150, at=T0)
    _archived(second, "j2", 150, at=T0)
    real = email_service.send_archive_over
    calls = []

    def flaky(email, lang, **kw):
        calls.append(email)
        if email == "a@b.it":
            raise RuntimeError("smtp boom")
        return real(email, lang, **kw)

    monkeypatch.setattr(email_service, "send_archive_over", flaky)
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out["errors"] == 1 and out["started"] == 1 and len(calls) == 2
    assert accounts.get(first["id"])["archive_over_since"] is None
    assert accounts.get(second["id"])["archive_over_since"] == T0 + 10


def test_sweep_rate_limited(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j1", 150, at=T0)
    out = archive_tolerance.sweep(now=T0, force=True)
    assert out["started"] == 1
    b = _login("c@d.it"); _consent(b)
    _archived(b, "j2", 150, at=T0)
    assert archive_tolerance.sweep(now=T0 + 10) == ZERO               # force aveva fissato l'istante
    assert len(mails.over) == 1
    out = archive_tolerance.sweep(now=T0 + archive_tolerance.SWEEP_INTERVAL_SEC)
    assert out["started"] == 1 and len(mails.over) == 2


def test_sweep_disabled_returns_zeros(env, mails, monkeypatch):
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert archive_tolerance.sweep(now=T0, force=True) == ZERO
