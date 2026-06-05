"""translation_core.py — Core condiviso di traduzione libro via LLM.

Libreria pura usata sia dal CLI scripts/translate_abm.py sia dalla web app
(generation_engine.run_translation). Nessun import dai moduli applicativi,
nessun side effect Flask. Thread-safe: lo stato di usage è per-istanza
(UsageTracker), mai module-global.

Config (env, con fallback ABM_LLM_*): vedi PARAMETRI_CONFIGURAZIONE.md.
"""

import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
PROMPT_DIR = REPO_ROOT / "prompt_opt_AI"

# Stima token quando il provider non riporta l'usage (chars per token).
EST_CHARS_PER_TOKEN = 4.0


# ---------------------------------------------------------------------------
# Errori
# ---------------------------------------------------------------------------

class TranslationError(Exception):
    """Errore generico di traduzione."""


class TranslationConfigError(TranslationError):
    """Configurazione backend LLM incompleta o invalida."""


class TranslationCancelled(TranslationError):
    """Traduzione annullata (cancel_cb ha restituito True)."""


# ---------------------------------------------------------------------------
# Config (letta a ogni chiamata: testabile con monkeypatch.setenv)
# ---------------------------------------------------------------------------

def _env(name, fallback_name="", default=""):
    v = os.environ.get(name, "").strip()
    if not v and fallback_name:
        v = os.environ.get(fallback_name, "").strip()
    return v or default


def api_key():
    return _env("ABM_TRANSLATE_API_KEY", "ABM_LLM_API_KEY")


def api_base():
    return _env("ABM_TRANSLATE_API_BASE", "ABM_LLM_API_BASE",
                "https://api.deepseek.com")


def model_name():
    return _env("ABM_TRANSLATE_MODEL", "ABM_LLM_MODEL", "deepseek-chat")


def backend_choice():
    return (_env("ABM_TRANSLATE_BACKEND") or "auto").lower()


def gcp_project():
    return _env("ABM_GCP_PROJECT_ID")


def gcp_creds_file():
    return _env("ABM_GOOGLE_CREDENTIALS_FILE")


def vertex_location():
    return _env("ABM_TRANSLATE_VERTEX_LOCATION", default="global")


def chunk_chars():
    return int(_env("ABM_TRANSLATE_CHUNK_CHARS", default="20000"))


def max_retries():
    return int(_env("ABM_TRANSLATE_MAX_RETRIES", default="4"))


def temperature():
    return float(_env("ABM_TRANSLATE_TEMPERATURE", default="0.3"))


def request_timeout():
    return float(_env("ABM_TRANSLATE_REQUEST_TIMEOUT_SEC", default="300"))


# ---------------------------------------------------------------------------
# Usage tracking per-esecuzione (thread-safe per istanza)
# ---------------------------------------------------------------------------

class UsageTracker:
    """Contatori cumulativi token/chiamate di UNA esecuzione di traduzione."""

    def __init__(self):
        self.calls = 0
        self.calls_with_usage = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.est_prompt_chars = 0
        self.est_completion_chars = 0
        # Settato a True se il provider rifiuta stream_options.
        self.no_stream_options = False

    def track(self, system_prompt, user_content, output_text, usage_obj=None):
        self.calls += 1
        self.est_prompt_chars += len(system_prompt) + len(user_content)
        self.est_completion_chars += len(output_text)
        if usage_obj is not None:
            self.prompt_tokens += getattr(usage_obj, "prompt_tokens", 0) or 0
            self.completion_tokens += getattr(usage_obj, "completion_tokens", 0) or 0
            self.calls_with_usage += 1

    def report(self):
        """Riepilogo: token reali se completi, altrimenti stima da caratteri."""
        estimated = self.calls_with_usage < self.calls
        if estimated:
            pt = int(self.est_prompt_chars / EST_CHARS_PER_TOKEN)
            ct = int(self.est_completion_chars / EST_CHARS_PER_TOKEN)
        else:
            pt, ct = self.prompt_tokens, self.completion_tokens
        return {"calls": self.calls, "estimated": estimated,
                "prompt_tokens": pt, "completion_tokens": ct}


# ---------------------------------------------------------------------------
# Lingue edge-tts (costante copiata invariata da scripts/translate_abm.py)
# ---------------------------------------------------------------------------

