# test/test_billing_paypal.py
"""Adattatore PayPal Subscriptions: richieste, mappature, errori, webhook."""
import pytest
import requests

import billing_paypal as bp
import payment


class _Resp:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self._body = body
        self.headers = headers or {}
        self.text = "" if body is None else str(body)

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


@pytest.fixture
def pp(monkeypatch):
    calls, queue = [], []

    def send(method, url, *, headers, json=None, params=None, timeout=15):
        calls.append({"method": method, "url": url, "headers": headers, "json": json,
                      "params": params, "timeout": timeout})
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(bp, "_send", send)
    monkeypatch.setattr(bp, "_sleep", lambda s: None)
    monkeypatch.setattr(payment, "_paypal_get_access_token", lambda: "tok")
    monkeypatch.setenv("ABM_PAYPAL_PLAN_SUB5", "P-FIVE")
    monkeypatch.setenv("ABM_PAYPAL_PLAN_SUB10", "P-TEN")
    monkeypatch.setenv("ABM_PAYPAL_WEBHOOK_ID", "WH-ID")
    return calls, queue


def test_create_checkout_sends_request_id_and_returns_approve_link(pp):
    calls, queue = pp
    queue.append(_Resp(201, {"id": "I-ABC123", "status": "APPROVAL_PENDING", "links": [
        {"rel": "self", "href": "https://api/self"},
        {"rel": "approve", "href": "https://www.paypal.com/webapps/billing/subscriptions?ba_token=X"}]}))
    ext, url = bp.create_checkout(sub_id="sub_x1", plan="sub_10", email="a@x.it", lang="it",
                                  return_url="https://h/r", cancel_url="https://h/c")
    assert ext == "I-ABC123" and url.endswith("ba_token=X")
    call = calls[0]
    assert call["method"] == "POST" and call["url"].endswith("/v1/billing/subscriptions")
    assert call["headers"]["PayPal-Request-Id"] == "sub_x1"
    assert call["headers"]["Authorization"] == "Bearer tok"
    body = call["json"]
    assert (body["plan_id"], body["custom_id"]) == ("P-TEN", "sub_x1")
    assert body["subscriber"] == {"email_address": "a@x.it"}
    ctx = body["application_context"]
    assert (ctx["locale"], ctx["shipping_preference"], ctx["user_action"]) == \
        ("it-IT", "NO_SHIPPING", "SUBSCRIBE_NOW")
    assert (ctx["return_url"], ctx["cancel_url"]) == ("https://h/r", "https://h/c")


def test_create_checkout_without_plan_or_link_fails(pp, monkeypatch):
    calls, queue = pp
    monkeypatch.setenv("ABM_PAYPAL_PLAN_SUB5", "")
    with pytest.raises(bp.ProviderError):
        bp.create_checkout(sub_id="s", plan="sub_5", email="", lang="en", return_url="r",
                           cancel_url="c")
    assert calls == []
    queue.append(_Resp(201, {"id": "I-1234", "links": []}))
    with pytest.raises(bp.ProviderError):
        bp.create_checkout(sub_id="s", plan="sub_10", email="", lang="en", return_url="r",
                           cancel_url="c")


def test_fetch_maps_plan_and_billing_info(pp):
    _calls, queue = pp
    queue.append(_Resp(200, {"id": "I-0001", "status": "ACTIVE", "plan_id": "P-FIVE", "custom_id": "sub_a",
                             "billing_info": {"next_billing_time": "2027-01-15T10:00:00Z",
                                              "failed_payments_count": 1,
                                              "last_payment": {"amount": {"value": "5.00"},
                                                               "time": "2026-12-15T10:00:00Z"}}}))
    r = bp.fetch("I-0001")
    assert (r.status, r.plan, r.custom_id, r.failed_payments, r.last_payment_eur) == \
        ("ACTIVE", "sub_5", "sub_a", 1, 5.0)
    assert r.next_billing_at - r.last_payment_at == 31 * 86400
    queue.append(_Resp(200, {"id": "I-0002", "status": "WEIRD", "plan_id": "P-OTHER"}))
    r = bp.fetch("I-0002")
    assert (r.status, r.plan, r.next_billing_at, r.last_payment_at) == ("", "", None, None)


def test_list_payments_maps_states_and_skips_garbage(pp):
    calls, queue = pp
    queue.append(_Resp(200, {"transactions": [
        {"id": "SALE1", "status": "COMPLETED", "time": "2026-12-15T10:00:00Z",
         "amount_with_breakdown": {"gross_amount": {"value": "5.00", "currency_code": "EUR"}}},
        {"id": "SALE2", "status": "PARTIALLY_REFUNDED", "time": "2026-11-15T10:00:00Z",
         "amount_with_breakdown": {"gross_amount": {"value": "5.00", "currency_code": "EUR"}}},
        {"id": "../x", "status": "COMPLETED", "time": "2026-11-15T10:00:00Z",
         "amount_with_breakdown": {"gross_amount": {"value": "5.00"}}},
        {"id": "SALE3", "status": "DECLINED", "time": "bad"}]}))
    got = bp.list_payments("I-0001", 1_800_000_000, 1_800_086_400)
    assert [(p.payment_id, p.state, p.amount_eur, p.currency) for p in got] == \
        [("SALE1", "completed", 5.0, "EUR"), ("SALE2", "refunded", 5.0, "EUR")]
    assert calls[0]["params"] == {"start_time": "2027-01-15T08:00:00.000Z",
                                  "end_time": "2027-01-16T08:00:00.000Z"}


