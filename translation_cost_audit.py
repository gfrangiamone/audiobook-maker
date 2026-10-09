"""Audit log writer/reader per il costo/margine dei job di traduzione libro.

Formato: JSONL append-only, file mensile in ABM_DATA_DIR (letto a ogni
chiamata; `_DATA_DIR`, se valorizzato, lo sovrascrive: lo fanno i test).
Filename: translation_cost_audit_YYYY-MM.jsonl

Gemello di gemini_cost_audit.py ma con assi lingua sorgente/destinazione.
Il costo provider (LLM) e' salvato dal chiamante sotto la chiave
`google_cost_eur_actual` (convenzione provider-agnostica condivisa con
l'audit TTS), cosi' gli helper di arricchimento in audiobook_app si riusano.
Writer e reader: `jsonl_audit.MonthlyJsonl`.
"""
from pathlib import Path

from env_utils import env_str
import jsonl_audit
from jsonl_audit import MonthlyJsonl

_DATA_DIR = None


def _dir():
    return _DATA_DIR if _DATA_DIR is not None else Path(env_str("ABM_DATA_DIR", "."))


_store = MonthlyJsonl("translation_cost_audit", _dir, keep_months=jsonl_audit.cost_keep_months)


def _current_file():
    return _store.path()


def append_record(record: dict):
    """Append atomico (append-mode + lock) di un record audit."""
    _store.append(record)


def iter_records(model=None, source_lang=None, target_lang=None,
                 outcome=None, date_from=None, date_to=None):
    """Itera record applicando filtri. date_from/to: ISO date 'YYYY-MM-DD'."""
    return _store.iter(filters={"model_key": model, "source_lang": source_lang,
                                "target_lang": target_lang},
                       outcome=outcome, date_from=date_from, date_to=date_to)
