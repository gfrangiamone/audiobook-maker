# test/test_subscriptions.py
"""Abbonamenti mensili (fase 2a): schema, stati, pagamenti, voucher, disdetta."""
import sqlite3
from types import SimpleNamespace

import pytest

import accounts
import db
import payment
import subscriptions


T0 = 1_800_000_000
DAY = 86400


@pytest.fixture
def sub_env(tmp_path, monkeypatch):
    db.init(tmp_path)
    accounts.init_schema()
    subscriptions.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(accounts, "_payments_path", None)
    monkeypatch.setattr(accounts, "_voice_ids_for_email", None)
    monkeypatch.setattr(accounts, "_link_voice", None)
    monkeypatch.setattr(accounts, "_unlink_voice", None)
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setenv("ABM_SUBSCRIPTIONS_ENABLE", "1")
    accounts._archive_cache_clear()

    def login(email, now=T0):
        token, code = accounts.request_code(email, "login", "it", now=now)
        status, acct = accounts.verify(token=token, code=code, purpose="login", now=now)
        assert status == "ok"
        return acct

    yield SimpleNamespace(login=login, tmp=tmp_path)
    accounts._archive_cache_clear()
    db.close()


# ------------------------------------------------------------------ schema

def _insert(c, **row):
    c.execute(f"INSERT INTO subscriptions({','.join(row)}) VALUES ({','.join('?' * len(row))})",
              tuple(row.values()))


def _row(account_id, sid, ext, status, plan="sub_5"):
    return dict(id=sid, account_id=account_id, provider="paypal", external_id=ext, plan=plan,
                status=status, created_at=T0, updated_at=T0, terms_version="v",
                withdrawal_waived_at=T0)


def test_schema_idempotent_and_one_live_per_account(sub_env):
    subscriptions.init_schema()                       # seconda volta: nessun effetto
    acct = sub_env.login("a@x.it")
    with db.tx() as c:
        _insert(c, **_row(acct["id"], "s1", "I-1", "active"))
        _insert(c, **_row(acct["id"], "s0", "I-0", "ended"))       # le righe chiuse non contano
        _insert(c, **_row(acct["id"], "sp", None, "pending"))      # neanche i checkout aperti
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as c:
            _insert(c, **_row(acct["id"], "s2", "I-2", "activating", plan="sub_10"))


def test_external_id_unique_per_provider(sub_env):
    a, b = sub_env.login("a@x.it"), sub_env.login("b@x.it")
    with db.tx() as c:
        _insert(c, **_row(a["id"], "s1", "I-1", "active"))
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as c:
            _insert(c, **_row(b["id"], "s2", "I-1", "pending"))
