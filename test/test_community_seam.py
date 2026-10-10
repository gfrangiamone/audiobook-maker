"""E3, seam community pubblica (2026-10-10): statistiche, news, feedback e
supporto nel blueprint `routes_community`; helper della app risolti a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_community as rc

ROUTES = ("/api/community/stats/today", "/api/community/stats/month", "/api/community/news",
          "/api/community/feedback", "/api/community/feedback/<item_id>", "/api/support/contact")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("community."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    for name in ("def _sanitize_text(", "def _feedback_check_rate(", "def _notify_admin_new_feedback(",
                 "def _process_new_feedback(", "_NEWS_TAGS = ", "_FB_LIMIT_HOUR = "):
        assert name not in src and name in inspect.getsource(rc), name
    assert "app.register_blueprint(routes_community.bp)" in src
    assert "routes_community._sanitize_text(" in src            # l'admin community la riceve via lambda
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rc), flags=re.M)
    for n in rc.FUNCS:
        assert callable(getattr(audiobook_app, n)), n


def test_helpers_resolve_on_the_app(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_EMAIL", "adm@seam.test")
    monkeypatch.setattr(audiobook_app, "_stats_today_count", lambda: 42)
    monkeypatch.setattr(audiobook_app, "_hash_ip", lambda ip: "h:" + ip)
    assert rc._admin_email() == "adm@seam.test" and rc._stats_today_count() == 42 and rc._hash_ip("1.1.1.1") == "h:1.1.1.1"
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    r = c.get("/api/community/stats/today")
    assert r.status_code == 200 and r.get_json().get("count") == 42


def test_sanitize_text_shared_rules():
    assert rc._sanitize_text("<b>ciao</b>  mondo", 100) == "ciao mondo"
    assert len(rc._sanitize_text("x" * 50, 10)) == 10
    assert "\n" in rc._sanitize_text("a\nb", 10, keep_newlines=True)
