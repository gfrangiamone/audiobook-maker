"""Translate feedback/news content into all UI languages via LLM.

Reuses the LLM client and configuration already initialized in
generation_engine.py. Exposes a synchronous translate() that returns a
dict shaped as:

    {
      "source_lang": "it",
      "it": {<input keys, original verbatim>},
      "en": {<input keys, translated>},
      "fr": {...}, "es": {...}, "de": {...}, "zh": {...}, "hi": {...}
    }

translate_async() runs the call in a daemon thread and invokes a callback
on completion (None on failure).
"""
from __future__ import annotations

import json
import re
import threading
import traceback

import generation_engine as ge


LANGS: tuple[str, ...] = ("it", "en", "fr", "es", "de", "zh", "hi")


_TRANSLATE_SYSTEM_PROMPT = """You are a translation engine for the AudioBook Maker app.
Translate the user-provided JSON content into 7 target languages: \
Italian (it), English (en), French (fr), Spanish (es), German (de), \
Chinese (zh), Hindi (hi).

Rules:
- Detect the source language of the input content.
- For the source language, output the input text VERBATIM (do not edit, \
improve, rephrase, or correct typos).
- Translate accurately into the other 6 languages, preserving tone, \
register, punctuation, emoji and newlines.
- Keep these proper nouns / brand terms untranslated: AudioBook Maker, \
EPUB, PDF, TXT, MP3, TTS.
- Content may use light Markdown: **bold**, *italic*, [label](url) links and \
"- " bullet lists. Reproduce every marker exactly, around the corresponding \
words of the translated sentence. Translate the link label only: copy each \
URL character by character, never translate or shorten it.
- Do not add explanations, prefixes, quotation marks, or extra keys.
- Preserve every input key exactly.

Output ONLY a single JSON object with this exact structure (no prose):
{
  "source_lang": "<two-letter ISO code: it/en/fr/es/de/zh/hi>",
  "it": { <same keys as input, Italian text> },
  "en": { ... English ... },
  "fr": { ... French ... },
  "es": { ... Spanish ... },
  "de": { ... German ... },
  "zh": { ... Chinese ... },
  "hi": { ... Hindi (Devanagari) ... }
}"""


# Soglia sotto la quale una traduzione identica all'originale e' plausibile
# ("nice", "goated", "Excellant" restano tali in ogni lingua). Sopra, invece,
# l'identita' e' quasi sempre il modello che ricopia il verbatim della lingua
# sorgente in uno slot sbagliato (incidente 30/08/2026: un commento tedesco
# finito verbatim anche in comment_i18n["it"], quindi mostrato in tedesco
# all'utente italiano e senza il toggle "mostra originale").
_IDENTITY_MIN_CHARS = 20
_IDENTITY_MIN_WORDS = 4


def _norm(txt: str) -> str:
    return re.sub(r"\s+", " ", (txt or "").strip().lower())


def _looks_untranslated(orig: str, txt: str) -> bool:
    """True se `txt` e' una copia dell'originale su un testo abbastanza lungo
    da rendere implausibile la coincidenza."""
    o = _norm(orig)
    if len(o) < _IDENTITY_MIN_CHARS or len(o.split()) < _IDENTITY_MIN_WORDS:
        return False
    return _norm(txt) == o


def needs_translation(orig: str, i18n: dict | None, src_lang: str = "") -> bool:
    """True se il set di traduzioni e' assente, incompleto o contiene copie
    dell'originale in lingue diverse da quella sorgente."""
    orig = (orig or "").strip()
    if not orig:
        return False
    dict_i18n = i18n if isinstance(i18n, dict) else {}
    src = (src_lang or "").lower()
    for lg in LANGS:
        val = (dict_i18n.get(lg) or "").strip()
        if not val:
            return True
        if src and lg != src and _looks_untranslated(orig, val):
            return True
    return False


def is_available() -> bool:
    """True if the LLM client is initialized."""
    return ge._llm_available()


