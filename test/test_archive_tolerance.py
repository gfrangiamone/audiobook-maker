# test/test_archive_tolerance.py
"""Tolleranza sull'eccedenza dell'archivio: avviso email, promemoria, poi
cancellazione dei libri piu' vecchi (job tolti dalla protezione, upload tolti
da R2 e dal DB)."""
import hashlib
import json

import pytest

import accounts
import archive_tolerance
import db
import email_service
import storage_backend
import user_archive
from test.test_account_plans import T0, _consent, _done_job, _gift, _login
from test.test_user_archive import FakeR2

MIB = accounts.MIB
DAY = 86400
ZERO = {"gifts_expired": 0, "started": 0, "reminded": 0, "evicted": 0, "cleared": 0, "errors": 0,
        "deferred": 0}


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
    archive_tolerance._sweep_state["at"] = float("inf")     # i test non spazzano mai da soli: solo force=True
    archive_tolerance._sweep_state["cursor"] = None
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
        self.sent = []                  # titoli dei libri di ogni email partita davvero, nell'ordine
        self.ok = True

    def listed(self):
        """Titoli elencati dall'ultima email partita con successo: quello che l'utente sa."""
        return set(self.sent[-1]) if self.sent else set()


@pytest.fixture
def mails(monkeypatch):
    box = _Mails()

    def over(email, lang, **kw):
        box.over.append({"email": email, "lang": lang, **kw})
        if box.ok:
            box.sent.append([b[0] for b in kw["books"]])
        return box.ok

    def remind(email, lang, **kw):
        box.remind.append({"email": email, "lang": lang, **kw})
        if box.ok:
            box.sent.append([b[0] for b in kw["books"]])
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


def _small_quota(monkeypatch, nbytes=100):
    monkeypatch.setattr(accounts, "plan_quota_bytes", lambda p: nbytes)


def _state(acct):
    """(archive_over_since, archive_notice_stage, chiavi annunciate in ordine) dell'account."""
    acc = accounts.get(acct["id"])
    keys = accounts.archive_notice_keys(acc)
    return (acc["archive_over_since"], acc["archive_notice_stage"],
            None if keys is None else sorted(keys))


def _entry_ids(acct):
    return {e["id"] for e in accounts.archive_entries(acct["id"])}


def _sweep_checked(acct, mails, when):
    """Un giro; ritorna (esito, id delle voci tolte). Una voce tolta deve essere fra i libri
    dell'ultima email partita prima del giro: il vincolo dell'avviso."""
    listed = mails.listed()
    before = _entry_ids(acct)
    out = archive_tolerance.sweep(now=when, force=True)
    gone = before - _entry_ids(acct)
    assert gone <= listed, f"tolte senza essere elencate: {sorted(gone - listed)}"
    return out, gone


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
    assert acc["archive_notice_ids"] is None                           # senza notice_ids la colonna resta NULL
    assert accounts.archive_notice_keys(acc) is None
    accounts.set_archive_tolerance(a["id"], T0 + 7, 1, notice_ids={"job:j2", "item:i1", "job:j1"})
    acc = accounts.get(a["id"])
    assert json.loads(acc["archive_notice_ids"]) == ["item:i1", "job:j1", "job:j2"]   # array JSON ordinato
    assert accounts.archive_notice_keys(acc) == {"item:i1", "job:j1", "job:j2"}
    accounts.set_archive_tolerance(a["id"], T0 + 7, 2, notice_ids=[])     # insieme vuoto e' un valore, non NULL
    acc = accounts.get(a["id"])
    assert acc["archive_notice_ids"] == "[]" and accounts.archive_notice_keys(acc) == set()
    accounts.set_archive_tolerance(a["id"], None, 0, notice_ids=["job:j1"])   # chiudere azzera sempre
    acc = accounts.get(a["id"])
    assert (acc["archive_over_since"], acc["archive_notice_stage"]) == (None, 0)
    assert acc["archive_notice_ids"] is None
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


def test_delete_account_clears_notice_ids(env):
    a = _login("a@b.it")
    accounts.set_archive_tolerance(a["id"], T0, 1, notice_ids=["job:j1"])
    assert accounts.delete_account(a["id"], now=T0 + 1) is True
    with db.tx() as c:
        row = c.execute("SELECT archive_over_since, archive_notice_stage, archive_notice_ids "
                        "FROM accounts WHERE id=?", (a["id"],)).fetchone()
    assert tuple(row) == (None, 0, None)


