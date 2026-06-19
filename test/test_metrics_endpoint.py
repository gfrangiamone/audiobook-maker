"""Test POST /api/metrics/app_open and _client_platform helper."""
import pytest


@pytest.fixture
def client(monkeypatch):
    import audiobook_app
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


def test_app_open_increments(client, monkeypatch):
    import audiobook_app as app
    calls = []
    monkeypatch.setattr(app.metrics_store, "incr", lambda e, p, day=None: calls.append((e, p)))
    r = client.post("/api/metrics/app_open", json={"platform": "android", "app_version": "1.0.0"})
    assert r.status_code == 200 and r.get_json()["ok"] is True
    assert ("app_open", "android") in calls


def test_client_platform(monkeypatch):
    import audiobook_app as app
    with app.app.test_request_context(headers={"X-ABM-Cid": "abc12345", "X-ABM-Platform": "ios"}):
        assert app._client_platform() == "ios"
    with app.app.test_request_context(headers={"Cookie": "abm_cid=webcid123"}):
        assert app._client_platform() == "web"
    with app.app.test_request_context():
        assert app._client_platform() == ""
