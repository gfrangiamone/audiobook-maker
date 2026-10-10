"""E3, seam admin parte 2 (2026-10-10): console del log attivita' e funnel nel
blueprint `routes_admin_logs`; policy e stato della app risolti a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import routes_admin_logs as rl

ROUTES = ("/admin/log-activity", "/admin/log-activity/day", "/admin/log-activity/export", "/api/admin/funnel")


def test_routes_and_helpers_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("admin_logs."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    for name in ("def _log_sessions_cached(", "def _log_card_html(", "def _funnel_data(", "def _power_users_data(",
                 "_LOG_EVENT_ICONS", "_LOG_SESSIONS_CACHE = {}", "POWER_USER_JOBS_PER_DAY = "):
        assert name not in src and name in inspect.getsource(rl), name
    assert "app.register_blueprint(routes_admin_logs.bp)" in src
    assert "routes_admin_logs._funnel_data(" in src and "routes_admin_logs._power_users_data" in src   # digest admin
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rl), flags=re.M)


def test_policies_resolve_on_the_app_at_call_time(monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda s: None)
    c = audiobook_app.app.test_client()
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "")
    assert c.get("/admin/log-activity").status_code == 404
    assert c.get("/api/admin/funnel").status_code == 404
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-seam")
    assert c.get("/api/admin/funnel").status_code == 401
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: False)
    monkeypatch.setattr(audiobook_app, "_render_admin_gate", lambda title, url: f"GATE:{title}:{url}")
    r = c.get("/admin/log-activity")
    assert r.status_code == 200 and r.get_data(as_text=True) == "GATE:Log Activity:/admin/log-activity"
    seen = []
    monkeypatch.setattr(audiobook_app, "_parse_log_sessions", lambda ym: seen.append(ym) or ({}, {}))
    rl._LOG_SESSIONS_CACHE.clear()
    rl._log_sessions_cached("2026-10")
    assert seen == ["2026-10"]
    monkeypatch.setattr(audiobook_app, "jobs", {"S1": {"status": "generating"}})
    assert rl._jobs() == {"S1": {"status": "generating"}}


def test_constants_shared_with_the_app():
    assert rl.FAVICON_B64 == audiobook_app.FAVICON_B64 and rl.FAVICON_B64.startswith("data:image/svg+xml")
    assert rl._ACTIVE_JOB_STATUSES is audiobook_app._ACTIVE_JOB_STATUSES
    assert "ANALYZE" in rl._LOG_EVENT_ICONS and rl.POWER_USER_JOBS_PER_DAY >= 1
