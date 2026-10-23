# test/test_subscriptions.py
"""Abbonamenti mensili (fase 2a): schema, stati, pagamenti, voucher, disdetta."""
import dataclasses
import sqlite3
import time
from types import SimpleNamespace

import pytest

import accounts
import billing_paypal
import db
import email_service
import payment
import subscriptions


# I voucher nascono con l'ora vera (`time.time()`): il tempo dei test parte da adesso.
T0 = int(time.time()) // 3600 * 3600
DAY = 86400


class FakeProvider:
    """Fornitore finto con lo stato remoto in memoria."""

    def __init__(self):
        self.remote, self.payments, self.calls = {}, {}, []
        self.fail_cancel = self.fail_fetch = self.fail_refund = False

    def available(self):
        return True

    def create_checkout(self, *, sub_id, plan, email, lang, return_url, cancel_url):
        ext = "I-" + sub_id[-8:].upper().replace("_", "X").replace("-", "Y")
        self.remote[ext] = billing_paypal.Remote(
            external_id=ext, status="APPROVAL_PENDING", plan=plan, custom_id=sub_id,
            next_billing_at=None, last_payment_at=None, last_payment_eur=None, failed_payments=0)
        self.calls.append(("create", ext, return_url))
        return ext, "https://pp.test/approve/" + ext

    def fetch(self, ext):
        if self.fail_fetch:
            raise billing_paypal.ProviderError("down", transient=True)
        return self.remote[ext]

    def list_payments(self, ext, since, until):
        return [p for p in self.payments.get(ext, []) if since <= p.paid_at <= until]

    def cancel(self, ext, reason):
        self.calls.append(("cancel", ext, reason))
        if self.fail_cancel:
            raise billing_paypal.ProviderError("down", transient=True)
        self.set(ext, status="CANCELLED")
        return True

    def refund_payment(self, payment_id, amount_eur):
        self.calls.append(("refund", payment_id, amount_eur))
        if self.fail_refund:
            raise billing_paypal.ProviderError("down", transient=True)
        return True

    # aiuti dei test
    def set(self, ext, **fields):
        self.remote[ext] = dataclasses.replace(self.remote[ext], **fields)

    def pay(self, ext, pid, at, amount=5.0, next_at=None, webhook=True):
        p = billing_paypal.Payment(payment_id=pid, amount_eur=amount, paid_at=at,
                                   state="completed", currency="EUR")
        self.payments.setdefault(ext, []).append(p)
        self.set(ext, status="ACTIVE", last_payment_at=at, last_payment_eur=amount,
                 next_billing_at=next_at or subscriptions._add_month(at), failed_payments=0)
        return billing_paypal.Event(event_id="WH-" + pid, type="renewed", external_id=ext,
                                    payment=p, raw_type="PAYMENT.SALE.COMPLETED")

    def refresh_event(self, ext, eid):
        return billing_paypal.Event(event_id=eid, type="refresh", external_id=ext, payment=None,
                                    raw_type="BILLING.SUBSCRIPTION.UPDATED")


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
    fake = FakeProvider()
    monkeypatch.setitem(subscriptions.PROVIDERS, "paypal", fake)
    monkeypatch.setitem(subscriptions._sweep_state, "at", 0)
    mails, alerts = [], []
    monkeypatch.setattr(email_service, "send_subscription_active",
                        lambda email, lang, **kw: mails.append(("active", email)), raising=False)
    monkeypatch.setattr(email_service, "send_subscription_cancelled",
                        lambda email, lang, **kw: mails.append(("cancelled", email)), raising=False)
    monkeypatch.setattr(email_service, "admin_notify_subscription",
                        lambda kind, details: alerts.append(kind), raising=False)
    accounts._archive_cache_clear()

    def login(email, now=T0):
        token, code = accounts.request_code(email, "login", "it", now=now)
        status, acct = accounts.verify(token=token, code=code, purpose="login", now=now)
        assert status == "ok"
        return acct

    yield SimpleNamespace(login=login, tmp=tmp_path, fake=fake, mails=mails, alerts=alerts)
    accounts._archive_cache_clear()
    db.close()