@pytest.mark.parametrize("raw", ["not json{", "", '{"job:j1": 1}', "[1, 2]", '"job:j1"', "7", '["job:j1", null]'])
def test_malformed_notice_ids_is_an_empty_set_and_logged(env, monkeypatch, raw):
    seen = []
    monkeypatch.setattr(accounts, "_log", seen.append)
    a = _login("a@b.it")
    with db.tx() as c:
        c.execute("UPDATE accounts SET archive_notice_ids=? WHERE id=?", (raw, a["id"]))
    assert accounts.archive_notice_keys(accounts.get(a["id"])) == set()       # mai un'eccezione
    assert len(seen) == 1 and seen[0].startswith("WARNING accounts") and a["id"] in seen[0]
    seen.clear()
    with db.tx() as c:                                                        # NULL e' normale: nessun avviso
        c.execute("UPDATE accounts SET archive_notice_ids=NULL WHERE id=?", (a["id"],))
    assert accounts.archive_notice_keys(accounts.get(a["id"])) is None and seen == []


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
    assert _state(a) == (T0 + 10, 1, ["job:j_old"])                      # l'elenco dell'avviso, in chiavi
    deadline = T0 + 10 + 15 * DAY
    archive_tolerance.sweep(now=deadline - 3 * DAY, force=True)
    archive_tolerance.sweep(now=deadline - 2 * DAY, force=True)
    assert len(mails.remind) == 1 and accounts.get(a["id"])["archive_notice_stage"] == 2
    assert _state(a) == (T0 + 10, 2, ["job:j_old"])                      # il promemoria elenca gli stessi
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
    assert _state(a) == (None, 0, None)
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


# ------------------------------------------------------------ eccedenza cresciuta a tolleranza aperta

def _gift_drop_setup(monkeypatch, mails):
    """Regalo da 550 MiB che scade DOPO il promemoria e prima della scadenza; poi vale il
    gratuito (512 MiB). Archivio da 600 MiB: j1, j2, j3 da 30 MiB e j4 da 510 MiB. L'avviso
    (eccedenza 600 - 550 = 50 MiB) elenca j1 e j2."""
    monkeypatch.setattr(accounts, "plan_quota_bytes",
                        lambda p: {"free": 512 * MIB, "sub_10": 550 * MIB}.get(p, 0))
    a = _login("a@b.it"); _consent(a)
    for i, (job_id, size) in enumerate((("j1", 30), ("j2", 30), ("j3", 30), ("j4", 510))):
        _archived(a, job_id, size * MIB, at=T0 + 1 + i)
    _gift(a, "sub_10", T0 + 13 * DAY)
    start = T0 + 10
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1
    old_deadline = start + 15 * DAY
    assert archive_tolerance.sweep(now=old_deadline - 3 * DAY, force=True)["reminded"] == 1
    assert _state(a) == (start, 2, ["job:j1", "job:j2"])
    assert [b[0] for b in mails.over[0]["books"]] == ["j1", "j2"] and len(mails.remind) == 1
    return a, start, old_deadline


def _protected(*job_ids):
    return [accounts.archive_protects(j) for j in job_ids]


def test_quota_drop_after_reminder_restarts_tolerance(env, mails, monkeypatch):
    a, start, old_deadline = _gift_drop_setup(monkeypatch, mails)
    drop = T0 + 13 * DAY + 3600                               # il regalo e' scaduto dopo il promemoria
    out = archive_tolerance.sweep(now=drop, force=True)
    assert out["gifts_expired"] == 1 and out["started"] == 1
    assert out["evicted"] == 0 and out["errors"] == 0 and out["reminded"] == 0
    assert len(mails.over) == 2 and mails.over[1]["off"] is False
    assert [b[0] for b in mails.over[1]["books"]] == ["j1", "j2", "j3"]    # piano ricalcolato sulla quota di adesso
    assert mails.over[1]["deadline"] == "2027-02-12"
    assert mails.over[1]["quota"] == accounts.format_bytes(512 * MIB)
    assert _state(a) == (drop, 1, ["job:j1", "job:j2", "job:j3"])        # le chiavi dell'avviso di adesso
    out = archive_tolerance.sweep(now=old_deadline, force=True)            # la vecchia scadenza non vale piu'
    assert out["evicted"] == 0 and out["errors"] == 0
    assert _protected("j1", "j2", "j3", "j4") == [True] * 4
    new_deadline = drop + 15 * DAY
    out = archive_tolerance.sweep(now=new_deadline - 3 * DAY, force=True)  # promemoria della nuova finestra
    assert out["reminded"] == 1 and len(mails.remind) == 2
    assert [b[0] for b in mails.remind[1]["books"]] == ["j1", "j2", "j3"]
    assert _state(a) == (drop, 2, ["job:j1", "job:j2", "job:j3"])
    assert archive_tolerance.sweep(now=new_deadline - 1, force=True)["evicted"] == 0
    out = archive_tolerance.sweep(now=new_deadline, force=True)
    assert out["evicted"] == 3 and out["errors"] == 0
    assert _protected("j1", "j2", "j3", "j4") == [False, False, False, True]
    assert _state(a) == (None, 0, None)
    assert len(mails.over) == 2 and len(mails.remind) == 2


