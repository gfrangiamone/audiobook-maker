# test/test_accounts.py
"""accounts.py: codici magic link, verifica, sessioni."""
import pytest

import accounts
import db


@pytest.fixture
def acct_env(tmp_path, monkeypatch):
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    # accounts.configure() muta stato di modulo: isolare ogni test dai fn
    # iniettati (payments_path, voice_clone hooks) dai test precedenti.
    monkeypatch.setattr(accounts, "_payments_path", None)
    monkeypatch.setattr(accounts, "_voice_ids_for_email", None)
    monkeypatch.setattr(accounts, "_link_voice", None)
    monkeypatch.setattr(accounts, "_unlink_voice", None)
    yield tmp_path
    db.close()


T0 = 1_800_000_000


def test_request_code_returns_token_and_six_digits(acct_env):
    out = accounts.request_code("Mario@Example.com", "login", "it", now=T0)
    assert out is not None
    token, code = out
    assert len(token) >= 40
    assert len(code) == 6 and code.isdigit()
    row = db.conn().execute("SELECT * FROM auth_codes").fetchone()
    assert row["email"] == "mario@example.com"
    assert row["purpose"] == "login"
    assert row["lang"] == "it"
    assert row["expires_at"] == T0 + accounts.CODE_TTL_MIN * 60
    assert token not in row["token_hash"]
    assert code not in row["code_hash"]


def test_request_code_per_email_rate_limit(acct_env):
    for i in range(3):
        assert accounts.request_code("a@b.it", now=T0 + i) is not None
    assert accounts.request_code("a@b.it", now=T0 + 3) is None
    assert accounts.request_code("other@b.it", now=T0 + 3) is not None
    assert accounts.request_code("a@b.it", now=T0 + 601) is not None


def test_request_code_rejects_unknown_purpose(acct_env):
    with pytest.raises(ValueError):
        accounts.request_code("a@b.it", purpose="reset")


def test_verify_by_token_creates_account_and_consumes(acct_env):
    token, _ = accounts.request_code("a@b.it", "login", "fr", now=T0)
    status, acct = accounts.verify(token=token, now=T0 + 5)
    assert status == "ok"
    assert acct["email"] == "a@b.it"
    assert acct["lang"] == "fr"
    assert acct["plan"] == "free"
    assert acct["last_login_at"] == T0 + 5
    status2, acct2 = accounts.verify(token=token, now=T0 + 6)
    assert (status2, acct2) == ("none", None)


def test_verify_by_code_ok_and_wrong_then_locked(acct_env):
    _, code = accounts.request_code("a@b.it", now=T0)
    for _ in range(5):
        status, acct = accounts.verify(email="A@B.IT", code="000000" if code != "000000" else "111111", now=T0 + 1)
        assert (status, acct) == ("wrong", None)
    status, acct = accounts.verify(email="a@b.it", code=code, now=T0 + 2)
    assert (status, acct) == ("locked", None)


def test_verify_by_code_success(acct_env):
    _, code = accounts.request_code("a@b.it", now=T0)
    status, acct = accounts.verify(email="a@b.it", code=code, now=T0 + 1)
    assert status == "ok"
    assert acct["email"] == "a@b.it"


def test_verify_expired(acct_env):
    token, code = accounts.request_code("a@b.it", now=T0)
    assert accounts.verify(token=token, now=T0 + accounts.CODE_TTL_MIN * 60 + 1) == ("expired", None)
    assert accounts.verify(email="a@b.it", code=code, now=T0 + accounts.CODE_TTL_MIN * 60 + 1) == ("expired", None)


def test_verify_none_for_unknown(acct_env):
    assert accounts.verify(token="nope") == ("none", None)
    assert accounts.verify(email="x@y.it", code="123456") == ("none", None)


def test_verify_uses_latest_code_for_email(acct_env):
    _, code1 = accounts.request_code("a@b.it", now=T0)
    _, code2 = accounts.request_code("a@b.it", now=T0 + 1)
    assert accounts.verify(email="a@b.it", code=code2, now=T0 + 2)[0] == "ok"
    assert accounts.verify(email="a@b.it", code=code1, now=T0 + 3)[0] in ("none", "wrong")


def test_verify_login_existing_account_updates_lang_and_last_login(acct_env):
    token, _ = accounts.request_code("a@b.it", "login", "it", now=T0)
    _, first = accounts.verify(token=token, now=T0 + 1)
    token2, _ = accounts.request_code("a@b.it", "login", "de", now=T0 + 10)
    status, again = accounts.verify(token=token2, now=T0 + 11)
    assert status == "ok"
    assert again["id"] == first["id"]
    assert again["lang"] == "de"
    assert again["last_login_at"] == T0 + 11
    assert db.conn().execute("SELECT COUNT(*) FROM accounts").fetchone()[0] == 1


