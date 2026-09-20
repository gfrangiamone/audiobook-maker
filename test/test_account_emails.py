"""Email account: codice/magic link e conferma cancellazione, 7 lingue."""
import json
from pathlib import Path

import pytest

import email_service

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
KEYS = ["brand", "login_subject", "login_body", "delete_subject", "delete_body",
        "deleted_subject", "deleted_body", "footer"]


@pytest.fixture
def sent(monkeypatch):
    box = []
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subject, body, **kw: box.append((to, subject, body)) or True)
    return box


def test_i18n_file_complete():
    data = json.loads((Path("i18n") / "account_emails.json").read_text(encoding="utf-8"))
    assert sorted(data) == sorted(LANGS)
    for lang in LANGS:
        assert sorted(data[lang]) == sorted(KEYS), lang
        assert "{code}" in data[lang]["login_body"] and "{link_url}" in data[lang]["login_body"]
        assert "{minutes}" in data[lang]["login_body"]
        assert "{code}" in data[lang]["delete_body"] and "{link_url}" in data[lang]["delete_body"]


@pytest.mark.parametrize("lang", LANGS + ["xx"])
def test_send_account_code_login(sent, lang):
    ok = email_service.send_account_code("a@b.it", lang, code="123456",
                                         link_url="https://x.test/auth/T0K", purpose="login",
                                         minutes=10)
    assert ok is True
    to, subject, body = sent[0]
    assert to == "a@b.it"
    assert "123456" in body and "https://x.test/auth/T0K" in body and "10" in body


def test_send_account_code_delete_uses_delete_texts(sent):
    email_service.send_account_code("a@b.it", "it", code="654321", link_url="https://x/auth/D",
                                    purpose="delete", minutes=10)
    _, subject, body = sent[0]
    data = json.loads((Path("i18n") / "account_emails.json").read_text(encoding="utf-8"))
    assert subject == data["it"]["delete_subject"]
    assert "654321" in body


def test_send_account_code_escapes_values(sent):
    email_service.send_account_code("a@b.it", "en", code="<b>1</b>", link_url="https://x/auth/T",
                                    purpose="login", minutes=10)
    assert "<b>1</b>" not in sent[0][2] and "&lt;b&gt;" in sent[0][2]


def test_send_account_code_rejects_bad_purpose(sent):
    assert email_service.send_account_code("a@b.it", "en", code="1", link_url="u",
                                           purpose="reset", minutes=10) is False
    assert sent == []


def test_send_account_deleted(sent):
    assert email_service.send_account_deleted("a@b.it", "de") is True
    assert sent[0][0] == "a@b.it"


def test_send_returns_false_on_smtp_error(monkeypatch):
    monkeypatch.setattr(email_service, "_send_email", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp")))
    assert email_service.send_account_code("a@b.it", "en", code="1", link_url="u",
                                           purpose="login", minutes=10) is False