def test_quota_drop_restart_needs_email(env, mails, monkeypatch, capsys):
    a, start, old_deadline = _gift_drop_setup(monkeypatch, mails)
    drop = T0 + 13 * DAY + 3600
    mails.ok = False                                          # il nuovo avviso non parte
    capsys.readouterr()
    for when in (drop, old_deadline, old_deadline + 20 * DAY):
        out = archive_tolerance.sweep(now=when, force=True)
        assert out["evicted"] == 0 and out["started"] == 0 and out["errors"] >= 1
        warn = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("WARNING")]
        assert len(warn) == 1 and "non si toglie niente fino a quando non parte" in warn[0]
        assert _protected("j1", "j2", "j3", "j4") == [True] * 4
        assert _state(a) == (start, 2, ["job:j1", "job:j2"])  # tolleranza e chiavi annunciate restano quelle di prima
    assert len(mails.over) == 4                               # un tentativo per giro, mai due avvisi insieme
    mails.ok = True
    later = old_deadline + 21 * DAY
    out = archive_tolerance.sweep(now=later, force=True)
    assert out["started"] == 1 and out["evicted"] == 0 and out["errors"] == 0
    assert _state(a) == (later, 1, ["job:j1", "job:j2", "job:j3"])
    assert _protected("j1", "j2", "j3", "j4") == [True] * 4


def test_consent_toggle_cannot_postpone_forever(env, mails):
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j1", 100 * MIB, at=T0 + 1)
    _archived(a, "j2", 100 * MIB, at=T0 + 2)
    _archived(a, "j3", 400 * MIB, at=T0 + 3)
    out = archive_tolerance.sweep(now=T0 + 10, force=True)             # gratuito: 512 MiB, ne usa 600
    assert out["started"] == 1 and [b[0] for b in mails.over[0]["books"]] == ["j1"]
    assert _state(a) == (T0 + 10, 1, ["job:j1"])

    accounts.free_plan_action(a["id"], "deactivate", "account", now=T0 + DAY)
    restart = T0 + 2 * DAY
    out = archive_tolerance.sweep(now=restart, force=True)             # quota 0: il piano e' j1, j2, j3 e j2, j3 non erano elencati
    assert out["started"] == 1 and len(mails.over) == 2 and mails.over[1]["off"] is True
    assert [b[0] for b in mails.over[1]["books"]] == ["j1", "j2", "j3"]
    assert _state(a) == (restart, 1, ["job:j1", "job:j2", "job:j3"])

    accounts.free_plan_action(a["id"], "activate", "account", now=T0 + 3 * DAY)
    out = archive_tolerance.sweep(now=T0 + 4 * DAY, force=True)        # la quota risale: il piano {j1} e' dentro le chiavi annunciate
    assert out == ZERO and len(mails.over) == 2
    assert _state(a) == (restart, 1, ["job:j1", "job:j2", "job:j3"])

    accounts.free_plan_action(a["id"], "deactivate", "account", now=T0 + 5 * DAY)
    out = archive_tolerance.sweep(now=T0 + 6 * DAY, force=True)        # e riscende: {j1, j2, j3} e' dentro, nessun riavvio
    assert out == ZERO and len(mails.over) == 2 and mails.remind == []
    assert _state(a) == (restart, 1, ["job:j1", "job:j2", "job:j3"])
    assert _protected("j1", "j2", "j3") == [True] * 3

    out, gone = _sweep_checked(a, mails, restart + 15 * DAY)           # scade la finestra dell'ultimo avviso
    assert out["evicted"] == 3 and out["errors"] == 0 and len(mails.over) == 2
    assert gone == {"j1", "j2", "j3"} and _protected("j1", "j2", "j3") == [False] * 3
    assert _state(a) == (None, 0, None)


def test_null_notice_ids_skips_the_check(env, mails):
    """Stato migrato (stage 2, scadenza passata, chiavi annunciate NULL) con un archivio ancora
    oltre una quota > 0: niente da confrontare, nessun nuovo avviso, vale la scadenza e si toglie
    il necessario."""
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_old", 300 * MIB, at=T0 + 1)
    _archived(a, "j_new", 300 * MIB, at=T0 + 2)
    accounts.set_archive_tolerance(a["id"], T0 - 16 * DAY, 2)
    assert accounts.get(a["id"])["archive_notice_ids"] is None
    out = archive_tolerance.sweep(now=T0, force=True)
    assert out["evicted"] == 1 and out["started"] == 0 and out["errors"] == 0
    assert mails.over == [] and _protected("j_old", "j_new") == [False, True]


