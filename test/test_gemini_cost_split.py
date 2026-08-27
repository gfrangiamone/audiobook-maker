"""Il prezzo e il costo reale sono due numeri distinti."""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _cf(monkeypatch):
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    yield
    gemini_tts._BACKEND = {}


def test_pricing_breakdown_uses_the_blended_rate():
    b = gemini_tts.pricing_cost_breakdown(1_000_000, 1_000_000, "flash31")
    # input misto: 1.00 - (1.00 - 0.7875) * 0.5 = 0.89375
    assert b["input_usd"] == pytest.approx(0.89375)
    assert b["output_usd"] == pytest.approx(16.30)


def test_actual_breakdown_on_cloudflare_uses_the_real_rate():
    b = gemini_tts.actual_cost_breakdown(1_000_000, 1_000_000, "flash31",
                                         "cloudflare")
    assert b["input_usd"] == pytest.approx(0.7875)
    assert b["output_usd"] == pytest.approx(12.60)


def test_actual_breakdown_on_vertex_uses_the_google_rate():
    b = gemini_tts.actual_cost_breakdown(1_000_000, 1_000_000, "flash31",
                                         "vertex")
    assert b["output_usd"] == pytest.approx(20.00)


def test_the_margin_between_price_and_real_cost_is_positive_on_cloudflare():
    price = gemini_tts.pricing_cost_breakdown(1000, 100_000, "flash31")
    real = gemini_tts.actual_cost_breakdown(1000, 100_000, "flash31",
                                            "cloudflare")
    assert price["total_eur"] > real["total_eur"]


def test_on_vertex_the_price_is_below_the_real_cost_before_margin():
    # E' la ragione per cui il failover va notificato: il margine lordo si
    # assottiglia fino a sfiorare il pareggio.
    price = gemini_tts.pricing_cost_breakdown(1000, 100_000, "flash31")
    real = gemini_tts.actual_cost_breakdown(1000, 100_000, "flash31", "vertex")
    assert price["total_eur"] < real["total_eur"]


def test_google_cost_breakdown_still_works_and_matches_the_price():
    legacy = gemini_tts.google_cost_breakdown(1000, 100_000, "flash31")
    price = gemini_tts.pricing_cost_breakdown(1000, 100_000, "flash31")
    assert legacy == price


def test_breakdown_keys_are_unchanged():
    b = gemini_tts.pricing_cost_breakdown(10, 10, "flash31")
    assert set(b) == {"input_usd", "output_usd", "total_usd", "total_eur"}