def test_verify_delete_purpose_requires_account(acct_env):
    token, _ = accounts.request_code("ghost@b.it", "delete", now=T0)
    assert accounts.verify(token=token, purpose="delete", now=T0 + 1) == ("none", None)
    tl, _ = accounts.request_code("a@b.it", "login", now=T0)
    accounts.verify(token=tl, now=T0 + 1)
    td, _ = accounts.request_code("a@b.it", "delete", now=T0 + 2)
    status, acct = accounts.verify(token=td, purpose="delete", now=T0 + 3)
    assert status == "ok" and acct["email"] == "a@b.it"


def test_verify_purpose_must_match_token(acct_env):
    tl, _ = accounts.request_code("a@b.it", "login", now=T0)
    assert accounts.verify(token=tl, purpose="delete", now=T0 + 1) == ("none", None)


def test_peek_reports_state_without_consuming(acct_env):
    token, code = accounts.request_code("a@b.it", "login", now=T0)
    state, info = accounts.peek(token, now=T0 + 1)
    assert state == "ok"
    assert info["email"] == "a@b.it"
    state, info = accounts.peek(token, now=T0 + 2)  # ripetere il peek non consuma
    assert (state, info["email"]) == ("ok", "a@b.it")
    assert accounts.peek(token, purpose="delete", now=T0 + 2) == ("none", None)
    state, info = accounts.peek("garbage", now=T0 + 2)
    assert state == "none"
    assert info is None
    state, info = accounts.peek(token, now=T0 + accounts.CODE_TTL_MIN * 60 + 1)
    assert state == "expired"
    assert info["email"] == "a@b.it"
    for _ in range(5):
        bad = "000000" if code != "000000" else "111111"
        accounts.verify(email="a@b.it", code=bad, now=T0 + 3)
    state, info = accounts.peek(token, now=T0 + 4)
    assert state == "locked"
    assert info["email"] == "a@b.it"


def _login(email, now=T0):
    token, _ = accounts.request_code(email, "login", now=now)
    return accounts.verify(token=token, now=now + 1)[1]


def test_session_open_resolve_revoke(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], device_name="Chrome", ip_hash="abcd", now=T0)
    assert len(tok) >= 40
    stored = db.conn().execute("SELECT id, device_name FROM sessions").fetchone()
    assert stored["id"] != tok and stored["device_name"] == "Chrome"
    res = accounts.resolve_session(tok, now=T0 + 10)
    assert res["email"] == "a@b.it" and res["session_id"] == stored["id"]
    assert accounts.sessions_count(acct["id"], now=T0 + 10) == 1
    assert accounts.revoke_session(tok) is True
    assert accounts.resolve_session(tok, now=T0 + 11) is None
    assert accounts.revoke_session(tok) is False
    assert accounts.resolve_session("", now=T0) is None
    assert accounts.resolve_session("garbage", now=T0) is None


def test_session_expires_after_session_days(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], now=T0)
    assert accounts.resolve_session(tok, now=T0 + 100) is not None   # under one hour: no renewal
    assert accounts.resolve_session(tok, now=T0 + accounts.SESSION_DAYS * 86400 + 1) is None


def test_session_read_in_last_hour_still_renews(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], now=T0)
    t_late = T0 + accounts.SESSION_DAYS * 86400 - 1
    assert accounts.resolve_session(tok, now=t_late) is not None
    row = db.conn().execute("SELECT expires_at FROM sessions").fetchone()
    assert row["expires_at"] == t_late + accounts.SESSION_DAYS * 86400


def test_session_rolling_renewal_only_after_one_hour(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], now=T0)
    accounts.resolve_session(tok, now=T0 + 100)
    row = db.conn().execute("SELECT last_seen_at, expires_at FROM sessions").fetchone()
    assert row["last_seen_at"] == T0
    accounts.resolve_session(tok, now=T0 + 3601)
    row = db.conn().execute("SELECT last_seen_at, expires_at FROM sessions").fetchone()
    assert row["last_seen_at"] == T0 + 3601
    assert row["expires_at"] == T0 + 3601 + accounts.SESSION_DAYS * 86400


