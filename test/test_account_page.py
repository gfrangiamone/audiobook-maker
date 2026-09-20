# test/test_account_page.py
"""Pagina /account, API storico e cancellazione self-service."""
import json
import time
from pathlib import Path

import pytest

import accounts
import audiobook_app
import db
import email_service
import voice_clone as vc
import community_store

T0 = 1_800_000_000


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_download_tokens", {})
    monkeypatch.setattr(audiobook_app, "_save_tokens", lambda: None)
    monkeypatch.setattr(audiobook_app, "_file_available", lambda p: True)
    audiobook_app._ip_rl_buckets.pop("auth_request", None)
    box = {"codes": [], "deleted": []}
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: box["codes"].append((email, kw)) or True)
    monkeypatch.setattr(email_service, "send_account_deleted",
                        lambda email, lang: box["deleted"].append(email) or True)
    audiobook_app.app.config["TESTING"] = True
    yield box
    db.close()


@pytest.fixture
def logged(env):
    c = audiobook_app.app.test_client()
    c.post("/api/auth/request", json={"email": "a@b.it", "lang": "it"})
    code = env["codes"][-1][1]["code"]
    r = c.post("/api/auth/verify", json={"email": "a@b.it", "code": code})
    assert r.status_code == 200
    acct = accounts.account_for_email("a@b.it")
    return c, acct


def _token(job_id, dl_type="audio", created_at=None, **extra):
    info = {"job_id": job_id, "created_at": created_at if created_at is not None else time.time(),
            "download_type": dl_type, "base_url": "https://abm.test", "book_title": "B"}
    info.update(extra)
    tok = "tok-" + job_id
    audiobook_app._download_tokens[tok] = info
    return tok


def test_i18n_complete():
    d = json.loads((Path(audiobook_app.SCRIPT_DIR) / "i18n" / "account_pages.json").read_text(encoding="utf-8"))
    assert set(d) == {"en", "it", "fr", "es", "de", "zh", "hi"}
    for lang, t in d.items():
        assert set(t) == set(d["en"]), lang
        assert "..." not in t, lang


def test_account_page_redirects_without_session(env):
    c = audiobook_app.app.test_client()
    r = c.get("/account")
    assert r.status_code == 302 and r.headers["Location"].endswith("/?login=1")


def test_account_page_disabled_404(env, monkeypatch):
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert audiobook_app.app.test_client().get("/account").status_code == 404


def test_account_page_lists_jobs_with_downloads(logged, monkeypatch):
    c, acct = logged
    accounts.record_job(acct["id"], "j1", kind="generate", book_title="Il Gattopardo <b>",
                        output_format="m4b", voice="Alice <i>", status="done", created_at=T0)
    accounts.record_job(acct["id"], "j2", kind="translate", book_title="Old", status="done",
                        created_at=T0 - 86400 * 400)
    _token("j1", "audio", output_m4b="/x/a.m4b")
    accounts.set_download_token("j1", "tok-j1")
    _token("j2", "translated", created_at=T0 - 86400 * 400)
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 3600.0)
    r = c.get("/account", headers={"Accept-Language": "it"})
    assert r.status_code == 200
    html = r.data.decode()
    assert "Il Gattopardo &lt;b&gt;" in html and "<b>" not in html.split("Gattopardo")[1][:10]
    assert "M4B" in html and "Alice &lt;i&gt;" in html
    assert "<i>" not in html.split("Alice")[1][:20]
    assert "/dl/tok-j1" in html and "/dl/tok-j1/m4b" in html
    assert "/dl/tok-j2" not in html and "scaduto" in html
    assert "Connesso come" in html and "a@b.it" in html
    assert "no-store" in r.headers.get("Cache-Control", "")


def test_account_page_voices_links(logged, monkeypatch):
    c, acct = logged
    monkeypatch.setattr(audiobook_app, "_account_voices_for",
                        lambda a: [{"name": "Nonna <b>", "url": "https://abm.test/vc/mt1/devices"}])
    r = c.get("/account")
    assert r.status_code == 200
    html = r.data.decode()
    assert 'href="https://abm.test/vc/mt1/devices"' in html
    assert "Nonna &lt;b&gt;" in html and "<b>" not in html.split("Nonna")[1][:10]
    assert "1" in html


def test_api_jobs_pagination_and_shape(logged, monkeypatch):
    c, acct = logged
    for i in range(3):
        accounts.record_job(acct["id"], f"j{i}", kind="generate", status="done", created_at=T0 + i)
    monkeypatch.setattr(audiobook_app, "_ACCT_PER_PAGE", 2)
    r = c.get("/api/account/jobs?p=2")
    assert r.status_code == 200
    d = r.get_json()
    assert d["page"] == 2 and d["total"] == 3 and d["per_page"] == 2 and len(d["jobs"]) == 1
    j = d["jobs"][0]
    assert set(j) >= {"job_id", "created_at", "kind", "book_title", "output_format", "status",
                      "paid_eur", "downloads"}
    assert j["job_id"] == "j0" and j["downloads"] == []


