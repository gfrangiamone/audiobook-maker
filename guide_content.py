"""
SEO Guide Pages for Audiobook Maker.

Provides long-form guide content targeting informational keywords:
  - /guide/epub-to-audiobook/
  - /guide/m4b-format/
  - /guide/text-to-speech-audiobook/

Each guide has full EN content + metadata for all 6 languages.
"""

from __future__ import annotations

from content_store import content_json, content_text, content_exists
from i18n import pick as _i18n_pick
import page_brand as _brand
import seo_ld as _seo_ld


def _guide_bodies(lang):
    """Corpi HTML delle guide statiche in una lingua: content/guides/<id>/<lang>.html."""
    return {gid: content_text("guides", gid, f"{lang}.html")
            for gid in content_json("guides", "meta.json")
            if content_exists("guides", gid, f"{lang}.html")}

def _guide_path(guide_id: str, lang: str) -> str:
    """URL path di una guida in una lingua (schema path-based).

    EN è la x-default e vive su /guide/<id>/ senza suffisso; le altre lingue
    su /guide/<id>/<lang>/. Usato per canonical, hreflang e sitemap così che
    tutte le sorgenti producano la stessa forma di URL.
    """
    return f"/guide/{guide_id}/" if lang == "en" else f"/guide/{guide_id}/{lang}/"

# ── Guide metadata per language ──────────────────────────────────────────────

_GUIDE_META = content_json("guides", "meta.json")

# ── Guide body content (English only; other languages use EN as fallback) ─────

_GUIDE_BODY_EN = _guide_bodies("en")

_GUIDE_BODY_IT = _guide_bodies("it")

# Map language code to body dict for per-language guide content.
# Each language dict has the same keys as _GUIDE_BODY_EN.

_GUIDE_BODY_FR = _guide_bodies("fr")


_GUIDE_BODY_ES = _guide_bodies("es")


_GUIDE_BODY_DE = _guide_bodies("de")


_GUIDE_BODY_ZH = _guide_bodies("zh")

# Guida «Audiolibri con la tua voce»: contenuti in guide_voice_clone.py, in 7 lingue.
import guide_voice_clone as _gvc  # noqa: E402

_GUIDE_META[_gvc.GUIDE_ID] = _gvc.META
for _gl, _gd in (("en", _GUIDE_BODY_EN), ("it", _GUIDE_BODY_IT), ("fr", _GUIDE_BODY_FR),
                 ("es", _GUIDE_BODY_ES), ("de", _GUIDE_BODY_DE), ("zh", _GUIDE_BODY_ZH)):
    _gd[_gvc.GUIDE_ID] = _gvc.body(_gl)
# Hindi: solo le guide tradotte, le altre ricadono su EN.
_GUIDE_BODY_HI = {_gvc.GUIDE_ID: _gvc.body("hi")}

# Missing languages fall back to EN.
_GUIDE_BODY = {"it": _GUIDE_BODY_IT, "fr": _GUIDE_BODY_FR, "es": _GUIDE_BODY_ES, "de": _GUIDE_BODY_DE, "zh": _GUIDE_BODY_ZH,
               "hi": _GUIDE_BODY_HI}

# JSON-LD aggiuntivi per guida (HowTo, FAQPage): fn(lang, canonical, meta) -> [json, ...]
_GUIDE_EXTRA_LD = {_gvc.GUIDE_ID: _gvc.extra_ld}




# Date pubblicazione iniziale per guida (statica). dateModified = mtime del file sorgente.
_GUIDE_PUBLISHED = {
    "epub-to-audiobook": "2024-09-15",
    "m4b-format": "2024-10-01",
    "text-to-speech-audiobook": "2024-11-10",
    "podcast": "2025-01-20",
    "gemini-tts": "2026-06-09",
    _gvc.GUIDE_ID: _gvc.PUBLISHED,
}

_GUIDE_SECTION = {
    "epub-to-audiobook": "Tutorials",
    "m4b-format": "File Formats",
    "text-to-speech-audiobook": "Text-to-Speech",
    "podcast": "Podcast Publishing",
    "gemini-tts": "Text-to-Speech",
    _gvc.GUIDE_ID: _gvc.SECTION,
}


def _build_article_ld(guide_id: str, lang: str, base_url: str, meta: dict) -> str:
    """Build Article JSON-LD schema for a guide page.

    Include datePublished/dateModified/image/keywords per AI citation engines
    (ChatGPT, Perplexity, Google AI Overview) e ranking E-E-A-T.
    """
    import os as _os
    from datetime import datetime as _dt

    # Stesso URL del <link rel=canonical> della pagina: EN su /guide/<id>/,
    # le altre lingue su /guide/<id>/<lang>/ (prima era sempre l'URL EN).
    canonical = f"{base_url}{_guide_path(guide_id, lang)}"
    base = base_url or _seo_ld.SITE_URL

    try:
        _mtime = _os.path.getmtime(__file__)
        date_modified = _dt.utcfromtimestamp(_mtime).strftime("%Y-%m-%d")
    except OSError:
        date_modified = _dt.utcnow().strftime("%Y-%m-%d")
    date_published = _GUIDE_PUBLISHED.get(guide_id, "2024-09-01")

    ld = {
        "@context": "https://schema.org",
        "@type": "Article",
        "headline": meta.get("h1", meta["title"]),
        "description": meta["desc"],
        "url": canonical,
        "inLanguage": _seo_ld.in_language(lang),
        "datePublished": date_published,
        "dateModified": date_modified,
        "image": {
            "@type": "ImageObject",
            "url": f"{base}/og-image.png",
            "width": 1200,
            "height": 630,
        },
        "author": _seo_ld.AUTHOR,
        "publisher": _seo_ld.publisher(base, logo_size=192),
        "isAccessibleForFree": True,
        "license": _seo_ld.LICENSE,
        "mainEntityOfPage": {
            "@type": "WebPage",
            "@id": canonical,
        },
        "articleSection": _GUIDE_SECTION.get(guide_id, "Guide"),
        "keywords": meta.get("kw", ""),
    }
    return _seo_ld.ld_json(ld)


