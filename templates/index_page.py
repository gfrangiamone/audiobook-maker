"""
HTML template for the Audiobook Maker landing page.

The template is assembled from modular fragments at startup:
  - _fragments/html_head.html         : HTML structure, CSS, early JS
  - _fragments/i18n_data.js           : UI translations (6 languages)
  - _fragments/free_books_data.js     : Free book sites data + functions
  - _fragments/podcast_guide_data.js  : Podcast guide (base64 images + per-language sections + About)
  - _fragments/seo_data.js            : SEO metadata per language + applySEO()
  - _fragments/html_tail.html         : Active jobs monitor, applyI18n, main app logic, closing tags

Server-side SEO:
  Meta tags (title, description, OG, hreflang, canonical, JSON-LD) are injected
  via placeholder replacement in html_head.html at startup.
  Visible SEO content (heading, text, features, FAQ + FAQPage schema) is injected
  before </body> via seo_content.build_seo_content_html().
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

# hreflang mapping
_HREFLANG_MAP = {
    "it": "it", "en": "en", "fr": "fr",
    "es": "es", "de": "de", "zh": "zh-Hans",
}
_SUPPORTED_LANGS = list(_HREFLANG_MAP.keys())


def build_html_template(
    lang: str = "en",
    seo: dict | None = None,
    base_url: str = "",
    version: str = "",
) -> str:
    """Assemble the full HTML template from fragments with server-side SEO.

    All SEO-critical content is injected into the static HTML BEFORE any
    JavaScript executes, so search engine crawlers see everything on first pass.

    Injections:
      1. <head> meta tags via placeholder replacement (__SEO_TITLE__, etc.)
      2. Visible SEO content block (text, features, FAQ) before </body>
      3. FAQPage JSON-LD schema in the SEO content block
      4. Version badge before </body>

    Args:
        lang: Language code (it, en, fr, es, de, zh).
        seo: Dict with keys: title, desc, kw, ld_name, ld_desc.
        base_url: Base URL for canonical/hreflang (e.g. "https://audiobook-maker.com").
        version: Version string for the badge (e.g. "2.1").

    Returns:
        Complete HTML string with all SEO baked in.
    """
    # ── 1. Assemble fragments ──
    parts = []
    for fname in _FRAGMENT_ORDER:
        fpath = _FRAGMENTS_DIR / fname
        parts.append(fpath.read_text(encoding="utf-8"))
    html = "".join(parts)

    # ── 2. Replace <head> placeholders with server-side SEO data ──
    if seo:
        html_lang = _HREFLANG_MAP.get(lang, "en")
        canonical = f"{base_url}/{lang}/" if base_url else ""

        # Build hreflang link tags
        hreflang_lines = []
        for lc, hl in _HREFLANG_MAP.items():
            href = f"{base_url}/{lc}/" if base_url else f"?lang={lc}"
            hreflang_lines.append(
                f'<link rel="alternate" hreflang="{hl}" href="{href}">'
            )
        x_default_href = f"{base_url}/" if base_url else "/"
        hreflang_lines.append(
            f'<link rel="alternate" hreflang="x-default" href="{x_default_href}">'
        )
        hreflang_block = "\n".join(hreflang_lines)

        replacements = {
            "__HTML_LANG__":     html_lang,
            "__SEO_TITLE__":     seo.get("title", "Audiobook Maker"),
            "__SEO_DESC__":      seo.get("desc", ""),
            "__SEO_KW__":        seo.get("kw", ""),
            "__SEO_CANONICAL__": canonical,
            "__SEO_HREFLANG__":  hreflang_block,
            "__SEO_LD_NAME__":   seo.get("ld_name", "Audiobook Maker"),
            "__SEO_LD_DESC__":   seo.get("ld_desc", ""),
        }
        for placeholder, value in replacements.items():
            html = html.replace(placeholder, value)

    # ── 3. Inject visible SEO content block before </body> ──
    from seo_content import build_seo_content_html
    seo_block = build_seo_content_html(lang)

    # ── 4. Inject version badge ──
    version_badge = ""
    if version:
        version_badge = (
            '<div id="appVersion" style="position:fixed;bottom:8px;left:12px;'
            'font-size:11px;color:var(--txm,#9e9890);opacity:0.6;'
            'font-family:monospace;z-index:1;pointer-events:none;'
            f'user-select:none">v{version}</div>'
        )

    # Insert both blocks before </body>
    html = html.replace("</body>", seo_block + version_badge + "\n</body>", 1)

    return html
