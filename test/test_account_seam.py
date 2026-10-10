"""E3, seam account (2026-10-10): magic link, sessione e pagina account nel
blueprint `routes_account`; helper e valori della app risolti a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_account as ra

ROUTES = ("/api/auth/request", "/api/auth/verify", "/auth/<token>", "/api/auth/logout", "/api/auth/logout_all",
          "/api/auth/logout_device", "/api/auth/me", "/account", "/api/account/jobs", "/api/account/jobs/delete",
          "/api/account/delete_request", "/api/account/delete_confirm")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("account."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    for name in ("def _current_account(", "def _acct_gate(", "def _acct_login_response(", "def _account_rows_for(",
                 "def _account_voices_for(", "_ACCT_SETTLE_MAP = ", "_ACCT_CSRF_COOKIE = "):
        assert name not in src and name in inspect.getsource(ra), name
    assert "app.register_blueprint(routes_account.bp)" in src
    # la app (generate, voce campionata, cleanup) continua a usare account corrente, gate e mappa esiti
    for n in ("routes_account._current_account(", "routes_account._acct_gate(", "routes_account._ACCT_SETTLE_MAP"):
        assert n in src, n
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(ra), flags=re.M)
    for n in ra.FUNCS:
        assert callable(getattr(audiobook_app, n)), n


def test_values_and_helpers_resolve_on_the_app(monkeypatch):
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://seam.test")
    monkeypatch.setattr(audiobook_app, "jobs", {"J": {"status": "done"}})
    assert ra._base_url() == "https://seam.test" and ra._jobs() == {"J": {"status": "done"}}
    assert ra._jobs_lock is audiobook_app._jobs_lock and ra._ACCT_PAGES_I18N is audiobook_app._ACCT_PAGES_I18N
    assert ra._ACCOUNT_SESSION_COOKIE == audiobook_app._ACCOUNT_SESSION_COOKIE and ra._LANG_COOKIE == audiobook_app._LANG_COOKIE
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: "smtp")
    monkeypatch.setattr(audiobook_app, "_hash_ip", lambda ip: "h:" + ip)
    assert ra._smtp_available() == "smtp" and ra._hash_ip("1.2.3.4") == "h:1.2.3.4"


def test_me_without_session_answers_from_the_blueprint():
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    r = c.get("/api/auth/me")
    assert r.status_code in (200, 401) and r.is_json
    assert not (r.get_json() or {}).get("email")