def build_guide_html(
    guide_id: str,
    lang: str = "en",
    base_url: str = "",
    version: str = "",
) -> str:
    """Build complete HTML for a guide page.

    Args:
        guide_id: One of 'epub-to-audiobook', 'm4b-format', 'text-to-speech-audiobook'.
        lang: Language code (it, en, fr, es, de, zh).
        base_url: Base URL for canonical/hreflang (e.g. "https://audiobook-maker.com").
        version: App version string.

    Returns:
        Complete HTML string with SEO baked in.
    """

    guide_meta_all = _GUIDE_META.get(guide_id)
    if not guide_meta_all:
        return f"<!-- Guide '{guide_id}' not found -->"

    meta = _i18n_pick(guide_meta_all, lang, merge=False)
    # Self-canonical per language, path-based: EN = x-default su /guide/<id>/,
    # le altre lingue su /guide/<id>/<lang>/. Coerente con sitemap.xml e link interni.
    canonical = f"{base_url}{_guide_path(guide_id, lang)}" if base_url else ""

    hreflang_block = _brand.hreflang_links(
        lambda lc: f"{base_url}{_guide_path(guide_id, lc)}",
        f"{base_url}/guide/{guide_id}/" if base_url else "/")

    # Article JSON-LD
    article_ld = _build_article_ld(guide_id, lang, base_url, meta)

    # Date visibili (datePublished/dateModified) per UX + AI scraping.
    import os as _os
    from datetime import datetime as _dt
    try:
        _mtime = _os.path.getmtime(__file__)
        _date_modified = _dt.utcfromtimestamp(_mtime).strftime("%Y-%m-%d")
    except OSError:
        _date_modified = _dt.utcnow().strftime("%Y-%m-%d")
    _date_published = _GUIDE_PUBLISHED.get(guide_id, "2024-09-01")
    _updated_label = {
        "it": "Ultimo aggiornamento", "en": "Last updated", "fr": "Dernière mise à jour",
        "es": "Última actualización", "de": "Zuletzt aktualisiert", "zh": "最后更新",
        "hi": "अंतिम बार अपडेट किया गया",
    }.get(lang, "Last updated")
    _published_label = {
        "it": "Pubblicato", "en": "Published", "fr": "Publié",
        "es": "Publicado", "de": "Veröffentlicht", "zh": "发布于",
        "hi": "प्रकाशित",
    }.get(lang, "Published")
    article_dates_html = (
        f'<p class="article-dates" style="font-size:.85rem;color:var(--txm);margin:8px 0 16px">'
        f'<time datetime="{_date_published}">{_published_label}: {_date_published}</time> &middot; '
        f'<time datetime="{_date_modified}">{_updated_label}: {_date_modified}</time>'
        f'</p>'
    )

    # BreadcrumbList JSON-LD
    crumb_names = {
        "it": "Guide", "en": "Guides", "fr": "Guides",
        "es": "Guías", "de": "Anleitungen", "zh": "指南",
        "hi": "गाइड",
    }
    crumb_name = crumb_names.get(lang, "Guides")
    breadcrumb_ld = _seo_ld.ld_json(_seo_ld.breadcrumb_ld(
        [("Audiobook Maker", base_url or _seo_ld.SITE_URL), (crumb_name, canonical)]))

    # Body content — select by language, fall back to EN
    _body_dict = _GUIDE_BODY.get(lang, _GUIDE_BODY_EN)
    body = _body_dict.get(guide_id) or _GUIDE_BODY_EN.get(guide_id, "<p>Guide content not available.</p>")

    # App home URL for internal links
    app_home = f"{base_url}/{lang}/" if base_url else "/"
    cta_label = {
        "it": "Prova Audiobook Maker gratis", "en": "Try Audiobook Maker Free",
        "fr": "Essayez Audiobook Maker gratuitement", "es": "Prueba Audiobook Maker gratis",
        "de": "Audiobook Maker kostenlos testen", "zh": "免费试用 Audiobook Maker",
        "hi": "Audiobook Maker मुफ़्त आज़माएँ",
    }.get(lang, "Try Audiobook Maker Free")

    _extra_fn = _GUIDE_EXTRA_LD.get(guide_id)
    extra_ld = _extra_fn(lang, canonical, meta) if _extra_fn else []

    head = _brand.seo_head(
        desc=meta["desc"], keywords=meta["kw"], canonical=canonical, hreflang=hreflang_block,
        og_type="article", og_title=meta["title"], og_desc=meta["desc"], og_url=canonical,
        og_image=f"{base_url}/og-image.png", lang=lang, twitter=True,
        ld=[article_ld, breadcrumb_ld, *extra_ld])
    body_html = (f'<article>\n<h1>{meta["h1"]}</h1>\n{article_dates_html}\n{body}\n'
                 f'<a class="cta" href="{app_home}">{cta_label} &rarr;</a>\n</article>')
    footer = (f'<p><strong>Audiobook Maker</strong> — Free & open-source EPUB/PDF to audiobook converter. '
              f'400+ AI voices, 50+ languages. <a href="{app_home}">Start converting</a>.</p>')
    return _brand.public_page(lang=lang, title=meta["title"], home=app_home,
                              crumb=f'{crumb_name} &rsaquo; {meta["h1"]}',
                              body=body_html, footer=footer, head=head)