def test_api_jobs_requires_session(env):
    c = audiobook_app.app.test_client()
    assert c.get("/api/account/jobs").status_code == 401


def test_downloads_for_handles_types_and_expiry(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 100.0)
    now = time.time()
    _token("ja", "audio", created_at=now - 10, output_m4b="")
    _token("jb", "optimized_abm", created_at=now - 10)
    _token("jc", "translated", created_at=now - 10)
    _token("jd", "audio", created_at=now - 500)
    f = audiobook_app._account_downloads_for
    assert [d["kind"] for d in f({"job_id": "ja", "download_token": ""}, now)] == ["page"]
    assert [d["kind"] for d in f({"job_id": "jb", "download_token": "tok-jb"}, now)] == ["page", "abm"]
    kinds = [d["kind"] for d in f({"job_id": "jc", "download_token": ""}, now)]
    assert kinds == ["page", "translated"]
    assert f({"job_id": "jd", "download_token": "tok-jd"}, now) == []
    assert f({"job_id": "nope", "download_token": ""}, now) == []
    d = f({"job_id": "ja", "download_token": ""}, now)[0]
    assert d["url"] == "https://abm.test/dl/tok-ja" and abs(d["expires_at"] - (now + 90)) < 2


def test_downloads_for_skips_missing_files(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 100.0)
    monkeypatch.setattr(audiobook_app, "_file_available", lambda p: False)
    now = time.time()
    _token("ja", "audio", created_at=now - 10, output_m4b="/x/a.m4b")
    _token("jb", "optimized_abm", created_at=now - 10, optimized_abm_path="/x/b.abm")
    _token("jc", "translated", created_at=now - 10, translated_path="/x/c.txt")
    f = audiobook_app._account_downloads_for
    assert [d["kind"] for d in f({"job_id": "ja", "download_token": ""}, now)] == ["page"]
    assert [d["kind"] for d in f({"job_id": "jb", "download_token": "tok-jb"}, now)] == ["page"]
    assert [d["kind"] for d in f({"job_id": "jc", "download_token": ""}, now)] == ["page"]


def test_downloads_for_job_id_fallback_picks_newest_token(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 100.0)
    now = time.time()
    # Inserito per primo (vincerebbe con un semplice "primo match" in ordine
    # di dict) ma ormai scaduto: la scelta corretta e' il token piu' recente.
    audiobook_app._download_tokens["tok-old"] = {
        "job_id": "je", "created_at": now - 5000, "download_type": "audio", "output_m4b": ""}
    audiobook_app._download_tokens["tok-new"] = {
        "job_id": "je", "created_at": now - 1, "download_type": "audio", "output_m4b": ""}
    f = audiobook_app._account_downloads_for
    out = f({"job_id": "je", "download_token": ""}, now)
    assert out and out[0]["url"] == "https://abm.test/dl/tok-new"
    assert abs(out[0]["expires_at"] - (now + 99)) < 2


def test_delete_flow_by_code(logged, env):
    c, acct = logged
    accounts.record_job(acct["id"], "j1", kind="generate", status="done")
    r = c.post("/api/account/delete_request")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    email, kw = env["codes"][-1]
    assert email == "a@b.it" and kw["purpose"] == "delete" and "?p=delete" in kw["link_url"]
    r = c.post("/api/account/delete_confirm", json={"code": kw["code"]})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert env["deleted"] == ["a@b.it"]
    assert accounts.account_for_email("a@b.it") is None
    assert accounts.list_jobs(acct["id"])[1] == 0
    assert c.get("/api/auth/me").get_json()["logged_in"] is False


def test_delete_flow_by_magic_link(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request")
    link = env["codes"][-1][1]["link_url"]
    path = link[len("https://abm.test"):]
    r = c.get(path)
    assert r.status_code == 200 and b"<form" in r.data
    assert accounts.account_for_email("a@b.it") is not None
    r = c.post(path)
    assert r.status_code == 200 and env["deleted"] == ["a@b.it"]
    assert accounts.account_for_email("a@b.it") is None


def test_delete_confirm_wrong_code_401_and_requires_session(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request")
    r = c.post("/api/account/delete_confirm", json={"code": "000000"})
    assert r.status_code == 401 and r.get_json()["error_code"] in ("wrong", "none")
    assert accounts.account_for_email("a@b.it") is not None
    anon = audiobook_app.app.test_client()
    assert anon.post("/api/account/delete_request").status_code == 401
    assert anon.post("/api/account/delete_confirm", json={"code": "1"}).status_code == 401


def test_delete_request_ignores_body_email(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request", json={"email": "victim@x.it"})
    assert env["codes"][-1][0] == "a@b.it"