def _subscribe(env, email, plan="sub_5", now=T0):
    acct = env.login(email, now=now)
    st, url = subscriptions.start_checkout(acct, plan, accepted_terms=True, waived_withdrawal=True,
                                           return_url="https://h/r", cancel_url="https://h/c",
                                           now=now)
    assert st == "ok"
    return acct, url.rsplit("/", 1)[1]


def _sub_of(ext):
    with db.tx() as c:
        return dict(c.execute("SELECT * FROM subscriptions WHERE external_id=?", (ext,)).fetchone())


def _vouchers_of(acct):
    return [v for _, v in payment.iter_vouchers() if v.get("account_id") == acct["id"]]


def _paid(env, email, plan="sub_5", amount=5.0):
    """Abbonamento attivo con il primo pagamento a T0 + 60."""
    acct, ext = _subscribe(env, email, plan)
    ev = env.fake.pay(ext, "SALE" + ext[2:], T0 + 60, amount=amount)
    assert subscriptions.handle_event("paypal", ev, now=T0 + 61) == "issued"
    return acct, ext


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


# ------------------------------------------------------------------ checkout

def test_checkout_reuses_link_and_abandons_other_plan(sub_env):
    acct, ext = _subscribe(sub_env, "a@x.it")
    assert sub_env.fake.calls[0][2].startswith("https://h/r?sid=sub_")
    st, url = subscriptions.start_checkout(acct, "sub_5", accepted_terms=True, waived_withdrawal=True,
                                           return_url="https://h/r", cancel_url="https://h/c",
                                           now=T0 + 10)
    assert (st, url.rsplit("/", 1)[1]) == ("ok", ext)                   # stesso link, nessun create
    assert len(sub_env.fake.calls) == 1
    st, url = subscriptions.start_checkout(acct, "sub_10", accepted_terms=True, waived_withdrawal=True,
                                           return_url="https://h/r", cancel_url="https://h/c",
                                           now=T0 + 20)
    assert st == "ok" and url.rsplit("/", 1)[1] != ext
    assert _sub_of(ext)["status"] == "abandoned"


def test_checkout_refusals(sub_env, monkeypatch):
    acct = sub_env.login("r@x.it")
    kw = dict(return_url="https://h/r", cancel_url="https://h/c", now=T0)
    assert subscriptions.start_checkout(acct, "sub_7", accepted_terms=True, waived_withdrawal=True,
                                        **kw) == ("bad_plan", None)
    assert subscriptions.start_checkout(acct, "sub_5", accepted_terms=True, waived_withdrawal=False,
                                        **kw) == ("terms_required", None)
    assert subscriptions.start_checkout(acct, "sub_5", accepted_terms="yes", waived_withdrawal=True,
                                        **kw) == ("terms_required", None)
    monkeypatch.setenv("ABM_SUBSCRIPTIONS_ENABLE", "0")
    assert subscriptions.start_checkout(acct, "sub_5", accepted_terms=True, waived_withdrawal=True,
                                        **kw) == ("disabled", None)
    monkeypatch.setenv("ABM_SUBSCRIPTIONS_ENABLE", "1")
    paid, _ext = _paid(sub_env, "p@x.it")
    assert subscriptions.start_checkout(paid, "sub_10", accepted_terms=True, waived_withdrawal=True,
                                        **kw) == ("exists", None)


def test_checkout_provider_error_leaves_no_open_row(sub_env, monkeypatch):
    acct = sub_env.login("e@x.it")

    def boom(**kw):
        raise billing_paypal.ProviderError("down", transient=True)

    monkeypatch.setattr(sub_env.fake, "create_checkout", boom)
    assert subscriptions.start_checkout(acct, "sub_5", accepted_terms=True, waived_withdrawal=True,
                                        return_url="r", cancel_url="c", now=T0) == ("error", None)
    assert subscriptions.current(acct["id"], now=T0) is None


# ------------------------------------------------------------------ pagamenti

