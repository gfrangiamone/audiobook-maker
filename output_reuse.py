"""output_reuse.py — Riuso dell'output di una generazione identica gia' consegnata.

Nel log di agosto 2026 un client ha rigenerato 165 volte gli stessi titoli con
la stessa voce: ogni volta il server ha risintetizzato da zero. Questo modulo
indicizza, per client, l'impronta di ogni generazione completata con voce
STANDARD (testo dei capitoli selezionati + voce + rate + formato + flag
parentesi). Una nuova richiesta con la stessa impronta, dallo stesso client,
mentre i file del job sorgente sono ancora sul disco locale (finestra calda),
viene servita copiando l'output invece di rigenerarlo.

Invarianti:
- solo voci standard, mai job premium/pagati (semantica pagamento intatta);
- stesso client_id: mai riuso fra utenti diversi;
- il job sorgente deve essere `done` (non `partial`) senza chunk falliti;
- tutti i file referenziati dal job sorgente devono esistere in locale, altrimenti
  miss (il chiamante genera normalmente): mai un output a meta'.

File indice: `ABM_DATA_DIR/_output_reuse.json`
    {"<key>": {"job_id", "client_id", "output_dir", "ts"}}
Modulo foglia: solo stdlib + community_store.atomic_write_json.
"""
import hashlib
import json
import os
import shutil
import threading
import time
from pathlib import Path

from community_store import atomic_write_json

_lock = threading.RLock()
SCHEMA_VERSION = 1
# Voci di indice piu' vecchie di cosi' vengono potate: oltre la finestra calda
# massima i file locali non esistono piu' e la voce e' comunque un miss.
_MAX_AGE_SEC = 7 * 86400
_MAX_ENTRIES = 5000

# Campi del job sorgente che puntano a file dentro output_dir (str o lista).
_PATH_FIELDS = ("output_files", "output_m4b", "output_zip",
                "output_m4b_fallback_zip", "podcast_mp3s")
# Campi scalari da riportare tali e quali sul job che riusa.
_SCALAR_FIELDS = ("output_name", "bytes_generated", "podcast_ready",
                  "podcast_safe_name", "podcast_rss_included", "m4b_failed",
                  "total_chars", "total_chunks")


def _index_file():
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data")) / "_output_reuse.json"


def enabled():
    """Interruttore: ABM_OUTPUT_REUSE=0 disattiva il riuso (default attivo)."""
    return str(os.environ.get("ABM_OUTPUT_REUSE", "1")).strip().lower() not in ("0", "false", "no", "off")


def compute_key(chapters, voice, rate, output_format, single_file,
                strip_round=True, strip_square=True):
    """Impronta della generazione: hash del testo dei capitoli selezionati (in
    ordine) + parametri di sintesi/assembly che cambiano l'output."""
    h = hashlib.sha256()
    h.update(json.dumps({
        "schema": SCHEMA_VERSION,
        "voice": voice or "",
        "rate": rate or "",
        "output_format": output_format or "",
        "single_file": bool(single_file),
        "strip_round": bool(strip_round),
        "strip_square": bool(strip_square),
    }, sort_keys=True).encode("utf-8"))
    for ch in chapters or ():
        title = getattr(ch, "title", "") or ""
        text = getattr(ch, "text", "") or ""
        h.update(b"\x00T")
        h.update(title.encode("utf-8", "replace"))
        h.update(b"\x00X")
        h.update(text.encode("utf-8", "replace"))
    return h.hexdigest()


