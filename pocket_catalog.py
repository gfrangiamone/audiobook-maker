"""Catalogo delle voci del modello batch (Pocket TTS, «ABM TTS (batch)»).

Non e' un catalogo suo: sono le voci inventate del catalogo VoxCPM
(`voxcpm_catalog`), lette dal worker Pocket con stati calcolati da un taglio
di ~10 s dello stesso campione. Una voce e' offerta quando ha la clip
dimostrativa Pocket: le clip le genera il repo del worker
(`tools/make_demos.py`) solo per le voci che hanno uno stato sul worker, e
questo modulo le legge da `demos.json` nella cartella delle clip
(`ABM_POCKET_DEMO_DIR`). Consegnare la cartella e' l'atto che accende le voci;
`ABM_POCKET_LANGUAGES` restringe le lingue offerte senza toccarla.

Carattere, genere e accento vengono dal catalogo VoxCPM: le due liste restano
allineate senza un secondo file da mantenere.
"""
import json
import os
import threading

import voxcpm_catalog
from env_utils import env_str
from voice_utils import POCKET_VOICE_PREFIX

MODEL_ID = "v1"                         # la chiave modello nel voice id
MODEL_LABEL = "ABM TTS (batch)"  # etichetta del selettore MODELLO
_ID_PREFIX = f"{POCKET_VOICE_PREFIX}{MODEL_ID}:"
# Lingue che il worker sa leggere (un modello Pocket per lingua).
LANGUAGES = ("it", "en", "es", "fr", "de", "pt", "nl")
_DEFAULT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pocket_demo")

_lock = threading.Lock()
_cache = {"key": None, "voices": []}


def demo_dir():
    """Cartella delle clip dimostrative Pocket, assoluta."""
    raw = env_str("ABM_POCKET_DEMO_DIR")
    return os.path.abspath(raw) if raw else _DEFAULT_DIR


def languages():
    """Lingue offerte: `ABM_POCKET_LANGUAGES` (codici separati da virgola),
    dentro quelle del worker; vuota = tutte."""
    raw = env_str("ABM_POCKET_LANGUAGES")
    chosen = [c.strip().lower() for c in raw.split(",") if c.strip()] if raw else list(LANGUAGES)
    return tuple(c for c in chosen if c in LANGUAGES)


def _read_demos(path):
    """{"it-IT/Chiara": {"opening": "it-IT/Chiara-opening.wav", ...}} da demos.json.
    Le clip con `problem` (testo saltato anche all'ultimo tentativo) restano
    fuori: una clip che tradisce la voce non si fa ascoltare."""
    try:
        with open(path, encoding="utf-8") as fh:
            rows = json.load(fh)
    except Exception as e:  # noqa: BLE001 — clip assenti: nessuna voce, nessun errore
        print(f"[pocket_catalog] demos.json non leggibile ({path}): {e}")
        return {}
    out = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or row.get("problem"):
            continue
        voice, demo, rel = (str(row.get(k) or "").strip() for k in ("voice", "demo", "file"))
        if voice and demo and rel:
            out.setdefault(voice, {})[demo] = rel
    return out


def _load():
    base = demo_dir()
    demos = _read_demos(os.path.join(base, "demos.json"))
    langs = set(languages())
    out = []
    for rec in voxcpm_catalog.voices():
        if rec["lang"] not in langs:
            continue
        files = demos.get(f"{rec['locale']}/{rec['name']}") or {}
        clips = [{"id": d["id"], "common": d["common"], "file": files[d["id"]]}
                 for d in rec["demos"] if d["id"] in files]
        if not clips:
            continue
        out.append({**rec, "id": f"{_ID_PREFIX}{rec['locale']}/{rec['name']}", "demos": clips})
    return out


def voices():
    """Record delle voci offerte. La cache si rinnova quando cambia
    `demos.json`, la cartella o l'elenco delle lingue."""
    path = os.path.join(demo_dir(), "demos.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None
    key = (path, mtime, languages(), id(voxcpm_catalog.voices()))
    with _lock:
        if _cache["key"] == key:
            return _cache["voices"]
    loaded = _load() if mtime is not None else []
    with _lock:
        _cache.update(key=key, voices=loaded)
    return loaded


def _demo_url(voice_id, demo_id):
    from urllib.parse import quote
    return ("/api/voice_demo?voice=" + quote(voice_id, safe="")
            + "&clip=" + quote(demo_id, safe=""))


def get_voices():
    """Catalogo per l'UI, {codice lingua: [entry]}, nella forma di
    `voxcpm_catalog.get_voices()`: stesso carattere e stesse clip, senza
    campione (il batch non clona la voce dal campione: si ascoltano le clip)."""
    out = {}
    for rec in voices():
        out.setdefault(rec["lang"], []).append({
            "id": rec["id"],
            "name": voxcpm_catalog._display_name(rec),
            "locale": rec["locale"],
            "engine": "pocket",
            "model_key": MODEL_ID,
            "model_label": MODEL_LABEL,
            "gender": rec["gender"],
            "gender_icon": "\U0001f469" if rec["gender"] == "Female" else "\U0001f468",
            "persona": rec["persona"],
            "persona_role": rec["role"],
            "demos": [{"id": d["id"], "common": d["common"], "url": _demo_url(rec["id"], d["id"])}
                      for d in rec["demos"]],
        })
    for entries in out.values():
        entries.sort(key=lambda e: (e["gender"], e["name"]))
    return out


def demo_path(voice_id, clip_id):
    """Percorso assoluto della clip `clip_id` della voce. ValueError su voce o
    clip non offerte (messaggio con «non presente»), o percorso fuori dalla
    cartella; FileNotFoundError se il file manca."""
    rec = next((v for v in voices() if v["id"] == voice_id), None)
    if rec is None:
        raise ValueError(f"voce non presente: {voice_id!r}")
    clip = next((d for d in rec["demos"] if d["id"] == clip_id), None)
    if clip is None:
        raise ValueError(f"clip non presente: {clip_id!r}")
    base = demo_dir()
    path = os.path.abspath(os.path.join(base, clip["file"].replace("/", os.sep)))
    if os.path.commonpath([base, path]) != base:
        raise ValueError(f"clip fuori dalla cartella: {clip['file']!r}")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    return path
