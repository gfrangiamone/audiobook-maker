"""Helper condivisi sulle voci TTS.

Modulo FOGLIA: nessun import di progetto (regola anti-import-circolare,
CLAUDE.md §1). Qui vive la definizione unica del prefisso voce PREMIUM
Gemini e del relativo predicato, prima duplicati in audiobook_app,
generation_engine e storage_tiering.
"""

import os

GEMINI_VOICE_PREFIX = "gemini:"


def is_gemini_voice(voice):
    """True se la voce e' una voce PREMIUM Gemini (formato gemini:<model>:<voice>).

    Safe su input non-stringa/None/"": ritorna False senza sollevare.
    """
    return bool(voice) and isinstance(voice, str) and voice.startswith(GEMINI_VOICE_PREFIX)


SPEECHIFY_VOICE_PREFIX = "speechify:"


def is_speechify_voice(voice):
    """True se la voce e' una voce PREMIUM Speechify (formato speechify:<model>:<voice>).

    Safe su input non-stringa/None/"": ritorna False senza sollevare.
    """
    return bool(voice) and isinstance(voice, str) and voice.startswith(SPEECHIFY_VOICE_PREFIX)


# === Interruttori per modello PREMIUM ======================================
# Ogni modello premium ha una propria env `ABM_<MODELLO>_ENABLE`:
#   flash25    -> ABM_FLASH25_ENABLE
#   flash31    -> ABM_FLASH31_ENABLE
#   simba-3.2  -> ABM_SIMBA32_ENABLE
# Default ABILITATO: serve un valore esplicitamente falso ("0", "false",
# "no", "off") per togliere il modello dal catalogo voci e rifiutarlo sugli
# ingressi HTTP (anteprima, stima, ordine PayPal, generazione).
# NB: il gate NON tocca i path interni di sintesi/recovery/accounting: un job
# gia' registrato o pagato prosegue anche se il modello viene spento dopo.

_MODEL_DISABLE_VALUES = ("0", "false", "no", "off")


def premium_model_env_name(model_key):
    """Nome della env che governa il modello premium (es. 'ABM_FLASH25_ENABLE').

    Il model_key viene normalizzato togliendo ogni carattere non alfanumerico:
    'simba-3.2' -> 'SIMBA32'.
    """
    slug = "".join(c for c in str(model_key or "") if c.isalnum()).upper()
    return "ABM_%s_ENABLE" % slug


def premium_model_enabled(model_key):
    """True se il modello premium e' abilitato (default in assenza di env)."""
    if not model_key:
        return True
    raw = os.environ.get(premium_model_env_name(model_key))
    if raw is None:
        return True
    raw = raw.strip()
    if not raw:
        return True
    return raw.lower() not in _MODEL_DISABLE_VALUES


def voice_model_key(voice):
    """model_key di una voce premium ('gemini:flash25:Zephyr' -> 'flash25').

    Ritorna "" per voci non premium o con id malformato.
    """
    if not (is_gemini_voice(voice) or is_speechify_voice(voice)):
        return ""
    parts = voice.split(":")
    return parts[1] if len(parts) >= 3 and parts[1] else ""


def voice_model_enabled(voice):
    """False solo per una voce premium il cui modello e' spento via env."""
    model_key = voice_model_key(voice)
    if not model_key:
        return True
    return premium_model_enabled(model_key)