def test_usage_growth_during_tolerance_restarts(env, mails, monkeypatch):
    """La quota non cambia ma l'archivio cresce a tolleranza aperta (un libro piu' recente): il
    piano di sfratto non e' piu' quello dell'avviso, quindi un avviso nuovo prima di togliere."""
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_a", 60, at=T0 + 1)
    _archived(a, "j_b", 90, at=T0 + 2)
    assert archive_tolerance.sweep(now=T0 + 10, force=True)["started"] == 1       # 150 su 100: elenca j_a
    assert [b[0] for b in mails.over[0]["books"]] == ["j_a"]
    old_deadline = T0 + 10 + 15 * DAY
    assert _state(a) == (T0 + 10, 1, ["job:j_a"])
    _archived(a, "j_c", 30, at=T0 + 20)                       # senza controllo di quota: 180 su 100
    grow = T0 + 5 * DAY
    out = archive_tolerance.sweep(now=grow, force=True)
    assert out["started"] == 1 and out["evicted"] == 0 and out["errors"] == 0
    assert len(mails.over) == 2 and mails.over[1]["off"] is False
    assert [b[0] for b in mails.over[1]["books"]] == ["j_a", "j_b"]       # il piano ricalcolato su 80 di eccedenza
    assert mails.over[1]["deadline"] == "2027-02-04" and mails.over[1]["used"] == accounts.format_bytes(180)
    assert _state(a) == (grow, 1, ["job:j_a", "job:j_b"])
    out = archive_tolerance.sweep(now=old_deadline, force=True)            # la vecchia scadenza non vale piu'
    assert out["evicted"] == 0 and out["errors"] == 0 and out["reminded"] == 0
    assert _protected("j_a", "j_b", "j_c") == [True] * 3
    new_deadline = grow + 15 * DAY
    out, gone = _sweep_checked(a, mails, new_deadline)
    assert out["evicted"] == 2 and out["errors"] == 0 and len(mails.over) == 2
    assert gone == {"j_a", "j_b"} and _protected("j_a", "j_b", "j_c") == [False, False, True]
    assert _state(a) == (None, 0, None)


def test_freed_more_than_quota_drop_needs_no_new_email(env, mails, monkeypatch):
    """La quota scende di 30 ma l'utente ha tolto 40 dall'archivio prima del giro: il piano
    ricalcolato ({j1, j2}) resta dentro le chiavi annunciate ({j1, j2, j3}), quindi niente secondo
    avviso."""
    monkeypatch.setattr(accounts, "plan_quota_bytes", lambda p: {"free": 100, "sub_10": 130}.get(p, 0))
    a = _login("a@b.it"); _consent(a)
    for i, (job_id, size) in enumerate((("j1", 10), ("j2", 10), ("j3", 40), ("j4", 40), ("j5", 60))):
        _archived(a, job_id, size, at=T0 + 1 + i)
    _gift(a, "sub_10", T0 + 13 * DAY)
    start = T0 + 10
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1         # 160 su 130: annuncia 30
    old_deadline = start + 15 * DAY
    assert archive_tolerance.sweep(now=old_deadline - 3 * DAY, force=True)["reminded"] == 1
    assert [b[0] for b in mails.over[0]["books"]] == ["j1", "j2", "j3"]
    assert accounts.hide_job(a["id"], "j4", now=T0 + 13 * DAY - 60) == "ok"        # l'utente libera 40
    drop = T0 + 13 * DAY + 3600                               # il regalo scade: quota 100, usa 120
    out = archive_tolerance.sweep(now=drop, force=True)
    assert out["gifts_expired"] == 1 and out["started"] == 0 and out["errors"] == 0
    assert out["evicted"] == 0 and len(mails.over) == 1 and len(mails.remind) == 1
    assert _state(a) == (start, 2, ["job:j1", "job:j2", "job:j3"])        # niente di cambiato
    out, gone = _sweep_checked(a, mails, old_deadline)                     # scade la finestra originale
    assert out["evicted"] == 2 and out["errors"] == 0 and len(mails.over) == 1
    assert gone == {"j1", "j2"} and _protected("j1", "j2", "j3", "j5") == [False, False, True, True]
    assert _state(a) == (None, 0, None)


# ------------------------------------------------------------ si toglie solo cio' che l'ultima email ha elencato

def test_listed_book_deleted_then_new_book_restarts(env, mails, monkeypatch):
    """L'utente toglie il libro elencato e ne arriva uno uguale prima del giro: l'eccedenza e'
    identica ma il piano e' {j_b}, mai annunciato. Nuovo avviso, poi lo sfratto di j_b."""
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_a", 60, at=T0 + 1)
    _archived(a, "j_b", 90, at=T0 + 2)
    start = T0 + 10
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1
    assert [b[0] for b in mails.over[0]["books"]] == ["j_a"]
    assert _state(a) == (start, 1, ["job:j_a"])
    assert accounts.hide_job(a["id"], "j_a", now=T0 + 11) == "ok"           # l'utente toglie il libro elencato
    _archived(a, "j_c", 60, at=T0 + 12)                                      # e ne arriva uno uguale
    old_deadline = start + 15 * DAY
    out, gone = _sweep_checked(a, mails, old_deadline)
    assert out["started"] == 1 and out["evicted"] == 0 and out["errors"] == 0 and gone == set()
    assert len(mails.over) == 2 and [b[0] for b in mails.over[1]["books"]] == ["j_b"]
    assert _state(a) == (old_deadline, 1, ["job:j_b"])
    assert _protected("j_b", "j_c") == [True, True]
    new_deadline = old_deadline + 15 * DAY
    out, gone = _sweep_checked(a, mails, new_deadline)
    assert out["evicted"] == 1 and out["errors"] == 0 and gone == {"j_b"}
    assert _protected("j_b", "j_c") == [False, True] and len(mails.over) == 2
    assert _state(a) == (None, 0, None)


