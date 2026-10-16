# test/test_account_job_search.py
"""Ricerca per titolo nell'area personale su tutto lo storico (non sulla
pagina caricata) e filtro dei soli audiolibri per l'app."""
import pytest

import accounts
import db


@pytest.fixture
def acct(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    tok, _ = accounts.request_code("a@b.it", "login")
    a = accounts.verify(token=tok)[1]
    yield a
    db.close()


def _job(a, jid, title, kind="generate", fmt="m4b", created=1):
    accounts.record_job(a["id"], jid, kind=kind, status="done", book_title=title,
                        output_format=fmt, created_at=created)


def test_search_spans_whole_history_case_insensitive(acct):
    for i in range(120):
        _job(acct, f"j{i}", f"Libro {i}", created=1000 + i)
    _job(acct, "old", "La Storia Infinita", created=1)   # il piu' vecchio di tutti
    rows, total = accounts.list_jobs(acct["id"], page=1, per_page=50, q="storia infinita")
    assert total == 1 and [r["job_id"] for r in rows] == ["old"]
    rows, total = accounts.list_jobs(acct["id"], page=1, per_page=50, q="libro 11")
    assert total == 11      # 11, 110..119
    assert accounts.list_jobs(acct["id"], q="")[1] == 121


def test_search_escapes_like_wildcards(acct):
    _job(acct, "a", "Sconto 100% vero")
    _job(acct, "b", "Sconto 1000 falso")
    _job(acct, "c", "nome_con_underscore")
    _job(acct, "d", "nomeXconXunderscore")
    assert [r["job_id"] for r in accounts.list_jobs(acct["id"], q="100%")[0]] == ["a"]
    assert [r["job_id"] for r in accounts.list_jobs(acct["id"], q="e_c")[0]] == ["c"]


def test_audio_only_filter(acct):
    _job(acct, "m4b", "A")
    _job(acct, "mp3", "B", fmt="mp3")
    _job(acct, "nofmt", "C", fmt="")
    _job(acct, "zip", "D", fmt="zip")
    _job(acct, "opt", "E", kind="optimize", fmt="")
    _job(acct, "optaudio", "F", kind="optimize", fmt="m4b")
    _job(acct, "tr", "G", kind="translate", fmt="")
    ids = {r["job_id"] for r in accounts.list_jobs(acct["id"], audio_only=True)[0]}
    assert ids == {"m4b", "mp3", "nofmt", "optaudio"}
    assert accounts.list_jobs(acct["id"], audio_only=True)[1] == 4


def test_endpoint_passes_query(acct, monkeypatch):
    import audiobook_app
    import routes_account
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(routes_account, "_current_account", lambda: acct)
    seen = {}

    def fake_rows(a, page, q="", audio_only=False):
        seen.update(page=page, q=q, audio=audio_only)
        return [], 0
    monkeypatch.setattr(routes_account, "_account_rows_for", fake_rows)
    c = audiobook_app.app.test_client()
    r = c.get("/api/account/jobs?p=2&q=storia&audio=1")
    assert r.status_code == 200
    assert seen == {"page": 2, "q": "storia", "audio": True}
    c.get("/api/account/jobs")
    assert seen == {"page": 1, "q": "", "audio": False}
