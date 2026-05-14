"""Audit log writer/reader/aggregator per Gemini TTS cost estimation.

Formato: JSONL append-only, file mensile in ABM_DATA_DIR.
Filename: gemini_cost_audit_YYYY-MM.jsonl
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
    return _DATA_DIR / f"gemini_cost_audit_{ym}.jsonl"


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
    """Itera record applicando filtri. date_from/to: ISO date 'YYYY-MM-DD'."""
    for fp in sorted(_DATA_DIR.glob("gemini_cost_audit_*.jsonl")):
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


def aggregate(model=None, language=None, date_from=None, date_to=None):
    """Aggregati su record completed: count, revenue, cost, margin, delta avg."""
    n = 0
    revenue = 0.0
    cost = 0.0
    delta_pcts = []
    for rec in iter_records(model=model, language=language,
                            outcome="completed",
                            date_from=date_from, date_to=date_to):
        n += 1
        revenue += float(rec.get("user_price_eur_charged", 0) or 0)
        cost += float(rec.get("google_cost_eur_actual", 0) or 0)
        dp = rec.get("delta_pct")
        if dp is not None:
            delta_pcts.append(float(dp))
    return {
        "count": n,
        "revenue_eur": round(revenue, 4),
        "google_cost_eur": round(cost, 4),
        "margin_eur": round(revenue - cost, 4),
        "delta_pct_avg": round(sum(delta_pcts) / len(delta_pcts), 2) if delta_pcts else 0.0,
        "filters": {"model": model, "language": language,
                    "date_from": date_from, "date_to": date_to},
    }
