import json, importlib


def test_incr_and_read(tmp_path, monkeypatch):
    import metrics_store as ms
    importlib.reload(ms)
    monkeypatch.setattr(ms, "_METRICS_FILE", tmp_path / "_metrics.json")
    ms.incr("app_open", "android", day="2026-06-19")
    ms.incr("app_open", "android", day="2026-06-19")
    ms.incr("app_open", "ios", day="2026-06-19")
    ms.incr("web_visit_from_app", "android", day="2026-06-19")
    data = ms.read_range(["2026-06-19"])
    assert data["app_open"]["android"] == 2
    assert data["app_open"]["ios"] == 1
    assert data["web_visit_from_app"]["android"] == 1


def test_unknown_platform_defaults(tmp_path, monkeypatch):
    import metrics_store as ms
    importlib.reload(ms)
    monkeypatch.setattr(ms, "_METRICS_FILE", tmp_path / "_metrics.json")
    ms.incr("app_open", None, day="2026-06-19")
    data = ms.read_range(["2026-06-19"])
    assert data["app_open"]["unknown"] == 1
