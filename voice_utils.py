"""Helper condivisi sulle voci TTS.

Modulo FOGLIA: nessun import di progetto (regola anti-import-circolare,
CLAUDE.md §1). Qui vive la definizione unica del prefisso voce PREMIUM
Gemini e del relativo predicato, prima duplicati in audiobook_app,
generation_engine e storage_tiering.
"""

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