def _extract_json_object(raw: str) -> dict | None:
    """Best-effort JSON extraction: try strict parse, then locate the first
    balanced {...} block in the text and parse that.
    """
    raw = (raw or "").strip()
    if not raw:
        return None
    # Strip Markdown code fences if present
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # Find first { and matching } via depth scan
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        c = raw[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(raw[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:
                    return None
    return None


def _call_llm(payload: dict[str, str], *, timeout: float, use_json_mode: bool,
              system_prompt: str | None = None, temperature: float = 0.2) -> str | None:
    client = ge._llm_client
    if client is None:
        return None
    user_content = json.dumps(payload, ensure_ascii=False)
    kwargs: dict = dict(
        model=ge.LLM_MODEL,
        messages=[
            {"role": "system", "content": system_prompt or _TRANSLATE_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=4096,
        temperature=temperature,
        timeout=timeout,
        # Thinking off esplicito: il provider lo attiva di default (vedi
        # generation_engine.llm_thinking_kwargs) e qui serve solo latenza/costo.
        extra_body=ge.THINKING_OFF_BODY,
    )
    if use_json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    completion = client.chat.completions.create(**kwargs)
    return (completion.choices[0].message.content or "").strip()


def translate(payload: dict[str, str], *, timeout: float = 90.0) -> dict | None:
    """Translate a flat dict of strings into all 6 languages.

    Returns the translation dict, or None on failure.
    """
    if not is_available():
        print("[community_translator] LLM unavailable (client not initialized)")
        return None
    if not isinstance(payload, dict) or not payload:
        print(f"[community_translator] empty/invalid payload: {payload!r}")
        return None
    raw: str | None = None
    # Try JSON mode first; fall back to plain mode if the model rejects it.
    for use_json in (True, False):
        try:
            raw = _call_llm(payload, timeout=timeout, use_json_mode=use_json)
            if raw:
                break
        except Exception as e:
            err = type(e).__name__
            msg = str(e)
            print(f"[community_translator] call failed (json_mode={use_json}, {err}): {msg}")
            # If JSON-mode call failed with a parameter error, try plain mode.
            if use_json and ("response_format" in msg or "json_object" in msg or "Unsupported" in msg or "BadRequest" in err):
                continue
            traceback.print_exc()
            return None
    if not raw:
        print("[community_translator] empty response from LLM")
        return None
    data = _extract_json_object(raw)
    if not isinstance(data, dict):
        snippet = raw[:300].replace("\n", " ")
        print(f"[community_translator] could not parse JSON from response: {snippet!r}")
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
            for k in payload:
                if k not in slot or not isinstance(slot.get(k), str):
                    slot[k] = ""
    data["source_lang"] = src
    _drop_copied_slots(data, payload, src)
    _retry_missing_slots(data, payload, src, timeout=timeout)
    keys = ", ".join(payload.keys())
    print(f"[community_translator] translated {keys} (source={src or '?'}, langs={','.join(LANGS)})")
    return data


def _drop_copied_slots(data: dict, payload: dict[str, str], src: str) -> None:
    """Azzera gli slot che ricopiano l'originale in una lingua diversa dalla
    sorgente: meglio un buco (il client ripiega sull'inglese) che un testo
    illeggibile spacciato per traduzione."""
    if not src:
        # Senza lingua sorgente attendibile non si distingue la copia lecita
        # dallo sbaglio: non si tocca nulla.
        return
    for lg in LANGS:
        if lg == src:
            continue
        slot = data.get(lg) or {}
        for k, orig in payload.items():
            if _looks_untranslated(orig, slot.get(k, "")):
                print(f"[community_translator] slot {lg}.{k} ricopia l'originale "
                      f"({src}): scartato")
                slot[k] = ""


_RETRY_SYSTEM_PROMPT = """You are a translation engine.
The user sends a JSON object of source strings written in {src_name} ({src}).
Translate every value into EACH of these target languages: {targets}.

Rules:
- Output the translation in the target language. NEVER copy the source text
  into a target slot: if a value comes back identical to the input, it is wrong.
- Preserve tone, register, punctuation, emoji, newlines and Markdown markers.
- Keep proper nouns / brand terms untranslated: AudioBook Maker, EPUB, PDF,
  TXT, MP3, TTS.
- No explanations, no extra keys.

Output ONLY a JSON object keyed by language code:
{{ {skeleton} }}"""

_LANG_NAMES = {
    "it": "Italian", "en": "English", "fr": "French", "es": "Spanish",
    "de": "German", "zh": "Chinese", "hi": "Hindi",
}


def _retry_missing_slots(data: dict, payload: dict[str, str], src: str,
                         *, timeout: float) -> None:
    """Un secondo tentativo per le sole chiavi rimaste vuote.

    Non si ripete la chiamata iniziale: quella sbaglia in modo deterministico
    (30/08/2026: il backfill in produzione ha riscartato due volte lo stesso
    slot italiano). Si chiede la traduzione verso le sole lingue mancanti,
    dichiarando la lingua sorgente e vietando esplicitamente la copia."""
    missing_langs = sorted({lg for lg in LANGS for k in payload
                            if not (data.get(lg) or {}).get(k, "").strip()})
    if not missing_langs:
        return
    print(f"[community_translator] retry mirato per {','.join(missing_langs)}")
    skeleton = ", ".join(
        '"%s": { %s }' % (lg, ", ".join(f'"{k}": "..."' for k in payload))
        for lg in missing_langs
    )
    prompt = _RETRY_SYSTEM_PROMPT.format(
        src=src or "unknown",
        src_name=_LANG_NAMES.get(src, "an unknown language"),
        targets=", ".join(f"{_LANG_NAMES.get(lg, lg)} ({lg})" for lg in missing_langs),
        skeleton=skeleton,
    )
    try:
        raw = _call_llm(payload, timeout=timeout, use_json_mode=True,
                        system_prompt=prompt, temperature=0.4)
    except Exception as e:
        print(f"[community_translator] retry fallito: {type(e).__name__}: {e!s}")
        return
    missing = [(lg, k) for lg in missing_langs for k in payload
               if not (data.get(lg) or {}).get(k, "").strip()]
    retry = _extract_json_object(raw or "")
    if not isinstance(retry, dict):
        return
    for lg, k in missing:
        val = ((retry.get(lg) or {}).get(k) or "").strip() if isinstance(retry.get(lg), dict) else ""
        if not val:
            continue
        if src and lg != src and _looks_untranslated(payload.get(k, ""), val):
            continue
        data.setdefault(lg, {})[k] = val


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
