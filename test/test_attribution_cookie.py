"""Tests for abm_acq attribution cookie + web_visit_from_app counter on home route."""
import pytest


@pytest.fixture
def client(monkeypatch):
    import audiobook_app
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


def test_home_sets_attribution_cookie(client, monkeypatch):
    import audiobook_app as app
    seen = []
    monkeypatch.setattr(app.metrics_store, "incr", lambda e, p, day=None: seen.append((e, p)))
    r = client.get("/?utm_source=app&app_platform=android")
    cookies = r.headers.getlist("Set-Cookie")
    assert any("abm_acq=android" in c for c in cookies)
    assert ("web_visit_from_app", "android") in seen


def test_home_first_touch_not_overwritten(client):
    # Seed the cookie jar so request.cookies sees the existing abm_acq value.
    client.set_cookie("abm_acq", "android")
    r = client.get("/?utm_source=app&app_platform=ios")
    cookies = r.headers.getlist("Set-Cookie")
    assert not any("abm_acq=ios" in c for c in cookies)


def test_home_no_utm_no_cookie(client):
    r = client.get("/")
    assert not any("abm_acq=" in c for c in r.headers.getlist("Set-Cookie"))
