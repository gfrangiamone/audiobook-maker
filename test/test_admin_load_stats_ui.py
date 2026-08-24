"""Pannello Stats: selettore di finestra e rimozione del vecchio grafico."""
from unittest.mock import patch

import audiobook_app


def _page():
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_window_selector_present_with_four_windows():
    html = _page()
    for w in ("24h", "7d", "28d", "month"):
        assert f'data-window="{w}"' in html


def test_default_window_is_24h():
    html = _page()
    assert 'data-window="24h" class="lsw-btn active"' in html or \
           'class="lsw-btn active" data-window="24h"' in html


def test_stats_modal_fetches_the_admin_endpoint():
    html = _page()
    assert "/api/admin/load_stats?window=" in html


def test_old_hourly_language_chart_removed():
    html = _page()
    assert "chart-bar-wrap" not in html
    assert "hourlyData" not in html
    assert "Job Distribution (24h)" not in html


def test_cards_and_timeline_containers_present():
    html = _page()
    assert 'id="lsCards"' in html
    assert 'id="lsTimeline"' in html
    assert 'id="lsCoverage"' in html
