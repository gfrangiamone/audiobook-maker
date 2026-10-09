"""E2(a): la guardia admin e' un decoratore; ogni route conserva status, corpo e sleep storici."""
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


def test_statuses_and_bodies_are_preserved(client):
    r = client.get("/api/admin/funnel")
    assert r.status_code == 403 and r.get_json() == {"error": "forbidden"}
    r = client.get("/admin/api/news/list")
    assert r.status_code == 403 and r.get_data(as_text=True) == "forbidden"
    r = client.get("/admin/api/news/list", headers={"X-Admin-Token": "tok-test"})
    assert r.status_code == 200
    r = client.get("/api/admin/funnel", headers={"X-Admin-Token": "tok-test"})
    assert r.status_code == 200


def test_json401_routes_sleep_and_disabled(client, monkeypatch):
    sleeps = []
    monkeypatch.setattr(app.time, "sleep", lambda s: sleeps.append(s))
    # Una route per forma: 401 JSON con sleep (vouchers) e 401 senza sleep (monitor).
    r = client.get("/admin/api/vouchers")
    assert r.status_code == 401 and r.get_json() == {"error": "Unauthorized"} and sleeps == [0.5]
    r = client.get("/api/active_jobs")
    assert r.status_code == 401 and r.get_json() == {"error": "Unauthorized"} and sleeps == [0.5]
    monkeypatch.setattr(app, "ADMIN_TOKEN", "")
    r = client.get("/admin/api/vouchers")
    assert r.status_code == 404 and r.get_json() == {"error": "Admin UI disabled"}
    r = client.get("/api/active_jobs")
    assert r.status_code == 404 and r.get_json() == {"error": "Admin monitor disabled"}


def test_no_inline_guard_left():
    src = inspect.getsource(app)
    inline = [m.start() for m in re.finditer(r"^\s+if not _admin_auth_ok\(_admin_auth_from_request\(\)\):", src, flags=re.M)]
    assert len(inline) == 1                                       # solo dentro admin_required
    assert src.count("@admin_required(") == 32
