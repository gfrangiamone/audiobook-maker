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


def test_four_tabs_are_present_with_job_active():
    html = _page()
    for tab in ("job", "machine", "quality", "reliability"):
        assert f'data-tab="{tab}"' in html
    assert 'class="lst-btn active" data-tab="job"' in html


def test_body_is_scrollable_and_header_is_outside_it():
    html = _page()
    assert 'class="ls-body"' in html
    assert ".ls-body { padding:14px 22px 22px; overflow-y:auto; flex:1; }" in html
    # il selettore di finestra sta nell'intestazione fissa, non nel corpo scrollabile
    head = html.index('class="ls-head"')
    body = html.index('class="ls-body"')
    assert head < html.index('data-window="24h"') < body


def test_split_rows_render_all_and_premium_in_one_card():
    html = _page()
    assert "function lsSplit(" in html
    assert "lsRow('Tutti'" in html
    assert "lsRow('Premium'" in html
    # niente piu' card separate con badge PREMIUM nel titolo
    assert 'ls-badge' not in html
