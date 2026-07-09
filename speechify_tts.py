"""Speechify Simba-3.2 TTS — engine PREMIUM inglese.

Modello unico `simba-3.2` (flagship English-only). Speculare a gemini_tts.py:
config via env `ABM_SPEECHIFY_*`, catalogo voci/emozioni, pricing riusando la
pipeline premium, gate di concorrenza globale (limite abbonamento).

Anti-import-circolare: nessun import di audiobook_app. Le costanti condivise
(USD->EUR, fee PayPal) sono lette dalle STESSE env var di Gemini per coerenza.
"""

import base64
import contextlib as _contextlib
import io
import os
import threading
import time
import wave

# === Gate di concorrenza globale (limite abbonamento) =======================
# Un permesso per chiamata API. Ogni synthesize acquisisce/rilascia uno slot;
# l'invariante `active <= max_concurrency()` vale su tutti i job/client del
# processo. max_concurrency() e' riletto a ogni acquire (reload runtime).

_gate_lock = threading.Condition()
_gate_active = 0


def _reset_gate_for_test():
    """Reset dello stato del gate (solo test)."""
    global _gate_active
    with _gate_lock:
        _gate_active = 0
        _gate_lock.notify_all()


def acquire_slot(timeout=None):
    """Acquisisce un permesso globale, bloccando finche' `active < N`.

    Returns True se acquisito, False su timeout. timeout=None => attesa
    indefinita (admission gating trasparente).
    """
    global _gate_active
    deadline = None if timeout is None else (time.monotonic() + timeout)
    with _gate_lock:
        while _gate_active >= max_concurrency():
            if deadline is None:
                _gate_lock.wait()
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False
                _gate_lock.wait(timeout=remaining)
        _gate_active += 1
        return True


def release_slot():
    """Rilascia un permesso globale e sveglia un eventuale waiter."""
    global _gate_active
    with _gate_lock:
        if _gate_active > 0:
            _gate_active -= 1
        _gate_lock.notify()


def active_slots():
    with _gate_lock:
        return _gate_active


def free_slots():
    with _gate_lock:
        return max(0, max_concurrency() - _gate_active)


@_contextlib.contextmanager
def slot(timeout=None):
    """Context manager: acquisisce uno slot per la durata del blocco."""
    ok = acquire_slot(timeout=timeout)
    if not ok:
        raise TimeoutError("Speechify concurrency slot not available")
    try:
        yield
    finally:
        release_slot()


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


def _f(env, default):
    try:
        return float(str(os.environ.get(env, default)).replace(",", "."))
    except (ValueError, TypeError):
        return float(default)


def _i(env, default):
    try:
        return int(os.environ.get(env, str(default)))
    except (ValueError, TypeError):
        return int(default)


def api_key():
    return os.environ.get("ABM_SPEECHIFY_API_KEY", "").strip()


def is_available():
    """True sse la API key Speechify e' configurata."""
    return bool(api_key())


def max_concurrency():
    """Concorrenza API globale (limite abbonamento). Floor a 1."""
    return max(1, _i("ABM_SPEECHIFY_MAX_CONCURRENCY", 3))


def per_job_concurrency():
    """Chiamate API simultanee per singolo job. Floor a 1."""
    return max(1, _i("ABM_SPEECHIFY_PER_JOB_CONCURRENCY", 1))


def cost_usd_per_mchar():
    return _f("ABM_SPEECHIFY_COST_USD_PER_MCHAR", 11.18)


def margin_percent():
    return _f("ABM_SPEECHIFY_MARGIN_PERCENT", 60.0)


def free_threshold_eur():
    return _f("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", 0.50)


# Costanti condivise con Gemini (stesse env per non divergere sui prezzi).
def usd_eur_rate():
    return _f("ABM_GEMINI_USD_EUR_RATE", 0.86)


def paypal_fixed_fee_eur():
    return _f("ABM_GEMINI_PAYPAL_FIXED_FEE_EUR", 0.34)


def paypal_percent_fee():
    return _f("ABM_GEMINI_PAYPAL_PERCENT_FEE", 3.4)


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


def compute_user_price_eur(chars):
    """Prezzo finale utente per `chars` caratteri.

    Formula (allineata a gemini_tts.compute_user_price_eur):
        cost_usd = chars/1e6 * COST_USD_PER_MCHAR
        base_eur = cost_usd * USD_EUR_RATE * (1 + margin/100)
        gross    = (base_eur + PAYPAL_FIXED_FEE) / (1 - PAYPAL_PERCENT/100)
        user     = round(gross, 2); is_free se < FREE_THRESHOLD.
    """
    if chars is None or chars < 0:
        chars = 0
    cost_usd = chars / 1_000_000.0 * cost_usd_per_mchar()
    margin = margin_percent()
    base_eur = cost_usd * usd_eur_rate() * (1.0 + margin / 100.0)
    paypal_factor = 1.0 - (paypal_percent_fee() / 100.0)
    if paypal_factor <= 0:
        raise ValueError("PAYPAL_PERCENT_FEE >= 100, invalid config")
    gross = (base_eur + paypal_fixed_fee_eur()) / paypal_factor
    user_price = round(gross, 2)
    threshold = free_threshold_eur()
    is_free = user_price < threshold
    return {
        "chars": chars,
        "cost_usd": round(cost_usd, 6),
        "base_price_eur": round(base_eur, 4),
        "margin_percent": margin,
        "user_price_eur": 0.0 if is_free else user_price,
        "is_free": is_free,
        "free_threshold_eur": threshold,
    }


def estimate_book_cost(chapters, language="en"):
    """Stima costo end-to-end su caratteri di input (somma capitoli).

    Args:
        chapters: lista di oggetti con attributo `.text`.
        language: ISO 639-1 (solo 'en' supportato; parametro per simmetria).
    """
    chars_per_chapter = []
    chars_total = 0
    for ch in chapters:
        txt = getattr(ch, "text", "") or ""
        n = len(txt)
        chars_per_chapter.append(n)
        chars_total += n
    price = compute_user_price_eur(chars_total)
    return {
        "chars_total": chars_total,
        "chars_per_chapter": chars_per_chapter,
        "cost_usd": price["cost_usd"],
        "user_price_eur": price["user_price_eur"],
        "is_free": price["is_free"],
        "margin_percent": price["margin_percent"],
        "language": language,
        "model_key": MODEL_ID,
        "model_label": MODEL_LABEL,
    }
