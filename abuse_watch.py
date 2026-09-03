"""Moderazione LLM dell'abuso della quota voci standard.

Dossier comportamentale per gruppo (IP /24 hashato, fallback cid) con
ripartizione per cid, segnali S1-S4, giudizio DeepSeek e verdetto persistito
in `ABM_DATA_DIR/_abuse_dossiers.json`. Modulo foglia: stdlib +
`community_store.atomic_write_json`; il client LLM arriva da
`generation_engine` come in `community_moderator`.

Ogni funzione e' fail-open: un errore qui non deve mai fermare /api/generate,
il cleanup o il digest. Nessun testo utente, IP o email in chiaro: solo
contatori e hash salati con ABM_IP_SALT.

Spec: docs/superpowers/specs/2026-09-03-quota-containment-design.md
"""
import hashlib
import json
import os
import queue
import threading
import time
from pathlib import Path

from community_store import atomic_write_json

_lock = threading.RLock()

KINDS = ("generate", "quota_gate", "quota_block", "email")
VERDICTS = ("abuse", "clean", "inconclusive")

_DAY_SEC = 86400
_RETENTION_SEC = 60 * _DAY_SEC        # dossier senza eventi da 60 giorni: via
_QUOTA_S1_WINDOW_SEC = 31 * _DAY_SEC  # S1: quota esaurita nell'ultimo mese
_RECENT_KEEP = 20
_RECENT_GEN_KEEP = 200
_RECENT_GATE_KEEP = 100
_FILES_KEEP = 300
_EMAILS_KEEP = 50
_JUDGEMENTS_KEEP = 20
_KILLS_KEEP = 50
_BLOCKS_KEEP = 200
_DEFAULT_SALT = "abm-default-salt-v1"


# ---------------------------------------------------------------------------
# Configurazione (letta a ogni chiamata: i test cambiano l'env)
# ---------------------------------------------------------------------------

def _env_int(name, default, floor=0):
    try:
        return max(floor, int(os.environ.get(name, str(default)) or default))
    except (TypeError, ValueError):
        return default


def _env_float(name, default):
    try:
        raw = str(os.environ.get(name, str(default)) or default).replace(",", ".")
        return float(raw)
    except (TypeError, ValueError):
        return default


def kill_enabled():
    """Kill e 403 attivi solo con ABM_ABUSE_KILL_ENABLE=1 E un admin da avvisare
    (ABM_ADMIN_EMAIL): nessuna azione distruttiva senza audit nel digest."""
    flag = (os.environ.get("ABM_ABUSE_KILL_ENABLE", "0") or "0").strip().lower()
    admin = (os.environ.get("ABM_ADMIN_EMAIL") or "").strip()
    return flag in ("1", "true", "yes", "on") and bool(admin)


def confidence_threshold():
    return _env_float("ABM_ABUSE_LLM_CONFIDENCE", 0.9)


def keep_hours():
    return _env_int("ABM_ABUSE_KEEP_HOURS", 24, floor=1)


def verdict_ttl_sec():
    """In osservazione (kill spenta) il TTL e' forzato a 1 giorno: un prompt
    tarato male non lascia verdetti validi due settimane."""
    if not kill_enabled():
        return _DAY_SEC
    return _env_int("ABM_ABUSE_VERDICT_TTL_DAYS", 14, floor=1) * _DAY_SEC


def _gate_daily():
    return _env_int("ABM_ABUSE_GATE_DAILY", 5, floor=1)


def _chars_daily():
    return _env_int("ABM_ABUSE_CHARS_DAILY", 2_500_000, floor=1)


def _data_dir():
    return Path(os.environ.get("ABM_DATA_DIR", "/var/lib/audiobook-maker/data"))


def _dossier_file():
    return _data_dir() / "_abuse_dossiers.json"


# ---------------------------------------------------------------------------
# Identita' e persistenza
# ---------------------------------------------------------------------------

def _hash(value):
    salt = os.environ.get("ABM_IP_SALT", _DEFAULT_SALT) or _DEFAULT_SALT
    return hashlib.sha256((salt + str(value)).encode("utf-8")).hexdigest()[:16]


