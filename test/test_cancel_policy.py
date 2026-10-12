"""Test della funzione compute_cancel_retention (cancel_policy.py).

Trattenuto = listino del lavoro consegnato, col tetto del pagato. Niente
commissioni a parte: sono dentro la tariffa.
"""
import pytest

from cancel_policy import compute_cancel_retention


@pytest.mark.parametrize("paid,consumed,exp_retained,exp_refund", [
    (0.00, 0.00, 0.00, 0.00),
    (0.00, 0.10, 0.00, 0.00),
    (2.00, 0.00, 0.00, 2.00),
    (2.00, 0.30, 0.30, 1.70),
    (2.00, 1.80, 1.80, 0.20),
    (2.00, 2.00, 2.00, 0.00),
    (2.00, 5.00, 2.00, 0.00),   # tetto al pagato
    (1.50, 0.204, 0.20, 1.30),  # arrotondato al centesimo
])
def test_compute_cancel_retention_matrix(paid, consumed, exp_retained, exp_refund):
    out = compute_cancel_retention(consumed, paid)
    assert out["retained_eur"] == pytest.approx(exp_retained, abs=0.001)
    assert out["refund_eur"] == pytest.approx(exp_refund, abs=0.001)
    assert out["retained_eur"] + out["refund_eur"] == pytest.approx(paid, abs=0.011)


def test_compute_cancel_retention_returns_floats():
    out = compute_cancel_retention(0.30, 2.00)
    assert isinstance(out["retained_eur"], float)
    assert isinstance(out["refund_eur"], float)


def test_compute_cancel_retention_keys():
    out = compute_cancel_retention(0.0, 0.0)
    assert set(out) == {"retained_eur", "refund_eur", "list_price_consumed_eur"}


def test_valori_negativi_o_nulli_trattati_come_zero():
    out = compute_cancel_retention(-1.0, None)
    assert out == {"retained_eur": 0.0, "refund_eur": 0.0,
                   "list_price_consumed_eur": 0.0}
