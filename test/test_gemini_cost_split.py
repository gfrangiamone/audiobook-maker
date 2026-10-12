"""Il prezzo e il costo reale sono due numeri distinti."""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _cf(monkeypatch):
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    # Questo file fissa i numeri di costo sulle tariffe nette: l'IVA e'
    # testata a parte in test_gemini_vat.py.
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "0")
    yield
    gemini_tts._BACKEND = {}


def test_actual_breakdown_on_cloudflare_uses_the_real_rate():
    b = gemini_tts.actual_cost_breakdown(1_000_000, 1_000_000, "flash31",
                                         "cloudflare")
    assert b["input_usd"] == pytest.approx(0.7875)
    assert b["output_usd"] == pytest.approx(12.60)


def test_actual_breakdown_on_vertex_uses_the_google_rate():
    b = gemini_tts.actual_cost_breakdown(1_000_000, 1_000_000, "flash31",
                                         "vertex")
    assert b["output_usd"] == pytest.approx(20.00)


def test_the_price_is_the_same_whatever_backend_executes():
    # Un'ora di audio: 1,90 EUR, che l'abbia servita Cloudflare o Vertex.
    p = gemini_tts.compute_user_price_eur(3600.0, "flash31")
    gemini_tts._set_backend("flash31", "vertex")
    assert gemini_tts.compute_user_price_eur(3600.0, "flash31") == p


def test_the_margin_is_positive_on_cloudflare_and_on_vertex():
    # Un'ora di audio flash31 = 25 tok/s * 3600 = 90k token in uscita.
    price = gemini_tts.compute_user_price_eur(3600.0, "flash31")["list_price_eur"]
    cf = gemini_tts.actual_cost_breakdown(5000, 90_000, "flash31", "cloudflare")
    vx = gemini_tts.actual_cost_breakdown(5000, 90_000, "flash31", "vertex")
    assert price > cf["total_eur"]
    assert price > vx["total_eur"]


def test_the_ab_bench_measures_vertex_at_its_real_cost():
    """Il banco A/B (`scripts/tts_cloudflare_gemini_test.py`) deve misurare
    Vertex col costo reale del backend: lo script non e' importabile a costo
    ragionevole (argparse e I/O a livello di modulo), quindi la verifica e'
    sul sorgente."""
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "scripts" / "tts_cloudflare_gemini_test.py").read_text(encoding="utf-8")
    assert 'actual_cost_breakdown(\n        tokens_in, tokens_out, "flash31", "vertex")' in src, (
        "il ramo Vertex del banco deve usare actual_cost_breakdown(..., "
        '"vertex")')


def test_breakdown_keys_are_unchanged():
    b = gemini_tts.actual_cost_breakdown(10, 10, "flash31", "vertex")
    assert set(b) == {"input_usd", "output_usd", "total_usd", "total_eur",
                      "net_eur", "vat_eur"}
