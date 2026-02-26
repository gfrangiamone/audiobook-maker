"""
HTML template for the Audiobook Maker landing page.

Pre-rendered at startup — one copy per supported language for full server-side SEO.
"""

from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent / "_fragments"

_FRAGMENT_ORDER = [
    "html_head.html",
    "i18n_data.js",
    "free_books_data.js",
    "podcast_guide_data.js",
    "seo_data.js",
    "html_tail.html",
]

LANG_HTML_ATTRS = {
    "it": "it",
    "en": "en",
    "fr": "fr",
    "es": "es",
    "de": "de",
    "zh": "zh-Hans",
}


def _build_hreflang_block(base_url: str) -> str:
    if not base_url:
        return "<!-- hreflang non generato: impostare ABM_BASE_URL -->"
    lines = []
    for lang_code, html_lang in LANG_HTML_ATTRS.items():
        lines.append(
            f'<link rel="alternate" hreflang="{html_lang}" href="{base_url}/{lang_code}/">'
        )
    lines.append(f'<link rel="alternate" hreflang="x-default" href="{base_url}/">')
    return "\n".join(lines)


def build_html_template(
    lang: str = "en",
    seo: dict = None,
    base_url: str = "",
    version: str = "",
) -> str:
    seo = seo or {
        "title": "Audiobook Maker — EPUB to Audiobook TTS Converter",
        "desc": "Free online tool to convert EPUB ebooks into high-quality audiobooks.",
        "kw": "audiobook, epub, tts, text to speech",
        "ld_name": "Audiobook Maker",
        "ld_desc": "Free online tool to convert EPUB ebooks into high-quality audiobooks.",
    }

    parts = [(_FRAGMENTS_DIR / f).read_text(encoding="utf-8") for f in _FRAGMENT_ORDER]
    html = "".join(parts)

    canonical = f"{base_url}/{lang}/" if base_url else f"/{lang}/"

    replacements = {
        "__HTML_LANG__":     LANG_HTML_ATTRS.get(lang, lang),
        "__LANG_CODE__":     lang,
        "__SEO_TITLE__":     seo["title"],
        "__SEO_DESC__":      seo["desc"],
        "__SEO_KW__":        seo["kw"],
        "__SEO_CANONICAL__": canonical,
        "__SEO_HREFLANG__":  _build_hreflang_block(base_url),
        "__SEO_LD_NAME__":   seo.get("ld_name", "Audiobook Maker"),
        "__SEO_LD_DESC__":   seo.get("ld_desc", seo["desc"]),
    }
    for k, v in replacements.items():
        html = html.replace(k, v)

    if version:
        badge = (
            '<div id="appVersion" style="position:fixed;bottom:8px;left:12px;'
            'font-size:11px;color:var(--txm,#9e9890);opacity:0.6;'
            'font-family:monospace;z-index:1;pointer-events:none;'
            'user-select:none">v' + version + "</div>"
        )
        html = html.replace("</body>", badge + "\n</body>")

    return html
