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
