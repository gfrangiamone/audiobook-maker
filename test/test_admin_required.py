"""E2(a): la guardia admin e' un decoratore con una sola forma di risposta (401/404, JSON o testo)."""
import inspect
import re

import pytest

import audiobook_app as app


@pytest.fixture
def client(monkeypatch):
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "ADMIN_TOKEN", "tok-test")
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    with app.app.test_client() as c:
        yield c


def test_decorator_variants(client, monkeypatch):
    # Le route decorate hanno __wrapped__ (functools.wraps): senza token
    # rispondono tutte 401/403 (o 404 a UI spenta), mai 200.
    cases = [(rule, app.app.view_functions[rule.endpoint]) for rule in app.app.url_map.iter_rules()
             if hasattr(app.app.view_functions[rule.endpoint], "__wrapped__")]
    assert len(cases) >= 30
    monkeypatch.setattr(app, "ADMIN_TOKEN", "")
    for rule, fn in cases:
        if "GET" not in rule.methods or "<" in rule.rule:
            continue
        r = client.get(rule.rule)
        assert r.status_code in (401, 403, 404), (rule.rule, r.status_code)


def test_one_json_form_and_one_text_form(client, monkeypatch):
    sleeps = []
    monkeypatch.setattr(app.time, "sleep", lambda s: sleeps.append(s))
    json_routes = ("/api/admin/funnel", "/admin/api/vouchers", "/api/active_jobs", "/api/admin/load_stats",
                   "/api/admin/jobs_progress", "/admin/api/tts_backend")
    text_routes = ("/admin/api/news/list", "/admin/api/feedback/list", "/admin/log-activity/day")
    for route in json_routes:
        r = client.get(route)
        assert r.status_code == 401 and r.get_json() == {"error": "Unauthorized"}, route
        r = client.get(route, headers={"X-Admin-Token": "wrong"})
        assert r.status_code == 401, route
    for route in text_routes:
        r = client.get(route)
        assert r.status_code == 401 and r.get_data(as_text=True) == "Unauthorized", route
    assert sleeps == [0.5] * (2 * len(json_routes) + len(text_routes))      # anti brute-force ovunque
    assert client.get("/admin/api/news/list", headers={"X-Admin-Token": "tok-test"}).status_code == 200
    assert client.get("/api/admin/funnel", headers={"X-Admin-Token": "tok-test"}).status_code == 200


def test_ui_off_is_404_everywhere(client, monkeypatch):
    sleeps = []
    monkeypatch.setattr(app.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(app, "ADMIN_TOKEN", "")
    for route in ("/admin/api/vouchers", "/api/active_jobs", "/api/admin/funnel", "/api/admin/load_stats"):
        r = client.get(route)
        assert r.status_code == 404 and r.get_json() == {"error": "Admin UI disabled"}, route
    for route in ("/admin/api/news/list", "/admin/log-activity/day"):
        r = client.get(route)
        assert r.status_code == 404 and r.get_data(as_text=True) == "Admin UI disabled", route
    assert sleeps == []


def test_no_inline_guard_left():
    src = inspect.getsource(app)
    inline = [m.start() for m in re.finditer(r"^\s+if not _admin_auth_ok\(_admin_auth_from_request\(\)\):", src, flags=re.M)]
    assert len(inline) == 1                                       # solo dentro admin_required
    import routes_admin_audit, routes_admin_logs
    both = src + inspect.getsource(routes_admin_audit) + inspect.getsource(routes_admin_logs)
    assert len(re.findall(r"^@admin_required(\(as_json=False\))?$", both, flags=re.M)) == 32   # 18 app + 12 + 2 blueprint
    assert "@admin_required(4" not in src                          # nessuna forma storica residua
