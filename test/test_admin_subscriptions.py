# test/test_admin_subscriptions.py
"""Console admin, tab Utenti: vista abbonamento, rimborso, disdetta immediata, aggregati."""
import accounts
import audiobook_app as app
import payment
import subscriptions
from test.test_subscriptions import T0, DAY, _change, _paid, _sub_of, _vouchers_of, sub_env  # noqa: F401


def _admin(monkeypatch):
    monkeypatch.setattr(app, "ADMIN_TOKEN", "secret", raising=False)
    monkeypatch.setattr(app, "_admin_auth_ok", lambda tok: tok == "secret")
    app.app.config["TESTING"] = True
    return app.app.test_client()


H = {"X-Admin-Token": "secret"}


def test_admin_routes_need_the_token(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    assert c.get("/admin/api/accounts/subscription?account_id=x").status_code in (401, 403)
    assert c.post("/admin/api/subscriptions/refund", json={}).status_code in (401, 403)
    assert c.post("/admin/api/subscriptions/cancel_now", json={}).status_code in (401, 403)


def test_admin_view_masks_voucher_codes(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    acct, ext = _paid(sub_env, "view@x.it")
    code = _vouchers_of(acct)[0]["code"]
    r = c.get(f"/admin/api/accounts/subscription?account_id={acct['id']}", headers=H)
    v = r.get_json()
    assert r.status_code == 200 and v["subscriptions"][0]["status"] == "active"
    assert v["payments"][0]["state"] == "completed" and v["vouchers"][0]["remaining_eur"] == 5.0
    assert code not in r.get_data(as_text=True)                         # codice mai intero
    assert c.get("/admin/api/accounts/subscription?account_id=nobody", headers=H).status_code == 404


def test_admin_refund_with_end_now_closes_the_subscription(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    acct, ext = _paid(sub_env, "refund@x.it")
    sub, pid = _sub_of(ext), "SALE" + ext[2:]
    r = c.post("/admin/api/subscriptions/refund", headers=H,
               json={"sub_id": sub["id"], "payment_id": pid, "end_now": True})
    assert r.status_code == 200
    assert ("refund", pid, 5.0) in sub_env.fake.calls and ("cancel", ext, "admin_refund") in sub_env.fake.calls
    assert _sub_of(ext)["status"] == "ended" and accounts.get(acct["id"])["plan"] == "free"
    assert _vouchers_of(acct)[0]["revoked"] and sub_env.alerts == []          # niente avviso a se stessi
    r = c.post("/admin/api/subscriptions/refund", headers=H,
               json={"sub_id": sub["id"], "payment_id": pid, "end_now": True})
    assert r.status_code == 409 and r.get_json()["error"] == "not_refundable"


def test_admin_refund_without_end_now_keeps_the_plan(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    acct, ext = _paid(sub_env, "keep@x.it")
    r = c.post("/admin/api/subscriptions/refund", headers=H,
               json={"sub_id": _sub_of(ext)["id"], "payment_id": "SALE" + ext[2:], "end_now": False})
    assert r.status_code == 200 and _sub_of(ext)["status"] == "active"
    assert accounts.get(acct["id"])["plan"] == "sub_5"


def test_admin_refund_failure_is_502_and_changes_nothing(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    acct, ext = _paid(sub_env, "fail@x.it")
    sub_env.fake.fail_refund = True
    r = c.post("/admin/api/subscriptions/refund", headers=H,
               json={"sub_id": _sub_of(ext)["id"], "payment_id": "SALE" + ext[2:], "end_now": True})
    assert r.status_code == 502 and _sub_of(ext)["status"] == "active"
    assert not _vouchers_of(acct)[0].get("revoked")


def test_admin_cancel_now_ends_live_row_and_pending_change(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    acct, ext = _paid(sub_env, "now@x.it")
    new, _row = _change(sub_env, acct, "sub_10", T0 + DAY)
    r = c.post("/admin/api/subscriptions/cancel_now", headers=H, json={"sub_id": _sub_of(ext)["id"]})
    assert r.status_code == 200
    assert _sub_of(ext)["status"] == "ended" and _sub_of(new)["status"] == "ended"
    assert ("cancel", ext, "admin") in sub_env.fake.calls and ("cancel", new, "admin") in sub_env.fake.calls
    r = c.post("/admin/api/subscriptions/cancel_now", headers=H, json={"sub_id": _sub_of(ext)["id"]})
    assert r.status_code == 409


def test_accounts_audit_reports_sub_status_and_stats(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    monkeypatch.setattr(app, "_smtp_available", lambda: True)
    acct, _ext = _paid(sub_env, "stats@x.it")
    other = sub_env.login("idle@x.it")
    subscriptions.start_checkout(other, "sub_10", accepted_terms=True, waived_withdrawal=True,
                                 return_url="r", cancel_url="c", now=T0)
    subscriptions.sweep(now=T0 + 4 * 3600, force=True)                        # checkout abbandonato
    d = c.get("/admin/api/accounts_audit", headers=H).get_json()
    status = {r["email"]: r["sub_status"] for r in d["records"]}
    assert status["stats@x.it"] == "active" and status["idle@x.it"] == "abandoned"
    assert d["subscriptions"]["live"] == 1 and d["subscriptions"]["live_sub_5"] == 1
    assert d["subscriptions"]["abandoned_30d"] == 1


def test_accounts_audit_sub_live_filter_matches_the_box(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    monkeypatch.setattr(app, "_smtp_available", lambda: True)
    _paid(sub_env, "live@x.it")
    sub_env.login("nosub@x.it")
    other = sub_env.login("idle@x.it")
    subscriptions.start_checkout(other, "sub_10", accepted_terms=True, waived_withdrawal=True,
                                 return_url="r", cancel_url="c", now=T0)
    subscriptions.sweep(now=T0 + 4 * 3600, force=True)                        # checkout abbandonato

    def get(query):
        r = c.get("/admin/api/accounts_audit" + query, headers=H)
        assert r.status_code == 200
        return r.get_json()

    for on in ("?sub=live", "?sub=%20LIVE%20"):
        d = get(on)
        assert [r["email"] for r in d["records"]] == ["live@x.it"], on
        assert d["count"] == d["subscriptions"]["live"] == 1
        assert d["aggregates"]["total"] == 3                                  # aggregati sull'intera anagrafica
    assert get("?sub=boh")["count"] == get("")["count"] == 3                  # valori ignoti: nessun filtro
    assert get("?sub=live&origin=gift")["count"] == 0                         # filtri in AND


def test_admin_list_empty_account_ids_matches_nothing(sub_env):
    sub_env.login("one@x.it")
    out = accounts.admin_list(account_ids=[])
    assert out["count"] == 0 and out["records"] == [] and out["aggregates"]["total"] == 1
    assert accounts.admin_list(account_ids=None)["count"] == 1


def test_admin_page_has_the_subscription_popup(sub_env, monkeypatch):
    with open("templates/pages/admin_audit_premium.html", encoding="utf-8") as f:
        html = f.read()
    for needle in ('id="accSubModal"', "data-acc-sub-open", "/admin/api/subscriptions/refund",
                   "/admin/api/subscriptions/cancel_now", 'id="accSubLive"', 'id="accSubAbandoned"',
                   'id="accSubEndNow" checked', 'data-acc-agg="sub_live"', 'id="accSubFilter"',
                   '"sub_live":     {accSubFilter: "live"}'):
        assert needle in html, needle