def test_listed_book_deleted_and_gift_expiry_restarts(env, mails, monkeypatch):
    """Un libro elencato viene tolto e nello stesso intervallo scade il regalo: l'eccedenza resta 30
    ma il piano e' {j1, j2, j4}, e j4 non era nell'avviso."""
    monkeypatch.setattr(accounts, "plan_quota_bytes", lambda p: {"free": 90, "sub_10": 130}.get(p, 0))
    a = _login("a@b.it"); _consent(a)
    for i, (job_id, size) in enumerate((("j1", 10), ("j2", 10), ("j3", 40), ("j4", 40), ("j5", 60))):
        _archived(a, job_id, size, at=T0 + 1 + i)
    _gift(a, "sub_10", T0 + 13 * DAY)
    start = T0 + 10
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1             # 160 su 130
    assert [b[0] for b in mails.over[0]["books"]] == ["j1", "j2", "j3"]
    assert accounts.hide_job(a["id"], "j3", now=T0 + 13 * DAY - 60) == "ok"          # tolto un libro elencato
    drop = T0 + 13 * DAY + 3600                                                      # il regalo scade: 120 su 90
    out, gone = _sweep_checked(a, mails, drop)
    assert out["gifts_expired"] == 1 and out["started"] == 1 and out["evicted"] == 0 and gone == set()
    assert [b[0] for b in mails.over[1]["books"]] == ["j1", "j2", "j4"]
    assert _state(a) == (drop, 1, ["job:j1", "job:j2", "job:j4"])
    out, gone = _sweep_checked(a, mails, start + 15 * DAY)                           # la vecchia scadenza non vale piu'
    assert out["evicted"] == 0 and gone == set()
    out, gone = _sweep_checked(a, mails, drop + 15 * DAY)
    assert out["evicted"] == 3 and out["errors"] == 0 and gone == {"j1", "j2", "j4"}
    assert _protected("j1", "j2", "j4", "j5") == [False, False, False, True]
    assert _state(a) == (None, 0, None) and len(mails.over) == 2


def test_pending_upload_completing_restarts(env, mails, monkeypatch):
    """Un upload prenotato prima degli altri libri conta nell'uso mentre e' aperto; quando si chiude
    diventa il libro piu' vecchio e il piano cambia in {i_p}, mai annunciato."""
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_a", 60, at=T0 + 5)
    _archived(a, "j_b", 40, at=T0 + 6)
    _upload(a, "i_p", 70, at=T0, state="pending")
    start = T0 + 10
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1             # 170 su 100: eccedenza 70
    assert [b[0] for b in mails.over[0]["books"]] == ["j_a", "j_b"]
    assert _state(a) == (start, 1, ["job:j_a", "job:j_b"])
    with db.tx() as c:
        c.execute("UPDATE archive_items SET state='ready' WHERE id='i_p'")
    deadline = start + 15 * DAY
    out, gone = _sweep_checked(a, mails, deadline)
    assert out["started"] == 1 and out["evicted"] == 0 and out["errors"] == 0 and gone == set()
    assert [b[0] for b in mails.over[1]["books"]] == ["i_p"]
    assert _state(a) == (deadline, 1, ["item:i_p"])
    assert _item_ids(a) == ["i_p"] and _protected("j_a", "j_b") == [True, True]
    out, gone = _sweep_checked(a, mails, deadline + 15 * DAY)
    assert out["evicted"] == 1 and out["errors"] == 0 and gone == {"i_p"}
    assert _item_ids(a) == [] and _protected("j_a", "j_b") == [True, True]
    assert _state(a) == (None, 0, None) and len(mails.over) == 2


