# test/test_account_routes.py
"""Route di autenticazione account: request/verify/logout/me e /auth/<token>."""
import re

import pytest

import accounts
import audiobook_app
import db
import email_service

T0 = 1_800_000_000


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    audiobook_app._ip_rl_buckets.pop("auth_request", None)
    box = []
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: box.append((email, lang, kw)) or True)
    audiobook_app.app.config["TESTING"] = True
    yield box
    db.close()


@pytest.fixture
def client(env):
    return audiobook_app.app.test_client()


def _cookie(resp, name="abm_session"):
    for h in resp.headers.getlist("Set-Cookie"):
        if h.startswith(name + "="):
            return h
    return None


def _csrf(resp):
    """Il nonce nascosto del form di conferma (double-submit col cookie)."""
    m = re.search(r'name="csrf" value="([^"]+)"', resp.data.decode())
    return m.group(1) if m else ""


def test_request_sends_code_and_link(client, env):
    r = client.post("/api/auth/request", json={"email": "A@B.it", "lang": "it"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    email, lang, kw = env[0]
    assert email == "a@b.it" and lang == "it" and kw["purpose"] == "login"
    assert kw["link_url"].startswith("https://abm.test/auth/")
    assert kw["minutes"] == accounts.CODE_TTL_MIN and len(kw["code"]) == 6


def test_request_is_neutral_on_bad_email_and_rate_limit(client, env):
    r = client.post("/api/auth/request", json={"email": "not-an-email"})
    assert r.status_code == 400 and r.get_json()["error_code"] == "invalid_email"
    for _ in range(3):
        assert client.post("/api/auth/request", json={"email": "a@b.it"}).status_code == 200
    r = client.post("/api/auth/request", json={"email": "a@b.it"})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert len(env) == 3  # la 4a non manda nulla ma risponde uguale


def test_request_ip_rate_limit_429(client, env):
    for i in range(5):
        assert client.post("/api/auth/request", json={"email": f"u{i}@b.it"}).status_code == 200
    r = client.post("/api/auth/request", json={"email": "u9@b.it"})
    assert r.status_code == 429 and r.get_json()["error_code"] == "rate_limited"


def test_disabled_returns_404_and_me_reports_it(client, monkeypatch):
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert client.post("/api/auth/request", json={"email": "a@b.it"}).status_code == 404
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and r.get_json() == {"logged_in": False, "enabled": False}


def test_no_smtp_returns_404(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: False)
    assert client.post("/api/auth/request", json={"email": "a@b.it"}).status_code == 404


def test_verify_by_code_sets_cookie_and_me(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it", "lang": "fr"})
    code = env[0][2]["code"]
    r = client.post("/api/auth/verify", json={"email": "a@b.it", "code": code, "device_name": "Pixel"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True and d["email"] == "a@b.it" and d["lang"] == "fr" and d["plan"] == "free"
    assert "session_token" not in d
    ck = _cookie(r)
    assert ck and "HttpOnly" in ck and "SameSite=Lax" in ck and "Secure" in ck and "Path=/" in ck
    me = client.get("/api/auth/me").get_json()
    assert me["logged_in"] is True and me["email"] == "a@b.it" and me["sessions_count"] == 1


def test_verify_wrong_code_401_with_error_code(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    bad = "000000" if env[0][2]["code"] != "000000" else "111111"
    r = client.post("/api/auth/verify", json={"email": "a@b.it", "code": bad})
    assert r.status_code == 401 and r.get_json()["error_code"] == "wrong"
    r = client.post("/api/auth/verify", json={"email": "zz@b.it", "code": "123456"})
    assert r.status_code == 401 and r.get_json()["error_code"] == "none"


def test_verify_with_mobile_header_returns_session_token(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    code = env[0][2]["code"]
    r = client.post("/api/auth/verify", json={"email": "a@b.it", "code": code},
                    headers={"X-ABM-Cid": "mobile-cid-000001"})
    d = r.get_json()
    assert d["ok"] and d["session_token"]
    me = audiobook_app.app.test_client().get(
        "/api/auth/me", headers={"Authorization": "Bearer " + d["session_token"]}).get_json()
    assert me["logged_in"] is True and me["email"] == "a@b.it"


def test_bearer_has_precedence_over_cookie(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    client.post("/api/auth/verify", json={"email": "a@b.it", "code": env[0][2]["code"]})
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.get_json()["logged_in"] is False


def test_magic_link_get_does_not_consume_post_does(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    link = env[0][2]["link_url"]
    path = link[len("https://abm.test"):]
    r = client.get(path)
    assert r.status_code == 200 and b"<form" in r.data and b"method=\"post\"" in r.data
    csrf = _csrf(r)
    assert csrf
    ck = _cookie(r, "abm_auth_csrf")
    assert ck and "HttpOnly" in ck and "SameSite=Strict" in ck and "Path=/auth" in ck
    assert csrf in ck
    assert accounts.account_for_email("a@b.it") is None
    r = client.post(path, data={"csrf": csrf})
    assert r.status_code == 302 and r.headers["Location"].endswith("/account")
    assert _cookie(r) is not None
    # il cookie anti-CSRF e' bruciato con il token
    assert "Max-Age=0" in (_cookie(r, "abm_auth_csrf") or "")
    assert accounts.account_for_email("a@b.it") is not None
    r = client.post(path, data={"csrf": csrf})
    assert r.status_code in (403, 410)


def test_magic_link_post_without_csrf_is_rejected(client, env):
    """Login-CSRF: un form auto-inviato da un sito terzo non porta il cookie
    posato dal GET sul browser della vittima. Il 403 non deve consumare il
    token: lo stesso link resta usabile dal browser legittimo."""
    client.post("/api/auth/request", json={"email": "a@b.it"})
    path = env[0][2]["link_url"][len("https://abm.test"):]
    anon = audiobook_app.app.test_client()
    r = anon.post(path)
    assert r.status_code == 403 and b"<html" in r.data
    assert _cookie(r) is None
    assert accounts.account_for_email("a@b.it") is None
    # campo presente ma cookie assente: comunque rifiutato
    r = anon.post(path, data={"csrf": "made-up-value"})
    assert r.status_code == 403
    assert accounts.account_for_email("a@b.it") is None
    # il token e' ancora buono per il GET+POST legittimo
    g = client.get(path)
    assert g.status_code == 200
    r = client.post(path, data={"csrf": _csrf(g)})
    assert r.status_code == 302
    assert accounts.account_for_email("a@b.it") is not None


def test_magic_link_post_cross_origin_is_rejected(client, env):
    """Allow-list su Origin/Referer: anche con cookie e campo validi (es. un
    sottodominio compromesso che riesce a farli combaciare) un POST che si
    dichiara di un'altra origine non consuma il token."""
    client.post("/api/auth/request", json={"email": "a@b.it"})
    path = env[0][2]["link_url"][len("https://abm.test"):]
    g = client.get(path)
    csrf = _csrf(g)
    r = client.post(path, data={"csrf": csrf},
                    headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    assert accounts.account_for_email("a@b.it") is None
    r = client.post(path, data={"csrf": csrf},
                    headers={"Referer": "https://evil.example/page"})
    assert r.status_code == 403
    assert accounts.account_for_email("a@b.it") is None
    # stessa origine della richiesta (host_url del test client): passa
    r = client.post(path, data={"csrf": csrf},
                    headers={"Origin": "http://localhost"})
    assert r.status_code == 302
    assert accounts.account_for_email("a@b.it") is not None


def test_magic_link_origin_allow_list_accepts_base_url(client, env, monkeypatch):
    """L'allow-list ammette l'origine di BASE_URL anche quando non coincide
    con l'host della richiesta (server dietro proxy), e nient'altro."""
    with audiobook_app.app.test_request_context(
            "/auth/x", method="POST", headers={"Origin": "https://abm.test"}):
        assert audiobook_app._acct_origin_ok() is True
    with audiobook_app.app.test_request_context(
            "/auth/x", method="POST", headers={"Referer": "https://abm.test/auth/x"}):
        assert audiobook_app._acct_origin_ok() is True
    with audiobook_app.app.test_request_context(
            "/auth/x", method="POST", headers={"Origin": "http://abm.test"}):
        assert audiobook_app._acct_origin_ok() is False
    with audiobook_app.app.test_request_context(
            "/auth/x", method="POST", headers={"Origin": "null"}):
        assert audiobook_app._acct_origin_ok() is False
    # nessun header: navigazione diretta, consentita
    with audiobook_app.app.test_request_context("/auth/x", method="POST"):
        assert audiobook_app._acct_origin_ok() is True


def test_magic_link_unknown_token_410_page(client, env):
    r = client.get("/auth/doesnotexist")
    assert r.status_code == 410 and b"<html" in r.data


def test_magic_link_get_shows_masked_email_and_code_lang(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it", "lang": "it"})
    link = env[0][2]["link_url"]
    path = link[len("https://abm.test"):]
    r = client.get(path, headers={"Accept-Language": "de"})
    assert r.status_code == 200
    assert b"a***@b.it" in r.data
    assert b"a@b.it" not in r.data
    assert "Accedi".encode() in r.data
    assert "Anmelden".encode() not in r.data


def test_verify_stores_device_name(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    code = env[0][2]["code"]
    client.post("/api/auth/verify", json={"email": "a@b.it", "code": code, "device_name": "Pixel"})
    row = db.conn().execute(
        "SELECT device_name FROM sessions ORDER BY id DESC LIMIT 1").fetchone()
    assert row["device_name"] == "Pixel"


def test_logout_routes_404_when_disabled(client, monkeypatch):
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert client.post("/api/auth/logout").status_code == 404
    assert client.post("/api/auth/logout_all").status_code == 404


def test_verify_by_token_json(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    token = env[0][2]["link_url"].rsplit("/", 1)[1]
    r = client.post("/api/auth/verify", json={"token": token})
    assert r.status_code == 200 and r.get_json()["email"] == "a@b.it"


def test_logout_and_logout_all(client, env):
    client.post("/api/auth/request", json={"email": "a@b.it"})
    code = env[0][2]["code"]
    client.post("/api/auth/verify", json={"email": "a@b.it", "code": code})
    acct = accounts.account_for_email("a@b.it")
    other = accounts.open_session(acct["id"])
    r = client.post("/api/auth/logout")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert "abm_session=;" in _cookie(r) or "Max-Age=0" in _cookie(r)
    assert client.get("/api/auth/me").get_json()["logged_in"] is False
    assert accounts.resolve_session(other) is not None
    r = audiobook_app.app.test_client().post(
        "/api/auth/logout_all", headers={"Authorization": "Bearer " + other})
    assert r.status_code == 200 and r.get_json() == {"ok": True, "revoked": 1}
    assert accounts.resolve_session(other) is None
    assert client.post("/api/auth/logout_all").status_code == 401


def test_login_logs_activity_with_hashed_sid(client, env, monkeypatch):
    rows = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda sid, fn, op, **kw: rows.append((sid, fn, op)))
    client.post("/api/auth/request", json={"email": "a@b.it"})
    client.post("/api/auth/verify", json={"email": "a@b.it", "code": env[0][2]["code"]})
    assert rows and rows[-1][2] == "ACCOUNT_LOGIN"
    assert rows[-1][0] == "acct-" + accounts.email_hash("a@b.it")[:8]
    assert "a@b.it" not in rows[-1][0] + rows[-1][1]
