"""Residui E1/E2 (2026-10-10): cookie_secure() unico, _is_resume_or_probe_request
nei 7 inline, request.json -> get_json(silent=True), trim_preview in text_reflow,
_pagination in routes_admin_audit, niente UTC naive in guide_content."""
import ast
import inspect
import re

import audiobook_app as aa
import guide_content
import routes_account
import routes_admin_audit
import routes_admin_jobs
import routes_admin_vouchers
import routes_dl
import text_reflow


def test_cookie_secure_single_rule(monkeypatch):
    app = aa.app
    monkeypatch.setattr(aa, "BASE_URL", "http://localhost:5601")
    with app.test_request_context("/"):
        assert aa.cookie_secure() is False
    with app.test_request_context("/", base_url="https://x.test"):
        assert aa.cookie_secure() is True
    with app.test_request_context("/", headers={"X-Forwarded-Proto": "https"}):
        assert aa.cookie_secure() is True
    monkeypatch.setattr(aa, "BASE_URL", "https://audiobook.example")
    with app.test_request_context("/"):
        assert aa.cookie_secure() is True
        assert routes_account._acct_cookie_secure() is True
    src = inspect.getsource(aa)
    assert "is_https" not in src
    # Ogni `secure=` dei cookie e' cookie_secure() (AST, non conteggio: M6).
    secure = [kw.value for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call)
              for kw in n.keywords if kw.arg == "secure"]
    assert secure and all(isinstance(v, ast.Call) and getattr(v.func, "id", "") == "cookie_secure" for v in secure)


def test_no_inline_probe_or_request_json_left():
    for mod in (aa, routes_dl, routes_admin_jobs, routes_admin_vouchers, routes_admin_audit, routes_account):
        src = inspect.getsource(mod)
        assert "request.json or {}" not in src, mod.__name__
        inline = re.findall(r'request\.method [!=]= "HEAD"', src)
        assert len(inline) == (1 if mod is aa else 0), mod.__name__   # solo la definizione
    assert inspect.getsource(aa).count("request.get_json(silent=True) or {}") >= 8   # 8 migrati + 5 gia' cosi'


def test_pagination_helper(monkeypatch):
    app = aa.app
    with app.test_request_context("/?limit=5000&offset=-3"):
        assert routes_admin_audit._pagination(200, 1000) == (1000, 0)
    with app.test_request_context("/"):
        assert routes_admin_audit._pagination(500, 2000) == (500, 0)
    with app.test_request_context("/?limit=0&offset=7"):
        assert routes_admin_audit._pagination(200, 1000) == (1, 7)
    assert inspect.getsource(routes_admin_audit).count("= _pagination(") == 6


def test_trim_preview_lives_in_text_reflow():
    assert aa._trim_preview is text_reflow.trim_preview
    assert "def _trim_preview" not in inspect.getsource(aa)
    short = "Una frase breve."
    assert text_reflow.trim_preview(short) == short
    long = ("Prima frase abbastanza lunga da contare. " * 20) + "Coda finale senza punto"
    out = text_reflow.trim_preview(long)
    assert 400 <= len(out) <= 600 and out.endswith(".") and len(long) > 600
    assert text_reflow.trim_preview("TITOLO\n\nCorpo (nota).")== "Titolo. Corpo (nota)."   # parentesi conservate


def test_guide_content_uses_aware_utc():
    src = inspect.getsource(guide_content)
    assert "utcnow()" not in src and "utcfromtimestamp(" not in src
