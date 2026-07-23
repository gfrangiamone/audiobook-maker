"""Test per il floor minimo di costo dell'ottimizzazione LLM standalone.

`payment._llm_apply_min_cost` alza l'importo dovuto ad almeno LLM_MIN_COST_EUR
quando la stima grezza supera la soglia gratuita, preservando il lato della
soglia (un job free resta free). Vale solo per l'ottimizzazione standalone.
"""
import pytest

import payment


@pytest.fixture
def floor_params(monkeypatch):
    """Soglia free 0.50, floor minimo 1.00 (deterministici)."""
    monkeypatch.setattr(payment, "LLM_FREE_THRESHOLD_EUR", 0.50)
    monkeypatch.setattr(payment, "LLM_MIN_COST_EUR", 1.00)


def test_below_threshold_unchanged(floor_params):
    # Sotto soglia: resta free, nessun floor applicato.
    assert payment._llm_apply_min_cost(0.30) == 0.30
    assert payment._llm_apply_min_cost(0.0) == 0.0


def test_at_threshold_unchanged(floor_params):
    # Pari alla soglia: ancora free (il confronto a valle usa `>`).
    assert payment._llm_apply_min_cost(0.50) == 0.50


def test_above_threshold_below_min_raised_to_floor(floor_params):
    # A pagamento ma sotto il minimo: alzato al floor.
    assert payment._llm_apply_min_cost(0.60) == 1.00
    assert payment._llm_apply_min_cost(0.99) == 1.00


def test_above_min_unchanged(floor_params):
    # Oltre il minimo: importo pieno, nessun ritocco.
    assert payment._llm_apply_min_cost(1.50) == 1.50
    assert payment._llm_apply_min_cost(2.00) == 2.00


def test_preserves_threshold_side(floor_params):
    # Invariante chiave: l'output resta dallo stesso lato della soglia
    # dell'input, cosi' i confronti `> LLM_FREE_THRESHOLD_EUR` a valle
    # restano identici su input grezzo e output.
    thr = payment.LLM_FREE_THRESHOLD_EUR
    for raw in (0.0, 0.10, 0.49, 0.50, 0.51, 0.75, 1.0, 3.0):
        due = payment._llm_apply_min_cost(raw)
        assert (raw > thr) == (due > thr)


def test_default_min_cost_is_one():
    # Default parametrico documentato: €1 (ABM_LLM_MIN_COST_EUR).
    assert payment.LLM_MIN_COST_EUR == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# llm_price_eur: source of truth unica del prezzo dell'ottimizzazione AI,
# usata da stima combinata, stima standalone, ordine PayPal, consumo voucher,
# addebito e audit. Consolida raw + soglia + floor in un unico punto.
# ---------------------------------------------------------------------------
@pytest.fixture
def price_params(monkeypatch):
    """Rate 2.00 €/Mchar, soglia free 0.50, floor 1.00 (deterministici)."""
    monkeypatch.setattr(payment, "LLM_RATE_EUR_PER_MCHAR", 2.00)
    monkeypatch.setattr(payment, "LLM_FREE_THRESHOLD_EUR", 0.50)
    monkeypatch.setattr(payment, "LLM_MIN_COST_EUR", 1.00)


def test_price_standalone_free(price_params):
    # 100k chars × 2.00/1M = 0.20 <= soglia -> free, due = grezzo (no floor).
    p = payment.llm_price_eur(100_000)
    assert p["raw_eur"] == pytest.approx(0.20)
    assert p["due_eur"] == pytest.approx(0.20)
    assert p["requires_payment"] is False
    assert p["floored"] is False


def test_price_standalone_paid_below_min_floored(price_params):
    # 300k chars × 2.00/1M = 0.60 > soglia ma < floor -> alzato a 1.00.
    p = payment.llm_price_eur(300_000)
    assert p["raw_eur"] == pytest.approx(0.60)
    assert p["due_eur"] == pytest.approx(1.00)
    assert p["requires_payment"] is True
    assert p["floored"] is True


def test_price_standalone_paid_above_min(price_params):
    # 800k chars × 2.00/1M = 1.60 > floor -> importo pieno, nessun ritocco.
    p = payment.llm_price_eur(800_000)
    assert p["raw_eur"] == pytest.approx(1.60)
    assert p["due_eur"] == pytest.approx(1.60)
    assert p["requires_payment"] is True
    assert p["floored"] is False


def test_price_combined_never_floored(price_params):
    # Quota LLM di un pagamento PREMIUM combinato: nessun floor, due = grezzo,
    # anche quando il grezzo supera la soglia (il pagamento e' del totale).
    p = payment.llm_price_eur(300_000, is_combined=True)
    assert p["raw_eur"] == pytest.approx(0.60)
    assert p["due_eur"] == pytest.approx(0.60)
    assert p["requires_payment"] is False
    assert p["floored"] is False


def test_price_matches_apply_min_cost_standalone(price_params):
    # Invariante di consolidamento: due_eur standalone == _llm_apply_min_cost(raw)
    # su tutto il dominio (free -> grezzo, paid -> floor).
    for chars in (0, 50_000, 250_000, 300_000, 499_000, 900_000):
        p = payment.llm_price_eur(chars)
        assert p["due_eur"] == pytest.approx(
            payment._llm_apply_min_cost(p["raw_eur"]))
