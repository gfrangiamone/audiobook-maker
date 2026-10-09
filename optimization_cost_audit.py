"""Audit log writer/reader per il costo/margine dei job di OTTIMIZZAZIONE AI.

Formato: JSONL append-only, file mensile in ABM_DATA_DIR (letto a ogni
chiamata; `_DATA_DIR`, se valorizzato, lo sovrascrive: lo fanno i test).
Filename: optimization_cost_audit_YYYY-MM.jsonl

Gemello di translation_cost_audit.py. Il costo provider (LLM) e' salvato dal
chiamante sotto la chiave `google_cost_eur_actual` (convenzione provider-agnostica
condivisa con gli altri audit), cosi' gli helper di arricchimento in
audiobook_app (_apply_cancel_effective) si riusano invariati.
Writer e reader: `jsonl_audit.MonthlyJsonl`.
"""
from pathlib import Path

from env_utils import env_str
from jsonl_audit import MonthlyJsonl

_DATA_DIR = None


def _dir():
    return _DATA_DIR if _DATA_DIR is not None else Path(env_str("ABM_DATA_DIR", "."))


_store = MonthlyJsonl("optimization_cost_audit", _dir)


def _current_file():
    return _store.path()


def append_record(record: dict):
    """Append atomico (append-mode + lock) di un record audit."""
    _store.append(record)


def iter_records(model=None, language=None, outcome=None,
                 date_from=None, date_to=None):
    """Itera record applicando filtri. date_from/to: ISO date 'YYYY-MM-DD'.

    `model` e' accettato per simmetria d'API con gli altri audit ma qui filtra
    su `model_key` (es. 'deepseek-chat') se valorizzato.
    """
    return _store.iter(filters={"model_key": model, "language": language},
                       outcome=outcome, date_from=date_from, date_to=date_to)
