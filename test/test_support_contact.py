"""Form pubblico "Contatta supporto": endpoint, validazione, email."""
import re
from pathlib import Path

import pytest

import audiobook_app
import email_service


VALID = {
    "email": "utente@example.com",
    "plan": "premium",
    "book_title": "I Promessi Sposi",
    "download_link": "https://audiobook-maker.com/dl/abc123",
    "message": "Il file M4B scaricato si interrompe a meta' del capitolo 3.",
    "lang": "it",
}


@pytest.fixture
def client():
    # svuota il bucket del rate limit IP: i test condividono 127.0.0.1
    audiobook_app._ip_rl_buckets.pop("support", None)
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


@pytest.fixture
def sent(monkeypatch):
    """Cattura le chiamate a send_support_request senza toccare l'SMTP."""
    calls = []

    def _fake(*args, **kwargs):
        calls.append((args, kwargs))
        return True

    monkeypatch.setattr(audiobook_app.email_service, "send_support_request", _fake)
    return calls


def test_valid_request_sends_email(client, sent):
    r = client.post("/api/support/contact", json=VALID)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.get_json() == {"ok": True}
    assert len(sent) == 1
    args, kwargs = sent[0]
    assert args[0] == "utente@example.com"
    assert args[1] == "premium"
    assert args[2] == "I Promessi Sposi"
    assert args[3] == "https://audiobook-maker.com/dl/abc123"
    assert "capitolo 3" in args[4]
    assert kwargs["ui_lang"] == "it"
    assert kwargs["ip_hash"]


def test_download_link_is_optional(client, sent):
    body = dict(VALID)
    body.pop("download_link")
    r = client.post("/api/support/contact", json=body)
    assert r.status_code == 200
    assert sent[0][0][3] == ""


@pytest.mark.parametrize("patch,expected", [
    ({"email": "non-una-email"}, "invalid_email"),
    ({"email": ""}, "invalid_email"),
    ({"plan": "gratis"}, "invalid_plan"),
    ({"plan": ""}, "invalid_plan"),
    ({"book_title": "   "}, "missing_title"),
    ({"message": "corto"}, "missing_message"),
])
def test_validation_errors(client, sent, patch, expected):
    body = dict(VALID)
    body.update(patch)
    r = client.post("/api/support/contact", json=body)
    assert r.status_code == 400
    assert r.get_json()["error"] == expected
    assert sent == []


def test_honeypot_is_silently_accepted(client, sent):
    body = dict(VALID)
    body["website"] = "http://spam.example"
    r = client.post("/api/support/contact", json=body)
    assert r.status_code == 200
    assert sent == [], "il honeypot non deve generare email"


def test_rate_limit_after_burst(client, sent):
    limit = audiobook_app._SUPPORT_RL_PER_MIN
    for _ in range(limit):
        assert client.post("/api/support/contact", json=VALID).status_code == 200
    r = client.post("/api/support/contact", json=VALID)
    assert r.status_code == 429
    assert r.get_json()["error"] == "rate_limit"
    assert len(sent) == limit


def test_send_failure_returns_502(client, monkeypatch):
    monkeypatch.setattr(audiobook_app.email_service, "send_support_request",
                        lambda *a, **k: False)
    r = client.post("/api/support/contact", json=VALID)
    assert r.status_code == 502
    assert r.get_json()["error"] == "send_failed"


# ── email_service.send_support_request ────────────────────────────────

@pytest.fixture
def captured(monkeypatch):
    box = {}

    def _fake(to_addr, subject, html_body, reply_to=None):
        box.update(to=to_addr, subject=subject, body=html_body, reply_to=reply_to)
        return True

    monkeypatch.setattr(email_service, "_send_email", _fake)
    return box


def test_support_email_goes_to_support_box_with_reply_to(captured, monkeypatch):
    monkeypatch.setattr(email_service, "SUPPORT_EMAIL", "support@audiobook-maker.com")
    ok = email_service.send_support_request(
        "utente@example.com", "free", "Titolo", "", "Descrizione del problema.")
    assert ok is True
    assert captured["to"] == "support@audiobook-maker.com"
    assert captured["reply_to"] == "utente@example.com"
    assert "Titolo" in captured["subject"]