def test_list_sessions_and_revoke_by_id(acct_env):
    acct = _login("a@b.it")
    other = _login("c@d.it")
    t1 = accounts.open_session(acct["id"], device_name="Chrome · Windows", now=T0)
    t2 = accounts.open_session(acct["id"], device_name="", now=T0 + 10)
    t3 = accounts.open_session(other["id"], device_name="Safari · iPhone", now=T0)
    accounts.resolve_session(t1, now=T0 + 7200)   # rinnovo: t1 diventa la piu' recente
    rows = accounts.list_sessions(acct["id"], now=T0 + 7200)
    assert [r["device_name"] for r in rows] == ["Chrome · Windows", ""]
    assert rows[0]["created_at"] == T0 and rows[0]["last_seen_at"] == T0 + 7200
    assert rows[0]["id"] == accounts.resolve_session(t1, now=T0 + 7200)["session_id"]
    assert all(len(r["id"]) == 64 for r in rows)   # hash, mai il token
    assert t1 not in str(rows) and t2 not in str(rows)
    # id di un altro account: nessuna revoca
    sid3 = accounts.resolve_session(t3, now=T0)["session_id"]
    assert accounts.revoke_session_id(acct["id"], sid3) is False
    assert accounts.resolve_session(t3, now=T0 + 1) is not None
    assert accounts.revoke_session_id(acct["id"], rows[1]["id"]) is True
    assert accounts.resolve_session(t2, now=T0 + 20) is None
    assert accounts.revoke_session_id(acct["id"], rows[1]["id"]) is False
    assert accounts.revoke_session_id(acct["id"], "") is False
    assert len(accounts.list_sessions(acct["id"], now=T0 + 7200)) == 1
    # scadute e revocate fuori dalla lista
    assert accounts.list_sessions(acct["id"], now=T0 + accounts.SESSION_DAYS * 86400 * 2) == []


def test_revoke_all(acct_env):
    acct = _login("a@b.it")
    t1 = accounts.open_session(acct["id"], now=T0)
    t2 = accounts.open_session(acct["id"], now=T0)
    assert accounts.sessions_count(acct["id"], now=T0) == 2
    assert accounts.revoke_all(acct["id"]) == 2
    assert accounts.resolve_session(t1, now=T0) is None
    assert accounts.resolve_session(t2, now=T0) is None
    assert accounts.sessions_count(acct["id"], now=T0) == 0


def test_get_and_account_for_email(acct_env):
    acct = _login("a@b.it")
    assert accounts.get(acct["id"])["email"] == "a@b.it"
    assert accounts.account_for_email("A@B.it")["id"] == acct["id"]
    assert accounts.get("missing") is None
    assert accounts.account_for_email("no@b.it") is None


def test_enabled_requires_flag_and_db(acct_env, monkeypatch):
    assert accounts.enabled() is True
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert accounts.enabled() is False
    monkeypatch.setattr(accounts, "ENABLE", True)
    db.close()
    assert accounts.enabled() is False


def test_email_hash_normalizes(acct_env):
    assert accounts.email_hash(" A@B.it ") == accounts.email_hash("a@b.it")
    assert len(accounts.email_hash("a@b.it")) == 64


# --- appendere in fondo a test/test_accounts.py ---
import json


def test_record_job_upsert_and_list(acct_env):
    acct = _login("a@b.it")
    accounts.record_job(acct["id"], "j1", kind="generate", book_title="Libro", output_format="m4b",
                        voice="it-IT-ElsaNeural", lang="it", created_at=T0)
    accounts.record_job(acct["id"], "j2", kind="translate", book_title="Book", created_at=T0 + 10)
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 2
    assert [r["job_id"] for r in rows] == ["j2", "j1"]
    assert rows[1]["status"] == "running" and rows[1]["source"] == "forced"
    accounts.record_job(acct["id"], "j1", kind="generate", book_title="Libro 2", paid_eur=1.5,
                        status="running", created_at=T0)
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 2
    j1 = [r for r in rows if r["job_id"] == "j1"][0]
    assert j1["book_title"] == "Libro 2" and j1["paid_eur"] == 1.5
    assert j1["voice"] == "it-IT-ElsaNeural"  # campo vuoto non sovrascrive


def test_list_jobs_pagination(acct_env):
    acct = _login("a@b.it")
    for i in range(7):
        accounts.record_job(acct["id"], f"j{i}", kind="generate", created_at=T0 + i)
    rows, total = accounts.list_jobs(acct["id"], page=2, per_page=3)
    assert total == 7
    assert [r["job_id"] for r in rows] == ["j3", "j2", "j1"]
    rows, _ = accounts.list_jobs(acct["id"], page=99, per_page=3)
    assert rows == []


