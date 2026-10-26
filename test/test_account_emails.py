"""Email account: codice/magic link e conferma cancellazione, 7 lingue."""
import json
import re
from pathlib import Path

import pytest

import accounts
import email_service
import i18n
from test.test_archive_tolerance import T0, _archived, _login, _upload, env  # noqa: F401

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
ARCHIVE_KEYS = ["archive_over_subject", "archive_over_body", "archive_off_subject",
                "archive_off_body", "archive_remind_subject", "archive_remind_body",
                "archive_books_more"]
SUBSCRIPTION_KEYS = ["subscription_active_subject", "subscription_active_body",
                     "subscription_cancelled_subject", "subscription_cancelled_body",
                     "subscription_voucher_subject", "subscription_voucher_body",
                     "subscription_reminder_subject", "subscription_reminder_body",
                     "subscription_voucher_scope"]
KEYS = ["brand", "login_subject", "login_body", "delete_subject", "delete_body",
        "deleted_subject", "deleted_body", "footer", *ARCHIVE_KEYS, *SUBSCRIPTION_KEYS]


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
    assert subject == data["it"]["delete_subject"].format(code="654321")
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


def test_send_account_code_bad_minutes_returns_false(sent):
    assert email_service.send_account_code("a@b.it", "en", code="123456", link_url="https://x/auth/T",
                                           purpose="login", minutes="abc") is False
    assert sent == []


def _table():
    return json.loads((Path("i18n") / "account_emails.json").read_text(encoding="utf-8"))


def _mail_args(books, **kw):
    return dict(books=books, deadline="2027-01-30", quota="512 MB", used="600 MB",
                manage_url="https://x.test/account", **kw)


def test_archive_keys_in_every_language_without_provider_names():
    data = _table()
    assert sorted(i18n.LANGS) == sorted(LANGS)
    for lang in i18n.LANGS:
        for key in ARCHIVE_KEYS:
            text = data[lang][key]
            assert text.strip(), (lang, key)
            assert not re.search(r"DeepSeek|Gemini|Speechify|VoxCPM", text, re.I), (lang, key)
        for key in ("archive_over_body", "archive_off_body", "archive_remind_body"):
            body = data[lang][key]
            assert "{books_html}" in body and "{deadline}" in body and "{manage_url}" in body, (lang, key)
        assert "{n}" in data[lang]["archive_books_more"], lang
        assert "{quota}" in data[lang]["archive_over_body"] and "{used}" in data[lang]["archive_over_body"]
        assert "{used}" in data[lang]["archive_off_body"] and "{used}" in data[lang]["archive_remind_body"]
        assert "{deadline}" in data[lang]["archive_off_subject"]
        assert "{deadline}" in data[lang]["archive_remind_subject"]


@pytest.mark.parametrize("lang", LANGS + ["xx"])
def test_send_archive_mails_in_every_language(sent, lang):
    books = [("Titolo", "10 MB")]
    assert email_service.send_archive_over("a@b.it", lang, **_mail_args(books)) is True
    assert email_service.send_archive_over("a@b.it", lang, **_mail_args(books), off=True) is True
    assert email_service.send_archive_remind("a@b.it", lang, **_mail_args(books)) is True
    assert len(sent) == 3
    for to, subject, body in sent:
        assert to == "a@b.it" and subject
        assert "<li>Titolo (10 MB)</li>" in body and "2027-01-30" in body
        assert 'href="https://x.test/account"' in body
        for left in ("{books_html}", "{deadline}", "{manage_url}", "{used}", "{quota}"):
            assert left not in body


def test_off_uses_off_texts_and_over_uses_over_texts(sent):
    data = _table()["en"]
    email_service.send_archive_over("a@b.it", "en", **_mail_args([("T", "1 MB")], off=True))
    email_service.send_archive_over("a@b.it", "en", **_mail_args([("T", "1 MB")]))
    email_service.send_archive_remind("a@b.it", "en", **_mail_args([("T", "1 MB")]))
    assert sent[0][1] == data["archive_off_subject"].format(deadline="2027-01-30")
    assert sent[1][1] == data["archive_over_subject"]
    assert sent[2][1] == data["archive_remind_subject"].format(deadline="2027-01-30")
    assert "600 MB" in sent[0][2] and "512 MB" in sent[1][2] and "512 MB" in sent[2][2]