def group_key(ip, cid=""):
    """`net:<hash(/24)>` per IPv4, `net:<hash(/64)>` per IPv6, altrimenti
    `cid:<cid>`. Raggruppa, non giudica: un /24 mobile ospita migliaia di
    utenti e il giudice lo sa (marker di innocenza nel prompt)."""
    ip = (ip or "").strip()
    parts = ip.split(".")
    if len(parts) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in parts):
        return "net:" + _hash(".".join(parts[:3]) + ".0/24")
    if ":" in ip:
        hextets = ip.split(":")
        if 3 <= len(hextets) <= 8:
            return "net:" + _hash(":".join(hextets[:4]) + "::/64")
    return "cid:" + str(cid or "")


def _load():
    try:
        with open(_dossier_file(), "r", encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict) or not isinstance(d.get("groups"), dict):
            return {"groups": {}, "meta": {}}
        if not isinstance(d.get("meta"), dict):
            d["meta"] = {}
        return d
    except Exception:
        return {"groups": {}, "meta": {}}


def _save(d):
    now = time.time()
    groups = d.setdefault("groups", {})
    for key in [k for k, g in groups.items()
                if now - float(g.get("updated", now) or now) > _RETENTION_SEC]:
        groups.pop(key, None)
    try:
        atomic_write_json(_dossier_file(), d)
    except Exception:
        pass


def _new_bucket():
    return {"generate": 0, "quota_gate": 0, "quota_block": 0, "email": 0,
            "chars": 0, "emails": [], "files": [], "voices": {}, "langs": {},
            "recent": [], "recent_generate": [], "recent_gate": [],
            "quota_exhausted_ts": 0, "first_ts": 0, "last_ts": 0}


def _new_group(now):
    return {"created": now, "updated": now, "all": _new_bucket(), "cids": {},
            "verdict": None, "judgements": [], "kills": [], "blocks": []}


def _push(lst, item, keep):
    lst.append(item)
    del lst[:-keep]


def _add_unique(lst, item, keep):
    if item and item not in lst:
        lst.append(item)
        del lst[:-keep]


def _apply(bucket, kind, data, now):
    bucket[kind] = int(bucket.get(kind, 0)) + 1
    bucket["first_ts"] = bucket.get("first_ts") or now
    bucket["last_ts"] = now
    _push(bucket["recent"], now, _RECENT_KEEP)
    try:
        chars = int(data.get("chars") or 0)
    except (TypeError, ValueError):
        chars = 0
    if kind == "generate":
        bucket["chars"] = int(bucket.get("chars", 0)) + chars
        _push(bucket["recent_generate"], [now, chars], _RECENT_GEN_KEEP)
        voice = str(data.get("voice") or "")
        if voice:
            bucket["voices"][voice] = int(bucket["voices"].get(voice, 0)) + 1
    if kind == "quota_gate":
        _push(bucket["recent_gate"], now, _RECENT_GATE_KEEP)
    if kind in ("quota_gate", "quota_block"):
        bucket["quota_exhausted_ts"] = now
    if kind == "email":
        email = str(data.get("email") or "").strip().lower()
        if email:
            _add_unique(bucket["emails"], _hash(email), _EMAILS_KEEP)
    fn = str(data.get("filename") or "")
    if fn:
        _add_unique(bucket["files"], _hash(fn), _FILES_KEEP)
    lang = str(data.get("lang") or "").strip().lower()[:2]
    if lang:
        bucket["langs"][lang] = int(bucket["langs"].get(lang, 0)) + 1


def record_event(group, cid, kind, data=None):
    """Aggiorna il dossier del gruppo e del cid. `kind` fuori da KINDS: no-op."""
    if kind not in KINDS or not group:
        return
    data = data if isinstance(data, dict) else {}
    cid = str(cid or "")
    with _lock:
        d = _load()
        now = time.time()
        g = d["groups"].setdefault(group, _new_group(now))
        g["updated"] = now
        _apply(g["all"], kind, data, now)
        if cid:
            _apply(g["cids"].setdefault(cid, _new_bucket()), kind, data, now)
        _save(d)


def dossier(group):
    with _lock:
        g = _load()["groups"].get(group)
    return json.loads(json.dumps(g)) if g is not None else None