def test_over_quota_after_full_eviction_needs_new_email(env, mails, monkeypatch):
    """Tolto tutto il piano annunciato l'account resta oltre la quota per un upload ancora aperto:
    finche' non c'e' niente da togliere non si fa niente e la tolleranza resta aperta; quando
    l'upload si chiude il libro nuovo si toglie solo dopo un avviso che lo elenca."""
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_a", 60, at=T0 + 5)
    _upload(a, "i_p", 120, at=T0, state="pending")
    start = T0 + 10
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1             # 180 su 100
    assert [b[0] for b in mails.over[0]["books"]] == ["j_a"]
    deadline = start + 15 * DAY
    out, gone = _sweep_checked(a, mails, deadline - 3 * DAY)
    assert out["reminded"] == 1 and gone == set()
    out, gone = _sweep_checked(a, mails, deadline)
    assert out["evicted"] == 1 and out["errors"] == 0 and gone == {"j_a"}
    assert _state(a) == (start, 2, ["job:j_a"])               # 120 su 100 per l'upload aperto: tolleranza ancora aperta
    out, gone = _sweep_checked(a, mails, deadline + 3600)     # niente da togliere: nessuna email, nessun cambio
    assert out == ZERO and gone == set() and len(mails.over) == 1 and len(mails.remind) == 1
    assert _state(a) == (start, 2, ["job:j_a"])
    with db.tx() as c:
        c.execute("UPDATE archive_items SET state='ready' WHERE id='i_p'")
    later = deadline + 7200
    out, gone = _sweep_checked(a, mails, later)               # ora c'e' un libro e non era nell'ultima email
    assert out["started"] == 1 and out["evicted"] == 0 and out["errors"] == 0 and gone == set()
    assert [b[0] for b in mails.over[1]["books"]] == ["i_p"]
    assert _state(a) == (later, 1, ["item:i_p"]) and _item_ids(a) == ["i_p"]
    out, gone = _sweep_checked(a, mails, later + 15 * DAY)
    assert out["evicted"] == 1 and gone == {"i_p"} and _item_ids(a) == []
    assert _state(a) == (None, 0, None) and len(mails.over) == 2


def test_reminder_narrows_the_announced_set(env, mails, monkeypatch):
    """L'avviso elenca {j_a, j_b}; l'utente libera spazio e il promemoria elenca solo {j_a}: da li'
    la promessa e' {j_a}. Se il piano torna a includere j_b si riparte con un avviso."""
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    for i, (job_id, size) in enumerate((("j_a", 40), ("j_b", 40), ("j_c", 30), ("j_d", 40))):
        _archived(a, job_id, size, at=T0 + 1 + i)
    start = T0 + 10
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1             # 150 su 100: eccedenza 50
    assert [b[0] for b in mails.over[0]["books"]] == ["j_a", "j_b"]
    assert _state(a) == (start, 1, ["job:j_a", "job:j_b"])
    deadline = start + 15 * DAY
    assert accounts.hide_job(a["id"], "j_d", now=start + DAY) == "ok"                # l'utente libera 40: eccedenza 10
    out, gone = _sweep_checked(a, mails, deadline - 3 * DAY)
    assert out["reminded"] == 1 and out["started"] == 0 and gone == set()
    assert [b[0] for b in mails.remind[0]["books"]] == ["j_a"]
    assert _state(a) == (start, 2, ["job:j_a"])                # la promessa si restringe all'ultimo elenco
    _archived(a, "j_e", 40, at=deadline - 2 * DAY)             # l'archivio ricresce: eccedenza 50, piano {j_a, j_b}
    out, gone = _sweep_checked(a, mails, deadline)
    assert out["started"] == 1 and out["evicted"] == 0 and out["errors"] == 0 and gone == set()
    assert [b[0] for b in mails.over[1]["books"]] == ["j_a", "j_b"]
    assert _state(a) == (deadline, 1, ["job:j_a", "job:j_b"])
    assert _protected("j_a", "j_b", "j_c", "j_e") == [True] * 4
    out, gone = _sweep_checked(a, mails, deadline + 15 * DAY)
    assert out["evicted"] == 2 and gone == {"j_a", "j_b"} and len(mails.over) == 2
    assert _state(a) == (None, 0, None)


def test_malformed_notice_ids_force_a_new_notice_not_an_eviction(env, mails, monkeypatch):
    """Chiavi annunciate illeggibili valgono "nessun libro elencato": a tolleranza scaduta non si
    toglie niente (l'utente non sa cosa rischia), parte un nuovo avviso e la finestra riparte;
    l'anomalia finisce nel log."""
    seen = []
    monkeypatch.setattr(accounts, "_log", seen.append)
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_a", 60, at=T0 + 1)
    _archived(a, "j_b", 90, at=T0 + 2)
    start = T0 + 10
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1
    with db.tx() as c:
        c.execute("UPDATE accounts SET archive_notice_ids='{rotto' WHERE id=?", (a["id"],))
    later = start + 15 * DAY
    out = archive_tolerance.sweep(now=later, force=True)
    assert out["evicted"] == 0 and out["started"] == 1 and out["errors"] == 0 and len(mails.over) == 2
    assert _protected("j_a", "j_b") == [True, True]
    assert _state(a) == (later, 1, ["job:j_a"])               # elenco e scadenza ricalcolati
    assert any("archive_notice_ids" in m and a["id"] in m for m in seen)


