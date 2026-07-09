"""JSON file persistence for community widgets (news, feedback).

Atomic write (tmp + rename), per-file lock, single backup .bak.
No SQLite — small datasets, simple deployment.

Espone anche `atomic_write_json`, il primitivo di scrittura JSON atomica
condiviso da tutte le persistenze snapshot dell'app (token, pagamenti,
voucher, usage, metriche): prima era duplicato in ~10 copie inline nei
singoli moduli. Non richiede init() e non tocca _data_dir.
"""
from __future__ import annotations

import json
import os
import secrets
import threading
import time
from pathlib import Path
from typing import Any


_data_dir: Path | None = None
_stores: dict[str, "JsonStore"] = {}
_init_lock = threading.Lock()


def atomic_write_json(path, data, *, fsync=True, ensure_ascii=False, indent=None):
    """Scrive `data` come JSON su `path` in modo atomico: tmp + fsync opzionale
    + os.replace. Un crash a metà write lascia intatto il file precedente; il
    rename atomico garantisce che il file non sia mai osservabile troncato.

    NON è thread-safe di per sé: la disciplina di lock resta a carico del
    chiamante (ogni store mantiene il proprio lock, come prima). Propaga le
    eccezioni: la gestione errori (log best-effort vs fatal) resta nei wrapper
    per-store. I parametri di formato replicano quelli del writer originale
    per mantenere byte-stabile il contenuto su disco.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=ensure_ascii, indent=indent)
        if fsync:
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass  # filesystem senza fsync (rari edge case)
    os.replace(str(tmp), str(path))


def init(data_dir: str | os.PathLike) -> None:
    """Initialize the module pointing at the persistent data directory."""
    global _data_dir
    p = Path(data_dir)
    p.mkdir(parents=True, exist_ok=True)
    _data_dir = p


class JsonStore:
    """Append-mostly JSON store with id-keyed items list."""

    def __init__(self, filename: str):
        if _data_dir is None:
            raise RuntimeError("community_store.init() must be called first")
        self.path = _data_dir / filename
        self.bak = _data_dir / (filename + ".bak")
        self._lock = threading.Lock()
        if not self.path.exists():
            self._write_unlocked({"items": []})

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            if self.bak.exists():
                try:
                    with open(self.bak, "r", encoding="utf-8") as f:
                        return json.load(f)
                except (OSError, json.JSONDecodeError):
                    pass
            return {"items": []}

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        # Backup current file before overwriting
        if self.path.exists():
            try:
                self.path.replace(self.bak)
            except OSError:
                pass
        # fsync=False: comportamento storico di questo store (dataset piccoli,
        # best-effort); il .bak sopra copre il recovery.
        atomic_write_json(self.path, data, fsync=False, indent=2)

    def all(self, include_archived: bool = False) -> list[dict]:
        with self._lock:
            data = self._read_unlocked()
        items = data.get("items", [])
        if not include_archived:
            items = [it for it in items if not it.get("archived")]
        return items

    def get(self, item_id: str) -> dict | None:
        with self._lock:
            data = self._read_unlocked()
        for it in data.get("items", []):
            if it.get("id") == item_id:
                return it
        return None

    def add(self, item: dict) -> dict:
        item = dict(item)
        item.setdefault("id", secrets.token_hex(8))
        item.setdefault("created_at", int(time.time()))
        item.setdefault("archived", False)
        with self._lock:
            data = self._read_unlocked()
            data.setdefault("items", []).insert(0, item)
            self._write_unlocked(data)
        return item

    def update(self, item_id: str, patch: dict) -> dict | None:
        with self._lock:
            data = self._read_unlocked()
            for it in data.get("items", []):
                if it.get("id") == item_id:
                    it.update(patch)
                    self._write_unlocked(data)
                    return it
        return None

    def archive(self, item_id: str) -> bool:
        return self.update(item_id, {"archived": True}) is not None

    def unarchive(self, item_id: str) -> bool:
        return self.update(item_id, {"archived": False}) is not None

    def delete(self, item_id: str) -> bool:
        """Hard delete — for admin use only."""
        with self._lock:
            data = self._read_unlocked()
            items = data.get("items", [])
            new_items = [it for it in items if it.get("id") != item_id]
            if len(new_items) == len(items):
                return False
            data["items"] = new_items
            self._write_unlocked(data)
            return True


def news() -> JsonStore:
    with _init_lock:
        if "news" not in _stores:
            _stores["news"] = JsonStore("news.json")
        return _stores["news"]


def feedback() -> JsonStore:
    with _init_lock:
        if "feedback" not in _stores:
            _stores["feedback"] = JsonStore("feedback.json")
        return _stores["feedback"]
