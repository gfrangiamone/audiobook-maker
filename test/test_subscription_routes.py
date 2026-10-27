# test/test_subscription_routes.py
"""Route degli abbonamenti: checkout, ritorno, disdetta, webhook, account cancellato."""
import json

import pytest

import accounts
import billing_paypal
import db
import email_service
import payment
import subscriptions
from test.test_subscriptions import T0, FakeProvider


@pytest.fixture
def web(tmp_path, monkeypatch):
    import audiobook_app
    import routes_account
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    subscriptions.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(accounts, "_payments_path", None)
    monkeypatch.setattr(accounts, "_voice_ids_for_email", None)
    monkeypatch.setattr(accounts, "_link_voice", None)
    monkeypatch.setattr(accounts, "_unlink_voice", None)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_ip_rl_check", lambda *a, **k: (True, 0))
    # URL di ritorno indipendente da ABM_BASE_URL: in CI manca e vale il default di sviluppo
    import routes_subscriptions
    monkeypatch.setitem(routes_subscriptions._cfg, "base_url", lambda: "https://abm.test")
    monkeypatch.setattr(payment, "_vouchers", {})
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setenv("ABM_SUBSCRIPTIONS_ENABLE", "1")
    fake = FakeProvider()
    fake.verify_webhook = lambda headers, event: headers.get("X-Test-Sig") == "ok"
    fake.parse_webhook = billing_paypal.parse_webhook
    monkeypatch.setitem(subscriptions.PROVIDERS, "paypal", fake)
    mails = []
    for kind in ("active", "cancelled", "voucher", "reminder"):
        monkeypatch.setattr(email_service, f"send_subscription_{kind}",
                            lambda email, lang, _k=kind, **kw: mails.append((_k, email)), raising=False)
    monkeypatch.setattr(email_service, "admin_notify_subscription", lambda kind, details: None,
                        raising=False)
    monkeypatch.setattr(email_service, "send_account_deleted", lambda *a, **k: None)
    holder = {"acct": None}
    monkeypatch.setattr(routes_account, "_current_account", lambda: holder["acct"])
    token, code = accounts.request_code("a@x.it", "login", "it", now=T0)
    _st, acct = accounts.verify(token=token, code=code, purpose="login", now=T0)
    yield audiobook_app.app.test_client(), holder, acct, fake, mails
    db.close()


def _checkout(c, plan="sub_5", **extra):
    body = {"plan": plan, "accept_terms": True, "waive_withdrawal": True, **extra}
    return c.post("/api/subscription/checkout", json=body)


def _ext(r):
    return r.get_json()["approve_url"].rsplit("/", 1)[1]


def _sale_event(eid, ext, sale, amount="5.00"):
    return {"id": eid, "event_type": "PAYMENT.SALE.COMPLETED",
            "resource": {"id": sale, "billing_agreement_id": ext, "create_time": "2026-10-23T10:00:00Z",
                         "amount": {"total": amount, "currency": "EUR"}}}


def _hook(c, event, sig="ok"):
    return c.post("/api/billing/paypal/webhook", data=json.dumps(event),
                  headers={"Content-Type": "application/json", "X-Test-Sig": sig})


def test_checkout_requires_terms_and_login(web):
    c, holder, acct, _fake, _mails = web
    assert _checkout(c).status_code == 401
    holder["acct"] = acct
    r = _checkout(c, accept_terms=False)
    assert r.status_code == 400 and r.get_json()["error_code"] == "terms_required"
    r = _checkout(c, waive_withdrawal="true")
    assert r.status_code == 400 and r.get_json()["error_code"] == "terms_required"
    r = _checkout(c, plan="gold")
    assert r.status_code == 400 and r.get_json()["error_code"] == "bad_plan"


def test_checkout_disabled_is_404(web, monkeypatch):
    c, holder, acct, _fake, _mails = web
    holder["acct"] = acct
    monkeypatch.setenv("ABM_SUBSCRIPTIONS_ENABLE", "0")
    r = _checkout(c)
    assert r.status_code == 404 and r.get_json()["error_code"] == "subscriptions_disabled"


def test_checkout_returns_approve_url_and_status(web):
    c, holder, acct, fake, _mails = web
    holder["acct"] = acct
    r = _checkout(c)
    assert r.status_code == 200 and r.get_json()["approve_url"].startswith("https://pp.test/approve/")
    assert fake.calls[0][2].startswith("https://abm.test/account/subscription/return?sid=sub_")
    st = c.get("/api/subscription").get_json()
    assert st["subscription"]["status"] == "pending" and st["plans"][1]["price_eur"] == 10.0


def test_status_route_pokes_activating_subscription(web):
    c, holder, acct, fake, _mails = web
    holder["acct"] = acct
    ext = _ext(_checkout(c))
    fake.set(ext, status="ACTIVE")
    sid = subscriptions.current(acct["id"])["id"]
    subscriptions.refresh(sid, now=T0 - 60)
    fake.pay(ext, "SALEQ", T0 - 55)
    st = c.get("/api/subscription").get_json()                     # ora reale: oltre POKE_MIN_SEC
    assert st["subscription"]["status"] == "active"


