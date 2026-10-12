"""Helper engine-agnostic per il calcolo del trattenuto su cancel volontario.

Usato da Gemini TTS (run_generation, ramo _CancelledError). Il chiamante passa
il LISTINO della quota di lavoro gia' eseguita (per Gemini: tariffa €/ora x
ore di audio prodotte), mai il costo sostenuto dal backend che ha eseguito:
l'utente paga lo stesso lavoro allo stesso prezzo, qualunque infrastruttura
lo abbia servito.

Reference: docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md
"""
from __future__ import annotations

from typing import Dict


def compute_cancel_retention(list_price_consumed_eur: float,
                             paid_eur: float) -> Dict[str, float]:
    """Trattenuto e rimborso per un cancel volontario di un job pagato.

    Il trattenuto e' il PREZZO di listino del lavoro gia' consegnato, col
    tetto di quanto pagato: le commissioni PayPal sono dentro la tariffa,
    quindi non si sommano a parte.

        retained = min(paid, max(0, listino_consumato))
        refund   = paid - retained
    """
    paid = max(0.0, float(paid_eur or 0.0))
    consumed = max(0.0, float(list_price_consumed_eur or 0.0))
    retained = round(min(paid, consumed), 2)
    refund = round(max(0.0, paid - retained), 2)
    return {
        "retained_eur": retained,
        "refund_eur": refund,
        "list_price_consumed_eur": round(consumed, 4),
    }
