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
