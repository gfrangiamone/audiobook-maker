r"""Server-side mirror of the client-side i18n strings.

Why this exists:
    The home page renders its texts into empty `data-t` placeholders
    (<span data-t="…"></span>, <h2 data-t="…"></h2>, …) that `applyI18n()`
    fills after the client JS loads. Two problems follow:
      - crawlers and AI scrapers that don't execute JS see empty elements
        instead of localized text (FAQ rich results, anchor text);
      - real users see the layout grow when the texts arrive, which is the
        main source of the home page's Cumulative Layout Shift.

What it does:
    Parses templates/_fragments/i18n_data.js once at startup (the main
    `const L={…}` object plus every later `Object.assign(L.xx,{…})` block)
    into { lang: { key: text } }. `prefill_seo_text()` then fills every empty
    `data-t` element server-side with the same text `applyI18n()` would write
    (lang first, English fallback), so the first paint already has its final
    size. The client `applyI18n()` runs afterwards and rewrites the same
    nodes idempotently.

The parser only understands the format written by hand in i18n_data.js:
bare identifier keys, double-quoted values, JS escapes (\n \t \" \' \\
\uXXXX). A block it cannot read is skipped from the first unexpected token
on, never raised: the client still fills those elements.
"""
from __future__ import annotations

from html import escape as _esc
from pathlib import Path
import re

_LANGS: list[str] = ["it", "en", "fr", "es", "de", "zh", "hi"]

# One `key:"value"` pair followed by its separator. Values never contain an
# unescaped double quote.
_PAIR_RE = re.compile(r'\s*([A-Za-z_$][\w$]*)\s*:\s*"((?:[^"\\]|\\.)*)"\s*([,}])', re.S)
_LANG_OPEN_RE = re.compile(r"\s*([a-z]{2})\s*:\s*\{")
_COMMA_RE = re.compile(r"\s*,")
_NESTED_RE = re.compile(r"\s*[A-Za-z_$][\w$]*\s*:\s*[{\[]")
_SEP_RE = re.compile(r"\s*([,}])")
_STR_RE = re.compile(r'"(?:[^"\\]|\\.)*"', re.S)
_ESC_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|.)", re.S)
_ESC_MAP = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f", "v": "\v", "0": "\0"}


def _unescape_js(s: str) -> str:
    """Reverse the JS string escapes used in i18n_data.js."""
    def _one(m: "re.Match[str]") -> str:
        e = m.group(1)
        if len(e) == 5:
            return chr(int(e[1:], 16))
        return _ESC_MAP.get(e, e)
    return _ESC_RE.sub(_one, s)


def _skip_nested(src: str, pos: int) -> int:
    """Skip a nested `{…}` / `[…]` value (e.g. the `langs` name table) whose
    opener is at `pos`; returns the index just past its closer, or -1."""
    depth, i, n = 0, pos, len(src)
    while i < n:
        c = src[i]
        if c == '"':
            m = _STR_RE.match(src, i)
            if not m:
                return -1
            i = m.end()
            continue
        if c in "{[":
            depth += 1
        elif c in "}]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def _read_pairs(src: str, pos: int, into: dict[str, str]) -> int:
    """Read `key:"value"` pairs starting right after an opening brace.

    Nested object/array values are skipped (no data-t points at them).
    Returns the index just past the closing brace, or -1 if the block holds
    something else (the pairs read so far are kept)."""
    while True:
        m = _PAIR_RE.match(src, pos)
        if m:
            into[m.group(1)] = _unescape_js(m.group(2))
            pos = m.end()
            if m.group(3) == "}":
                return pos
            continue
        nested = _NESTED_RE.match(src, pos)
        if not nested:
            return -1
        pos = _skip_nested(src, nested.end() - 1)
        if pos < 0:
            return -1
        sep = _SEP_RE.match(src, pos)
        if not sep:
            return -1
        pos = sep.end()
        if sep.group(1) == "}":
            return pos


def _parse_i18n(js_path: Path) -> dict[str, dict[str, str]]:
    src = js_path.read_text(encoding="utf-8")
    out: dict[str, dict[str, str]] = {lang: {} for lang in _LANGS}

    main = re.search(r"const L\s*=\s*\{", src)
    if main:
        pos = main.end()
        while True:
            m = _LANG_OPEN_RE.match(src, pos)
            if not m or m.group(1) not in out:
                break
            pos = _read_pairs(src, m.end(), out[m.group(1)])
            if pos < 0:
                break
            sep = _COMMA_RE.match(src, pos)
            if not sep:
                break
            pos = sep.end()

    # Later blocks override the main object, as they do in the browser.
    for m in re.finditer(r"Object\.assign\(L\.([a-z]{2})\s*,\s*\{", src):
        if m.group(1) in out:
            _read_pairs(src, m.end(), out[m.group(1)])
    return out


_ASSIGN_RE = re.compile(r"Object\.assign\(L\.([a-z]{2})\s*,\s*\{")
_ASSIGN_END_RE = re.compile(r"\s*\)\s*;?")
_LINE_COMMENT_RE = re.compile(r"^\s*//[^\n]*$", re.M)
_SHELL_RE = re.compile(r"\s*const L\s*=\s*\{[\s,]*\}\s*;?\s*")


