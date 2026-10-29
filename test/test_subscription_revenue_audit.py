# test/test_subscription_revenue_audit.py
"""Cruscotto audit: ricavi degli abbonamenti al pagamento/rinnovo e ricavo zero
sui job pagati con i voucher degli abbonamenti (restano i costi)."""
from datetime import datetime, timezone

import pytest

import audiobook_app as app
import gemini_tts
import payment
import routes_admin_audit
import subscriptions
import voice_clone_audit
from test.test_subscriptions import T0, DAY, _change, _paid, _sub_of, _vouchers_of, sub_env  # noqa: F401


H = {"X-Admin-Token": "secret"}


def _admin(monkeypatch):
    monkeypatch.setattr(app, "ADMIN_TOKEN", "secret", raising=False)
    monkeypatch.setattr(app, "_admin_auth_ok", lambda tok: tok == "secret")
    monkeypatch.setattr(gemini_tts, "PAYPAL_PERCENT_FEE", 3.4)
    monkeypatch.setattr(gemini_tts, "PAYPAL_FIXED_FEE_EUR", 0.35)
    app.app.config["TESTING"] = True
    return app.app.test_client()


def _day(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d")


def test_is_subscription_voucher_reads_full_and_masked_codes():
    f = payment.is_subscription_voucher
    assert f("voucher", "SUB-ABCD-EFGH-JKLM") and f("VOUCHER", "SUB-ABCD...") and f("voucher", "sub-abcd")
    assert not f("paypal", "SUB-ABCD...")                      # serve il metodo voucher
    assert not f("voucher", "ABCD-EFGH-JKLM") and not f("voucher", "") and not f(None, None)
    assert payment._generate_voucher_code()[4] == "-"          # nessun codice generato fa "SUB-"


def test_subscription_voucher_job_keeps_only_costs():
    """Ricavo, fee e margine azzerati sul ricavo; il delta resta sul prezzo applicato, anche
    sulla trattenuta di un annullamento parziale. Un voucher normale non cambia."""
    base = {"outcome": "completed", "payment_method": "voucher", "user_price_eur_charged": 3.0,
            "google_cost_eur_actual": 1.0, "user_price_eur_should_have_been": 3.0}
    rec = routes_admin_audit._apply_cancel_effective(dict(base, payment_token_short="SUB-ABCD..."))
    assert rec["_sub_voucher"] is True
    assert (rec["_eff_revenue_eur"], rec["_eff_margin_eur"], rec["_net_margin_eur"]) == (0.0, -1.0, -1.0)
    assert rec["_paypal_fee_eur"] == 0.0 and rec["_eff_delta_eur"] == 0.0
    part = routes_admin_audit._apply_cancel_effective(
        dict(base, payment_token_short="SUB-ABCD...", outcome="cancelled_partial", cancel_retained_eur=2.0))
    assert part["_eff_revenue_eur"] == 0.0 and part["_eff_delta_eur"] == 1.0
    plain = routes_admin_audit._apply_cancel_effective(dict(base, payment_token_short="ABCD-EFG..."))
    assert plain["_sub_voucher"] is False and plain["_eff_revenue_eur"] == 3.0
    live = routes_admin_audit._apply_cancel_effective(dict(base, _sub_voucher=True))
    assert live["_eff_revenue_eur"] == 0.0


def test_voucher_spent_counts_uses_net_of_refunds():
    v = {"uses": [{"amount_eur": 2.0}, {"amount_eur": 1.5}, {"amount_eur": -1.5}, {"amount_eur": "x"}],
         "remaining_eur": 0.0, "revoked": True}
    assert payment.voucher_spent_eur(v) == 2.0
    assert payment.voucher_spent_eur({}) == 0.0 and payment.voucher_spent_eur({"uses": [{"amount_eur": -1}]}) == 0.0


def test_live_rows_flag_subscription_vouchers():
    flag = routes_admin_audit._live_sub_voucher
    assert flag({"payment": {"method": "voucher", "token": "SUB-ABCD-EFGH-JKLM"}})
    assert not flag({"payment": {"method": "voucher", "token": "ABCD-EFGH-JKLM"}})
    assert not flag({"payment": {"method": "paypal", "token": "SUB-ABCD"}}) and not flag({})


def test_voice_clone_paid_with_subscription_voucher_has_no_revenue():
    rec = {"id": "vc_1", "state": "ready", "demo_cost": {"usd": 0.5},
           "payment": {"type": "voucher", "token": "SUB-ABCD-EFGH-JKLM", "amount_eur": 5.0}}
    r = voice_clone_audit.row(rec, sub_voucher_fn=payment.is_subscription_voucher)
    assert r["sub_voucher"] and r["revenue_eur"] == 0.0 and r["charged_eur"] == 5.0
    assert r["net_margin_eur"] == -0.5 and "SUB-ABCD" not in str(r)       # mai il codice
    assert voice_clone_audit.row(rec)["revenue_eur"] == 5.0                # senza predicato: com'era


def test_subscription_revenue_audit_counts_payments_once(sub_env, monkeypatch):
    """Ricavo al pagamento, fee PayPal sul ricavo, rimborsato a zero ma visibile; voucher
    mascherato con lo speso; filtro sulla data del pagamento."""
    c = _admin(monkeypatch)
    acct, ext = _paid(sub_env, "uno@x.it")
    gone, gext = _paid(sub_env, "due@x.it")
    code = next(k for k, v in payment.iter_vouchers() if v.get("account_id") == acct["id"])
    payment._voucher_consume(code, 1.5, job_id="j1", service="voxcpm", account_id=acct["id"])
    r = c.post("/admin/api/subscriptions/refund", headers=H,
               json={"sub_id": _sub_of(gext)["id"], "payment_id": "SALE" + gext[2:], "end_now": False})
    assert r.status_code == 200

    day = _day(T0 + 60)
    r = c.get(f"/admin/api/subscription_revenue_audit?date_from={day}&date_to={day}", headers=H)
    assert r.status_code == 200 and code not in r.get_data(as_text=True)
    d = r.get_json()
    rows = {x["email"]: x for x in d["records"]}
    ok, refunded = rows["uno@x.it"], rows["due@x.it"]
    assert (ok["state"], ok["revenue_eur"], ok["plan"]) == ("completed", 5.0, "sub_5")
    assert ok["paypal_fee_eur"] == pytest.approx(0.52) and ok["net_margin_eur"] == pytest.approx(4.48)
    assert ok["voucher_code"] == code[:4] + "…" and ok["voucher_spent_eur"] == 1.5
    assert (refunded["state"], refunded["revenue_eur"], refunded["paypal_fee_eur"]) == ("refunded", 0.0, 0.0)
    assert refunded["voucher_revoked"] and refunded["voucher_spent_eur"] == 0.0   # la revoca non e' spesa
    a = d["aggregates"]
    assert (d["count"], a["count"], a["revenue_eur"], a["refunded_eur"]) == (2, 2, 5.0, 5.0)
    assert a["paypal_fees_eur"] == pytest.approx(0.52) and a["net_margin_eur"] == pytest.approx(4.48)
    assert a["voucher_spent_eur"] == 1.5 and a["voucher_eur"] == 5.0      # il revocato non conta

    later = _day(T0 + 60 + DAY)
    assert c.get(f"/admin/api/subscription_revenue_audit?date_from={later}", headers=H).get_json()["count"] == 0
    earlier = _day(T0 + 60 - DAY)
    assert c.get(f"/admin/api/subscription_revenue_audit?date_to={earlier}", headers=H).get_json()["count"] == 0
    assert c.get("/admin/api/subscription_revenue_audit?limit=1", headers=H).get_json()["count"] == 2


def test_revoked_voucher_counts_only_what_was_spent(sub_env, monkeypatch):
    """Fra i voucher emessi un revocato vale solo la parte spesa prima della revoca."""
    c = _admin(monkeypatch)
    acct, ext = _paid(sub_env, "rev@x.it")
    code = next(k for k, v in payment.iter_vouchers() if v.get("account_id") == acct["id"])
    payment._voucher_consume(code, 2.0, job_id="j1", service="voxcpm", account_id=acct["id"])
    assert c.post("/admin/api/subscriptions/refund", headers=H,
                  json={"sub_id": _sub_of(ext)["id"], "payment_id": "SALE" + ext[2:],
                        "end_now": True}).status_code == 200
    d = c.get("/admin/api/subscription_revenue_audit", headers=H).get_json()
    row = d["records"][0]
    assert row["voucher_revoked"] and (row["voucher_eur"], row["voucher_spent_eur"]) == (5.0, 2.0)
    assert (d["aggregates"]["voucher_eur"], d["aggregates"]["voucher_spent_eur"]) == (2.0, 2.0)


def test_admin_cancel_state():
    f = subscriptions._admin_cancel_state
    assert f("active", None, "") == ""
    assert f("active", T0, "user") == "running"            # chiesta, PayPal non ha ancora confermato
    assert f("cancelled", T0, "user") == "running"
    assert f("past_due", T0, "provider") == "running"
    assert f("active", T0, "plan_change") == ""            # prosegue nella riga del nuovo piano
    assert f("ended", T0, "user") == "ended" and f("ended", None, "") == "ended"
    assert f("replaced", T0, "plan_change") == "" and f("abandoned", None, "") == ""


def test_subscription_revenue_audit_flags_cancelled_subscriptions(sub_env, monkeypatch):
    """Disdetto ma in corso: stato, fine dei benefici, motivo e ripresa programmata;
    chiuso dal rimborso admin; un abbonamento attivo resta senza segno."""
    c = _admin(monkeypatch)
    _paid(sub_env, "attivo@x.it")
    gone, gext = _paid(sub_env, "disdetto@x.it")
    end = _sub_of(gext)["period_end"]
    subscriptions.request_cancel(gone["id"], "user", now=T0 + DAY)
    back, bext = _paid(sub_env, "ripresa@x.it")
    subscriptions.request_cancel(back["id"], "user", now=T0 + DAY)
    _change(sub_env, back, "sub_5", T0 + 2 * DAY)
    shut, sext = _paid(sub_env, "chiuso@x.it")
    assert c.post("/admin/api/subscriptions/refund", headers=H,
                  json={"sub_id": _sub_of(sext)["id"], "payment_id": "SALE" + sext[2:],
                        "end_now": True}).status_code == 200

    rows = {x["email"]: x for x in c.get("/admin/api/subscription_revenue_audit",
                                         headers=H).get_json()["records"]}
    assert (rows["attivo@x.it"]["sub_cancel"], rows["attivo@x.it"]["resume_at"]) == ("", None)
    r = rows["disdetto@x.it"]
    assert (r["sub_cancel"], r["sub_status"], r["sub_period_end"]) == ("running", "cancelled", end)
    assert (r["cancel_reason"], r["cancel_requested_at"]) == ("user", T0 + DAY)
    assert r["cancel_confirmed_at"] and r["resume_at"] is None
    assert (rows["ripresa@x.it"]["sub_cancel"], rows["ripresa@x.it"]["resume_at"]) == (
        "running", _sub_of(bext)["period_end"])
    r = rows["chiuso@x.it"]
    assert (r["sub_cancel"], r["sub_status"], r["cancel_reason"]) == ("ended", "ended", "admin_refund")
    assert r["sub_ended_at"]


def test_subscription_revenue_audit_needs_the_token(sub_env, monkeypatch):
    c = _admin(monkeypatch)
    assert c.get("/admin/api/subscription_revenue_audit").status_code in (401, 403)


def test_premium_page_has_subscriptions_tab_in_totals(monkeypatch):
    c = _admin(monkeypatch)
    body = c.get("/admin/audit-premium", headers=H).get_data(as_text=True)
    assert 'data-tab="subscriptions"' in body and 'id="tab_subscriptions"' in body
    assert "/admin/api/subscription_revenue_audit?" in body
    assert 'setServiceTotals("subscriptions", a.revenue_eur, 0, a.net_margin_eur)' in body
    assert "subscriptions: null" in body
    assert '"vcaDateFrom","subDateFrom"' in body and '"vcaDateTo","subDateTo"' in body
    assert "window._subLoaded = true;\n  subFetch();" in body and '_h === "#tab-subscriptions"' in body
    for cell in ("subMark(r._sub_voucher)", "subMark(r.sub_voucher)"):
        assert cell in body
    # Disdetta sulla riga piu' recente di ogni abbonamento, popup "Abbonamento" della
    # tab Utenti anche qui, con la rilettura della lista da cui lo si e' aperto.
    assert "${cancel}</td>" in body and "latest ? subCancelCell(r)" in body
    assert 'data-acc-sub-open="${escAttr(r.account_id)}">Abbonamento</button>' in body
    assert "accSubReload = subFetch; accSubOpen(" in body and "accSubReload = accFetch; accSubOpen(" in body
    assert "(accSubReload || accFetch)();" in body
