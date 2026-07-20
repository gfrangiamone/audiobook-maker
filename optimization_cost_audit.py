"""Audit log writer/reader per il costo/margine dei job di OTTIMIZZAZIONE AI.

Formato: JSONL append-only, file mensile in ABM_DATA_DIR.
Filename: optimization_cost_audit_YYYY-MM.jsonl

Gemello di translation_cost_audit.py. Il costo provider (LLM) e' salvato dal
chiamante sotto la chiave `google_cost_eur_actual` (convenzione provider-agnostica
condivisa con gli altri audit), cosi' gli helper di arricchimento in
audiobook_app (_apply_cancel_effective) si riusano invariati.
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
    return _DATA_DIR / f"optimization_cost_audit_{ym}.jsonl"


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


def iter_records(model=None, language=None, outcome=None,
                 date_from=None, date_to=None):
    """Itera record applicando filtri. date_from/to: ISO date 'YYYY-MM-DD'.

    `model` e' accettato per simmetria d'API con gli altri audit ma qui filtra
    su `model_key` (es. 'deepseek-chat') se valorizzato.
    """
    for fp in sorted(_DATA_DIR.glob("optimization_cost_audit_*.jsonl")):
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
                    if language and rec.get("language") != language:
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