def test_support_email_escapes_user_input(captured):
    email_service.send_support_request(
        "utente@example.com", "free",
        "<img src=x onerror=alert(1)>",
        "javascript:alert(1)",
        "<script>alert(1)</script> problema serio")
    body = captured["body"]
    assert "<script>" not in body
    assert "<img src=x" not in body
    assert "&lt;script&gt;" in body


def test_foreign_download_link_is_not_clickable(captured, monkeypatch):
    monkeypatch.setattr(email_service, "BASE_URL", "https://audiobook-maker.com")
    email_service.send_support_request(
        "utente@example.com", "free", "Titolo",
        "https://phishing.example/steal", "Descrizione del problema.")
    assert 'href="https://phishing.example' not in captured["body"]
    assert "https://phishing.example/steal" in captured["body"]


def test_own_download_link_is_clickable(captured, monkeypatch):
    monkeypatch.setattr(email_service, "BASE_URL", "https://audiobook-maker.com")
    email_service.send_support_request(
        "utente@example.com", "free", "Titolo",
        "https://audiobook-maker.com/dl/tok", "Descrizione del problema.")
    assert 'href="https://audiobook-maker.com/dl/tok"' in captured["body"]


# ── UI: link nel footer, markup del modal, i18n ───────────────────────

ROOT = Path(__file__).resolve().parent.parent
HEAD = ROOT / "templates" / "_fragments" / "html_head.html"
I18N = ROOT / "templates" / "_fragments" / "i18n_data.js"
APP_JS = ROOT / "static" / "js" / "app.js"
LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
SUP_KEYS = [
    "footer_support", "sup_title", "sup_intro", "sup_email_label", "sup_email_ph",
    "sup_plan_label", "sup_plan_choose", "sup_plan_free", "sup_plan_premium",
    "sup_book_label", "sup_book_ph", "sup_link_label", "sup_link_ph",
    "sup_link_hint", "sup_msg_label", "sup_msg_ph", "sup_submit", "sup_sending",
    "sup_ok", "sup_err_email", "sup_err_plan", "sup_err_book", "sup_err_msg",
    "sup_err_rate", "sup_err_send", "sup_err_network",
]


def test_footer_has_support_link():
    html = HEAD.read_text(encoding="utf-8")
    assert 'id="supportBtn"' in html
    assert 'data-t="footer_support"' in html
    # deve stare nella riga di link del footer, accanto a privacy
    footer = html.split('<footer class="footer-bar">')[1].split("</footer>")[0]
    assert 'id="supportBtn"' in footer


def test_support_modal_markup_complete():
    html = HEAD.read_text(encoding="utf-8")
    for el_id in ("supportModal", "supportForm", "supEmail", "supPlan", "supBook",
                  "supLink", "supMsg", "supHoneypot", "supSubmit", "supMsgBox"):
        assert f'id="{el_id}"' in html, f"manca #{el_id}"
    assert '<option value="free"' in html
    assert '<option value="premium"' in html


def test_support_i18n_keys_in_all_langs():
    js = I18N.read_text(encoding="utf-8")
    missing = []
    for lang in LANGS:
        m = re.search(r"Object\.assign\(L\." + lang + r",\{(.*?footer_support.*?)\}\);", js)
        block = m.group(1) if m else ""
        for k in SUP_KEYS:
            if f"{k}:" not in block:
                missing.append(f"{lang}.{k}")
    assert not missing, f"chiavi i18n mancanti: {missing}"


def test_app_js_wires_support_form():
    js = APP_JS.read_text(encoding="utf-8")
    assert "/api/support/contact" in js
    assert "openSupportModal" in js
    assert "closeSupportModal" in js
    # i placeholder del form devono seguire il cambio lingua
    assert "[data-t-ph]" in js.split("function applyI18n")[1].split("function setLang")[0]
