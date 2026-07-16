"""Audit log writer/reader per il costo/margine dei job di traduzione libro.

Formato: JSONL append-only, file mensile in ABM_DATA_DIR.
Filename: translation_cost_audit_YYYY-MM.jsonl

Gemello di gemini_cost_audit.py ma con assi lingua sorgente/destinazione.
Il costo provider (LLM) e' salvato dal chiamante sotto la chiave
`google_cost_eur_actual` (convenzione provider-agnostica condivisa con
l'audit TTS), cosi' gli helper di arricchimento in audiobook_app si riusano.
"""
import os
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

_DATA_DIR = Path(os.environ.get("ABM_DATA_DIR", "."))
_lock = threading.Lock()


def _current_file():
    ym = datetime.now(timezone.utc).strftime("%Y-%m")
    return _DATA_DIR / f"translation_cost_audit_{ym}.jsonl"


def append_record(record: dict):
    """Append atomico (append-mode + lock) di un record audit."""
    rec = dict(record)
    rec.setdefault("ts", datetime.now(timezone.utc).isoformat())
    line = json.dumps(rec, ensure_ascii=False, separators=(",", ":"))
    with _lock:
        fp = _current_file()
        fp.parent.mkdir(parents=True, exist_ok=True)
        with open(fp, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def iter_records(model=None, source_lang=None, target_lang=None,
                 outcome=None, date_from=None, date_to=None):
    """Itera record applicando filtri. date_from/to: ISO date 'YYYY-MM-DD'."""
    for fp in sorted(_DATA_DIR.glob("translation_cost_audit_*.jsonl")):
        try:
            with open(fp, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if model and rec.get("model_key") != model:
                        continue
                    if source_lang and rec.get("source_lang") != source_lang:
                        continue
                    if target_lang and rec.get("target_lang") != target_lang:
                        continue
                    if outcome and rec.get("outcome") != outcome:
                        continue
                    ts = rec.get("ts", "")
                    if date_from and ts[:10] < date_from:
                        continue
                    if date_to and ts[:10] > date_to:
                        continue
                    yield rec
        except IOError:
            continue