def test_first_payment_activates_once(sub_env):
    acct, ext = _subscribe(sub_env, "a@x.it")
    end = T0 + 31 * DAY
    ev = sub_env.fake.pay(ext, "SALE1", T0 + 60, next_at=end)
    assert subscriptions.handle_event("paypal", ev, now=T0 + 61) == "issued"
    assert subscriptions.handle_event("paypal", ev, now=T0 + 62) == "duplicate_event"
    assert subscriptions.record_payment(_sub_of(ext)["id"], ev.payment, now=T0 + 63) == "duplicate"
    a = accounts.get(acct["id"])
    assert (a["plan"], a["plan_source"], a["plan_until"]) == ("sub_5", "paid", end + 10 * DAY)
    assert a["free_consent_at"] is not None
    sub = _sub_of(ext)
    assert (sub["status"], sub["period_start"], sub["period_end"]) == ("active", T0 + 60, end)
    vs = _vouchers_of(acct)
    assert [(v["kind"], v["amount_eur"], v["key"]) for v in vs] == [("subscription", 5.0, "paypal:SALE1")]
    assert sub_env.mails == [("active", "a@x.it")] and sub_env.alerts == []


def test_activated_without_payment_gives_nothing(sub_env):
    acct, ext = _subscribe(sub_env, "n@x.it")
    sub_env.fake.set(ext, status="ACTIVE")
    assert subscriptions.handle_event("paypal", sub_env.fake.refresh_event(ext, "WH-A"),
                                      now=T0 + 30) == "refreshed"
    assert _sub_of(ext)["status"] == "activating"
    assert accounts.get(acct["id"])["plan"] == "free" and _vouchers_of(acct) == []


def test_renewal_extends_and_issues_second_voucher(sub_env):
    acct, ext = _paid(sub_env, "w@x.it")
    end1 = _sub_of(ext)["period_end"]
    ev = sub_env.fake.pay(ext, "SALE2", end1 + 120)
    assert subscriptions.handle_event("paypal", ev, now=end1 + 130) == "issued"
    sub = _sub_of(ext)
    assert sub["period_start"] == end1 + 120 and sub["period_end"] > end1 + 25 * DAY
    assert len(_vouchers_of(acct)) == 2
    assert sub_env.mails == [("active", "w@x.it")]                          # una sola email di attivazione


def test_amount_mismatch_alerts_but_issues(sub_env):
    acct, _ext = _paid(sub_env, "m@x.it", amount=4.0)
    assert _vouchers_of(acct)[0]["amount_eur"] == 5.0
    assert sub_env.alerts == ["amount_mismatch"]


def test_payment_after_cancel_request_is_refunded(sub_env):
    acct, ext = _paid(sub_env, "c@x.it")
    sub_env.fake.fail_cancel = True
    out = subscriptions.request_cancel(acct["id"], "user", now=T0 + 10 * DAY)
    assert out["confirmed"] is False and out["ends_at"] == _sub_of(ext)["period_end"]
    assert accounts.get(acct["id"])["plan_until"] == _sub_of(ext)["period_end"]   # niente grazia
    ev = sub_env.fake.pay(ext, "SALE2", T0 + 31 * DAY)
    assert subscriptions.handle_event("paypal", ev, now=T0 + 31 * DAY + 1) == "rejected"
    assert ("refund", "SALE2", 5.0) in sub_env.fake.calls
    assert len(_vouchers_of(acct)) == 1 and "rejected_payment" in sub_env.alerts
    with db.tx() as c:
        assert c.execute("SELECT state FROM subscription_payments WHERE payment_id='SALE2'"
                         ).fetchone()[0] == "rejected"


def test_cancel_keeps_benefits_until_period_end(sub_env):
    acct, ext = _paid(sub_env, "k@x.it")
    end = _sub_of(ext)["period_end"]
    out = subscriptions.request_cancel(acct["id"], "user", now=T0 + DAY)
    assert out == {"status": "cancelled", "confirmed": True, "ends_at": end}
    assert ("cancel", ext, "user") in sub_env.fake.calls
    assert accounts.get(acct["id"])["plan_until"] == end
    assert sub_env.mails[-1] == ("cancelled", "k@x.it")
    assert subscriptions.request_cancel(acct["id"], "user", now=T0 + DAY + 5)["confirmed"] is True
    assert sub_env.fake.calls.count(("cancel", ext, "user")) == 1
    subscriptions.sweep(now=end + 120, force=True)
    sub = _sub_of(ext)
    assert sub["status"] == "ended" and sub["next_check_at"] == 0
    a = accounts.get(acct["id"])
    assert (a["plan"], a["plan_source"]) == ("free", "")
    assert accounts.archive_quota_for(a) == accounts.plan_quota_bytes("free")   # resta il gratuito


