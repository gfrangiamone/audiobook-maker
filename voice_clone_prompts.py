"""Frasi guidate delle voci campionate (spec voci-campionate §4).

Modulo foglia: solo stdlib. Il file JSON e' tracciato in git e si ricarica
da solo quando cambia l'mtime, cosi' correggere una frase non richiede un
restart. Il record della voce salva la frase letta cosi' com'era
(`prompt_text` + `prompt_version`): cambiare il file vale solo per le
registrazioni future.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import unicodedata

SCHEMA = "abm-voice-clone-prompts/1"
PROMPTS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "voice_clone_prompts.json")
_GENDERS = ("m", "f")

_lock = threading.Lock()
_cache = None        # dict lingua -> {"m": testo, "f": testo}
_cache_mtime = None


def invalidate_cache():
    global _cache, _cache_mtime
    with _lock:
        _cache = None
        _cache_mtime = None


def _clean(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _normalize(raw):
    """`{"text": ...}` o `{"text_by_gender": {"m":..,"f":..}}` -> {"m","f"}.

    Un genere senza variante ripiega su `text`; se resta un buco la lingua
    non e' offerta (spec §4): meglio assente che una frase mancante a meta'
    wizard.
    """
    if not isinstance(raw, dict):
        return None
    base = _clean(raw.get("text"))
    per = raw.get("text_by_gender") if isinstance(raw.get("text_by_gender"), dict) else {}
    out = {}
    for g in _GENDERS:
        t = _clean(per.get(g)) or base
        if not t:
            return None
        out[g] = t
    return out


def _load():
    global _cache, _cache_mtime
    try:
        mtime = os.stat(PROMPTS_PATH).st_mtime
    except OSError:
        mtime = None
    with _lock:
        if _cache is not None and _cache_mtime == mtime:
            return _cache
    data = {}
    if mtime is not None:
        try:
            with open(PROMPTS_PATH, "r", encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict) and raw.get("schema") == SCHEMA:
                for lang, entry in (raw.get("prompts") or {}).items():
                    norm = _normalize(entry)
                    if norm:
                        data[str(lang).strip().lower()] = norm
            else:
                print(f"[voice_clone_prompts] schema inatteso in {PROMPTS_PATH}")
        except Exception as e:
            print(f"[voice_clone_prompts] file non leggibile ({PROMPTS_PATH}): {e}")
            data = {}
    with _lock:
        _cache, _cache_mtime = data, mtime
    return data


def languages():
    """Codici lingua con una frase usabile per entrambi i generi, ordinati."""
    return sorted(_load().keys())


def prompt_for(lang, gender):
    """La frase da leggere, o None se lingua o genere non sono offerti."""
    if gender not in _GENDERS:
        return None
    entry = _load().get((lang or "").strip().lower())
    return entry[gender] if entry else None


def prompt_version(text):
    """`sha1:<16 hex>` del testo in NFC: identifica la frase salvata nel record."""
    norm = unicodedata.normalize("NFC", text or "")
    return "sha1:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
