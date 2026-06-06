"""
HTML template for the Audiobook Maker landing page.

The template is assembled from modular fragments at startup:
  - _fragments/html_head.html         : HTML structure, CSS, early JS
  - _fragments/i18n_data.js           : UI translations (7 languages)
  - _fragments/free_books_data.js     : Free book sites data + functions
  - _fragments/podcast_guide_data.js  : Podcast guide (base64 images + per-language sections + About)
  - _fragments/seo_data.js            : SEO metadata per language + applySEO()
  - _fragments/html_tail.html         : Active jobs monitor, applyI18n, main app logic, closing tags

Server-side SEO:
  Meta tags (title, description, OG, hreflang, canonical, JSON-LD) are injected
  via placeholder replacement in html_head.html at startup.
  JSON-LD schema (FAQPage, HowTo, SoftwareApplication) is injected into <head>.
"""

import os
from datetime import datetime
from pathlib import Path

_FRAGMENTS_DIR = Path(__file__).parent / "_fragments"

# Baidu Tongji analytics — attivo solo se ABM_BAIDU_TONGJI_ID configurato
_BAIDU_TONGJI_ID = os.environ.get("ABM_BAIDU_TONGJI_ID", "")
if _BAIDU_TONGJI_ID:
    _BAIDU_TONGJI_SNIPPET = (
        "<script>var _hmt=_hmt||[];"
        "(function(){var hm=document.createElement('script');"
        f"hm.src='https://hm.baidu.com/hm.js?{_BAIDU_TONGJI_ID}';"
        "var s=document.getElementsByTagName('script')[0];"
        "s.parentNode.insertBefore(hm,s);"
        "})();</script>"
    )
else:
    _BAIDU_TONGJI_SNIPPET = ""

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
    "hi": "hi",
}
# Open Graph locale mapping
_OG_LOCALE_MAP = {
    "it": "it_IT", "en": "en_US", "fr": "fr_FR",
    "es": "es_ES", "de": "de_DE", "zh": "zh_CN",
    "hi": "hi_IN",
}
_SUPPORTED_LANGS = list(_HREFLANG_MAP.keys())


def build_html_template(
    lang: str = "en",
    seo: dict | None = None,
    base_url: str = "",
    version: str = "",
    canonical_url: str = "",
    updated_date: str = "",
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
        lang: Language code (it, en, fr, es, de, zh, hi).
        seo: Dict with keys: title, desc, kw, ld_name, ld_desc.
        base_url: Base URL for canonical/hreflang (e.g. "https://audiobook-maker.com").
        version: Version string for the badge (e.g. "2.1").
        canonical_url: Override for the canonical URL. If empty, defaults to
                       "{base_url}/{lang}/". Used by the root route (/) to set
                       canonical to "{base_url}/" so that hreflang x-default
                       points to a self-canonicalizing URL.

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
        canonical = canonical_url or (f"{base_url}/{lang}/" if base_url else "")

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

        # Build og:locale:alternate tags (all locales except the current one)
        current_locale = _OG_LOCALE_MAP.get(lang, "en_US")
        og_locale_alt_lines = [
            f'<meta property="og:locale:alternate" content="{loc}">'
            for code, loc in _OG_LOCALE_MAP.items()
            if loc != current_locale
        ]
        og_locale_alt_block = "\n".join(og_locale_alt_lines)

        replacements = {
            "__HTML_LANG__":     html_lang,
            "__LANG_CODE__":     lang,          # ← inietta INIT_LANG per il JS
            "__SEO_TITLE__":     seo.get("title", "Audiobook Maker"),
            "__SEO_DESC__":      seo.get("desc", ""),
            "__SEO_KW__":        seo.get("kw", ""),
            "__SEO_CANONICAL__": canonical,
            "__SEO_HREFLANG__":  hreflang_block,
            "__SEO_LD_NAME__":   seo.get("ld_name", "Audiobook Maker"),
            "__SEO_LD_DESC__":   seo.get("ld_desc", ""),
            "__H1_TAGLINE__":    seo.get("tagline", ""),
            "__SUBTITLE__":      seo.get("subtitle", ""),
            "__SEO_OG_IMAGE__":  f"{base_url}/og-image.png" if base_url else "/og-image.png",
            "__OG_LOCALE__":     current_locale,
            "__OG_LOCALE_ALT__": og_locale_alt_block,
            "__SEO_PUBLISHED__": "2022-06-01",
            "__SEO_MODIFIED__":  datetime.now().strftime("%Y-%m-%d"),
        }
        for placeholder, value in replacements.items():
            html = html.replace(placeholder, value)

    # ── 3. Inject FAQPage + HowTo + SoftwareApplication JSON-LD into <head> placeholders ──
    from seo_content import get_schema_ld
    faq_ld, howto_ld, app_ld = get_schema_ld(lang)
    html = html.replace("__SEO_FAQ_LD__", faq_ld)
    html = html.replace("__SEO_HOWTO_LD__", howto_ld)
    html = html.replace("__SEO_APP_LD__", app_ld)
    html = html.replace("__APP_VERSION__", version or "3.3")
    html = html.replace("__BAIDU_TONGJI__", _BAIDU_TONGJI_SNIPPET)
    # Limite upload (MB) esposto al JS per il pre-check dimensione file lato client
    # (stessa env var che governa MAX_CONTENT_LENGTH in audiobook_app.py).
    try:
        _max_upload_mb = int(os.environ.get("ABM_MAX_UPLOAD_MB", "50"))
    except ValueError:
        _max_upload_mb = 50
    html = html.replace("__MAX_UPLOAD_MB__", str(_max_upload_mb))

    # ── 4. Inject version badge ──
    version_badge = ""
    if version:
        version_badge = (
            '<div id="appVersion" style="position:fixed;bottom:8px;left:12px;'
            'font-size:11px;color:var(--txm,#9e9890);opacity:0.6;'
            'font-family:monospace;z-index:1;pointer-events:none;'
            f'user-select:none">v{version}</div>'
        )

    # ── 5. Inject updated date badge (bottom-right) ──
    updated_badge = ""
    if updated_date:
        updated_badge = (
            '<div id="appUpdated" style="position:fixed;bottom:8px;right:12px;'
            'font-size:11px;color:var(--txm,#9e9890);opacity:0.6;'
            'font-family:monospace;z-index:1;pointer-events:none;'
            f'user-select:none">Updated: {updated_date}</div>'
        )

    # ── 5b. Server-side prefill of i18n placeholders for SEO-critical text ──
    # Crawlers and AI scrapers that don't run JS would otherwise see empty
    # <span data-t="…">/<summary> nodes for the FAQ block and guide-card link
    # labels. We mirror the relevant subset of the JS i18n into Python and
    # fill the elements before serving. Client-side applyI18n() runs after
    # and overwrites idempotently, so no behavior change for human visitors.
    from templates.seo_i18n import prefill_seo_text
    html = prefill_seo_text(html, lang)

    # ── 6. Build the multilingual visible SEO content block ──
    # Removed: server-rendered visible SEO block duplicated content already
    # present in the app interface. JSON-LD schema remains in <head>.
    seo_content_html = ""

    # Insert version/updated badges before </body>
    html = html.replace(
        "</body>",
        version_badge + updated_badge + "\n</body>",
        1,
    )

    return html
