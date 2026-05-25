"""Helper engine-agnostic per il calcolo del trattenuto su cancel volontario.

Usato in Fase 1 da Gemini TTS (run_generation branch _CancelledError) e in
Fase 2 (futura, spec separata) dall'optimization LLM. La firma e' agnostica
rispetto al provider: il chiamante passa il costo reale del provider gia'
accumulato per la quota di lavoro eseguita.

Reference: docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md
"""
from __future__ import annotations

import os
from typing import Dict


def _paypal_fee_pct() -> float:
    try:
        return float(os.environ.get("ABM_GEMINI_PAYPAL_PERCENT_FEE", "3.4")
                     .replace(",", "."))
    except (TypeError, ValueError):
        return 3.4


def _paypal_fee_fixed_eur() -> float:
    try:
        return float(os.environ.get("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", "0.34")
                     .replace(",", "."))
    except (TypeError, ValueError):
        return 0.34


def compute_cancel_retention(provider_cost_eur: float,
                              payment_method: str,
                              paid_eur: float) -> Dict[str, float]:
    """Calcola trattenuto e refund per un cancel volontario di un job pagato.

    Floor = provider_cost_eur + paypal_fees (se metodo PayPal).
    retained = min(paid, max(0, floor))
    refund   = paid - retained
    """
    paid = max(0.0, float(paid_eur or 0.0))
    cost = max(0.0, float(provider_cost_eur or 0.0))
    if payment_method == "paypal" and paid > 0:
        fees = round(_paypal_fee_fixed_eur() + paid * _paypal_fee_pct() / 100.0, 2)
    else:
        fees = 0.0
    raw_retained = cost + fees
    retained = round(min(paid, max(0.0, raw_retained)), 2)
    refund = round(max(0.0, paid - retained), 2)
    return {
        "retained_eur": retained,
        "refund_eur": refund,
        "paypal_fees_eur": round(fees, 2),
    }
