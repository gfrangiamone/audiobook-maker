"""Content moderation for community feedback via URL detection and LLM check.

Two engines, in order:

1. `semantic_judge` (System One): una richiesta, cinque domande indipendenti
   con risposta gia' tipizzata. Le soglie di rifiuto stanno qui sotto, in
   codice, non dentro un prompt: si cambiano senza riscrivere le istruzioni
   e senza rimettere mano a un parser JSON.
2. il client LLM di `generation_engine`, che resta come ripiego quando il
   primo non e' configurato o non risponde.

Come `community_translator.py`: nessun import circolare, `validate()`
sincrona, e fail-open (un commento passa marcato `unvalidated` se nessuno
dei due motori ha risposto).
"""
from __future__ import annotations

import json
import os
import re
import time
import traceback

import generation_engine as ge
import semantic_judge as sj


_URL_RE = re.compile(
    r'(?:https?://|www\.)[^\s<>"]+'
    r'|[^\s@]+@[^\s@]+\.[^\s@]+'
    r'|\b[a-zA-Z0-9-]+\.[a-zA-Z]{2,}\b',
    re.IGNORECASE,
)

_MODERATION_SYSTEM_PROMPT = """You are a content moderation assistant for the AudioBook Maker app.
Your task is to evaluate whether a user comment is appropriate for public display.

Evaluate the combined text of the user's name and comment for the following issues:
- Spam or unsolicited promotional content
- Profanity or vulgar language
- Violent or threatening language
- Sexual or explicit content
- Off-topic or nonsensical spam

Rules:
- Be strict: reject anything that would be inappropriate in a public product review.
- Output ONLY a single JSON object with this exact structure (no prose):
  {"approved": true, "reason": "ok"}
  or
  {"approved": false, "reason": "spam"}
- Do not add explanations, markdown, or extra keys.
"""

_MAX_RETRIES = 3
_BACKOFF_DELAYS = (1.0, 2.0, 4.0)


def _has_url(text: str) -> bool:
    """True if the text contains a URL, www, domain-like string, or email."""
    return bool(_URL_RE.search(text))


# ---------------------------------------------------------------------------
# Motore 1: giudizi tipizzati (System One)
# ---------------------------------------------------------------------------

# Una domanda per motivo di rifiuto, indipendenti fra loro: girano in
# parallelo in una sola richiesta e ognuna ha la sua soglia. Un unico
# "approved: true/false" non lo permetteva: il prompt decideva anche la
# severita', e per cambiarla bisognava riscriverlo.
#
# I commenti arrivano in 7 lingue: le istruzioni restano in inglese (come
# ogni stringa di sistema non localizzata del progetto), il testo giudicato
# resta nella lingua in cui e' stato scritto.
def _questions():
    """Costruite a ogni chiamata: senza SDK importato le classi sono None."""
    if sj.Noul is None:
        return {}
    Noul, Crit = sj.Noul, sj.NoulCriteria
    return {
        "spam": Noul(
            instructions="Is `comment` unsolicited promotion, advertising, or "
                         "spam?",
            criteria=Crit(
                true="It advertises another product, service, site or contact, "
                     "or repeats promotional boilerplate.",
                false="It talks about the user's own experience with this app, "
                      "however short, enthusiastic or critical.",
            ),
        ),
        "profanity": Noul(
            instructions="Does `comment` or `name` contain profanity, slurs or "
                         "insults directed at someone?",
        ),
        "threat": Noul(
            instructions="Does `comment` contain threats, incitement to "
                         "violence, or harassment of a person or group?",
        ),
        "sexual": Noul(
            instructions="Does `comment` contain explicit sexual content?",
            criteria=Crit(
                true="It describes sexual acts or uses sexually explicit "
                     "language.",
                false="It merely mentions a book, title or topic that deals "
                      "with love, romance or sexuality.",
            ),
        ),
        "gibberish": Noul(
            instructions="Is `comment` meaningless text, such as random "
                         "characters or keyboard mashing?",
            criteria=Crit(
                true="It carries no meaning in any language.",
                false="It is a real message, even if very short, misspelled, "
                      "or written in a language you handle rarely.",
            ),
        ),
    }


def _env_float(name: str, default: float) -> float:
    try:
        return float((os.environ.get(name) or "").strip() or default)
    except (TypeError, ValueError):
        return default


# Soglia di rifiuto per motivo. Piu' alta per `gibberish`: un rifiuto sbagliato
# li' colpisce le recensioni vere brevissime ("top!", "👌"), che sono la
# materia prima dei rich snippet di seo_reviews.
_REJECT_THRESHOLDS = {
    "spam": 0.70,
    "profanity": 0.70,
    "threat": 0.60,          # piu' bassa: il falso negativo costa di piu'
    "sexual": 0.70,
    "gibberish": 0.90,
}