def test_eviction_guard_refuses_unannounced_entries(env, mails, monkeypatch, capsys):
    """Difesa in profondita': con un piano che esce dall'insieme annunciato `_evict` non toglie
    niente, registra un ERROR e conta un errore."""
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j_a", 60, at=T0 + 1)
    _archived(a, "j_b", 90, at=T0 + 2)
    plan = accounts.archive_entries(a["id"])
    out = {"evicted": 0, "errors": 0}
    capsys.readouterr()
    archive_tolerance._evict(accounts.get(a["id"]), plan, 100, T0 + 100, out, {"job:j_a"})
    assert out == {"evicted": 0, "errors": 1} and _protected("j_a", "j_b") == [True, True]
    logged = capsys.readouterr().out
    assert "ERROR archive_tolerance" in logged and "job:j_b" in logged and a["id"] in logged


# ------------------------------------------------------------ tetto di email per giro

def _open_two(monkeypatch):
    _small_quota(monkeypatch)
    ids = []
    for i, email in enumerate(("a@b.it", "c@d.it")):
        acct = _login(email); _consent(acct)
        _archived(acct, f"j{i}", 150, at=T0)
        ids.append(acct["id"])
    return ids


def test_notice_ids_cover_the_whole_plan_not_only_the_books_listed_in_the_email(env, mails, monkeypatch):
    """Un piano piu' lungo di ARCHIVE_MAIL_MAX_BOOKS: l'email ne elenca solo i primi, ma le chiavi
    salvate (e quindi cio' che a scadenza si puo' togliere) sono tutte quelle del piano."""
    _small_quota(monkeypatch, 10)
    a = _login("a@b.it"); _consent(a)
    n = email_service.ARCHIVE_MAIL_MAX_BOOKS + 4
    for i in range(n + 1):                                    # una voce in piu': resta in quota
        _archived(a, f"j{i:02d}", 10, at=T0 + i)
    start = T0 + 100
    assert archive_tolerance.sweep(now=start, force=True)["started"] == 1
    assert len(mails.over[0]["books"]) == n > email_service.ARCHIVE_MAIL_MAX_BOOKS
    assert _state(a) == (start, 1, sorted(f"job:j{i:02d}" for i in range(n)))
    out = archive_tolerance.sweep(now=start + 15 * DAY, force=True)    # a scadenza il piano e' ancora annunciato
    assert out["evicted"] == n and out["started"] == 0 and out["errors"] == 0
    assert _protected(f"j{n:02d}") == [True] and len(mails.over) == 1


def test_notice_cap_defers_the_remaining_accounts(env, mails, monkeypatch):
    monkeypatch.setattr(archive_tolerance, "MAX_NOTICES_PER_SWEEP", 1)
    ids = _open_two(monkeypatch)
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert len(mails.over) == 1 and out["started"] == 1 and out["deferred"] == 1 and out["errors"] == 0
    started = [i for i in ids if accounts.get(i)["archive_over_since"] is not None]
    assert len(started) == 1                                  # l'altro non ha tolleranza ne' stadio
    other = accounts.get(next(i for i in ids if i not in started))
    assert (other["archive_over_since"], other["archive_notice_stage"], other["archive_notice_ids"]) == (
        None, 0, None)
    out = archive_tolerance.sweep(now=T0 + 3600, force=True)  # al giro dopo tocca all'altro
    assert len(mails.over) == 2 and out["started"] == 1 and out["deferred"] == 0
    assert all(accounts.get(i)["archive_over_since"] is not None for i in ids)


def test_notice_cap_counts_failed_attempts_and_reminders(env, mails, monkeypatch):
    ids = _open_two(monkeypatch)
    archive_tolerance.sweep(now=T0 + 10, force=True)
    assert len(mails.over) == 2
    deadline = T0 + 10 + 15 * DAY
    monkeypatch.setattr(archive_tolerance, "MAX_NOTICES_PER_SWEEP", 1)
    mails.ok = False                                          # un tentativo fallito consuma comunque il tetto
    out = archive_tolerance.sweep(now=deadline - 3 * DAY, force=True)
    assert len(mails.remind) == 1 and out["reminded"] == 0 and out["errors"] == 1 and out["deferred"] == 1
    assert [accounts.get(i)["archive_notice_stage"] for i in ids] == [1, 1]
    mails.ok = True
    out = archive_tolerance.sweep(now=deadline - 3 * DAY + 3600, force=True)
    assert len(mails.remind) == 2 and out["reminded"] == 1 and out["deferred"] == 1
    out = archive_tolerance.sweep(now=deadline - 3 * DAY + 7200, force=True)
    assert len(mails.remind) == 3 and out["reminded"] == 1 and out["deferred"] == 0
    assert [accounts.get(i)["archive_notice_stage"] for i in ids] == [2, 2]