EDGE_LANGS_FALLBACK = {
    "af", "am", "ar", "az", "bg", "bn", "bs", "ca", "cs", "cy", "da", "de",
    "el", "en", "es", "et", "fa", "fi", "fil", "fr", "ga", "gu", "he", "hi",
    "hr", "hu", "id", "is", "it", "ja", "jv", "ka", "kk", "km", "kn", "ko",
    "lo", "lt", "lv", "mk", "ml", "mr", "ms", "mt", "my", "nb", "ne", "nl",
    "pl", "ps", "pt", "ro", "ru", "si", "sk", "sl", "so", "sq", "sr", "sv",
    "sw", "ta", "te", "th", "tr", "uk", "ur", "uz", "vi", "zh", "zu",
}


# ---------------------------------------------------------------------------
# Chunking (copiato da scripts/translate_abm.py:202-237, con fix sep space)
# ---------------------------------------------------------------------------

def split_text_into_chunks(text, max_chars):
    """Spezza il testo in chunk rispettando i confini di paragrafo."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current_chunk = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)
        if para_size > max_chars:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            sentences = re.split(r'(?<=[.!?…])\s+', para)
            sub_chunk = []
            sub_size = 0
            for sent in sentences:
                sep = 1 if sub_chunk else 0
                if sub_size + sep + len(sent) > max_chars and sub_chunk:
                    chunks.append(" ".join(sub_chunk))
                    sub_chunk = []
                    sub_size = 0
                    sep = 0
                sub_chunk.append(sent)
                sub_size += sep + len(sent)
            if sub_chunk:
                chunks.append(" ".join(sub_chunk))
            continue
        if current_size + para_size + 2 > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_size = 0
        current_chunk.append(para)
        current_size += para_size + 2
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return chunks


# ---------------------------------------------------------------------------
# Prompt (copiato da scripts/translate_abm.py:244-287, con modifica
# load_tts_prompt: print(...) → log(...), parametro log=print)
# ---------------------------------------------------------------------------

def load_tts_prompt(lang, log=print):
    """Carica il prompt di ottimizzazione TTS per la lingua (fallback generic)."""
    path = PROMPT_DIR / f"prompt_tts_{lang}.md"
    if not path.exists():
        path = PROMPT_DIR / "prompt_tts_generic.md"
    if path.exists():
        try:
            log(f"[prompt] Ottimizzazione TTS: uso {path.name}")
            return path.read_text(encoding="utf-8").strip()
        except Exception as e:
            log(f"[prompt] WARNING: lettura {path} fallita: {e}")
    else:
        log(f"[prompt] WARNING: nessun prompt TTS trovato in {PROMPT_DIR}")
    return ""


def build_system_prompt(source, target, optimize):
    base = (
        f"You are a professional literary translator.\n"
        f"Translate the text provided by the user from the language with "
        f"ISO 639-1 code '{source}' to the language with ISO 639-1 code "
        f"'{target}'.\n\n"
        "Rules:\n"
        "- Preserve the meaning, tone, register and narrative style of the "
        "original.\n"
        "- Preserve the paragraph structure and blank lines exactly.\n"
        "- Keep proper names unchanged unless a conventional translation "
        "exists in the target language.\n"
        "- Do not summarize, omit or add content.\n"
        "- Output ONLY the translated text: no comments, no preambles, no "
        "explanations, no markdown fences."
    )
    if optimize:
        tts_prompt = load_tts_prompt(target)
        if tts_prompt:
            base += (
                "\n\nAfter translating, apply to the TRANSLATED text the "
                "following text-optimization rules for TTS narration, and "
                "output only the final optimized translation (single pass, "
                "single output):\n\n"
                "----- TTS OPTIMIZATION RULES -----\n"
                f"{tts_prompt}"
            )
    return base


# ---------------------------------------------------------------------------
# _strip_fences (copiato invariato da scripts/translate_abm.py:433-437)
# ---------------------------------------------------------------------------

def _strip_fences(text):
    """Rimuove un eventuale wrapping completo in fence markdown."""
    stripped = text.strip()
    m = re.match(r"^```[a-zA-Z]*\n(.*)\n```$", stripped, re.DOTALL)
    return m.group(1).strip() if m else stripped