def _split_i18n(src: str) -> dict[str, list[str]] | None:
    """Split i18n_data.js into per-language JS statements.

    For each language: `L.xx={…};` from the main object, then every
    `Object.assign(L.xx,{…});` in file order. They only touch their own
    language, so any subset of languages can be loaded in any order and
    gives the same L[xx] as the whole file. Returns None when something
    in the file is not one of those blocks (a comment aside): the caller
    then inlines the whole file, as before."""
    out: dict[str, list[str]] = {lang: [] for lang in _LANGS}
    spans: list[tuple[int, int]] = []
    main = re.search(r"const L\s*=\s*\{", src)
    if not main:
        return None
    pos = main.end()
    while True:
        m = _LANG_OPEN_RE.match(src, pos)
        if not m:
            break
        if m.group(1) not in out:
            return None
        end = _read_pairs(src, m.end(), {})
        if end < 0:
            return None
        out[m.group(1)].append(f"L.{m.group(1)}={src[m.end() - 1:end]};")
        spans.append((m.start(), end))
        sep = _COMMA_RE.match(src, end)
        if not sep:
            break
        pos = sep.end()
    for m in _ASSIGN_RE.finditer(src):
        if m.group(1) not in out:
            return None
        end = _read_pairs(src, m.end(), {})
        tail = _ASSIGN_END_RE.match(src, end) if end >= 0 else None
        if not tail:
            return None
        out[m.group(1)].append(src[m.start():end] + ");")
        spans.append((m.start(), tail.end()))
    # Everything outside the blocks must be the `const L={…};` shell and
    # comments, or a statement would be lost.
    spans.sort()
    rest, last = [], 0
    for a, b in spans:
        rest.append(src[last:a])
        last = b
    rest.append(src[last:])
    leftover = _LINE_COMMENT_RE.sub("", "".join(rest))
    if not _SHELL_RE.fullmatch(leftover):
        return None
    return out


# Parse once at import time; re-import to refresh.
_FRAGMENTS_DIR = Path(__file__).parent / "_fragments"
_I18N_SRC = (_FRAGMENTS_DIR / "i18n_data.js").read_text(encoding="utf-8")
SEO_TEXT: dict[str, dict[str, str]] = _parse_i18n(_FRAGMENTS_DIR / "i18n_data.js")
_I18N_SPLIT = _split_i18n(_I18N_SRC)


def i18n_page_js(lang: str) -> str:
    """i18n_data.js as inlined in the home of `lang`: only `lang` and the
    English fallback; the other languages come from i18n_lang_js() when
    the user switches (setLang). Whole file if the split failed."""
    if _I18N_SPLIT is None or lang not in _I18N_SPLIT:
        return _I18N_SRC
    keep = [lang] if lang == "en" else [lang, "en"]
    body = "\n".join(s for lc in keep for s in _I18N_SPLIT[lc])
    return f"// ═══════════════════ i18n ═══════════════════\nconst L={{}};\n{body}\n"


def i18n_lang_js(lang: str) -> str | None:
    """The statements of one language, served as /i18n/<lang>.js; None if
    unknown or the split failed (then the page already has every language)."""
    if _I18N_SPLIT is None or lang not in _I18N_SPLIT:
        return None
    return "\n".join(_I18N_SPLIT[lang]) + "\n"

# Any empty element carrying a data-t / data-t-html attribute:
# <tag … data-t="KEY" …></tag>. `\sdata-t(-html)?="` excludes data-t-title
# and data-t-ph, which translate attributes and stay client-only. Elements
# that already have content are never touched.
_EMPTY_RE = re.compile(r'<([a-z][a-z0-9]*)(\s[^<>]*?)></\1>')
_KEY_RE = re.compile(r'\sdata-t(-html)?="([^"]+)"')
_FAQ_RE = re.compile(r'\sclass="[^"]*\bfaq-answer\b')
_HTML_RE = re.compile(r"<[a-z][\s\S]*>", re.I)
_RAW_BLOCK_RE = re.compile(r"(<(?:script|style)\b[^>]*>.*?</(?:script|style)>)", re.S | re.I)


def prefill_seo_text(html: str, lang: str) -> str:
    """Inject server-side text into empty data-t placeholders for `lang`.

    Mirrors `applyI18n()`: `lang` first, English fallback, text escaped.
    Written as HTML, like the client does, are `data-t-html` values and
    `.faq-answer` values holding links: both come from i18n_data.js, never
    from users. Unknown keys stay empty so a typo never breaks the page."""
    table = SEO_TEXT.get(lang) or {}
    fallback = SEO_TEXT.get("en") or {}
    if not table and not fallback:
        return html

    def _fill(m: "re.Match[str]") -> str:
        tag, attrs = m.group(1), m.group(2)
        k = _KEY_RE.search(attrs)
        if not k:
            return m.group(0)
        text = table.get(k.group(2))
        if text is None:
            text = fallback.get(k.group(2))
        if not text:
            return m.group(0)
        if k.group(1):
            body = text
        elif _FAQ_RE.search(attrs):
            body = text if _HTML_RE.search(text) else _esc(text).replace("\n", "<br>")
        else:
            body = _esc(text, quote=False)
        return f"<{tag}{attrs}>{body}</{tag}>"

    # Inline <script>/<style> blocks are copied untouched: markup inside a JS
    # string must not get text injected into it.
    parts = _RAW_BLOCK_RE.split(html)
    for i in range(0, len(parts), 2):
        parts[i] = _EMPTY_RE.sub(_fill, parts[i])
    return "".join(parts)