def test_return_route_activates_and_rejects_other_account(web):
    c, holder, acct, fake, mails = web
    holder["acct"] = acct
    ext = _ext(_checkout(c))
    sid = subscriptions.current(acct["id"])["id"]
    fake.pay(ext, "SALE1", T0 + 60)
    other = {"id": "ac_other", "email": "o@x.it"}
    holder["acct"] = other
    assert c.get(f"/account/subscription/return?sid={sid}").status_code == 404
    holder["acct"] = acct
    assert c.get(f"/account/subscription/return?sid={sid}&subscription_id=I-WRONG1").status_code == 404
    r = c.get(f"/account/subscription/return?sid={sid}&subscription_id={ext}")
    assert r.status_code == 302 and r.headers["Location"].endswith("/account?sub=ok")
    assert accounts.get(acct["id"])["plan_source"] == "paid" and mails == [("active", "a@x.it")]
    subscriptions.request_cancel(acct["id"], "user")
    r = c.get(f"/account/subscription/return?sid={sid}")            # disdetto: nessun avviso di attesa
    assert r.headers["Location"].endswith("/account")
    holder["acct"] = None
    assert c.get(f"/account/subscription/return?sid={sid}").headers["Location"].endswith("/account")


def test_cancel_returns_ends_at(web):
    c, holder, acct, fake, mails = web
    holder["acct"] = acct
    assert c.post("/api/subscription/cancel", json={"confirm": True}).status_code == 404
    ext = _ext(_checkout(c))
    fake.pay(ext, "SALE1", T0 + 60)
    subscriptions.reconcile_one(subscriptions.current(acct["id"])["id"], now=T0 + 61)
    assert c.post("/api/subscription/cancel", json={}).status_code == 400
    r = c.post("/api/subscription/cancel", json={"confirm": True})
    body = r.get_json()
    assert r.status_code == 200 and body["ok"] and body["status"] == "cancelled"
    assert body["ends_at"] == subscriptions.current(acct["id"])["period_end"]
    assert mails[-1] == ("cancelled", "a@x.it")


def test_webhook_rejects_bad_signature(web):
    c, holder, acct, _fake, _mails = web
    holder["acct"] = acct
    ext = _ext(_checkout(c))
    r = _hook(c, _sale_event("WH-1", ext, "SALE1"), sig="bad")
    assert r.status_code == 400 and r.get_json()["error_code"] == "bad_signature"
    assert c.post("/api/billing/paypal/webhook", data="not json",
                  headers={"X-Test-Sig": "ok"}).status_code == 400
    with db.tx() as cx:
        assert cx.execute("SELECT COUNT(*) FROM subscription_events").fetchone()[0] == 0
        assert cx.execute("SELECT COUNT(*) FROM subscription_payments").fetchone()[0] == 0


def test_webhook_valid_event_processed_once(web):
    c, holder, acct, fake, _mails = web
    holder["acct"] = acct
    ext = _ext(_checkout(c))
    fake.set(ext, status="ACTIVE")
    event = _sale_event("WH-2", ext, "SALE2")
    r = _hook(c, event)
    assert r.status_code == 200 and r.get_json()["outcome"] == "issued"
    assert _hook(c, event).get_json()["outcome"] == "duplicate_event"
    assert len([v for _, v in payment.iter_vouchers() if v.get("account_id") == acct["id"]]) == 1
    other = {"id": "WH-3", "event_type": "CHECKOUT.ORDER.APPROVED", "resource": {"id": "X1"}}
    assert _hook(c, other).get_json()["outcome"] == "ignored"


def test_webhook_processing_error_is_500(web, monkeypatch):
    c, holder, acct, _fake, _mails = web
    holder["acct"] = acct
    ext = _ext(_checkout(c))

    def boom(*a, **k):
        raise RuntimeError("db hiccup")

    monkeypatch.setattr(subscriptions, "handle_event", boom)
    assert _hook(c, _sale_event("WH-4", ext, "SALE4")).status_code == 500


