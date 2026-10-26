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
    assert "data-subpoll" in act and "data-subpoll" not in html


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


# ------------------------------------------------------------------ fase 2b: schede e cambi

def _prev(mode, kind):
    return {"kind": kind, "mode": mode, "charge_today_eur": 10.0 if mode == "prepaid" else 0.0,
            "period_from": 1_800_000_000, "period_to": 1_802_678_400 if mode == "prepaid" else None}


def _status2(sub, changes, change=None, enabled=True):
    st = _status(sub, enabled)
    for p in st["plans"]:
        p["change"] = changes.get(p["plan"])
    if change:
        st["change"] = change
    return st


_ACTIVE5 = {"plan": "sub_5", "status": "active", "period_end": 1_800_000_000, "renews": True,
            "ends_at": None, "voucher": None}


def test_cards_show_switch_on_the_other_plan():
    t = _t()
    html = account_page._subscription_block(
        t, _status2(_ACTIVE5, {"sub_10": _prev("prepaid", "upgrade")}),
        tolerance_days=15, free_quota_bytes=512 * accounts.MIB, free_active=True)
    assert html.count(account_page._e(t["sub_current_badge"])) == 1           # solo sul 5 GB
    assert 'data-subchange="sub_10"' in html and 'id="subChgDlg_sub_10"' in html
    assert 'id="subCancel"' in html and "data-subplan" not in html
    assert "10 €" in html and "2027-01-15" in html and "2027-02-15" in html  # addebito e periodo
    box = re.findall(r"<button[^>]*data-subchgo[^>]*>", html)
    assert box and all("disabled" in b for b in box)


def test_cards_after_cancel_offer_reactivate_same_and_other_plan():
    t = _t()
    gone = dict(_ACTIVE5, status="cancelled", ends_at=1_800_000_000, renews=False)
    html = account_page._subscription_block(
        t, _status2(gone, {"sub_5": _prev("scheduled", "resume"), "sub_10": _prev("prepaid", "resume")}))
    assert 'data-subchange="sub_5"' in html and 'data-subchange="sub_10"' in html
    assert account_page._e(t["sub_resume_btn"]) in html
    assert account_page._e(t["sub_resume_other_btn"]) in html
    assert 'id="subCancel"' not in html


def test_cards_with_pending_change_hide_reactivate_and_show_cancel_change():
    t = _t()
    gone = dict(_ACTIVE5, status="cancelled", ends_at=1_800_000_000, renews=False)
    change = {"kind": "resume", "plan": "sub_5", "status": "scheduled", "start_at": 1_800_000_000,
              "approved": True}
    html = account_page._subscription_block(t, _status2(gone, {}, change))
    assert "data-subchange" not in html and 'id="subChangeCancel"' in html
    paying = dict(change, kind="upgrade", plan="sub_10", status="switching")
    html = account_page._subscription_block(t, _status2(_ACTIVE5, {}, paying))
    assert 'data-subpoll="change"' in html


def test_downgrade_dialog_says_no_charge_today():
    t = _t()
    ten = dict(_ACTIVE5, plan="sub_10")
    html = account_page._subscription_block(
        t, _status2(ten, {"sub_5": _prev("scheduled", "downgrade")}), tolerance_days=15)
    assert account_page._e(t["sub_change_down_p"].split(".")[0]) in html and "15" in html
