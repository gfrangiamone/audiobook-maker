"""E3, seam admin parte 5 (2026-10-10): news, feedback, community e reset
anti-abuso nel blueprint `routes_admin_community`."""
import inspect
import re

import pytest

import audiobook_app
import routes_community
import community_store
import routes_admin_community as rc

ROUTES = ("/admin/api/news", "/admin/api/news/<item_id>", "/admin/api/news/list", "/admin/api/feedback/list",
          "/admin/api/feedback/translate-missing", "/admin/api/feedback/<item_id>",
          "/admin/api/feedback/<item_id>/reply", "/admin/community", "/admin/api/abuse/clear/<group>")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("admin_community."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    assert "def _translate_news_async(" not in src and "def _translate_news_async(" in inspect.getsource(rc)
    assert "app.register_blueprint(routes_admin_community.bp)" in src
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rc), flags=re.M)
    assert not re.search(r"^@admin_required", src, flags=re.M)              # nessuna route admin resta nella app


def test_guard_text_form_and_shared_constants(monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda s: None)
    c = audiobook_app.app.test_client()
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-seam")
    r = c.get("/admin/api/news/list")
    assert r.status_code == 401 and r.get_data(as_text=True) == "Unauthorized"       # forma testo
    r = c.post("/admin/api/abuse/clear/not-a-group")
    assert r.status_code == 401 and r.get_json() == {"error": "Unauthorized"}         # forma JSON
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: False)
    monkeypatch.setattr(audiobook_app, "_render_admin_gate", lambda title, url: f"GATE:{title}")
    r = c.get("/admin/community")
    assert r.status_code == 200 and r.get_data(as_text=True) == "GATE:Community Admin"
    assert rc._NEWS_LANGS is routes_community._NEWS_LANGS and rc._NEWS_TAGS is routes_community._NEWS_TAGS
    assert rc._ABUSE_GROUP_RE is audiobook_app._ABUSE_GROUP_RE
    monkeypatch.setattr(routes_community, "_sanitize_text", lambda t, *a, **k: f"S:{t}")
    assert rc._sanitize_text("x") == "S:x"
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: True)
    r = c.post("/admin/api/abuse/clear/not-a-group", headers={"X-Admin-Token": "tok-seam"})
    assert r.status_code == 400 and r.get_json() == {"error": "invalid group"}
