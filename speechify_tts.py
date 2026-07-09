"""Speechify Simba-3.2 TTS — engine PREMIUM inglese.

Modello unico `simba-3.2` (flagship English-only). Speculare a gemini_tts.py:
config via env `ABM_SPEECHIFY_*`, catalogo voci/emozioni, pricing riusando la
pipeline premium, gate di concorrenza globale (limite abbonamento).

Anti-import-circolare: nessun import di audiobook_app. Le costanti condivise
(USD->EUR, fee PayPal) sono lette dalle STESSE env var di Gemini per coerenza.
"""

import base64
import io
import os
import threading
import wave

MODEL_ID = "simba-3.2"
MODEL_LABEL = "Simba (English)"

# (code, descrizione leggibile). Il primo e' il default.
ACCENTS = [
    ("en-US", "American English"),
    ("en-GB", "British English"),
]

# Tutte accettate (HTTP 200) da simba-3.2. Set di prodotto, non vincolo API.
EMOTIONS = [
    "angry", "cheerful", "sad", "terrified", "relaxed", "fearful",
    "surprised", "calm", "assertive", "energetic", "warm", "direct", "bright",
]

# 8 voci `_32`. gender: "Female"/"Male".
VOICES = [
    {"id": "dominic_32",  "gender": "Male",   "locale": "en-US"},
    {"id": "geffen_32",   "gender": "Male",   "locale": "en-US"},
    {"id": "harper_32",   "gender": "Female", "locale": "en-US"},
    {"id": "wyatt_32",    "gender": "Male",   "locale": "en-US"},
    {"id": "beatrice_32", "gender": "Female", "locale": "en-GB"},
    {"id": "edmund_32",   "gender": "Male",   "locale": "en-GB"},
    {"id": "hugh_32",     "gender": "Male",   "locale": "en-GB"},
    {"id": "imogen_32",   "gender": "Female", "locale": "en-GB"},
]

_VOICE_LOCALE = {v["id"]: v["locale"] for v in VOICES}
_VOICE_GENDER = {v["id"]: v["gender"] for v in VOICES}
_VALID_VOICE_NAMES = set(_VOICE_LOCALE.keys())

API_BASE = "https://api.speechify.ai"
SPEECH_ENDPOINT = "/v1/audio/speech"
CHUNK_MAX_CHARS = 1800  # cap sotto il limite ~2000 char/richiesta dell'endpoint


def voice_locale(voice_name):
    """Locale (en-US/en-GB) della voce, o None se sconosciuta."""
    return _VOICE_LOCALE.get(voice_name)


def _gender_icon(gender):
    return "♀" if gender == "Female" else "♂"  # ♀ / ♂


def get_voices(ui_lang="en"):
    """Catalogo voci per l'UI. Solo inglese (chiave 'en').

    Returns: {"en": [voice_entry, ...]} — Female prima, poi Male (coerente col
    combo Edge). Ogni entry porta id `speechify:simba-3.2:<voiceId>`.
    """
    sorted_voices = sorted(
        VOICES,
        key=lambda v: (0 if v["gender"] == "Female" else 1, v["id"]),
    )
    entries = []
    for v in sorted_voices:
        entries.append({
            "id": f"speechify:{MODEL_ID}:{v['id']}",
            "name": f"{v['id']} ({MODEL_LABEL})",
            "locale": v["locale"],
            "engine": "speechify",
            "model_key": MODEL_ID,
            "model_label": MODEL_LABEL,
            "gender": v["gender"],
            "gender_icon": _gender_icon(v["gender"]),
        })
    return {"en": entries}


def parse_voice_id(voice_id):
    """Estrae (model_key, voice_name, locale) da 'speechify:simba-3.2:harper_32'.

    Raises ValueError se formato non valido, modello != simba-3.2 o voce ignota.
    """
    if not isinstance(voice_id, str) or not voice_id.startswith("speechify:"):
        raise ValueError(f"Invalid Speechify voice ID: {voice_id!r}")
    parts = voice_id.split(":")
    if len(parts) != 3:
        raise ValueError(f"Invalid Speechify voice ID: {voice_id!r} (expected 'speechify:<model>:<voice>')")
    _, model_key, voice_name = parts
    if model_key != MODEL_ID:
        raise ValueError(f"Unknown Speechify model: {model_key!r} (only {MODEL_ID!r})")
    if voice_name not in _VALID_VOICE_NAMES:
        raise ValueError(f"Unknown Speechify voice: {voice_name!r}")
    return model_key, voice_name, _VOICE_LOCALE[voice_name]
