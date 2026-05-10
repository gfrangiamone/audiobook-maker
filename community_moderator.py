"""Content moderation for community feedback via URL detection and LLM check.

Reuses the DeepSeek client from generation_engine. Follows the same pattern
as community_translator.py: no circular imports, synchronous validate().
"""
from __future__ import annotations

import json
import re
import time
import traceback

import generation_engine as ge


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


def _call_llm(text: str, *, timeout: float) -> dict | None:
    """Call DeepSeek LLM for moderation. Returns parsed JSON dict or None."""
    client = ge._deepseek_client
    if client is None:
        return None
    kwargs = dict(
        model=ge.DEEPSEEK_MODEL,
        messages=[
            {"role": "system", "content": _MODERATION_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
        max_tokens=256,
        temperature=0.0,
        timeout=timeout,
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
        reason: str      — "url", "spam", "llm_error", "ok"
        unvalidated: bool — True when LLM check failed after retries
    """
    combined = f"{name or ''} {comment or ''}".strip()
    if not combined:
        return {"approved": True, "reason": "ok", "unvalidated": False}

    # Step 1: fast URL check (zero LLM cost)
    if _has_url(combined):
        return {"approved": False, "reason": "url", "unvalidated": False}

    # Step 2: LLM content check (only if no URL)
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