def _thresholds() -> dict:
    """Soglie con override per env: ABM_MODERATION_MIN_<MOTIVO>."""
    return {k: _env_float(f"ABM_MODERATION_MIN_{k.upper()}", v)
            for k, v in _REJECT_THRESHOLDS.items()}


def _typesafe_verdict(name: str, comment: str) -> dict | None:
    """Verdetto dai giudizi tipizzati, o None se il motore non ha risposto.

    None significa "nessun giudizio", mai "approvato": il chiamante ripiega
    sul motore LLM."""
    questions = _questions()
    if not questions:
        return None
    resp = sj.ask({"name": name or "", "comment": comment or ""}, questions)
    if resp is None:
        return None
    worst_reason, worst_margin = "", 0.0
    for reason, threshold in _thresholds().items():
        p = sj.noul(resp, reason)
        if p is None:
            # Una risposta senza tutte le domande e' una risposta monca: non
            # si approva su un giudizio parziale.
            return None
        if p >= threshold and (p - threshold) >= worst_margin:
            worst_reason, worst_margin = reason, p - threshold
    if worst_reason:
        print(f"[community_moderator] rifiutato ({worst_reason}) da System One")
        return {"approved": False, "reason": worst_reason, "unvalidated": False}
    return {"approved": True, "reason": "ok", "unvalidated": False}


# ---------------------------------------------------------------------------
# Motore 2: client LLM di generation_engine (ripiego)
# ---------------------------------------------------------------------------


def _call_llm(text: str, *, timeout: float) -> dict | None:
    """Call LLM for moderation. Returns parsed JSON dict or None."""
    client = ge._llm_client
    if client is None:
        return None
    kwargs = dict(
        model=ge.LLM_MODEL,
        messages=[
            {"role": "system", "content": _MODERATION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        max_tokens=256,
        temperature=0.0,
        timeout=timeout,
        # Thinking off esplicito: con max_tokens=256 il reasoning_content
        # brucerebbe il budget e il verdetto JSON arriverebbe troncato.
        extra_body=ge.THINKING_OFF_BODY,
    )
    try:
        completion = client.chat.completions.create(**kwargs)
        raw = (completion.choices[0].message.content or "").strip()
    except Exception as e:
        print(f"[community_moderator] LLM call failed: {type(e).__name__}: {e}")
        traceback.print_exc()
        return None
    if not raw:
        return None
    # Try strict JSON parse first; fallback to extracting first {...} block
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            return obj
    except json.JSONDecodeError:
        pass
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
                except json.JSONDecodeError:
                    return None
    return None


def validate(name: str, comment: str) -> dict:
    """Validate feedback content.

    Returns a dict:
        approved: bool   — False means reject immediately
        reason: str      — "url", "spam", "profanity", "threat", "sexual",
                           "gibberish", "llm_error", "ok"
        unvalidated: bool — True when no engine could judge the content
    """
    combined = f"{name or ''} {comment or ''}".strip()
    if not combined:
        return {"approved": True, "reason": "ok", "unvalidated": False}

    # Step 1: fast URL check (zero LLM cost)
    if _has_url(combined):
        return {"approved": False, "reason": "url", "unvalidated": False}

    # Step 2: giudizi tipizzati. Su None (non configurato, servizio giu',
    # risposta monca) si prosegue col motore LLM: mai un'approvazione presa
    # da un silenzio.
    verdict = _typesafe_verdict(name, comment)
    if verdict is not None:
        return verdict

    # Step 3: LLM content check (only if no URL)
    if not ge._llm_available():
        print("[community_moderator] LLM unavailable; allowing unvalidated")
        return {"approved": True, "reason": "llm_error", "unvalidated": True}

    for attempt in range(_MAX_RETRIES):
        result = _call_llm(combined, timeout=20.0)
        if result is not None:
            approved = bool(result.get("approved", True))
            reason = result.get("reason", "ok") if approved else "spam"
            return {"approved": approved, "reason": reason, "unvalidated": False}
        delay = _BACKOFF_DELAYS[attempt] if attempt < len(_BACKOFF_DELAYS) else 4.0
        print(f"[community_moderator] attempt {attempt + 1}/{_MAX_RETRIES} failed, retry in {delay}s")
        time.sleep(delay)

    # All retries exhausted: allow but mark unvalidated
    print("[community_moderator] all retries failed; allowing unvalidated")
    return {"approved": True, "reason": "llm_error", "unvalidated": True}
