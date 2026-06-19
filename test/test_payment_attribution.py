"""Test payment attribution: _acquisition_from_request helper and payment_from_app metric."""
import pytest


@pytest.fixture
def client(monkeypatch):
    import audiobook_app
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


def test_acquisition_from_cookie(client):
    import audiobook_app as app
    with app.app.test_request_context(environ_overrides={"HTTP_COOKIE": "abm_acq=ios"}):
        src, plat = app._acquisition_from_request()
    assert src == "app" and plat == "ios"


def test_acquisition_android(client):
    import audiobook_app as app
    with app.app.test_request_context(environ_overrides={"HTTP_COOKIE": "abm_acq=android"}):
        src, plat = app._acquisition_from_request()
    assert src == "app" and plat == "android"


def test_acquisition_unknown_platform(client):
    """Cookie present but unknown platform value → src='app', plat=''."""
    import audiobook_app as app
    with app.app.test_request_context(environ_overrides={"HTTP_COOKIE": "abm_acq=web"}):
        src, plat = app._acquisition_from_request()
    assert src == "app" and plat == ""


def test_acquisition_absent():
    import audiobook_app as app
    with app.app.test_request_context():
        src, plat = app._acquisition_from_request()
    assert src == "" and plat == ""


def test_metrics_store_accepts_payment_event(tmp_path, monkeypatch):
    import importlib
    import metrics_store as ms
    importlib.reload(ms)
    monkeypatch.setattr(ms, "_METRICS_FILE", tmp_path / "_metrics.json")
    ms.incr("payment_from_app", "android", day="2026-06-19")
    data = ms.read_range(["2026-06-19"])
    assert data["payment_from_app"]["android"] == 1


def test_metrics_store_payment_event_ios(tmp_path, monkeypatch):
    import importlib
    import metrics_store as ms
    importlib.reload(ms)
    monkeypatch.setattr(ms, "_METRICS_FILE", tmp_path / "_metrics.json")
    ms.incr("payment_from_app", "ios", day="2026-06-19")
    data = ms.read_range(["2026-06-19"])
    assert data["payment_from_app"]["ios"] == 1


def test_metrics_store_invalid_event_ignored(tmp_path, monkeypatch):
    """Unknown events must still be rejected (existing behaviour)."""
    import importlib
    import metrics_store as ms
    importlib.reload(ms)
    monkeypatch.setattr(ms, "_METRICS_FILE", tmp_path / "_metrics.json")
    ms.incr("unknown_event", "android", day="2026-06-19")
    data = ms.read_range(["2026-06-19"])
    assert "unknown_event" not in data
