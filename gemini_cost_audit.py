"""Audit log writer/reader/aggregator per Gemini TTS cost estimation.

Formato: JSONL append-only, file mensile in ABM_DATA_DIR (letto a ogni
chiamata; `_DATA_DIR`, se valorizzato, lo sovrascrive: lo fanno i test).
Filename: gemini_cost_audit_YYYY-MM.jsonl

Writer, reader e filtri vengono da `jsonl_audit.MonthlyJsonl`; qui restano
l'API pubblica (`append_record`, `iter_records`) e `aggregate`.
"""
from pathlib import Path

from env_utils import env_str
import jsonl_audit
from jsonl_audit import MonthlyJsonl

_DATA_DIR = None


def _dir():
    return _DATA_DIR if _DATA_DIR is not None else Path(env_str("ABM_DATA_DIR", "."))


_store = MonthlyJsonl("gemini_cost_audit", _dir, keep_months=jsonl_audit.cost_keep_months)


def _current_file():
    return _store.path()


def append_record(record: dict):
    """Append atomico (append-mode + lock) di un record audit."""
    _store.append(record)


def iter_records(model=None, language=None, outcome=None,
                 date_from=None, date_to=None):
    """Itera record applicando filtri. date_from/to: ISO date 'YYYY-MM-DD'."""
    return _store.iter(filters={"model_key": model, "language": language},
                       outcome=outcome, date_from=date_from, date_to=date_to)


def aggregate(model=None, language=None, date_from=None, date_to=None):
    """Aggregati su record completed: count, revenue, cost, margin, delta avg.

    `delta_pct_avg` e` ricomputato dai totali euro
    (sum(delta_eur) / sum(pricing_cost) * 100), sempre sulla base di LISTINO
    (D1), mai sul costo reale sostenuto dal backend che ha eseguito il job:
    un denominatore sul costo reale non genera un falso allarme dal nulla,
    ma gonfia ogni deriva genuina, rendendo inaffidabile la cifra letta
    durante un incidente vero. Fallback su google_cost_eur_actual per record
    storici pre-esistenti alla separazione listino/reale (dove i due numeri
    coincidevano comunque).
    """
    n = 0
    revenue = 0.0
    cost = 0.0
    pricing_cost = 0.0
    delta_eur_sum = 0.0
    for rec in iter_records(model=model, language=language,
                            outcome="completed",
                            date_from=date_from, date_to=date_to):
        n += 1
        revenue += float(rec.get("user_price_eur_charged", 0) or 0)
        google_cost_actual = float(rec.get("google_cost_eur_actual", 0) or 0)
        cost += google_cost_actual
        pricing_cost += float(rec.get("pricing_cost_eur_actual", google_cost_actual) or google_cost_actual)
        delta_eur_sum += float(rec.get("delta_eur", 0) or 0)
    delta_pct_avg = round((delta_eur_sum / pricing_cost * 100), 2) if pricing_cost > 0 else 0.0
    return {
        "count": n,
        "revenue_eur": round(revenue, 4),
        "google_cost_eur": round(cost, 4),
        "margin_eur": round(revenue - cost, 4),
        "delta_pct_avg": delta_pct_avg,
        "filters": {"model": model, "language": language,
                    "date_from": date_from, "date_to": date_to},
    }
