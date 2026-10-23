# test/test_subscription_vouchers.py
"""Voucher mensile degli abbonamenti: idempotente per pagamento, legato all'account."""
import pytest

import accounts
import db
import payment


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(payment, "_vouchers", {}, raising=False)
    monkeypatch.setattr(payment, "_save_vouchers", lambda: None)
    monkeypatch.setattr(payment, "_save_paid_jobs_done", lambda: None)


def _issue(key="paypal:S1", account_id="acc1", email="a@x.it", amount=5.0):
    return payment.issue_subscription_voucher(key=key, account_id=account_id, email=email,
                                              amount_eur=amount, days=30)


def test_subscription_voucher_idempotent_by_key(store):
    a, b = _issue(), _issue()
    assert a == b and a.startswith("SUB-")
    v = payment.voucher_info(a)
    assert (v["kind"], v["account_id"], v["key"], v["amount_eur"], v["remaining_eur"]) == \
        ("subscription", "acc1", "paypal:S1", 5.0, 5.0)
    assert 29.9 * 86400 < v["expires_at"] - v["created_at"] <= 30 * 86400
    assert payment.voucher_covers(v, "voxcpm") and payment.voucher_covers(v, "translate")
    assert not payment.voucher_covers(v, "flash38") and not payment.voucher_covers(v, "speechify")
    assert _issue(key="paypal:S2") != a


def test_subscription_voucher_needs_key_and_account(store):
    with pytest.raises(ValueError):
        _issue(key="")
    with pytest.raises(ValueError):
        _issue(account_id=None)


def test_subscription_voucher_owner_only(store):
    code = _issue(key="paypal:S2", amount=10.0)
    assert payment.best_voucher_for("other@x.it", "voxcpm", 1.0, account_id="acc1")["code"] == code
    assert payment.best_voucher_for("a@x.it", "voxcpm", 1.0, account_id="acc2") is None
    assert payment.best_voucher_for("a@x.it", "voxcpm", 1.0) is None
    with pytest.raises(ValueError, match="another account"):
        payment._voucher_consume(code, 1.0, job_id="j1", service="voxcpm", account_id="acc2")
    with pytest.raises(ValueError, match="another account"):
        payment.consume_payment_token(code, 1.0, "j2", purpose="voice_clone",
                                      service="voice_clone")
    assert payment.voucher_info(code)["remaining_eur"] == 10.0
    assert payment._voucher_consume(code, 1.0, job_id="j3", service="voxcpm", account_id="acc1") == 9.0
    assert payment.consume_payment_token(code, 2.0, "j4", purpose="voice_clone",
                                         service="voice_clone", account_id="acc1") == "voucher"


def test_vouchers_without_account_unchanged(store):
    code, _ = payment._create_voucher("a@x.it", 3.0, kind="promo", apply_bonus=False,
                                      created_by="admin")
    assert "account_id" not in payment.voucher_info(code)
    assert payment.voucher_usable_by(payment.voucher_info(code), None)
    assert payment.best_voucher_for("a@x.it", "voxcpm", 1.0, account_id="acc9")["code"] == code
    assert payment._voucher_consume(code, 1.0, job_id="j1", service="voxcpm") == 2.0


def test_best_voucher_prefers_the_one_expiring_first(store):
    late = _issue(key="paypal:L", amount=10.0)
    payment._vouchers[late]["expires_at"] += 86400
    soon = _issue(key="paypal:E", amount=10.0)
    assert payment.best_voucher_for("a@x.it", "voxcpm", 1.0, account_id="acc1")["code"] == soon


# ------------------------------------------------------------ route

@pytest.fixture
def client(store, tmp_path, monkeypatch):
    import audiobook_app
    import routes_account
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_voucher_rl_check", lambda ip, email: (True, 0, None))
    monkeypatch.setattr(audiobook_app, "_voucher_rl_record_result", lambda email, ok: None)
    holder = {"acct": None}
    monkeypatch.setattr(routes_account, "_current_account", lambda: holder["acct"])
    yield audiobook_app.app.test_client(), holder
    db.close()


def test_voucher_validate_rejects_other_account(client):
    c, holder = client
    code = _issue(key="paypal:V1", account_id="acc1", email="a@x.it")
    body = {"code": code, "email": "a@x.it", "purpose": "voice_clone", "amount_eur": 1}
    r = c.post("/api/voucher_validate", json=body)                  # anonimo
    assert r.status_code == 400 and r.get_json()["reason"] == "account_only"
    holder["acct"] = {"id": "acc2", "email": "a@x.it"}
    assert c.post("/api/voucher_validate", json=body).get_json()["reason"] == "account_only"
    holder["acct"] = {"id": "acc1", "email": "a@x.it"}
    r = c.post("/api/voucher_validate", json=body)
    assert r.status_code == 200 and r.get_json()["valid"] is True
    assert payment.voucher_info(code)["remaining_eur"] == 5.0          # validare non consuma


def test_voucher_suggest_finds_account_voucher(client):
    c, holder = client
    code = _issue(key="paypal:V2", account_id="acc1", email="a@x.it")
    holder["acct"] = {"id": "acc1", "email": "a@x.it"}
    r = c.get("/api/account/voucher_suggest?purpose=voice_clone&amount_eur=1")
    assert r.status_code == 200 and r.get_json()["voucher"]["code"] == code
    holder["acct"] = {"id": "acc2", "email": "a@x.it"}
    assert c.get("/api/account/voucher_suggest?purpose=voice_clone&amount_eur=1"
                 ).get_json()["voucher"] is None


def test_current_account_id_outside_request_is_none():
    import routes_account
    assert routes_account.current_account_id() is None