def test_cancel_failure_retried_by_sweep(sub_env):
    acct, ext = _paid(sub_env, "f@x.it")
    sub_env.fake.fail_cancel = True
    subscriptions.request_cancel(acct["id"], "user", now=T0 + DAY)
    assert _sub_of(ext)["status"] == "active" and _sub_of(ext)["cancel_requested_at"] == T0 + DAY
    sub_env.fake.fail_cancel = False
    out = subscriptions.sweep(now=T0 + DAY + 700, force=True)
    assert out["cancelled"] == 1
    sub = _sub_of(ext)
    assert sub["status"] == "cancelled" and sub["cancel_confirmed_at"] == T0 + DAY + 700
    assert sub_env.mails[-1] == ("cancelled", "f@x.it")


def test_cancel_before_first_payment_ends_at_once(sub_env):
    acct, ext = _subscribe(sub_env, "b@x.it")
    sub_env.fake.set(ext, status="ACTIVE")
    subscriptions.refresh(_sub_of(ext)["id"], now=T0 + 10)
    out = subscriptions.request_cancel(acct["id"], "user", now=T0 + 20)
    assert out["status"] == "ended" and accounts.get(acct["id"])["plan"] == "free"


def test_cancelled_on_provider_side(sub_env):
    acct, ext = _paid(sub_env, "s@x.it")
    sub_env.fake.set(ext, status="CANCELLED")
    subscriptions.handle_event("paypal", sub_env.fake.refresh_event(ext, "WH-C"), now=T0 + DAY)
    sub = _sub_of(ext)
    assert (sub["status"], sub["cancel_reason"]) == ("cancelled", "provider")
    assert accounts.get(acct["id"])["plan_until"] == sub["period_end"]
    assert sub_env.mails[-1] == ("cancelled", "s@x.it")


def test_past_due_grace_then_suspension(sub_env):
    acct, ext = _paid(sub_env, "d@x.it")
    end = _sub_of(ext)["period_end"]
    sub_env.fake.set(ext, failed_payments=1)
    subscriptions.handle_event("paypal", sub_env.fake.refresh_event(ext, "WH-F"), now=end + 3600)
    assert _sub_of(ext)["status"] == "past_due"
    a = accounts.get(acct["id"])
    assert a["plan_until"] == end + 10 * DAY and accounts.effective_plan(a, end + 9 * DAY) == "sub_5"
    assert accounts.effective_plan(a, end + 10 * DAY) == "free"
    assert len(_vouchers_of(acct)) == 1
    sub_env.fake.set(ext, status="SUSPENDED")
    subscriptions.handle_event("paypal", sub_env.fake.refresh_event(ext, "WH-S"), now=end + 10 * DAY)
    assert _sub_of(ext)["status"] == "ended"
    assert accounts.get(acct["id"])["plan"] == "free"


def test_late_renewal_reactivates(sub_env):
    acct, ext = _paid(sub_env, "l@x.it")
    end = _sub_of(ext)["period_end"]
    sub_env.fake.set(ext, failed_payments=1)
    subscriptions.refresh(_sub_of(ext)["id"], now=end + 11 * DAY)          # oltre la grazia
    assert accounts.effective_plan(accounts.get(acct["id"]), end + 11 * DAY) == "free"
    ev = sub_env.fake.pay(ext, "SALE2", end + 11 * DAY + 60)
    assert subscriptions.handle_event("paypal", ev, now=end + 11 * DAY + 61) == "issued"
    sub = _sub_of(ext)
    assert sub["status"] == "active" and sub["period_start"] == end + 11 * DAY + 60
    assert accounts.effective_plan(accounts.get(acct["id"]), end + 12 * DAY) == "sub_5"
    v = _vouchers_of(acct)[-1]
    assert 29.9 * DAY < v["expires_at"] - v["created_at"] <= 30 * DAY