def test_webhook_is_the_only_csrf_exempt_path(web):
    import audiobook_app
    import routes_subscriptions
    assert audiobook_app._CSRF_EXEMPT_PATHS == {routes_subscriptions.WEBHOOK_PATH}
    c, _holder, _acct, _fake, _mails = web
    r = c.post("/api/subscription/cancel", json={"confirm": True},
               headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_account_deletion_cancels_subscription(web):
    import routes_account
    c, holder, acct, fake, mails = web
    holder["acct"] = acct
    ext = _ext(_checkout(c))
    fake.pay(ext, "SALE1", T0 + 60)
    sid = subscriptions.current(acct["id"])["id"]
    subscriptions.reconcile_one(sid, now=T0 + 61)
    fake.fail_cancel = True
    routes_account._acct_do_delete(acct, "it")
    assert accounts.get(acct["id"])["deleted_at"] is not None
    row = subscriptions.get(sid)
    assert row["cancel_reason"] == "account_deleted" and row["cancel_confirmed_at"] is None
    fake.fail_cancel = False
    subscriptions.sweep(now=row["next_check_at"] + 1, force=True)
    assert subscriptions.get(sid)["cancel_confirmed_at"] is not None
    assert fake.calls.count(("cancel", ext, "account_deleted")) == 2
    assert ("cancelled", "a@x.it") not in mails


def test_auth_me_exposes_subscription_without_prices(web):
    c, holder, acct, fake, _mails = web
    holder["acct"] = acct
    ext = _ext(_checkout(c))
    fake.pay(ext, "SALE1", T0 + 60)
    subscriptions.reconcile_one(subscriptions.current(acct["id"])["id"], now=T0 + 61)
    holder["acct"] = accounts.get(acct["id"])
    me = c.get("/api/auth/me").get_json()
    sub = me["subscription"]
    assert sub["subscription"]["plan"] == "sub_5" and sub["subscription"]["voucher"]["remaining_eur"] == 5.0
    assert "plans" not in sub and "price" not in json.dumps(sub)


def test_auth_me_exposes_proposals(web, monkeypatch):
    """Spec §9.3 punti 2-3: la SPA legge da /api/auth/me se proporre i piani a
    libreria quasi piena e il tetto/servizi della riga nel modale di pagamento."""
    c, holder, acct, _fake, _mails = web
    holder["acct"] = acct
    me = c.get("/api/auth/me").get_json()
    assert me["archive_nudge"] == ""
    assert me["sub_promo"] == {"max_eur": 10.0, "services": list(payment.VOUCHER_DEFAULT_SERVICES)}
    accounts.free_plan_action(acct["id"], "activate", "account", now=T0)
    accounts.record_job(acct["id"], "j1", kind="generate", status="done", created_at=T0)
    accounts.mark_archived("j1", 512 * accounts.MIB, now=T0)
    holder["acct"] = accounts.get(acct["id"])
    assert c.get("/api/auth/me").get_json()["archive_nudge"] == "full"
    monkeypatch.setenv("ABM_SUBSCRIPTIONS_ENABLE", "0")
    me = c.get("/api/auth/me").get_json()
    assert me["archive_nudge"] == "" and me["sub_promo"] is None


# ------------------------------------------------------------------ fase 2b: cambi di piano

def _paid_via_routes(c, fake, acct):
    ext = _ext(_checkout(c))
    fake.pay(ext, "SALE1", T0 + 60)
    sid = subscriptions.current(acct["id"])["id"]
    subscriptions.reconcile_one(sid, now=T0 + 61)
    return ext, sid


def test_change_route_upgrade_and_cancel_change(web):
    c, holder, acct, fake, _mails = web
    holder["acct"] = acct
    assert c.post("/api/subscription/change", json={"plan": "sub_10", "accept_terms": True,
                                                     "waive_withdrawal": True}).status_code == 404
    _ext_old, _sid = _paid_via_routes(c, fake, acct)
    body = {"plan": "sub_10", "accept_terms": True, "waive_withdrawal": True}
    r = c.post("/api/subscription/change", json=body)
    assert r.status_code == 200 and r.get_json()["approve_url"].startswith("https://pp.test/approve/")
    new = r.get_json()["approve_url"].rsplit("/", 1)[1]
    assert fake.created[new]["setup_fee_eur"] == 10.0
    r = c.post("/api/subscription/change", json=body)
    assert r.status_code == 409 and r.get_json()["error_code"] == "change_pending"
    st = c.get("/api/subscription").get_json()
    assert st["change"]["plan"] == "sub_10" and all(p["change"] is None for p in st["plans"])
    assert c.post("/api/subscription/change_cancel", json={}).status_code == 400
    assert c.post("/api/subscription/change_cancel", json={"confirm": True}).status_code == 200
    assert c.post("/api/subscription/change_cancel", json={"confirm": True}).status_code == 404


def test_change_route_refusals(web):
    c, holder, acct, fake, _mails = web
    holder["acct"] = acct
    _paid_via_routes(c, fake, acct)
    r = c.post("/api/subscription/change", json={"plan": "sub_5", "accept_terms": True,
                                                  "waive_withdrawal": True})
    assert r.status_code == 409 and r.get_json()["error_code"] == "same_plan"
    r = c.post("/api/subscription/change", json={"plan": "sub_10", "accept_terms": True})
    assert r.status_code == 400 and r.get_json()["error_code"] == "terms_required"


def test_return_route_for_scheduled_change(web):
    c, holder, acct, fake, _mails = web
    holder["acct"] = acct
    _paid_via_routes(c, fake, acct)
    subscriptions.request_cancel(acct["id"], "user")
    r = c.post("/api/subscription/change", json={"plan": "sub_5", "accept_terms": True,
                                                  "waive_withdrawal": True})
    new = r.get_json()["approve_url"].rsplit("/", 1)[1]
    fake.set(new, status="ACTIVE")
    with db.tx() as cx:
        sid = cx.execute("SELECT id FROM subscriptions WHERE external_id=?", (new,)).fetchone()[0]
    r = c.get(f"/account/subscription/return?sid={sid}")
    assert r.headers["Location"].endswith("/account?sub=scheduled")
