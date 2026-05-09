"""Translate feedback/news content into all UI languages via DeepSeek LLM.

Reuses the DeepSeek client and configuration already initialized in
generation_engine.py. Exposes a synchronous translate() that returns a
dict shaped as:

    {
      "source_lang": "it",
      "it": {<input keys, original verbatim>},
      "en": {<input keys, translated>},
      "fr": {...}, "es": {...}, "de": {...}, "zh": {...}
    }

translate_async() runs the call in a daemon thread and invokes a callback
on completion (None on failure).
"""
from __future__ import annotations

import json
import threading

import generation_engine as ge


LANGS: tuple[str, ...] = ("it", "en", "fr", "es", "de", "zh")


_TRANSLATE_SYSTEM_PROMPT = """You are a translation engine for the AudioBook Maker app.
Translate the user-provided JSON content into 6 target languages: \
Italian (it), English (en), French (fr), Spanish (es), German (de), \
Chinese (zh).

Rules:
- Detect the source language of the input content.
- For the source language, output the input text VERBATIM (do not edit, \
improve, rephrase, or correct typos).
- Translate accurately into the other 5 languages, preserving tone, \
register, punctuation, emoji and newlines.
- Keep these proper nouns / brand terms untranslated: AudioBook Maker, \
EPUB, PDF, TXT, MP3, TTS.
- Do not add explanations, prefixes, quotation marks, or extra keys.
- Preserve every input key exactly.

Output ONLY a single JSON object with this exact structure (no prose):
{
  "source_lang": "<two-letter ISO code: it/en/fr/es/de/zh>",
  "it": { <same keys as input, Italian text> },
  "en": { ... English ... },
  "fr": { ... French ... },
  "es": { ... Spanish ... },
  "de": { ... German ... },
  "zh": { ... Chinese ... }
}"""


def is_available() -> bool:
    """True if the DeepSeek client is initialized."""
    return ge._llm_available()


def translate(payload: dict[str, str], *, timeout: float = 60.0) -> dict | None:
    """Translate a flat dict of strings into all 6 languages.

    Returns the translation dict, or None on failure.
    """
    if not is_available():
        return None
    client = ge._deepseek_client
    if client is None:
        return None
    if not isinstance(payload, dict) or not payload:
        return None
    try:
        user_content = json.dumps(payload, ensure_ascii=False)
        completion = client.chat.completions.create(
            model=ge.DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": _TRANSLATE_SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            response_format={"type": "json_object"},
            max_tokens=4096,
            temperature=0.2,
            timeout=timeout,
        )
        raw = (completion.choices[0].message.content or "").strip()
        if not raw:
            return None
        data = json.loads(raw)
        if not isinstance(data, dict):
            return None
        src = (data.get("source_lang") or "").lower()
        if src not in LANGS:
            src = ""
        # Backfill any missing language with empty values so the caller can
        # safely index every LANG without KeyError.
        for lg in LANGS:
            slot = data.get(lg)
            if not isinstance(slot, dict):
                data[lg] = {k: "" for k in payload}
            else:
                # Ensure every input key exists in the per-lang dict.
                for k in payload:
                    if k not in slot or not isinstance(slot.get(k), str):
                        slot[k] = ""
        data["source_lang"] = src
        return data
    except Exception as e:
        print(f"[community_translator] translate failed: {e!s}")
        return None


def translate_async(payload: dict[str, str], on_done) -> threading.Thread:
    """Run translate() in a background daemon thread; call on_done(result_or_None)."""
    def _run():
        try:
            result = translate(payload)
        except Exception as e:
            print(f"[community_translator] async error: {e!s}")
            result = None
        try:
            on_done(result)
        except Exception as e:
            print(f"[community_translator] on_done callback failed: {e!s}")

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    return t