def test_update_status_and_token(acct_env):
    acct = _login("a@b.it")
    accounts.record_job(acct["id"], "j1", kind="generate", created_at=T0)
    assert accounts.update_status("j1", "canceled") is True
    assert accounts.list_jobs(acct["id"])[0][0]["status"] == "cancelled"
    assert accounts.update_status("j1", "done", download_token="tok123") is True
    row = accounts.list_jobs(acct["id"])[0][0]
    assert row["status"] == "done" and row["download_token"] == "tok123"
    assert accounts.update_status("j1", "weird") is False
    assert accounts.update_status("missing", "done") is False
    assert accounts.set_download_token("j1", "tok456") is True
    assert accounts.list_jobs(acct["id"])[0][0]["download_token"] == "tok456"
    assert accounts.set_download_token("missing", "x") is False


def test_attach_if_known(acct_env):
    assert accounts.attach_if_known("j1", "nobody@b.it", kind="generate") is False
    acct = _login("a@b.it")
    assert accounts.attach_if_known("j1", "A@B.it", kind="generate", book_title="T", paid_eur=2.0,
                                    created_at=T0) is True
    row = accounts.list_jobs(acct["id"])[0][0]
    assert row["source"] == "payments" and row["paid_eur"] == 2.0 and row["status"] == "running"
    accounts.record_job(acct["id"], "j2", kind="generate", book_title="X", created_at=T0)
    accounts.update_status("j2", "done")
    assert accounts.attach_if_known("j2", "a@b.it", kind="generate", paid_eur=3.0) is True
    j2 = [r for r in accounts.list_jobs(acct["id"])[0] if r["job_id"] == "j2"][0]
    assert j2["paid_eur"] == 3.0 and j2["status"] == "done" and j2["source"] == "forced"
    assert j2["book_title"] == "X"


def test_adopt_history_from_payments_and_voices(acct_env, tmp_path, monkeypatch):
    pays = {
        "O1": {"amount_eur": 2.5, "email": "a@b.it", "job_id": "old1", "captured_at": T0 - 100, "used": True},
        "O2": {"amount_eur": 1.0, "email": "A@B.IT", "job_id": "old2", "captured_at": T0 - 50, "used": False},
        "O3": {"amount_eur": 9.0, "email": "other@b.it", "job_id": "x", "captured_at": T0 - 10},
        "O4": {"amount_eur": 1.0, "email": "a@b.it", "job_id": "", "captured_at": T0 - 5},
        "O5": {"amount_eur": 1.0, "email": "a@b.it", "job_id": "nocap", "captured_at": 0},
    }
    p = tmp_path / "_payments.json"
    p.write_text(json.dumps(pays), encoding="utf-8")
    linked = []
    accounts.configure(
        payments_path=p,
        voice_clone_ids_for_email_fn=lambda email: ["vc_1", "vc_2"] if email == "a@b.it" else [],
        link_voice_fn=lambda cid, aid: linked.append((cid, aid)) or True,
    )
    acct = _login("a@b.it")
    rows, total = accounts.list_jobs(acct["id"])
    assert total == 2
    assert [r["job_id"] for r in rows] == ["old2", "old1"]
    assert rows[0]["source"] == "payments" and rows[0]["status"] == "done"
    assert rows[0]["created_at"] == T0 - 50 and rows[1]["paid_eur"] == 2.5
    assert linked == [("vc_1", acct["id"]), ("vc_2", acct["id"])]
    # idempotente
    assert accounts.adopt_history(acct) == (0, 2)
    assert accounts.list_jobs(acct["id"])[1] == 2


def test_adopt_history_survives_missing_or_broken_payments(acct_env, tmp_path):
    accounts.configure(payments_path=tmp_path / "missing.json")
    acct = _login("a@b.it")
    assert accounts.adopt_history(acct) == (0, 0)
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    accounts.configure(payments_path=bad)
    assert accounts.adopt_history(acct) == (0, 0)


