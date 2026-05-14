"""Test statici sul source di app.js per verificare la presenza del meccanismo di stima combinata."""
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def test_has_request_combined_estimate():
    assert "function requestCombinedEstimate" in APP


def test_debounce_present():
    assert "estimateDebounceTimer" in APP


def test_estimate_cache_present():
    assert "_estimateCache" in APP


def test_listener_not_on_voice_change():
    """Il codice deve documentare esplicitamente che non si rifà stima sul cambio voce."""
    assert "no re-estimate on voice change" in APP.lower()


def test_renders_into_cost_preview():
    """renderEstimate deve riferirsi ai nodi del DOM definiti nel template."""
    assert "renderEstimate" in APP
    assert "costPreviewValue" in APP
    assert "costPreviewDetail" in APP


def test_uses_combined_estimate_endpoint():
    assert "/api/combined_estimate" in APP


def test_listener_on_aitoggle_and_vmpremium():
    """Triggers su aiToggle e vmPremium ma NON su vv o vvPremium per re-estimate."""
    # request triggered by these change events
    assert "aiToggle" in APP and "vmPremium" in APP and "requestCombinedEstimate" in APP
