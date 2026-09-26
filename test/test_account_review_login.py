# test/test_account_review_login.py
"""Account demo per i revisori degli store: codice di login fisso, nessuna
email; tutti gli altri account e la cancellazione restano invariati."""
import pytest

import accounts
import audiobook_app
import db
import email_service

REVIEW = "review@example.com"
CODE = "246810"


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(accounts, "REVIEW_EMAIL", REVIEW)
    monkeypatch.setattr(accounts, "REVIEW_CODE", CODE)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    sent = []
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: sent.append((email, kw["purpose"])))
    yield sent
    db.close()


@pytest.mark.parametrize("email,code,purpose,expected", [
    (REVIEW, CODE, "login", True),
    (" Review@Example.com ", CODE, "login", True),
    (REVIEW, CODE, "delete", False),
    ("other@example.com", CODE, "login", False),
    (REVIEW, "", "login", False),
    (REVIEW, "12345", "login", False),
    (REVIEW, "abcdef", "login", False),
])
def test_is_review_login(monkeypatch, email, code, purpose, expected):
    monkeypatch.setattr(accounts, "REVIEW_EMAIL", REVIEW)
    monkeypatch.setattr(accounts, "REVIEW_CODE", code)
    assert accounts.is_review_login(email, purpose) is expected


def test_disabled_without_email(monkeypatch):
    monkeypatch.setattr(accounts, "REVIEW_EMAIL", "")
    monkeypatch.setattr(accounts, "REVIEW_CODE", CODE)
    assert accounts.is_review_login("", "login") is False


def test_review_code_is_fixed_and_verifies(env):
    assert accounts.request_code(REVIEW, "login")[1] == CODE
    state, acct = accounts.verify(email=REVIEW, code=CODE)
    assert state == "ok" and acct["email"] == REVIEW
    # Riusabile: ogni nuova richiesta riemette lo stesso codice.
    assert accounts.request_code(REVIEW, "login")[1] == CODE
    assert accounts.verify(email=REVIEW, code=CODE)[0] == "ok"


def test_review_account_keeps_attempt_lock(env):
    accounts.request_code(REVIEW, "login")
    for _ in range(accounts.CODE_MAX_ATTEMPTS):
        assert accounts.verify(email=REVIEW, code="000000")[0] == "wrong"
    assert accounts.verify(email=REVIEW, code=CODE)[0] == "locked"


def test_delete_code_for_review_account_stays_random(env):
    codes = {accounts.request_code(REVIEW, "delete")[1] for _ in range(3)}
    assert codes != {CODE}


def test_endpoint_sends_no_email_for_review_account(env):
    sent = env
    client = audiobook_app.app.test_client()
    assert client.post("/api/auth/request", json={"email": REVIEW}).status_code == 200
    assert sent == []
    r = client.post("/api/auth/verify", json={"email": REVIEW, "code": CODE})
    assert r.status_code == 200 and r.get_json()["email"] == REVIEW
    client.post("/api/auth/request", json={"email": "someone@example.com"})
    assert sent == [("someone@example.com", "login")]
