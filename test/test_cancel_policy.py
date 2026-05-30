"""Test della funzione compute_cancel_retention (cancel_policy.py).

Matrice da spec docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md §10.1.
"""
import os
import pytest

os.environ.setdefault("ABM_GEMINI_PAYPAL_PERCENT_FEE", "3.4")
os.environ.setdefault("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", "0.34")

from cancel_policy import compute_cancel_retention


@pytest.mark.parametrize("paid,prov_cost,method,exp_retained,exp_refund,exp_fees", [
    (0.00, 0.00, "",        0.00, 0.00, 0.00),
    (0.00, 0.10, "",        0.00, 0.00, 0.00),
    (2.00, 0.00, "voucher", 0.00, 2.00, 0.00),
    (2.00, 0.00, "paypal",  0.41, 1.59, 0.41),
    (2.00, 0.30, "voucher", 0.30, 1.70, 0.00),
    (2.00, 0.30, "paypal",  0.71, 1.29, 0.41),
    (2.00, 1.80, "voucher", 1.80, 0.20, 0.00),
    (2.00, 1.80, "paypal",  2.00, 0.00, 0.41),
    (2.00, 5.00, "paypal",  2.00, 0.00, 0.41),
    (0.60, 0.30, "paypal",  0.60, 0.00, 0.36),
    (1.50, 0.20, "paypal",  0.59, 0.91, 0.39),
])
def test_compute_cancel_retention_matrix(paid, prov_cost, method,
                                          exp_retained, exp_refund, exp_fees):
    out = compute_cancel_retention(prov_cost, method, paid)
    assert out["retained_eur"] == pytest.approx(exp_retained, abs=0.01)
    assert out["refund_eur"] == pytest.approx(exp_refund, abs=0.01)
    assert out["paypal_fees_eur"] == pytest.approx(exp_fees, abs=0.01)


def test_compute_cancel_retention_returns_floats():
    out = compute_cancel_retention(0.30, "voucher", 2.00)
    assert isinstance(out["retained_eur"], float)
    assert isinstance(out["refund_eur"], float)
    assert isinstance(out["paypal_fees_eur"], float)


def test_compute_cancel_retention_keys():
    out = compute_cancel_retention(0.0, "", 0.0)
    assert {"retained_eur", "refund_eur", "paypal_fees_eur",
            "provider_cost_eur", "cost_with_margin_eur",
            "margin_percent"}.issubset(out.keys())


def test_compute_cancel_retention_unknown_method_treated_as_no_fees():
    out = compute_cancel_retention(0.30, "stripe", 2.00)
    assert out["paypal_fees_eur"] == 0.00
    assert out["retained_eur"] == pytest.approx(0.30, abs=0.01)


# ─── Margin (ricarico) tests ─────────────────────────────────────────────────
# Il trattenuto = costo_provider * (1 + margin/100) + paypal_fees (se PayPal).
# Vincolato dal cap paid_eur.
@pytest.mark.parametrize("paid,prov_cost,margin,method,exp_retained,exp_refund", [
    # voucher (no fees): retained = cost * (1 + margin/100), capped a paid
    (10.00, 1.00, 40.0, "voucher", 1.40, 8.60),
    (10.00, 2.00, 40.0, "voucher", 2.80, 7.20),
    (10.00, 5.00, 30.0, "voucher", 6.50, 3.50),
    (10.00, 8.00, 40.0, "voucher", 10.00, 0.00),     # cap a paid
    (5.00,  4.00, 40.0, "voucher", 5.00, 0.00),      # cap a paid
    # margin 0 = comportamento legacy
    (2.00, 0.30, 0.0, "voucher", 0.30, 1.70),
    # paypal: retained = cost*(1+margin) + paypal_fees
    (10.00, 1.00, 40.0, "paypal", 1.40 + 0.34 + 10.00*0.034, 10.00 - (1.40 + 0.34 + 10.00*0.034)),
    (10.00, 5.00, 30.0, "paypal", 6.50 + 0.34 + 10.00*0.034, 10.00 - (6.50 + 0.34 + 10.00*0.034)),
])
def test_compute_cancel_retention_with_margin(paid, prov_cost, margin, method,
                                                exp_retained, exp_refund):
    out = compute_cancel_retention(prov_cost, method, paid, margin_percent=margin)
    assert out["retained_eur"] == pytest.approx(exp_retained, abs=0.01)
    assert out["refund_eur"] == pytest.approx(exp_refund, abs=0.01)
    assert out["margin_percent"] == pytest.approx(margin, abs=0.001)
    assert out["cost_with_margin_eur"] == pytest.approx(
        prov_cost * (1 + margin / 100.0), abs=0.001)


def test_compute_cancel_retention_margin_zero_is_legacy():
    """margin=0 (default) deve coincidere col comportamento pre-margin."""
    a = compute_cancel_retention(0.30, "paypal", 2.00)
    b = compute_cancel_retention(0.30, "paypal", 2.00, margin_percent=0.0)
    assert a["retained_eur"] == b["retained_eur"]
    assert a["refund_eur"] == b["refund_eur"]


def test_compute_cancel_retention_negative_margin_clamped_to_zero():
    out = compute_cancel_retention(1.00, "voucher", 5.00, margin_percent=-50.0)
    assert out["retained_eur"] == pytest.approx(1.00, abs=0.01)
    assert out["margin_percent"] == 0.0