def test_delete_account(acct_env):
    acct = _login("a@b.it")
    tok = accounts.open_session(acct["id"], now=T0)
    accounts.record_job(acct["id"], "j1", kind="generate", created_at=T0)
    accounts.request_code("a@b.it", "delete", now=T0 + 1)
    assert accounts.delete_account(acct["id"], now=T0 + 2) is True
    assert accounts.resolve_session(tok, now=T0 + 3) is None
    assert accounts.account_for_email("a@b.it") is None
    assert accounts.list_jobs(acct["id"]) == ([], 0)
    assert db.conn().execute("SELECT COUNT(*) FROM auth_codes WHERE email='a@b.it'").fetchone()[0] == 0
    gone = accounts.get(acct["id"])
    assert gone["deleted_at"] == T0 + 2 and gone["email"].startswith("deleted:")
    assert accounts.delete_account(acct["id"]) is False
    # la stessa email puo' registrarsi di nuovo e cancellarsi di nuovo
    again = _login("a@b.it", now=T0 + 100)
    assert again["id"] != acct["id"]
    assert accounts.delete_account(again["id"], now=T0 + 200) is True


def test_delete_account_unlinks_voice_clones(acct_env, monkeypatch):
    """Spec: la cancellazione toglie `account_id` dalle voci campionate.

    La voce sopravvive (ha un link di gestione suo), ma non deve restare
    agganciata a un account che non esiste piu'."""
    unlinked = []
    accounts.configure(
        voice_clone_ids_for_email_fn=lambda e: ["vc_1", "vc_2"] if e == "a@b.it" else [],
        unlink_voice_fn=lambda cid: unlinked.append(cid) or True,
    )
    acct = _login("a@b.it")
    other = _login("z@b.it")
    assert accounts.delete_account(acct["id"], now=T0 + 2) is True
    assert unlinked == ["vc_1", "vc_2"]
    # nessuna voce dell'altro account viene toccata
    unlinked.clear()
    assert accounts.delete_account(other["id"], now=T0 + 3) is True
    assert unlinked == []


def test_delete_account_survives_voice_registry_errors(acct_env):
    """Il registro delle voci e' un file JSON: un suo errore non deve
    impedire la cancellazione dell'account (gia' committata)."""
    def _boom(cid):
        raise RuntimeError("registro non scrivibile")

    accounts.configure(voice_clone_ids_for_email_fn=lambda e: ["vc_1"],
                       unlink_voice_fn=_boom)
    acct = _login("a@b.it")
    assert accounts.delete_account(acct["id"], now=T0 + 2) is True
    assert accounts.account_for_email("a@b.it") is None


def test_purge_expired(acct_env):
    free = _login("free@b.it")
    paid = _login("paid@b.it")
    lapsed = _login("lapsed@b.it")
    db.conn().execute("UPDATE accounts SET plan='paid', plan_until=NULL WHERE id=?", (paid["id"],))
    db.conn().execute("UPDATE accounts SET plan='paid', plan_until=? WHERE id=?",
                      (T0 - (accounts.GRACE_DAYS + 1) * 86400, lapsed["id"]))
    old = T0 - accounts.HISTORY_MONTHS * accounts.MONTH_SEC - 10
    for a in (free, paid, lapsed):
        accounts.record_job(a["id"], "old_" + a["id"], kind="generate", created_at=old)
        accounts.record_job(a["id"], "new_" + a["id"], kind="generate", created_at=T0 - 10)
    accounts.request_code("free@b.it", now=T0 - 2 * 86400)   # scaduto da >24h
    accounts.request_code("free@b.it", now=T0 - 60)           # ancora vivo
    tok_old = accounts.open_session(free["id"], now=T0 - 200 * 86400)   # scaduta da >30 giorni
    tok_live = accounts.open_session(free["id"], now=T0)
    out = accounts.purge_expired(now=T0)
    assert out == {"jobs": 2, "codes": 1, "sessions": 1}
    assert accounts.list_jobs(free["id"])[1] == 1
    assert accounts.list_jobs(lapsed["id"])[1] == 1
    assert accounts.list_jobs(paid["id"])[1] == 2
    assert accounts.resolve_session(tok_live, now=T0) is not None
    assert db.conn().execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
    assert tok_old  # solo per chiarezza: la riga e' stata eliminata


def test_history_functions_noop_when_disabled(acct_env, monkeypatch):
    acct = _login("a@b.it")
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert accounts.record_job(acct["id"], "j1", kind="generate", created_at=T0) is False
    assert accounts.list_jobs(acct["id"]) == ([], 0)
    assert accounts.adopt_history(acct) == (0, 0)
    assert accounts.delete_account(acct["id"]) is False
    assert accounts.purge_expired() == {"jobs": 0, "codes": 0, "sessions": 0}
    monkeypatch.setattr(accounts, "ENABLE", True)
    assert accounts.list_jobs(acct["id"]) == ([], 0)