def test_abandoned_checkout_paid_later_is_refunded(sub_env):
    acct, old = _subscribe(sub_env, "o@x.it", plan="sub_5")
    st, url = subscriptions.start_checkout(acct, "sub_10", accepted_terms=True, waived_withdrawal=True,
                                           return_url="https://h/r", cancel_url="https://h/c",
                                           now=T0 + 30)
    new = url.rsplit("/", 1)[1]
    assert subscriptions.handle_event("paypal", sub_env.fake.pay(new, "SALEN", T0 + 60, amount=10.0),
                                      now=T0 + 61) == "issued"
    assert subscriptions.handle_event("paypal", sub_env.fake.pay(old, "SALEO", T0 + 90),
                                      now=T0 + 91) == "rejected"
    assert ("refund", "SALEO", 5.0) in sub_env.fake.calls
    assert ("cancel", old, "rejected: closed") in sub_env.fake.calls
    assert [v["amount_eur"] for v in _vouchers_of(acct)] == [10.0]
    assert accounts.get(acct["id"])["plan"] == "sub_10"


def test_second_live_subscription_is_abandoned_by_refresh(sub_env):
    acct, ext = _paid(sub_env, "t@x.it")
    other_id = "sub_other"
    with db.tx() as c:
        c.execute("INSERT INTO subscriptions(id, account_id, provider, external_id, plan, status, "
                  "created_at, updated_at, terms_version, withdrawal_waived_at) "
                  "VALUES (?, ?, 'paypal', 'I-OTHER1', 'sub_10', 'pending', ?, ?, 'v', ?)",
                  (other_id, acct["id"], T0, T0, T0))
    sub_env.fake.remote["I-OTHER1"] = dataclasses.replace(sub_env.fake.remote[ext],
                                                          external_id="I-OTHER1")
    assert subscriptions.refresh(other_id, now=T0 + 100)["status"] == "abandoned"
    assert accounts.get(acct["id"])["plan"] == "sub_5"


def test_reconcile_recovers_lost_webhook(sub_env):
    acct, ext = _subscribe(sub_env, "g@x.it")
    sub_env.fake.pay(ext, "SALEL", T0 + 60)                                 # nessun webhook
    out = subscriptions.sweep(now=T0 + 700, force=True)
    assert out["checked"] == 1
    assert _sub_of(ext)["status"] == "active" and len(_vouchers_of(acct)) == 1
    subscriptions.sweep(now=T0 + 2000, force=True)
    assert len(_vouchers_of(acct)) == 1


def test_voucher_reissued_after_issue_failure(sub_env, monkeypatch):
    real = payment.issue_subscription_voucher

    def boom(**kw):
        raise OSError("disk full")

    monkeypatch.setattr(payment, "issue_subscription_voucher", boom)
    acct, ext = _paid(sub_env, "v@x.it")
    assert _vouchers_of(acct) == []
    monkeypatch.setattr(payment, "issue_subscription_voucher", real)
    assert subscriptions.sweep(now=T0 + 120, force=True)["vouchers"] == 1
    assert len(_vouchers_of(acct)) == 1
    assert subscriptions.sweep(now=T0 + 240, force=True)["vouchers"] == 0


def test_reversal_revokes_voucher(sub_env):
    acct, ext = _paid(sub_env, "x@x.it")
    pay = billing_paypal.Payment(payment_id="SALE" + ext[2:], amount_eur=5.0, paid_at=T0 + 900,
                                 state="reversed", currency="EUR")
    ev = billing_paypal.Event(event_id="WH-R", type="payment_reversed", external_id=ext, payment=pay,
                              raw_type="PAYMENT.SALE.REVERSED")
    assert subscriptions.handle_event("paypal", ev, now=T0 + 901) == "reversed"
    v = _vouchers_of(acct)[0]
    assert v["revoked"] and v["remaining_eur"] == 0.0
    assert sub_env.alerts == ["reversal"]
    ev2 = dataclasses.replace(ev, event_id="WH-R2")
    assert subscriptions.handle_event("paypal", ev2, now=T0 + 902) == "duplicate"


def test_own_refund_confirmation_is_quiet(sub_env):
    acct, ext = _paid(sub_env, "q@x.it")
    sub_env.fake.fail_cancel = True
    subscriptions.request_cancel(acct["id"], "user", now=T0 + DAY)
    subscriptions.handle_event("paypal", sub_env.fake.pay(ext, "SALE2", T0 + 2 * DAY), now=T0 + 2 * DAY)
    sub_env.alerts.clear()
    pay = billing_paypal.Payment(payment_id="SALE2", amount_eur=5.0, paid_at=T0 + 2 * DAY,
                                 state="refunded", currency="EUR")
    ev = billing_paypal.Event(event_id="WH-RF", type="payment_reversed", external_id=ext, payment=pay,
                              raw_type="PAYMENT.SALE.REFUNDED")
    assert subscriptions.handle_event("paypal", ev, now=T0 + 2 * DAY + 5) == "refund_confirmed"
    assert sub_env.alerts == []