def test_books_html_escapes_and_falls_back(sent, env):  # noqa: F811
    books = [("<b>X</b>", "1 MB")] + [(f"Libro {i}", "2 MB") for i in range(30)]
    assert len(books) == 31
    assert email_service.send_archive_over("a@b.it", "en", **_mail_args(books)) is True
    body = sent[0][2]
    assert "<b>X</b>" not in body and "&lt;b&gt;X&lt;/b&gt; (1 MB)" in body
    assert body.count("<li>") == 30 and "Libro 28" in body and "Libro 29" not in body
    assert _table()["en"]["archive_books_more"].format(n=1) in body
    assert "<script" not in body
    a = _login("a@b.it")
    _archived(a, "j_notitle", 10, at=T0)
    _upload(a, "i_notitle", 10, at=T0 + 1, filename="libro.m4b")
    titles = {e["id"]: e["title"] for e in accounts.archive_entries(a["id"])}
    assert titles == {"j_notitle": "j_notitle", "i_notitle": "libro.m4b"}


def test_books_html_exact_limit_has_no_more_line(sent):
    books = [(f"L{i}", "1 MB") for i in range(30)]
    email_service.send_archive_over("a@b.it", "en", **_mail_args(books))
    body = sent[0][2]
    assert body.count("<li>") == 30
    assert _table()["en"]["archive_books_more"].format(n=0) not in body


def test_archive_mail_url_values_stay_unescaped_and_other_values_escaped(sent):
    email_service.send_archive_over("a@b.it", "en", **{**_mail_args([("T", "1 MB")]),
                                                       "used": "<i>1</i>", "quota": "<u>2</u>"})
    body = sent[0][2]
    assert "<i>1</i>" not in body and "&lt;i&gt;1&lt;/i&gt;" in body
    assert "<u>2</u>" not in body and "&lt;u&gt;2&lt;/u&gt;" in body
    assert 'href="https://x.test/account"' in body


def test_send_archive_returns_false_on_smtp_error(monkeypatch):
    monkeypatch.setattr(email_service, "_send_email",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("smtp")))
    assert email_service.send_archive_over("a@b.it", "en", **_mail_args([("T", "1 MB")])) is False
    assert email_service.send_archive_remind("a@b.it", "en", **_mail_args([("T", "1 MB")])) is False


def test_send_archive_returns_false_when_books_cannot_be_composed(sent, monkeypatch, capsys):
    """L'elenco dei libri si compone prima dell'invio: un testo rotto o una forma sbagliata
    non fanno uscire un'eccezione (il chiamante si aspetta sempre un bool)."""
    many = [(f"L{i}", "1 MB") for i in range(31)]
    real = email_service._acct_t
    monkeypatch.setattr(email_service, "_acct_t", lambda lang: {**real(lang), "archive_books_more": "{x} {"})
    assert email_service.send_archive_over("a@b.it", "en", **_mail_args(many)) is False
    assert email_service.send_archive_remind("a@b.it", "en", **_mail_args(many)) is False
    assert "[email]" in capsys.readouterr().out
    monkeypatch.setattr(email_service, "_acct_t", real)
    for bad in ([("solo titolo",)], [None], None, 5):
        assert email_service.send_archive_over("a@b.it", "en", **_mail_args(bad)) is False
        assert email_service.send_archive_remind("a@b.it", "en", **_mail_args(bad)) is False
    assert sent == []
    assert email_service.send_archive_over("a@b.it", "en", **_mail_args(many)) is True
    assert len(sent) == 1


@pytest.mark.parametrize("key", ARCHIVE_KEYS)
def test_archive_placeholders_match_english_in_every_language(key):
    data = _table()
    want = set(re.findall(r"\{(\w+)\}", data["en"][key]))
    for lang in LANGS:
        assert set(re.findall(r"\{(\w+)\}", data[lang][key])) == want, (lang, key)
