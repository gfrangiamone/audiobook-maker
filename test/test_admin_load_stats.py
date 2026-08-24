"""Endpoint admin /api/admin/load_stats."""
from unittest.mock import patch

import pytest

import audiobook_app as app
import load_metrics as lm


@pytest.fixture
def client(tmp_path):
    app.app.config["TESTING"] = True
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield app.app.test_client()
    lm.reset_for_tests()


def test_requires_admin_auth(client):
    with patch.object(app, "_admin_auth_ok", return_value=False):
        r = client.get("/api/admin/load_stats?window=24h")
    assert r.status_code == 403


def test_returns_all_sections(client):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        r = client.get("/api/admin/load_stats?window=24h")
    assert r.status_code == 200
    data = r.get_json()
    for key in ("meta", "job", "ffmpeg", "machine", "quality", "reliability", "timeline"):
        assert key in data


def test_empty_history_is_not_an_error(client):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        data = client.get("/api/admin/load_stats?window=28d").get_json()
    assert data["meta"]["coverage_pct"] == 0
    assert data["meta"]["first_sample_ts"] is None
    assert data["job"]["gen_peak"] == 0


def test_invalid_window_falls_back_to_24h(client):
    with patch.object(app, "_admin_auth_ok", return_value=True):
        data = client.get("/api/admin/load_stats?window=../etc/passwd").get_json()
    assert data["meta"]["window"] == "24h"


def test_caps_are_passed_through_for_saturation(client):
    with patch.object(app, "_admin_auth_ok", return_value=True), \
         patch.object(app, "MAX_CONCURRENT_GLOBAL", 6), \
         patch.object(lm, "query", side_effect=lm.query) as spy:
        client.get("/api/admin/load_stats?window=7d")
    assert spy.call_args.kwargs["global_cap"] == 6
    assert spy.call_args.kwargs["assembly_slots"] >= 1