def test_cancel_and_already_cancelled_is_ok(pp):
    calls, queue = pp
    queue.append(_Resp(204))
    assert bp.cancel("I-0001", "user") is True
    assert calls[0]["url"].endswith("/v1/billing/subscriptions/I-0001/cancel")
    assert calls[0]["json"] == {"reason": "user"}
    queue.append(_Resp(422, {"name": "UNPROCESSABLE_ENTITY",
                             "details": [{"issue": "SUBSCRIPTION_STATUS_INVALID"}]}))
    assert bp.cancel("I-0001", "user") is True
    queue.append(_Resp(422, {"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "OTHER"}]}))
    with pytest.raises(bp.ProviderError):
        bp.cancel("I-0001", "user")


def test_refund_payment(pp):
    calls, queue = pp
    queue.append(_Resp(201, {"id": "R1", "state": "completed"}))
    assert bp.refund_payment("SALE9", 5) is True
    assert calls[0]["url"].endswith("/v1/payments/sale/SALE9/refund")
    assert calls[0]["json"] == {"amount": {"total": "5.00", "currency": "EUR"}}


def test_transient_error_retried_then_ok(pp):
    calls, queue = pp
    queue.extend([_Resp(503, {"name": "SERVICE_UNAVAILABLE"}),
                  requests.ConnectionError("reset"),
                  _Resp(200, {"id": "I-0001", "status": "ACTIVE"})])
    assert bp.fetch("I-0001").status == "ACTIVE"
    assert len(calls) == 3


def test_client_error_not_retried(pp):
    calls, queue = pp
    queue.append(_Resp(400, {"name": "INVALID_REQUEST", "details": [{"issue": "MISSING_FIELD"}]},
                       headers={"PayPal-Debug-Id": "dbg1"}))
    with pytest.raises(bp.ProviderError) as ei:
        bp.fetch("I-0001")
    assert (ei.value.status, ei.value.issue, ei.value.debug_id, ei.value.transient) == \
        (400, "MISSING_FIELD", "dbg1", False)
    assert len(calls) == 1


def test_bad_external_id_never_reaches_url(pp):
    calls, _queue = pp
    for bad in ("../x", "I-1/../../payments", "", None):
        with pytest.raises(ValueError):
            bp.fetch(bad)
        with pytest.raises(ValueError):
            bp.cancel(bad, "user")
    assert calls == []


_HDRS = {"PAYPAL-TRANSMISSION-ID": "t1", "PAYPAL-TRANSMISSION-TIME": "2026-10-23T10:00:00Z",
         "PAYPAL-TRANSMISSION-SIG": "sig", "PAYPAL-AUTH-ALGO": "SHA256withRSA",
         "PAYPAL-CERT-URL": "https://api.paypal.com/v1/notifications/certs/CERT-1"}


def test_verify_webhook_rejects_foreign_cert_url_without_remote_call(pp):
    calls, _queue = pp
    for url in ("https://evil.example/cert", "http://api.paypal.com/cert",
                "https://api.paypal.com.evil.example/cert"):
        assert bp.verify_webhook({**_HDRS, "PAYPAL-CERT-URL": url}, {"id": "WH-1"}) is False
    missing = dict(_HDRS)
    missing.pop("PAYPAL-TRANSMISSION-SIG")
    assert bp.verify_webhook(missing, {"id": "WH-1"}) is False
    assert calls == []


def test_verify_webhook_requires_success(pp, monkeypatch):
    calls, queue = pp
    queue.append(_Resp(200, {"verification_status": "SUCCESS"}))
    lower = {k.lower(): v for k, v in _HDRS.items()}            # header case-insensitive
    assert bp.verify_webhook(lower, {"id": "WH-1"}) is True
    body = calls[0]["json"]
    assert (body["webhook_id"], body["transmission_sig"], body["webhook_event"]) == \
        ("WH-ID", "sig", {"id": "WH-1"})
    queue.append(_Resp(200, {"verification_status": "FAILURE"}))
    assert bp.verify_webhook(_HDRS, {"id": "WH-1"}) is False
    queue.append(_Resp(400, {"name": "VALIDATION_ERROR"}))
    assert bp.verify_webhook(_HDRS, {"id": "WH-1"}) is False
    monkeypatch.setenv("ABM_PAYPAL_WEBHOOK_ID", "")
    assert bp.verify_webhook(_HDRS, {"id": "WH-1"}) is False


def test_parse_webhook_mapping():
    sale = {"id": "SALE1", "billing_agreement_id": "I-0001", "create_time": "2026-12-15T10:00:00Z",
            "amount": {"total": "5.00", "currency": "EUR"}}
    ev = bp.parse_webhook({"id": "WH-1", "event_type": "PAYMENT.SALE.COMPLETED", "resource": sale})
    assert (ev.type, ev.external_id, ev.payment.payment_id, ev.payment.amount_eur,
            ev.payment.state) == ("renewed", "I-0001", "SALE1", 5.0, "completed")
    refund = {"id": "R1", "sale_id": "SALE1", "amount": {"total": "5.00", "currency": "EUR"}}
    ev = bp.parse_webhook({"id": "WH-2", "event_type": "PAYMENT.SALE.REFUNDED", "resource": refund})
    assert (ev.type, ev.payment.payment_id, ev.payment.state) == ("payment_reversed", "SALE1", "refunded")
    ev = bp.parse_webhook({"id": "WH-3", "event_type": "PAYMENT.SALE.REVERSED", "resource": sale})
    assert (ev.type, ev.payment.payment_id, ev.payment.state) == ("payment_reversed", "SALE1", "reversed")
    for t in ("ACTIVATED", "RE-ACTIVATED", "UPDATED", "PAYMENT.FAILED", "SUSPENDED", "CANCELLED",
              "EXPIRED"):
        ev = bp.parse_webhook({"id": "WH-" + t, "event_type": "BILLING.SUBSCRIPTION." + t,
                               "resource": {"id": "I-0001"}})
        assert (ev.type, ev.external_id, ev.payment) == ("refresh", "I-0001", None)
    assert bp.parse_webhook({"id": "WH-4", "event_type": "PAYMENT.CAPTURE.COMPLETED",
                             "resource": {"id": "C1"}}) is None
    assert bp.parse_webhook({"id": "WH-5", "event_type": "PAYMENT.SALE.COMPLETED",
                             "resource": {"id": "SALE1"}}) is None          # vendita fuori abbonamento
    assert bp.parse_webhook({"event_type": "BILLING.SUBSCRIPTION.ACTIVATED",
                             "resource": {"id": "I-0001"}}) is None         # senza id evento
    assert bp.parse_webhook("garbage") is None


def test_available_needs_plans_and_webhook(pp, monkeypatch):
    monkeypatch.setattr(payment, "_paypal_available", lambda: True)
    assert bp.available() is True
    monkeypatch.setenv("ABM_PAYPAL_WEBHOOK_ID", "")
    assert bp.available() is False


def test_setup_plans_creates_missing_and_checks_existing(pp, monkeypatch):
    calls, queue = pp
    monkeypatch.setenv("ABM_PAYPAL_PLAN_SUB5", "")
    queue.extend([_Resp(201, {"id": "PROD-1"}), _Resp(201, {"id": "P-NEW5"}),
                  _Resp(200, {"status": "ACTIVE", "billing_cycles": [
                      {"pricing_scheme": {"fixed_price": {"value": "9.00", "currency_code": "EUR"}}}]})])
    out = []
    problems = bp.setup_plans({"sub_5": 5.0, "sub_10": 10.0}, out=out.append)
    assert "ABM_PAYPAL_PLAN_SUB5=P-NEW5" in out and problems == 1
    plan_body = calls[1]["json"]
    assert plan_body["billing_cycles"][0]["pricing_scheme"]["fixed_price"] == \
        {"value": "5.00", "currency_code": "EUR"}
    assert plan_body["payment_preferences"]["payment_failure_threshold"] == 1


def test_create_checkout_with_start_and_setup_fee(pp):
    calls, queue = pp
    queue.append(_Resp(201, {"id": "I-SCHED1", "links": [{"rel": "approve", "href": "https://pp/a"}]}))
    bp.create_checkout(sub_id="sub_s", plan="sub_10", email="", lang="it", return_url="r",
                       cancel_url="c", start_at=1_800_000_000, setup_fee_eur=10)
    body = calls[0]["json"]
    assert body["start_time"] == "2027-01-15T08:00:00.000Z"
    assert body["plan"] == {"payment_preferences": {
        "setup_fee": {"value": "10.00", "currency_code": "EUR"}, "setup_fee_failure_action": "CANCEL"}}
    queue.append(_Resp(201, {"id": "I-PLAIN1", "links": [{"rel": "approve", "href": "https://pp/a"}]}))
    bp.create_checkout(sub_id="sub_p", plan="sub_5", email="", lang="it", return_url="r", cancel_url="c")
    assert "start_time" not in calls[1]["json"] and "plan" not in calls[1]["json"]


def test_fetch_reads_start_time(pp):
    _calls, queue = pp
    queue.append(_Resp(200, {"id": "I-0003", "status": "ACTIVE", "plan_id": "P-FIVE",
                             "start_time": "2026-10-27T16:31:51Z",
                             "billing_info": {"next_billing_time": "2026-10-27T10:00:00Z"}}))
    r = bp.fetch("I-0003")
    assert r.start_at == bp._epoch("2026-10-27T16:31:51Z") and r.last_payment_at is None
