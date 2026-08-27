"""Tariffe di prezzo (Cloudflare) e tariffe di costo reale (per backend)."""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    gemini_tts._BACKEND = {}
    yield
    gemini_tts._BACKEND = {}


def _cf_configured(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")


def test_flash31_carries_the_cloudflare_rates():
    m = gemini_tts.GEMINI_MODELS["flash31"]
    assert m["cf_input_usd_per_mtok"] == pytest.approx(0.75)
    assert m["cf_output_usd_per_mtok"] == pytest.approx(12.00)


def test_flash25_has_no_cloudflare_rates():
    m = gemini_tts.GEMINI_MODELS["flash25"]
    assert m["cf_input_usd_per_mtok"] is None
    assert m["cf_output_usd_per_mtok"] is None


def test_saving_share_defaults_to_half(monkeypatch):
    monkeypatch.delenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", raising=False)
    assert gemini_tts.cf_saving_share() == pytest.approx(0.5)


def test_saving_share_is_clamped(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "170")
    assert gemini_tts.cf_saving_share() == pytest.approx(1.0)
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "-3")
    assert gemini_tts.cf_saving_share() == pytest.approx(0.0)


def test_pricing_rates_blend_google_and_cloudflare(monkeypatch):
    _cf_configured(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    _, out_rate = gemini_tts.pricing_rates("flash31")
    # c_eff = 12.00 * 1.05 = 12.60 ; 20.00 - (20.00 - 12.60) * 0.5 = 16.30
    assert out_rate == pytest.approx(16.30)


def test_share_zero_keeps_the_google_list_price(monkeypatch):
    _cf_configured(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "0")
    _, out_rate = gemini_tts.pricing_rates("flash31")
    assert out_rate == pytest.approx(20.00)


def test_share_hundred_passes_the_whole_saving_to_the_customer(monkeypatch):
    _cf_configured(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT", "100")
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    _, out_rate = gemini_tts.pricing_rates("flash31")
    assert out_rate == pytest.approx(12.60)


def test_pricing_rates_ignore_a_trip_to_vertex(monkeypatch):
    # D1: lo switch e' una condizione straordinaria, il listino non oscilla.
    _cf_configured(monkeypatch)
    gemini_tts._set_backend("flash31", "vertex")
    _, out_rate = gemini_tts.pricing_rates("flash31")
    assert out_rate == pytest.approx(16.30)


def test_without_cloudflare_configured_pricing_is_pure_google(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    inp, out = gemini_tts.pricing_rates("flash31")
    assert (inp, out) == pytest.approx((1.00, 20.00))


def test_a_model_not_on_cloudflare_is_priced_on_google(monkeypatch):
    _cf_configured(monkeypatch)
    inp, out = gemini_tts.pricing_rates("flash25")
    assert (inp, out) == pytest.approx((0.50, 10.00))


def test_actual_rates_follow_the_executing_backend(monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    assert gemini_tts.actual_rates("flash31", "cloudflare") == \
        pytest.approx((0.7875, 12.60))
    assert gemini_tts.actual_rates("flash31", "vertex") == \
        pytest.approx((1.00, 20.00))
    assert gemini_tts.actual_rates("flash31", "apikey") == \
        pytest.approx((1.00, 20.00))


def test_actual_rates_on_a_model_without_cloudflare_fall_back_to_google():
    assert gemini_tts.actual_rates("flash25", "cloudflare") == \
        pytest.approx((0.50, 10.00))
