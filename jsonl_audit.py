"""jsonl_audit — file JSONL mensili append-only (audit, dataset, metriche).

Modulo foglia (stdlib + `fileio`). Prima: tre `*_cost_audit.py` con lo
stesso writer e lo stesso reader, cinque `write_audit` dei judge, tre
writer in `generation_engine`/`load_metrics` e due lettori che parsavano
i file da soli (`gemini_tts.get_daily_spent_eur`, `voxcpm_digest`).

`MonthlyJsonl(prefix, data_dir_fn)` scrive e legge `<dir>/<prefix>_YYYY-MM.jsonl`:
- `append(rec)`: una riga, con lock e `ts` UTC se manca; `append_many(recs)`
  per un blocco in una sola scrittura.
- `iter(filters=..., outcome=..., date_from=..., date_to=..., month=...)`:
  record in ordine di file, righe vuote o corrotte saltate, filtri per
  uguaglianza (valori falsy ignorati) e per data ISO `YYYY-MM-DD` su `ts`.
- `purge(keep_months)`: cancella i file piu' vecchi di N mesi.

`data_dir_fn` e' una funzione: la cartella si risolve a ogni chiamata, mai
all'import (i test cambiano `ABM_DATA_DIR` a runtime). `compact=True` usa
`separators=(",", ":")` (audit di costo), `False` lo stile di `json.dumps`
(audit dei judge): i file gia' scritti restano leggibili con lo stesso
formato con cui sono nati.
"""
import json
import threading
from datetime import datetime, timezone
from pathlib import Path

from fileio import data_dir as _default_data_dir


def month_now():
    """Mese corrente UTC, `YYYY-MM`."""
    return datetime.now(timezone.utc).strftime("%Y-%m")


def ts_now():
    """Timestamp ISO UTC come lo scrivono tutti gli audit."""
    return datetime.now(timezone.utc).isoformat()


class MonthlyJsonl:
    def __init__(self, prefix, data_dir_fn=None, *, compact=True, ascii=False,
                 require_dir=False):
        """`require_dir=True`: se la cartella non esiste non si scrive (e non
        si crea), come fanno gli audit dei judge; altrimenti `mkdir -p`."""
        self.prefix = prefix
        self._dir_fn = data_dir_fn or _default_data_dir
        self._kw = ({"separators": (",", ":")} if compact else {})
        self._ascii = ascii
        self._require_dir = require_dir
        self._lock = threading.Lock()

    def data_dir(self):
        return Path(self._dir_fn())

    def path(self, month=None):
        return self.data_dir() / f"{self.prefix}_{month or month_now()}.jsonl"

    def dumps(self, rec):
        return json.dumps(rec, ensure_ascii=self._ascii, **self._kw)

    def _writable_path(self, month):
        fp = self.path(month)
        if self._require_dir:
            if not fp.parent.is_dir():
                return None
        else:
            fp.parent.mkdir(parents=True, exist_ok=True)
        return fp

    def append(self, rec, *, month=None, add_ts=True):
        """Scrive una riga. Ritorna False se `require_dir` e la cartella manca."""
        return self.append_many([rec], month=month, add_ts=add_ts)

    def append_many(self, recs, *, month=None, add_ts=True):
        lines = []
        for rec in recs:
            rec = dict(rec)
            if add_ts:
                rec.setdefault("ts", ts_now())
            lines.append(self.dumps(rec))
        if not lines:
            return True
        with self._lock:
            fp = self._writable_path(month)
            if fp is None:
                return False
            with open(fp, "a", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
        return True

    def files(self, month=None):
        """I file del prefisso in ordine di nome (= cronologico), o solo quello
        di `month`."""
        if month:
            fp = self.path(month)
            return [fp] if fp.exists() else []
        return sorted(self.data_dir().glob(f"{self.prefix}_*.jsonl"))

    def iter(self, *, filters=None, outcome=None, date_from=None, date_to=None,
             month=None):
        """Record (dict) che passano i filtri; file illeggibili saltati."""
        active = {k: v for k, v in (filters or {}).items() if v}
        if outcome:
            active["outcome"] = outcome
        for fp in self.files(month):
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
                        if not isinstance(rec, dict):
                            continue
                        if any(rec.get(k) != v for k, v in active.items()):
                            continue
                        ts = str(rec.get("ts") or "")
                        if date_from and ts[:10] < date_from:
                            continue
                        if date_to and ts[:10] > date_to:
                            continue
                        yield rec
            except OSError:
                continue

    def purge(self, keep_months, *, now=None):
        """Cancella i file piu' vecchi di `keep_months` mesi (il mese corrente
        conta come 1). Ritorna i path rimossi."""
        if keep_months is None or keep_months <= 0:
            return []
        now = now or datetime.now(timezone.utc)
        idx = now.year * 12 + now.month - 1
        removed = []
        for fp in self.files():
            ym = fp.name[len(self.prefix) + 1:-len(".jsonl")]
            try:
                y, m = int(ym[:4]), int(ym[5:7])
            except ValueError:
                continue
            if idx - (y * 12 + m - 1) >= keep_months:
                try:
                    fp.unlink()
                    removed.append(fp)
                except OSError:
                    pass
        return removed
