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


def test_no_request_estimate_on_voice_change():
    """vv e vvPremium NON devono triggerare requestCombinedEstimate (la voce non cambia il costo)."""
    import re
    forbidden = [
        re.compile(r"getElementById\(['\"]vv['\"]\)[^;]{0,80}requestCombinedEstimate"),
        re.compile(r"getElementById\(['\"]vvPremium['\"]\)[^;]{0,80}requestCombinedEstimate"),
        re.compile(r"['\"]vv['\"]\s*\)\.addEventListener\(['\"]change['\"]\s*,\s*requestCombinedEstimate"),
        re.compile(r"['\"]vvPremium['\"]\s*\)\.addEventListener\(['\"]change['\"]\s*,\s*requestCombinedEstimate"),
    ]
    for pat in forbidden:
        m = pat.search(APP)
        assert m is None, f"voice change must not trigger requestCombinedEstimate (matched: {m.group(0) if m else None})"


def test_stale_response_guarded():
    """Dopo l'await fetch, deve esserci un confronto fra getEstimateCacheKey() corrente e la key snapshot."""
    assert "getEstimateCacheKey()" in APP
    # In particolare deve apparire il pattern: after await, check getEstimateCacheKey() !== key
    assert ("getEstimateCacheKey() !== key" in APP) or ("getEstimateCacheKey()!==key" in APP)


def test_cache_key_includes_jobid():
    """getEstimateCacheKey deve includere jobId per evitare cross-job cache pollution."""
    import re
    m = re.search(r"function getEstimateCacheKey\(\)\s*\{(.*?)^\}", APP, re.MULTILINE | re.DOTALL)
    assert m, "getEstimateCacheKey not found"
    body = m.group(1)
    assert "jobId" in body, "cache key must include jobId"
