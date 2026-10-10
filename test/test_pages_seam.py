"""E3, seam SEO/pagine (2026-10-10): home per lingua, FAQ, guide, sitemap, robots,
llms, well-known, get-app, privacy, support, favicon e manifest nel blueprint
`routes_pages`; valori della app risolti a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_pages as rp

ROUTES = ("/", "/it/", "/en/", "/faq/", "/faq/<lang>/", "/content/<lang>/", "/guide/<guide_id>/", "/sitemap.xml",
          "/robots.txt", "/llms.txt", "/.well-known/assetlinks.json", "/get-app", "/privacy", "/support",
          "/favicon.ico", "/manifest.json")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("pages."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    for name in ("def _inject_reviews(", "def _serve_lang(", "def _install_buttons_html(", "def _render_install_page(",
                 "_PLAY_STORE_URL = ", "_APP_PACKAGE = "):
        assert name not in src and name in inspect.getsource(rp), name
    assert "app.register_blueprint(routes_pages.bp)" in src
    assert "routes_tokens.configure(routes_pages._render_install_page)" in src        # i deep link riusano la pagina install
    assert "routes_pages._APP_PACKAGE" in src                                      # intent URL Android
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rp), flags=re.M)
    for bad in ("os.environ.get(", ".utcfromtimestamp(", ".utcnow()"):
        assert bad not in inspect.getsource(rp), bad
    for n in rp.FUNCS:
        assert callable(getattr(audiobook_app, n)), n


def test_values_resolve_on_the_app(monkeypatch):
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://seam.test")
    assert rp._base_url() == "https://seam.test"
    assert rp._SUPPORTED_LANGS is audiobook_app._SUPPORTED_LANGS and rp.HTML_TEMPLATES is audiobook_app.HTML_TEMPLATES
    monkeypatch.setattr(audiobook_app, "_detect_lang_from_request", lambda: "zh")
    assert rp._detect_lang_from_request() == "zh"


def test_public_pages_are_served():
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    assert c.get("/robots.txt").status_code == 200
    r = c.get("/manifest.json")
    assert r.status_code == 200 and r.is_json
    r = c.get("/it/")
    assert r.status_code == 200 and "<html" in r.get_data(as_text=True).lower()
