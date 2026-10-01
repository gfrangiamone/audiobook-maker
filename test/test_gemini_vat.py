"""IVA come costo per backend: vertex/apikey si', cloudflare no."""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "22")
    monkeypatch.setitem(gemini_tts.GEMINI_MODELS["flash31"], "input_usd_per_mtok", 1.00)
    monkeypatch.setitem(gemini_tts.GEMINI_MODELS["flash31"], "output_usd_per_mtok", 20.00)


def test_fattore_iva_per_backend():
    assert gemini_tts._vat_factor("vertex") == pytest.approx(1.22)
    assert gemini_tts._vat_factor("apikey") == pytest.approx(1.22)
    assert gemini_tts._vat_factor("cloudflare") == 1.0
    assert gemini_tts._vat_factor(None) == pytest.approx(1.22)


def test_actual_rates_vertex_lordo():
    assert gemini_tts.actual_rates("flash31", "vertex") == pytest.approx((1.22, 24.4))


def test_actual_rates_cloudflare_senza_iva():
    fee = 1.0 + gemini_tts._cf_topup_fee()
    assert gemini_tts.actual_rates("flash31", "cloudflare") == pytest.approx((0.75 * fee, 12.0 * fee))


def test_breakdown_reale_separa_iva():
    bd = gemini_tts.actual_cost_breakdown(0, 1_000_000, "flash31", "vertex")
    net = 20.0 * gemini_tts.USD_EUR_RATE
    assert bd["net_eur"] == pytest.approx(net)
    assert bd["vat_eur"] == pytest.approx(net * 0.22)
    assert bd["total_eur"] == pytest.approx(net * 1.22)


def test_breakdown_cloudflare_iva_zero():
    bd = gemini_tts.actual_cost_breakdown(0, 1_000_000, "flash31", "cloudflare")
    assert bd["vat_eur"] == 0.0
    assert bd["total_eur"] == pytest.approx(bd["net_eur"])


def test_listino_non_espone_iva():
    bd = gemini_tts.pricing_cost_breakdown(100, 1000, "flash31")
    assert not any("vat" in k for k in bd)


def test_listino_flash31_invariato_rispetto_a_env_gonfiate(monkeypatch):
    # Oggi in prod: env Vertex gonfiate del 22% e nessuna IVA separata.
    # Dopo: env al netto + IVA 22%. Il listino misto deve coincidere.
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    nuovo = gemini_tts.pricing_rates("flash31")
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "0")
    monkeypatch.setitem(gemini_tts.GEMINI_MODELS["flash31"], "input_usd_per_mtok", 1.22)
    monkeypatch.setitem(gemini_tts.GEMINI_MODELS["flash31"], "output_usd_per_mtok", 24.4)
    vecchio = gemini_tts.pricing_rates("flash31")
    assert nuovo == pytest.approx(vecchio)


def test_iva_negativa_trattata_come_zero(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "-5")
    assert gemini_tts._vat_factor("vertex") == 1.0
