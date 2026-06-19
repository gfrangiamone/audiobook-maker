"""Test funnel endpoint /api/admin/funnel and helper _funnel_data."""
import pytest
from unittest.mock import patch

TOKEN = "test-admin-token-funnel"


@pytest.fixture
def app_mod(monkeypatch):
    import audiobook_app
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", TOKEN)
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app


def test_funnel_data_totals(monkeypatch):
    import audiobook_app as app
    monkeypatch.setattr(app.metrics_store, "read_range", lambda days: {
        "app_open": {"android": 10, "ios": 2, "unknown": 0},
        "web_visit_from_app": {"android": 5, "ios": 1, "unknown": 0},
        "payment_from_app": {"android": 2, "ios": 0, "unknown": 0}})
    d = app._funnel_data(["2026-06-19"])
    assert d["app_open"]["total"] == 12
    assert d["web_visit_from_app"]["total"] == 6
    assert d["payment_from_app"]["total"] == 2
    assert round(d["conversion_rate"], 4) == round(2 / 6, 4)
    assert d["app_open"]["android"] == 10 and d["app_open"]["ios"] == 2


def test_funnel_zero_web(monkeypatch):
    import audiobook_app as app
    monkeypatch.setattr(app.metrics_store, "read_range", lambda days: {
        "app_open": {"android": 0, "ios": 0, "unknown": 0},
        "web_visit_from_app": {"android": 0, "ios": 0, "unknown": 0},
        "payment_from_app": {"android": 0, "ios": 0, "unknown": 0}})
    d = app._funnel_data(["2026-06-19"])
    assert d["conversion_rate"] == 0.0


def test_funnel_endpoint_rejects_no_auth(app_mod):
    """GET /api/admin/funnel without auth -> 401 or 403."""
    client = app_mod.app.test_client()
    resp = client.get("/api/admin/funnel")
    assert resp.status_code in (401, 403)


def test_funnel_endpoint_accepts_admin_token(app_mod, monkeypatch):
    """GET /api/admin/funnel with valid X-Admin-Token -> 200 with expected keys."""
    import audiobook_app as app
    monkeypatch.setattr(app.metrics_store, "read_range", lambda days: {
        "app_open": {"android": 3, "ios": 1, "unknown": 0},
        "web_visit_from_app": {"android": 2, "ios": 0, "unknown": 0},
        "payment_from_app": {"android": 1, "ios": 0, "unknown": 0}})
    client = app_mod.app.test_client()
    resp = client.get("/api/admin/funnel", headers={"X-Admin-Token": TOKEN})
    assert resp.status_code == 200
    data = resp.get_json()
    assert "app_open" in data
    assert "web_visit_from_app" in data
    assert "payment_from_app" in data
    assert "conversion_rate" in data
    assert data["app_open"]["total"] == 4
    assert data["web_visit_from_app"]["total"] == 2
    assert data["payment_from_app"]["total"] == 1
    assert round(data["conversion_rate"], 4) == round(1 / 2, 4)