def test_notice_cap_rotates_so_failing_accounts_do_not_starve_the_rest(env, mails, monkeypatch):
    """I primi MAX_NOTICES_PER_SWEEP account (per id) hanno la posta che rifiuta: senza rotazione
    i loro tentativi falliti occuperebbero tutti i posti a ogni giro e l'ultimo non riceverebbe
    mai l'avviso."""
    _small_quota(monkeypatch)
    n = archive_tolerance.MAX_NOTICES_PER_SWEEP
    accts = []
    for i in range(n + 1):
        a = _login(f"u{i}@b.it"); _consent(a)
        _archived(a, f"j{i}", 150, at=T0)
        accts.append(a)
    last = max(accts, key=lambda a: a["id"])                  # il 21esimo nell'ordine del giro
    attempts = []

    def over(email, lang, **kw):
        attempts.append(email)
        return email == last["email"]                         # solo la sua posta funziona

    monkeypatch.setattr(email_service, "send_archive_over", over)
    out = archive_tolerance.sweep(now=T0 + 10, force=True)
    assert out["deferred"] == 1 and out["errors"] == n and out["started"] == 0
    assert len(attempts) == n and last["email"] not in attempts
    assert accounts.get(last["id"])["archive_over_since"] is None
    out = archive_tolerance.sweep(now=T0 + 3600, force=True)  # al giro dopo parte da dove si era fermato
    assert last["email"] in attempts[n:]
    assert out["started"] == 1 and out["deferred"] == 1 and out["errors"] == n - 1
    assert accounts.get(last["id"])["archive_over_since"] == T0 + 3600


def test_notice_cap_does_not_hold_back_evictions_without_email(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    due = _login("a@b.it"); _consent(due)
    _archived(due, "j_due", 150, at=T0)
    accounts.set_archive_tolerance(due["id"], T0 - 16 * DAY, 2, notice_ids=["job:j_due"])  # come annunciato
    for i, email in enumerate(("c@d.it", "e@f.it")):          # due da avvisare, uno solo ne ha il posto
        acct = _login(email); _consent(acct)
        _archived(acct, f"j_new{i}", 150, at=T0)
    monkeypatch.setattr(archive_tolerance, "MAX_NOTICES_PER_SWEEP", 1)
    out = archive_tolerance.sweep(now=T0, force=True)
    assert out["started"] == 1 and out["deferred"] == 1 and out["evicted"] == 1 and out["errors"] == 0
    assert len(mails.over) == 1 and _protected("j_due") == [False]


def test_unlisted_plan_needing_email_is_deferred_not_evicted(env, mails, monkeypatch):
    """A tetto raggiunto un riavvio per piano non annunciato salta il giro: niente sfratto neanche allora."""
    _small_quota(monkeypatch, 100)
    a = _login("a@b.it"); _consent(a)
    _archived(a, "j1", 150, at=T0)
    accounts.set_archive_tolerance(a["id"], T0, 1, notice_ids=["job:j0"])  # annunciato un altro libro, oggi il piano e' j1
    monkeypatch.setattr(archive_tolerance, "MAX_NOTICES_PER_SWEEP", 0)
    out = archive_tolerance.sweep(now=T0 + 20 * DAY, force=True)
    assert out["deferred"] == 1 and out["evicted"] == 0 and out["started"] == 0 and mails.over == []
    assert accounts.archive_protects("j1")
    monkeypatch.setattr(archive_tolerance, "MAX_NOTICES_PER_SWEEP", 20)
    out = archive_tolerance.sweep(now=T0 + 20 * DAY + 3600, force=True)
    assert out["started"] == 1 and out["evicted"] == 0 and accounts.archive_protects("j1")


# ------------------------------------------------------------ eviction parziale

def test_partial_eviction_keeps_the_first_removal(env, mails, monkeypatch):
    _small_quota(monkeypatch)
    a = _login("a@b.it"); _consent(a)
    k1 = _upload(a, "i1", 30, at=T0 + 1)
    k2 = _upload(a, "i2", 30, at=T0 + 2)
    _upload(a, "i3", 80, at=T0 + 3)                           # eccedenza 40: servono i1 e i2
    archive_tolerance.sweep(now=T0 + 10, force=True)
    deadline = T0 + 10 + 15 * DAY

    def flaky(key):
        if key == k2:
            raise RuntimeError("r2 down")
        env.delete(key)

    monkeypatch.setattr(storage_backend, "delete_object", flaky)
    out = archive_tolerance.sweep(now=deadline, force=True)
    assert out["evicted"] == 1 and out["errors"] == 1
    assert env.deleted == [k1] and _item_ids(a) == ["i2", "i3"]    # il primo resta tolto, il secondo c'e' ancora
    assert _state(a) == (T0 + 10, 1, ["item:i1", "item:i2"])
    monkeypatch.setattr(storage_backend, "delete_object", env.delete)
    out = archive_tolerance.sweep(now=deadline + 3600, force=True)  # 110 byte su 100: basta i2
    assert out["evicted"] == 1 and out["errors"] == 0 and out["cleared"] == 0
    assert env.deleted == [k1, k2] and _item_ids(a) == ["i3"]
    assert _state(a) == (None, 0, None)


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
