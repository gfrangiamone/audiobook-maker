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


def test_the_ab_bench_measures_vertex_at_its_real_cost_not_at_the_listino():
    """Ottavo "specchio" prezzo-vs-costo (F6 della revisione finale), in
    `scripts/tts_cloudflare_gemini_test.py`: il ramo Vertex del banco A/B
    calcolava la colonna di costo con `google_cost_breakdown`, che e' un alias
    del LISTINO. Girando in una shell con `ABM_GEMINI_BACKEND=cloudflare` —
    il caso naturale mentre si prova Cloudflare — quel listino e' la tariffa
    mista, scontata della quota di risparmio ceduta al cliente: la colonna
    "costo Vertex" scendeva esattamente di quella quota e il confronto
    economico A/B, cioe' il numero per cui il banco esiste, sottostimava
    Vertex.

    Che i due numeri NON siano intercambiabili e' gia' fissato qui sopra da
    `test_on_vertex_the_price_is_below_the_real_cost_before_margin`. Quello
    che non era fissato da niente e' il call site: lo script non e' importabile
    a costo ragionevole (argparse e I/O a livello di modulo) e nessun test lo
    tocca, quindi la verifica e' sul sorgente.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parent.parent
           / "scripts" / "tts_cloudflare_gemini_test.py").read_text(encoding="utf-8")
    assert 'actual_cost_breakdown(\n        tokens_in, tokens_out, "flash31", "vertex")' in src, (
        "il ramo Vertex del banco deve usare actual_cost_breakdown(..., "
        '"vertex")')
    assert "gemini_tts.google_cost_breakdown(" not in src, (
        "google_cost_breakdown e' l'alias del listino: nel banco A/B "
        "sottostima Vertex della quota di risparmio ceduta al cliente")


def test_breakdown_keys_are_unchanged():
    b = gemini_tts.pricing_cost_breakdown(10, 10, "flash31")
    assert set(b) == {"input_usd", "output_usd", "total_usd", "total_eur"}
