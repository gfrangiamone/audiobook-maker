# test/test_subscription_texts.py
"""Area personale, email e testi degli abbonamenti (fase 2a)."""
import json
import re

import pytest

import account_page
import accounts
import email_service
import i18n

LANGS = ("it", "en", "fr", "es", "de", "zh", "hi")
_PH = re.compile(r"\{(\w+)\}")


def _t(lang="it"):
    return i18n.pick(i18n.load("account_pages"), lang)


@pytest.mark.parametrize("table,prefix", [("account_pages", "sub_"),
                                          ("account_emails", "subscription_")])
def test_subscription_keys_all_langs_same_placeholders(table, prefix):
    with open(f"i18n/{table}.json", encoding="utf-8") as f:
        data = json.load(f)
    keys = [k for k in data["en"] if k.startswith(prefix)]
    assert keys
    for lang in LANGS:
        for k in keys:
            assert data[lang].get(k), f"{lang}.{k} mancante"
            assert set(_PH.findall(data[lang][k])) == set(_PH.findall(data["en"][k])), f"{lang}.{k}"


def test_no_provider_names_in_subscription_texts():
    for table in ("account_pages", "account_emails"):
        with open(f"i18n/{table}.json", encoding="utf-8") as f:
            data = json.load(f)
        for lang in LANGS:
            text = " ".join(v for k, v in data[lang].items() if k.startswith(("sub_", "subscription_")))
            for name in ("PayPal", "Gemini", "DeepSeek", "VoxCPM", "Speechify", "Stripe"):
                assert name not in text, f"{table}.{lang}: {name}"


def test_oneoff_notice_updated():
    with open("templates/_fragments/i18n_data.js", encoding="utf-8") as f:
        js = f.read()
    assert "nessun abbonamento, nessun" not in js and "no subscription, no recurring" not in js
    assert "no subscription or recurring charge needed" in js
    with open("templates/_fragments/html_head.html", encoding="utf-8") as f:
        assert "non è necessario nessun abbonamento" in f.read()


def _status(sub=None, enabled=True):
    return {"enabled": enabled, "subscription": sub, "plans": [
        {"plan": "sub_5", "price_eur": 5.0, "voucher_eur": 5.0, "quota_bytes": 5 * accounts.GIB},
        {"plan": "sub_10", "price_eur": 10.0, "voucher_eur": 10.0, "quota_bytes": 10 * accounts.GIB}]}


def test_subscription_block_offers_plans_with_withdrawal_box():
    html = account_page._subscription_block(_t(), _status(), tolerance_days=15)
    assert html.count("data-subplan=") == 2 and 'id="subDlg_sub_10"' in html
    box = re.findall(r"<input[^>]*data-subwaive[^>]*>", html)
    assert len(box) == 2 and all("required" in b and "checked" not in b for b in box)
    assert all("disabled" in b for b in re.findall(r"<button[^>]*data-subgo[^>]*>", html))
    assert "10 GB" in html and "10 €" in html


def test_subscription_block_empty_when_disabled_without_subscription():
    assert account_page._subscription_block(_t(), _status(enabled=False)) == ""
    assert account_page._subscription_block(_t(), None) == ""


def test_subscription_block_active_cancelled_and_past_due():
    t = _t()
    sub = {"plan": "sub_5", "status": "active", "period_end": 1_800_000_000, "renews": True,
           "ends_at": None, "voucher": {"remaining_eur": 3.5, "expires_at": 1_800_000_000}}
    html = account_page._subscription_block(t, _status(sub, enabled=False), tolerance_days=15)
    assert 'id="subCancel"' in html and 'id="subCancelDlg"' in html and "3.50" in html
    assert "data-subplan" not in html
    past = account_page._subscription_block(t, _status(dict(sub, status="past_due")))
    assert account_page._e(t["sub_past_due"]) in past
    gone = account_page._subscription_block(t, _status(dict(sub, status="cancelled", ends_at=1)))
    assert 'id="subCancel"' not in gone and "2027-01-15" in gone
    act = account_page._subscription_block(t, _status(dict(sub, status="activating")))
    assert account_page._e(t["sub_activating"]) in act and "data-subplan" not in act


def test_subscription_block_notice_whitelisted():
    t = _t()
    assert t["sub_notice_ok"] in account_page._subscription_block(t, _status(), notice="ok")
    assert "<script" not in account_page._subscription_block(t, _status(), notice="<script>")


def test_plan_header_hides_free_buttons_when_paid():
    t = _t()
    acct = {"free_consent_at": 1, "email": "a@x.it"}
    paid = {"plan": "sub_5", "plan_source": "paid", "plan_until": 2_000_000_000,
            "quota_bytes": 5 * accounts.GIB, "used_bytes": 0, "state": "active"}
    html = account_page._plan_header(t, acct, paid, free_quota_bytes=512 * accounts.MIB,
                                     tolerance_days=15)
    assert "freePlanOff" not in html and "freePlanDlg" not in html
    free = dict(paid, plan="free", plan_source="")
    assert "freePlanOff" in account_page._plan_header(t, acct, free, free_quota_bytes=1,
                                                      tolerance_days=15)


@pytest.mark.parametrize("lang", LANGS)
def test_subscription_emails_compose_in_every_language(lang, monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subject, body, **k: sent.append((subject, body)) or True)
    assert email_service.send_subscription_active("a@x.it", lang, space="5 GB", voucher="5",
                                                  voucher_until="2027-01-15", renews_at="2027-01-14")
    assert email_service.send_subscription_cancelled("a@x.it", lang, space="5 GB",
                                                     ends_at="2027-01-14", days=15)
    assert len(sent) == 2
    for subject, body in sent:
        assert subject and "{" not in body and "/account" in body


def test_admin_alert_escapes_details(monkeypatch):
    sent = []
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@x.it")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subject, body, **k: sent.append((to, subject, body)))
    email_service.admin_notify_subscription("refund_failed", {"payment": "<b>x</b>", "amount": 5.0})
    to, subject, body = sent[0]
    assert to == "admin@x.it" and "rimborso" in subject and "<b>x</b>" not in body