def test_pending_abandoned_after_ttl(sub_env):
    acct, ext = _subscribe(sub_env, "h@x.it")
    subscriptions.sweep(now=T0 + 3 * 3600 + 1, force=True)
    assert _sub_of(ext)["status"] == "abandoned"
    assert subscriptions.current(acct["id"], now=T0 + 3 * 3600 + 2) is None


def test_unknown_event_ignored_and_lost_link_recovered(sub_env, monkeypatch):
    ev = billing_paypal.Event(event_id="WH-U", type="refresh", external_id="I-NOBODY1", payment=None,
                              raw_type="BILLING.SUBSCRIPTION.ACTIVATED")
    sub_env.fake.remote["I-NOBODY1"] = billing_paypal.Remote(
        external_id="I-NOBODY1", status="ACTIVE", plan="sub_5", custom_id="sub_unknown",
        next_billing_at=None, last_payment_at=None, last_payment_eur=None, failed_payments=0)
    assert subscriptions.handle_event("paypal", ev, now=T0) == "unknown"
    # crash fra la creazione remota e il salvataggio dell'id esterno
    acct, ext = _subscribe(sub_env, "y@x.it")
    sid = _sub_of(ext)["id"]
    with db.tx() as c:
        c.execute("UPDATE subscriptions SET external_id=NULL WHERE id=?", (sid,))
    ev = sub_env.fake.pay(ext, "SALEY", T0 + 60)
    assert subscriptions.handle_event("paypal", ev, now=T0 + 61) == "issued"
    assert subscriptions.get(sid)["external_id"] == ext


def test_event_retried_after_processing_error(sub_env, monkeypatch):
    acct, ext = _subscribe(sub_env, "z@x.it")
    ev = sub_env.fake.pay(ext, "SALEZ", T0 + 60)

    def boom(*a, **k):
        raise RuntimeError("db hiccup")

    with monkeypatch.context() as m:
        m.setattr(subscriptions, "record_payment", boom)
        with pytest.raises(RuntimeError):
            subscriptions.handle_event("paypal", ev, now=T0 + 61)
    assert subscriptions.handle_event("paypal", ev, now=T0 + 62) == "issued"
    assert len(_vouchers_of(acct)) == 1


def test_account_deleted_cancels_and_abandons(sub_env):
    acct, ext = _paid(sub_env, "del@x.it")
    out = subscriptions.request_cancel(acct["id"], "account_deleted", now=T0 + DAY)
    assert out["confirmed"] is True and ("cancel", ext, "account_deleted") in sub_env.fake.calls
    assert sub_env.mails == [("active", "del@x.it")]                          # nessuna email di disdetta


# ------------------------------------------------------------------ stato e utilita'

def test_status_for_shapes(sub_env):
    acct, ext = _paid(sub_env, "u@x.it")
    st = subscriptions.status_for(acct, now=T0 + 120)
    assert st["enabled"] is True and [p["plan"] for p in st["plans"]] == ["sub_5", "sub_10"]
    assert st["plans"][0]["price_eur"] == 5.0
    sub = st["subscription"]
    assert (sub["plan"], sub["status"], sub["renews"], sub["ends_at"]) == ("sub_5", "active", True, None)
    assert sub["voucher"]["remaining_eur"] == 5.0
    app = subscriptions.status_for(acct, for_app=True, now=T0 + 120)
    assert "plans" not in app and "price" not in str(app)
    assert subscriptions.status_for(None)["subscription"] is None


def test_add_month():
    jan31 = int(time.mktime((2027, 1, 31, 12, 0, 0, 0, 0, 0)) - time.timezone)
    feb = subscriptions._add_month(jan31)
    assert time.gmtime(feb)[:3] == (2027, 2, 28)
    assert time.gmtime(subscriptions._add_month(feb))[:3] == (2027, 3, 28)
