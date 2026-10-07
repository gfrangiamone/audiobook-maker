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


VOXCPM_VOICE_PREFIX = "voxcpm:"


def is_voxcpm_voice(voice):
    """True se la voce e' una voce PREMIUM VoxCPM.

    Due formati sotto lo stesso prefisso: `voxcpm:v2:<locale>/<Nome>` per il
    catalogo di voci inventate, `voxcpm:mine:<token>` per la voce clonata
    dell'utente. Il predicato copre entrambi: la distinzione fra i due la fa
    `voxcpm_catalog.parse_voice_id`, non questo modulo.

    Safe su input non-stringa/None/"": ritorna False senza sollevare.
    """
    return bool(voice) and isinstance(voice, str) and voice.startswith(VOXCPM_VOICE_PREFIX)


def is_premium_voice(voice):
    """True per qualunque voce PREMIUM a pagamento (Gemini, Speechify, VoxCPM).

    Governa retention dei download, protezione no-download e finestra calda:
    i tre motori premium hanno gli stessi criteri di disponibilita'.
    """
    return is_gemini_voice(voice) or is_speechify_voice(voice) or is_voxcpm_voice(voice)


# === Interruttori per modello PREMIUM ======================================
# Ogni modello premium ha una propria env `ABM_<MODELLO>_ENABLE`:
#   flash31    -> ABM_FLASH31_ENABLE
#   flash38    -> ABM_FLASH38_ENABLE
#   simba-3.2  -> ABM_SIMBA32_ENABLE
# Default ABILITATO: serve un valore esplicitamente falso ("0", "false",
# "no", "off") per togliere il modello dal catalogo voci e rifiutarlo sugli
# ingressi HTTP (anteprima, stima, ordine PayPal, generazione).
# NB: il gate NON tocca i path interni di sintesi/recovery/accounting: un job
# gia' registrato o pagato prosegue anche se il modello viene spento dopo.

_MODEL_DISABLE_VALUES = ("0", "false", "no", "off")
# Modelli rilasciati spenti: servono un valore esplicitamente vero per
# comparire (flash38 si accende dopo il collaudo dell'utente).
_MODEL_DEFAULT_OFF = ("flash38",)
_MODEL_ENABLE_VALUES = ("1", "true", "yes", "on")


def premium_model_env_name(model_key):
    """Nome della env che governa il modello premium (es. 'ABM_FLASH31_ENABLE').

    Il model_key viene normalizzato togliendo ogni carattere non alfanumerico:
    'simba-3.2' -> 'SIMBA32'.
    """
    slug = "".join(c for c in str(model_key or "") if c.isalnum()).upper()
    return "ABM_%s_ENABLE" % slug


def premium_model_enabled(model_key):
    """True se il modello premium e' abilitato: default abilitato, salvo i
    modelli in `_MODEL_DEFAULT_OFF` (default spento, serve un valore
    esplicitamente vero)."""
    if not model_key:
        return True
    raw = (os.environ.get(premium_model_env_name(model_key)) or "").strip()
    if model_key in _MODEL_DEFAULT_OFF:
        return raw.lower() in _MODEL_ENABLE_VALUES
    if not raw:
        return True
    return raw.lower() not in _MODEL_DISABLE_VALUES


def voice_model_key(voice):
    """model_key di una voce premium ('gemini:flash31:Zephyr' -> 'flash31').

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

# === Voci VoxCPM: catalogo e voci campionate ================================
# Unica definizione dei due sotto-prefissi (prima: literal in sei moduli,
# `voice_clone.VOICE_ID_PREFIX`, `voxcpm_catalog._ID_PREFIX`,
# `voxcpm_tts.voice_clone_token`, quattro `startswith` in generation_engine).

VOXCPM_CATALOG_SCHEMA = "v2"
VOXCPM_CATALOG_PREFIX = VOXCPM_VOICE_PREFIX + VOXCPM_CATALOG_SCHEMA + ":"
VOXCPM_MINE_PREFIX = VOXCPM_VOICE_PREFIX + "mine:"
_HEX = frozenset("0123456789abcdef")


def is_cloned_voice(voice):
    """True per una voce campionata dell'utente (`voxcpm:mine:<token>`)."""
    return bool(voice) and isinstance(voice, str) and voice.startswith(VOXCPM_MINE_PREFIX)


def clone_token(voice, *, strict=True):
    """Il token di una voce campionata, None se `voice` non lo e'.

    `strict=True` (store, autorizzazioni): accetta solo 32 esadecimali
    minuscoli, la forma emessa da voice_clone. `strict=False` (solo
    sintassi, es. tag audio): qualunque token non vuoto.
    """
    if not is_cloned_voice(voice):
        return None
    tok = voice[len(VOXCPM_MINE_PREFIX):]
    if not tok:
        return None
    if strict and not (len(tok) == 32 and all(c in _HEX for c in tok)):
        return None
    return tok


def engine_for_voice(voice):
    """Motore TTS dal prefisso del voice id: 'gemini', 'speechify', 'voxcpm'
    o 'edge' (tutto il resto, incluse voci vuote)."""
    if is_gemini_voice(voice):
        return "gemini"
    if is_speechify_voice(voice):
        return "speechify"
    if is_voxcpm_voice(voice):
        return "voxcpm"
    return "edge"


# === Velocita' di lettura ("+10%") ===========================================
# Il pannello manda una stringa percentuale; prima ogni motore e ogni audit
# la riparsavano a modo proprio (dodici copie, tre clamp diversi). Qui solo
# il parsing: i clamp restano nel motore, perche' sono limiti del motore.

def parse_rate_pct(rate, default=0.0):
    """'+10%' -> 10.0, '-35 %' -> -35.0, 10 -> 10.0, '' / None / 'abc' ->
    `default`. Accetta anche decimali ('+12.5%')."""
    if rate is None or isinstance(rate, bool):
        return default
    if isinstance(rate, (int, float)):
        return float(rate)
    s = str(rate).replace("%", "").replace("+", "").replace(" ", "").strip()
    if not s:
        return default
    try:
        return float(s)
    except (TypeError, ValueError):
        return default


def rate_step(rate):
    """Passo intero [-3, +3] per le direttive Gemini e il raggruppamento degli
    audit: round(pct / 10) con clamp."""
    pct = parse_rate_pct(rate, 0.0)
    return max(-3, min(3, round(pct / 10)))


def rate_speed_factor(rate, *, floor=None, ceil=None):
    """Fattore moltiplicativo di velocita': '+10%' -> 1.10. `floor`/`ceil`
    opzionali per i limiti del motore."""
    f = 1.0 + parse_rate_pct(rate, 0.0) / 100.0
    if floor is not None and f < floor:
        f = floor
    if ceil is not None and f > ceil:
        f = ceil
    return f

