"""Server-side mirror of the client-side i18n strings that crawlers must see.

Why this exists:
    The home page renders many SEO-critical strings (FAQ questions/answers,
    guide-card link labels, heading texts) into <span data-t="…"></span>
    placeholders that are filled by `applyI18n()` after the client JS loads.
    Search engine crawlers and AI scrapers that don't execute JS therefore
    see empty <span>s instead of localized anchor text — which kills both
    keyword relevance and the FAQ rich-result eligibility.

What it does:
    Parses templates/_fragments/i18n_data.js once at startup and exposes a
    Python dict { lang: { key: text } } with only the SEO-critical keys.
    `prefill_seo_text()` then fills the placeholder elements server-side
    so the static HTML the crawler downloads already contains the
    localized text. The client `applyI18n()` runs afterwards and overwrites
    the same nodes idempotently.

The parser is intentionally minimal — it only handles the exact format
written by hand in i18n_data.js (keys are bare identifiers, values are
double-quoted strings, escapes are limited to \\\\, \\", \\n, \\t). If the
format changes, run the smoke test in _smoke_seo.py to catch breakage.
"""
from __future__ import annotations

from html import escape as _esc
from pathlib import Path
import re

# Keys whose translations must be visible to non-JS crawlers.
# Ordered roughly by where they appear in the body.
_SEO_KEYS: list[str] = [
    "guides_heading",
    "guide_epub", "guide_m4b", "guide_tts", "guide_podcast",
    "faq_heading_short",
    "faq_q1", "faq_a1",
    "faq_q2", "faq_a2",
    "faq_q3", "faq_a3",
    "faq_q4", "faq_a4",
    "faq_q5", "faq_a5",
    "faq_free_books_q", "faq_free_books_a",
]

_LANGS: list[str] = ["it", "en", "fr", "es", "de", "zh"]

# JS string literal: any char that isn't an unescaped " or backslash, OR a
# backslash followed by any char. Matches "Sì", "He said \"hi\"", etc.
_VAL_RE = r'((?:[^"\\]|\\.)*)'


def _unescape_js(s: str) -> str:
    """Reverse the small subset of JS string escapes used in i18n_data.js."""
    return (
        s.replace("\\n", "\n")
         .replace("\\t", "\t")
         .replace('\\"', '"')
         .replace("\\\\", "\\")
    )


def _parse_i18n(js_path: Path) -> dict[str, dict[str, str]]:
    src = js_path.read_text(encoding="utf-8")

    # Locate the start of each language object: "<lang>:{"
    starts: dict[str, int] = {}
    for lang in _LANGS:
        m = re.search(rf"(?:^|[,{{\s]){lang}:\{{", src)
        if m:
            # Position of the opening brace itself
            starts[lang] = m.end() - 1

    # Slice each lang's object content using the next lang's start as the end
    sorted_langs = sorted(starts.items(), key=lambda kv: kv[1])
    out: dict[str, dict[str, str]] = {}
    for i, (lang, pos) in enumerate(sorted_langs):
        end = sorted_langs[i + 1][1] if i + 1 < len(sorted_langs) else len(src)
        block = src[pos:end]
        lang_dict: dict[str, str] = {}
        for key in _SEO_KEYS:
            m = re.search(rf'(?:[,{{]){re.escape(key)}:"{_VAL_RE}"', block)
            if m:
                lang_dict[key] = _unescape_js(m.group(1))
        out[lang] = lang_dict
    return out


# Parse once at import time; re-import to refresh.
_FRAGMENTS_DIR = Path(__file__).parent / "_fragments"
SEO_TEXT: dict[str, dict[str, str]] = _parse_i18n(_FRAGMENTS_DIR / "i18n_data.js")


# Pre-compiled regexes for prefill. We rewrite three element shapes:
#   <span data-t="KEY"></span>            → <span data-t="KEY">text</span>
#   <summary data-t="KEY"></summary>      → <summary data-t="KEY">text</summary>
#   <div class="faq-answer" data-t="KEY"></div>
#                                          → <div … data-t="KEY">text</div>
#
# Empty elements only — we never overwrite text the author intentionally
# placed inline. The data-t attribute is preserved so client applyI18n()
# can still re-render on language switch.
_SPAN_RE = re.compile(r'<span data-t="([^"]+)"></span>')
_SUMMARY_RE = re.compile(r'<summary data-t="([^"]+)"></summary>')
_FAQDIV_RE = re.compile(
    r'<div class="faq-answer" data-t="([^"]+)"></div>'
)


def prefill_seo_text(html: str, lang: str) -> str:
    """Inject server-side text into empty data-t placeholders for `lang`.

    Only keys listed in `_SEO_KEYS` are filled — other placeholders are
    left to the client-side applyI18n(). Missing keys are silently left
    as empty <span>s so we never crash the page on a typo.
    """
    table = SEO_TEXT.get(lang) or SEO_TEXT.get("en") or {}
    if not table:
        return html

    def _span(m: "re.Match[str]") -> str:
        key = m.group(1)
        text = table.get(key)
        if text is None:
            return m.group(0)
        return f'<span data-t="{key}">{_esc(text)}</span>'

    def _summary(m: "re.Match[str]") -> str:
        key = m.group(1)
        text = table.get(key)
        if text is None:
            return m.group(0)
        return f'<summary data-t="{key}">{_esc(text)}</summary>'

    def _faqdiv(m: "re.Match[str]") -> str:
        key = m.group(1)
        text = table.get(key)
        if text is None:
            return m.group(0)
        # FAQ answers contain plain text, but we still preserve newlines as
        # <br> for readability when JS doesn't re-render.
        body = _esc(text).replace("\n", "<br>")
        return f'<div class="faq-answer" data-t="{key}">{body}</div>'

    html = _SPAN_RE.sub(_span, html)
    html = _SUMMARY_RE.sub(_summary, html)
    html = _FAQDIV_RE.sub(_faqdiv, html)
    return html
