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
    assert accounts.resolve_session(tok, now=T0 + accounts.SESSION_DAYS * 86400 - 1) is not None
    assert accounts.resolve_session(tok, now=T0 + accounts.SESSION_DAYS * 86400 + 1) is None


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