def _load():
    try:
        with open(_index_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        return d if isinstance(d, dict) else {}
    except Exception:
        return {}


def _prune(d, now=None):
    now = now or time.time()
    for k in [k for k, v in d.items()
              if not isinstance(v, dict) or (now - float(v.get("ts", 0) or 0)) > _MAX_AGE_SEC]:
        d.pop(k, None)
    if len(d) > _MAX_ENTRIES:
        for k, _v in sorted(d.items(), key=lambda kv: float(kv[1].get("ts", 0) or 0))[:len(d) - _MAX_ENTRIES]:
            d.pop(k, None)


def record(key, client_id, job_id, output_dir):
    """Indicizza una generazione completata. Best-effort, mai eccezioni."""
    if not key or not job_id or not client_id:
        return False
    with _lock:
        d = _load()
        _prune(d)
        d[key] = {"job_id": job_id, "client_id": client_id,
                  "output_dir": str(output_dir or ""), "ts": time.time()}
        try:
            atomic_write_json(_index_file(), d)
        except Exception:
            return False
    return True


def lookup(key, client_id):
    """Voce d'indice per (key, client) o None. Non verifica i file su disco."""
    if not key or not client_id:
        return None
    with _lock:
        d = _load()
    e = d.get(key)
    if not isinstance(e, dict) or e.get("client_id") != client_id:
        return None
    return e


def forget(key):
    with _lock:
        d = _load()
        if d.pop(key, None) is not None:
            try:
                atomic_write_json(_index_file(), d)
            except Exception:
                pass


def source_is_reusable(src_job, client_id):
    """True se il job sorgente in memoria puo' fare da origine del riuso."""
    if not isinstance(src_job, dict):
        return False
    if src_job.get("status") != "done":
        return False
    if (src_job.get("client_id") or "") != client_id:
        return False
    if int(src_job.get("failed_chunks") or 0) > 0:
        return False
    out_dir = src_job.get("output_dir") or ""
    if not out_dir or not os.path.isdir(out_dir):
        return False
    files = list(src_job.get("output_files") or [])
    if not files:
        return False
    for p in _referenced_paths(src_job):
        if not p.startswith(out_dir) or not os.path.isfile(p):
            return False  # evicted (hot->cold) o fuori da output_dir
    return True


def _referenced_paths(job):
    for f in _PATH_FIELDS:
        v = job.get(f)
        if isinstance(v, str) and v:
            yield v
        elif isinstance(v, (list, tuple)):
            for p in v:
                if isinstance(p, str) and p:
                    yield p


def _link_or_copy(src, dst):
    try:
        os.link(src, dst)
        return
    except OSError:
        pass
    shutil.copy2(src, dst)


def materialize(src_job, dst_output_dir):
    """Copia (hardlink, fallback copia) i file del job sorgente in
    `dst_output_dir` e ritorna i campi del job da impostare sul job che riusa,
    con i path riferiti alla nuova directory. None se qualcosa manca: il
    chiamante deve allora generare normalmente."""
    src_dir = src_job.get("output_dir") or ""
    dst_dir = str(dst_output_dir)
    if not src_dir or not os.path.isdir(src_dir):
        return None
    os.makedirs(dst_dir, exist_ok=True)

    def _rebase(p):
        rel = os.path.relpath(p, src_dir)
        if rel.startswith(".."):
            raise ValueError(f"path fuori da output_dir: {p}")
        return os.path.join(dst_dir, rel)

    try:
        for name in os.listdir(src_dir):
            sp = os.path.join(src_dir, name)
            if not os.path.isfile(sp):
                continue
            if name.endswith(".abm"):
                continue  # snapshot del progetto: rigenerato per il nuovo job
            dp = os.path.join(dst_dir, name)
            if os.path.exists(dp):
                os.remove(dp)
            _link_or_copy(sp, dp)
        fields = {}
        for f in _PATH_FIELDS:
            v = src_job.get(f)
            if isinstance(v, str) and v:
                fields[f] = _rebase(v)
            elif isinstance(v, (list, tuple)):
                fields[f] = [_rebase(p) for p in v if isinstance(p, str) and p]
        for p in _referenced_paths(fields):
            if not os.path.isfile(p):
                return None
        for f in _SCALAR_FIELDS:
            if f in src_job:
                fields[f] = src_job[f]
        return fields
    except Exception:
        return None
