"""routes_pages — pagine pubbliche e SEO (E3, seam SEO/pagine, 2026-10-10).

Blueprint `pages`: `/` e le home per lingua (`/it/` ... `/hi/`), `/faq/`,
`/content/<lang>/`, `/guide/<id>[/<lang>]/`, `/sitemap.xml`,
`/robots.txt`, `/llms.txt`, `/.well-known/{assetlinks.json,
apple-app-site-association}`, `/get-app`, `/privacy`, `/support`, favicon,
icone, immagine OG e `manifest.json`; con l'iniezione delle recensioni,
i bottoni degli store e la pagina install (usata anche dai deep link in
`routes_tokens`). Spostato pari pari da `audiobook_app`.

`configure(...)` riceve dalla app, come funzioni risolte a ogni chiamata,
la lingua dalla richiesta, l'attribuzione app e `BASE_URL`; per
riferimento le lingue supportate e i template HTML precaricati. Non
importa `audiobook_app`.
"""
import html as html_mod
import json
import os
from datetime import datetime, timezone

from flask import Blueprint, current_app, redirect, request, send_file

import i18n as _i18n
import page_brand
import privacy_content
import routes_tokens
import seo_content
import seo_ld
import seo_reviews
import support_content
from env_utils import env_str
from favicon_data import get_apple_touch_icon, get_favicon_ico, get_favicon_png_192, get_favicon_svg
from guide_content import _guide_path, build_guide_html
from og_image_data import get_og_image
from page_brand import render_page as _render_page
from version import __version__

bp = Blueprint("pages", __name__)

_cfg = {}
_SUPPORTED_LANGS = None
HTML_TEMPLATES = None
HTML_ROOT_TEMPLATES = None

FUNCS = ['_detect_lang_from_request', '_apply_app_attribution']
VALUES = ('base_url',)


def configure(*, _SUPPORTED_LANGS, HTML_TEMPLATES, HTML_ROOT_TEMPLATES, **fns):
    """`fns`: una funzione per ogni nome in FUNCS e VALUES (la app passa
    lambda che risolvono i suoi globali a ogni chiamata)."""
    missing = [n for n in FUNCS + list(VALUES) if n not in fns]
    assert not missing, f"routes_pages.configure: mancano {missing}"
    _cfg.update(fns)
    globals()["_SUPPORTED_LANGS"] = _SUPPORTED_LANGS
    globals()["HTML_TEMPLATES"] = HTML_TEMPLATES
    globals()["HTML_ROOT_TEMPLATES"] = HTML_ROOT_TEMPLATES


# Valori della app usati dal codice spostato: risolti a ogni chiamata.
def _base_url():
    return _cfg["base_url"]()


# Gli stessi nomi che il codice usava in audiobook_app: ogni chiamata passa
# dalla funzione configurata, cosi' `monkeypatch.setattr(audiobook_app, ...)`
# nei test vale anche qui.
def _detect_lang_from_request(*a, **k):
    return _cfg["_detect_lang_from_request"](*a, **k)

def _apply_app_attribution(*a, **k):
    return _cfg["_apply_app_attribution"](*a, **k)


def _inject_reviews(template_html: str, lang: str) -> str:
    """Swap __REVIEWS_LD__ placeholder with fresh AggregateRating + Review
    JSON-LD built from the live feedback store.

    Cost ≤ 1 ms per request. Falls back to empty replacement if the store
    is unavailable so the page still renders cleanly."""
    try:
        rev = seo_reviews.build_reviews(lang)
        ld = rev.get("ld_block", "") or ""
    except Exception as e:
        print(f"[seo_reviews] inject failed: {e!s}")
        ld = ""
    return template_html.replace("__REVIEWS_LD__", ld)


@bp.route("/")
def index():
    """Root: serve la lingua rilevata dall'Accept-Language, senza redirect.
    Il redirect 302 penalizzerebbe il PageRank; meglio rispondere con canonical.
    Usa HTML_ROOT_TEMPLATES: canonical punta a BASE_URL/ (non /{lang}/).
    Questo garantisce che l'URL x-default negli hreflang sia auto-canonicalizzante.
    """
    lang = _detect_lang_from_request()
    base = _i18n.pick(HTML_ROOT_TEMPLATES, lang, merge=False)
    resp = current_app.make_response(_inject_reviews(base, lang))
    resp.headers["Content-Type"] = "text/html; charset=utf-8"
    resp.headers["Vary"] = "Accept-Language"
    return _apply_app_attribution(resp)

def _serve_lang(lang: str):
    return (
        _inject_reviews(HTML_TEMPLATES[lang], lang),
        200,
        {"Content-Type": "text/html; charset=utf-8"},
    )

@bp.route("/it/")
def index_it():
    return _serve_lang("it")

@bp.route("/en/")
def index_en():
    return _serve_lang("en")

@bp.route("/fr/")
def index_fr():
    return _serve_lang("fr")

@bp.route("/es/")
def index_es():
    return _serve_lang("es")

@bp.route("/de/")
def index_de():
    return _serve_lang("de")

@bp.route("/zh/")
def index_zh():
    return _serve_lang("zh")

@bp.route("/hi/")
def index_hi():
    return _serve_lang("hi")


# ── FAQ Page (dedicated) ────────────────────────────────────────────

_FAQ_TITLES = {
    "it": "Domande Frequenti — Audiobook Maker",
    "en": "Frequently Asked Questions — Audiobook Maker",
    "fr": "Questions Fréquentes — Audiobook Maker",
    "es": "Preguntas Frecuentes — Audiobook Maker",
    "de": "Häufig Gestellte Fragen — Audiobook Maker",
    "zh": "常见问题 — Audiobook Maker",
    "hi": "अक्सर पूछे जाने वाले प्रश्न — Audiobook Maker",
}


@bp.route("/faq/")
def faq_page_root():
    """Redirect root FAQ to the browser-language or English variant."""
    lang = _detect_lang_from_request()
    if not lang or lang not in _SUPPORTED_LANGS:
        lang = "en"
    base = _base_url() or ""
    if base:
        return redirect(f"{base}/faq/{lang}/", code=301)
    return redirect(f"/faq/{lang}/", code=301)


@bp.route("/faq/<lang>/")
def faq_page(lang):
    """Dedicated FAQ page per language. Crawler-facing minimal HTML with
    JSON-LD FAQPage schema and full hreflang alternates."""
    if lang not in _SUPPORTED_LANGS:
        return "Language not supported", 404

    html_lang = page_brand.html_lang(lang)
    c = seo_content.lang_content(lang)
    title = html_mod.escape(_i18n.pick(_FAQ_TITLES, lang, merge=False))
    desc = html_mod.escape(c.get("direct_answer", ""))
    base = _base_url() or ""
    canonical = f"{base}/faq/{lang}/"
    hreflang_block = page_brand.hreflang_links(
        lambda lc: f"{base}/faq/{lc}/", f"{base}/faq/en/", sep="\n    ")

    # Build FAQ HTML
    faqs_html = ""
    for q, a in c.get("faqs", []):
        faqs_html += (
            f'  <details open><summary>{html_mod.escape(q)}</summary>\n'
            f'    <p>{html_mod.escape(a)}</p>\n'
            f'  </details>\n\n'
        )
    faq_ld_json = seo_ld.ld_json(seo_ld.faq_ld(c.get("faqs", [])))

    iso_modified = datetime.now().strftime("%Y-%m-%d")

    page = _render_page("faq", {"__P0__": (html_lang), "__P1__": (title), "__P2__": (desc), "__P3__": (canonical), "__P4__": (hreflang_block), "__P5__": (iso_modified), "__P6__": (faq_ld_json), "__P7__": (faqs_html)})
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.route("/content/<lang>/")
def seo_content_page(lang):
    """Dedicated SEO content page per language. Minimal HTML wrapper around
    the rich SEO block generated by build_seo_content_html(). Crawler-facing,
    no app CSS/JS required — the block already carries inline styles."""
    if lang not in _i18n.LANGS:
        return "Language not supported", 404

    html_lang = page_brand.html_lang(lang)
    c = seo_content.lang_content(lang)
    title = html_mod.escape(c.get("heading", "Audiobook Maker"))
    desc = html_mod.escape(c.get("direct_answer", ""))
    base = _base_url() or ""
    canonical = f'{base}/content/{lang}/' if base else ""

    seo_block = seo_content.build_seo_content_html(lang)

    head_extra = ""
    if canonical:
        head_extra += f'\n    <link rel="canonical" href="{canonical}" />'

    page = _render_page("seo_content", {"__P0__": (html_lang), "__P1__": (title), "__P2__": (desc), "__P3__": (head_extra), "__P4__": (seo_block)})
    return page, 200, {"Content-Type": "text/html; charset=utf-8"}


#  -  -  SEO Guide Pages  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
_VALID_GUIDES = {"epub-to-audiobook", "m4b-format", "text-to-speech-audiobook", "podcast", "gemini-tts", "free-ebooks", "voice-cloning-audiobook"}
_GUIDE_LANGS = _i18n.LANGS

@bp.route("/guide/<guide_id>/")
def guide_page(guide_id):
    if guide_id not in _VALID_GUIDES:
        return "Guide not found", 404
    # Back-compat: vecchio schema ?lang=xx → 301 al nuovo path /guide/<id>/<lang>/.
    qlang = request.args.get("lang", "").strip()
    if qlang:
        if qlang in _GUIDE_LANGS and qlang != "en":
            return redirect(f"/guide/{guide_id}/{qlang}/", code=301)
        return redirect(f"/guide/{guide_id}/", code=301)
    # Bare URL = x-default (inglese), canonical /guide/<id>/.
    html = build_guide_html(guide_id, "en", _base_url(), __version__)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


@bp.route("/guide/<guide_id>/<lang>/")
def guide_page_lang(guide_id, lang):
    if guide_id not in _VALID_GUIDES:
        return "Guide not found", 404
    lang = (lang or "").strip()
    if lang == "en":
        # EN canonico è senza suffisso → 301 alla forma x-default.
        return redirect(f"/guide/{guide_id}/", code=301)
    if lang not in _GUIDE_LANGS:
        return "Guide not found", 404
    html = build_guide_html(guide_id, lang, _base_url(), __version__)
    return html, 200, {"Content-Type": "text/html; charset=utf-8"}


#  -  -  -  sitemap.xml  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
@bp.route("/sitemap.xml")
def sitemap():
    """Sitemap con tutte le varianti linguistiche.
    Richiede ABM_BASE_URL configurato per gli URL assoluti (obbligatorio per Google).
    """
    if not _base_url():
        return "<!-- sitemap non disponibile: impostare ABM_BASE_URL -->", 200, {
            "Content-Type": "text/xml; charset=utf-8"
        }

    import os as _os
    from datetime import date, datetime as _dt

    def _file_lastmod(path: str) -> str:
        """Return ISO date of file mtime, or today as a safe fallback."""
        try:
            return _dt.fromtimestamp(_os.path.getmtime(path), timezone.utc).strftime("%Y-%m-%d")   # UTC esplicito
        except OSError:
            return date.today().isoformat()

    _here = _os.path.dirname(_os.path.abspath(__file__))
    # The home page reflects content from app + visible SEO + live user
    # reviews; pick the most recent of all three so Google sees a real change
    # signal whenever new feedback is approved.
    candidates = [
        _file_lastmod(_os.path.join(_here, "audiobook_app.py")),
        _file_lastmod(_os.path.join(_here, "seo_content.py")),
    ]
    try:
        latest_review_ts = seo_reviews.build_reviews("en").get("latest_ts", 0)
        if latest_review_ts:
            candidates.append(
                _dt.fromtimestamp(latest_review_ts, timezone.utc).strftime("%Y-%m-%d")
            )
    except Exception:
        pass
    home_lastmod = max(candidates)
    guide_lastmod = _file_lastmod(_os.path.join(_here, "guide_content.py"))

    # Blocco alternates condiviso da tutti gli URL (page_brand.hreflang_links)
    def _alts(path_fn, x_default):
        return page_brand.hreflang_links(path_fn, x_default, xhtml=True)

    alternates = _alts(lambda lc: f"{_base_url()}/{lc}/", f"{_base_url()}/")

    urls = []
    # Root (x-default)
    urls.append(f"""  <url>
    <loc>{_base_url()}/</loc>
    <lastmod>{home_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
{alternates}
  </url>""")

    # Una URL per lingua
    for lc in page_brand.SITE_LANGS:
        urls.append(f"""  <url>
    <loc>{_base_url()}/{lc}/</loc>
    <lastmod>{home_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.9</priority>
{alternates}
  </url>""")

    # Content SEO pages — 7 lingue
    content_alternates = _alts(lambda lc: f"{_base_url()}/content/{lc}/", f"{_base_url()}/content/en/")
    for lc in page_brand.SITE_LANGS:
        urls.append(f"""  <url>
    <loc>{_base_url()}/content/{lc}/</loc>
    <lastmod>{home_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.5</priority>
{content_alternates}
  </url>""")

    # FAQ pages — 7 lingue, priority 0.8 (high value for featured snippets)
    faq_alternates = _alts(lambda lc: f"{_base_url()}/faq/{lc}/", f"{_base_url()}/faq/en/")
    for lc in page_brand.SITE_LANGS:
        urls.append(f"""  <url>
    <loc>{_base_url()}/faq/{lc}/</loc>
    <lastmod>{home_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.8</priority>
{faq_alternates}
  </url>""")

    # Guide pages — schema path-based: EN su /guide/<id>/ (x-default, lc=="en"),
    # altre lingue su /guide/<id>/<lang>/. N guide × 7 lingue URL totali.
    for guide_id in sorted(_VALID_GUIDES):
        # Per-language alternates (hreflang) condivise da tutte le varianti.
        guide_alternates = _alts(lambda lc, g=guide_id: f"{_base_url()}{_guide_path(g, lc)}",
                                 f"{_base_url()}/guide/{guide_id}/")

        for lc in page_brand.SITE_LANGS:
            urls.append(f"""  <url>
    <loc>{_base_url()}{_guide_path(guide_id, lc)}</loc>
    <lastmod>{guide_lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.7</priority>
{guide_alternates}
  </url>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
{chr(10).join(urls)}
</urlset>"""
    return xml, 200, {"Content-Type": "application/xml; charset=utf-8"}


#  -  -  -  robots.txt  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# ── Deep link app mobile: QR /t/<token> + Android App Links ──
_APP_PACKAGE = "it.abm.audiobook_maker_mobile"
_APP_CERT_FINGERPRINTS = [
    # Upload key (APK di test / chiave di upload Play)
    "50:09:2D:2F:DD:99:FF:A7:F9:7E:40:39:04:C6:C3:DC:A1:3F:54:AE:0E:17:E1:6E:13:AD:07:20:83:8A:C4:BB",
    # App signing key di Google (Play Console) — copre le installazioni da Play
    "6A:77:8A:0E:75:60:E3:22:BB:AE:75:2C:03:1F:E4:C7:59:16:25:69:01:4B:C2:F6:89:75:46:BF:95:96:09:BB",
]
# iOS: appID = <Apple Team ID>.<Bundle ID>, usato nell'apple-app-site-association.
_IOS_APP_ID = "DXD84TM2T3.it.abm.audiobookMakerMobile"
# URL store da env (omogenei): se assenti, il bottone è mostrato ma disabilitato.
# Valore Play da impostare in ABM_PLAY_STORE_URL al rilascio: https://play.google.com/store/apps/details?id=it.nextsw.audiobook_maker_mobile
_PLAY_STORE_URL = env_str("ABM_PLAY_STORE_URL", "").strip()   # pattern env inline vietato nei moduli nuovi
_APP_STORE_URL = env_str("ABM_APP_STORE_URL", "").strip()

# ---------------------------------------------------------------------------
# Inline-SVG store badges (viewBox 0 0 135 40)
# ---------------------------------------------------------------------------
_PLAY_BADGE_SVG = (
    # Riproduzione fedele del badge ufficiale "Get it on Google Play":
    # icona a 4 facce con le sfumature del brand + lockup testuale.
    # Uso consentito senza oneri di licenza purche' l'artwork non venga
    # ricolorato/deformato (Google Play badge guidelines).
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 135 40" role="img">'
    '<defs><linearGradient id="abmgp1" x1="20.75" y1="8.71" x2="5.02" y2="24.44" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#00a0ff"/><stop offset=".26" stop-color="#00beff"/><stop offset=".51" stop-color="#00d2ff"/><stop offset=".76" stop-color="#00dfff"/><stop offset="1" stop-color="#00e3ff"/></linearGradient><linearGradient id="abmgp2" x1="29.34" y1="18.4" x2="9.64" y2="18.4" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#ffe000"/><stop offset=".41" stop-color="#ffbd00"/><stop offset=".78" stop-color="#ffa500"/><stop offset="1" stop-color="#ff9c00"/></linearGradient><linearGradient id="abmgp3" x1="26.56" y1="20.28" x2="2.26" y2="44.58" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#ff3a44"/><stop offset="1" stop-color="#c31162"/></linearGradient><linearGradient id="abmgp4" x1="7.3" y1="-3.36" x2="18.15" y2="7.5" gradientUnits="userSpaceOnUse"><stop offset="0" stop-color="#32a071"/><stop offset=".07" stop-color="#2da771"/><stop offset=".48" stop-color="#15cf74"/><stop offset=".8" stop-color="#06b070"/><stop offset="1" stop-color="#00b16a"/></linearGradient></defs>'
    '<rect width="135" height="40" rx="6" fill="#000"/>'
    '<rect x=".5" y=".5" width="134" height="39" rx="5.5" fill="none" stroke="#a6a6a6"/>'
    '<path d="M10.44 7.32a1.51 1.51 0 0 0-.35 1.06v18.25c0 .42.13.78.36 1.04l.06.06 10.23-10.23v-.24L10.5 7.26l-.06.06z" fill="url(#abmgp1)"/>'
    '<path d="M24.1 21.93l-3.4-3.41v-.24l3.41-3.42.08.05 4.04 2.3c1.15.65 1.15 1.72 0 2.38l-4.03 2.29-.1.05z" fill="url(#abmgp2)"/>'
    '<path d="M24.19 21.88L20.7 18.4 10.44 28.67c.38.4 1 .45 1.71.05l12.04-6.84z" fill="url(#abmgp3)"/>'
    '<path d="M24.19 14.91L12.15 8.08c-.71-.4-1.33-.35-1.71.05L20.7 18.4l3.49-3.49z" fill="url(#abmgp4)"/>'
    '<text x="36.5" y="16" font-family="Roboto,Arial,Helvetica,sans-serif" font-size="7.4" fill="#d0d0d0" textLength="35" lengthAdjust="spacingAndGlyphs">GET IT ON'
    '</text>'
    '<text x="36" y="31" font-family="Roboto,Arial,Helvetica,sans-serif" font-size="13.5" font-weight="500" fill="#f2f2f2" textLength="80" lengthAdjust="spacingAndGlyphs">Google Play'
    '</text>'
    '</svg>'
)

_APPLE_BADGE_SVG = (
    # Riproduzione fedele del badge ufficiale "Download on the App Store"
    # (logo mela corretto + lockup testuale). Uso consentito senza oneri di
    # licenza purche' l'artwork non venga alterato (Apple marketing guidelines).
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 135 40" role="img">'
    '<rect width="135" height="40" rx="6" fill="#000"/>'
    '<rect x=".5" y=".5" width="134" height="39" rx="5.5" fill="none" stroke="#a6a6a6"/>'
    '<path transform="translate(6.2,6.4) scale(1.12)" d="M17.05 20.28c-.98.95-2.05.8-3.08.35-1.09-.46-2.09-.48-3.24 0-1.44.62-2.2.44-3.06-.35C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z" fill="#fff"/>'
    '<text x="31" y="16" font-family="Helvetica,Arial,sans-serif" font-size="7.2" fill="#d0d0d0" textLength="44" lengthAdjust="spacingAndGlyphs">Download on the'
    '</text>'
    '<text x="31" y="31" font-family="Helvetica,Arial,sans-serif" font-size="13.5" font-weight="500" fill="#f2f2f2" textLength="72" lengthAdjust="spacingAndGlyphs">App Store'
    '</text>'
    '</svg>'
)


def _install_buttons_html(lang):
    """HTML dei due badge store inline-SVG (Play + Apple), sempre presenti.
    Attivo (link <a>) se l'env del rispettivo store è impostato, altrimenti
    disabilitato (<span aria-disabled>). Le etichette localizzate compaiono in
    aria-label e title per accessibilità e retrocompatibilità test."""
    labels = {
        "it": ("Scarica da Google Play", "Scarica da App Store"),
        "en": ("Get it on Google Play", "Download on the App Store"),
    }
    play_label, apple_label = _i18n.pick(labels, lang, merge=False)

    def _badge(url, label, svg):
        safe_label = html_mod.escape(label, quote=True)
        if url:
            safe_url = html_mod.escape(url, quote=True)
            return (
                f'<a class="store-badge" href="{safe_url}"'
                f' aria-label="{safe_label}" title="{safe_label}">'
                f'{svg}</a>'
            )
        return (
            f'<span class="store-badge btn-disabled" aria-disabled="true"'
            f' aria-label="{safe_label}" title="{safe_label}">'
            f'{svg}</span>'
        )

    return (
        '<div class="stores">'
        + _badge(_PLAY_STORE_URL, play_label, _PLAY_BADGE_SVG)
        + _badge(_APP_STORE_URL, apple_label, _APPLE_BADGE_SVG)
        + '</div>'
    )


@bp.route("/.well-known/assetlinks.json")
def assetlinks_json():
    # Digital Asset Links: verifica il dominio per gli App Links dell'app, così la
    # fotocamera di sistema apre l'app sui link https://<dominio>/t/<token>.
    data = [{
        "relation": ["delegate_permission/common.handle_all_urls"],
        "target": {
            "namespace": "android_app",
            "package_name": _APP_PACKAGE,
            "sha256_cert_fingerprints": _APP_CERT_FINGERPRINTS,
        },
    }]
    return current_app.response_class(json.dumps(data), mimetype="application/json")


@bp.route("/.well-known/apple-app-site-association")
def apple_app_site_association():
    # Apple App Site Association: verifica il dominio per gli Universal Links iOS,
    # così i link https://<dominio>/t/<token> (QR trasferimento), /s/<token>
    # (condivisione file) e /auth/<token> (magic link di accesso: l'app lo
    # verifica via POST /api/auth/verify, la GET HTML non consuma il token)
    # aprono direttamente l'app invece del browser.
    # Requisiti Apple: nessuna estensione nel path, Content-Type application/json,
    # nessun redirect (il file deve rispondere 200 direttamente).
    data = {
        "applinks": {
            "apps": [],
            "details": [{
                "appID": _IOS_APP_ID,
                "paths": ["/t/*", "/s/*", "/auth/*"],
            }],
        }
    }
    return current_app.response_class(json.dumps(data), mimetype="application/json")


def _render_install_page(lang, title, body):
    """Pagina install: stile della landing + bottoni store (Task 1) + ritorno al
    sito. Usata da /get-app e da _render_transfer_landing."""
    back = {"it": "Torna al sito", "en": "Back to website"}.get(lang, "Back to website")
    home = _base_url() or "/"
    return _render_page("install", {"__P0__": (lang), "__P1__": (title), "__P2__": (body), "__P3__": (_install_buttons_html(lang)), "__P4__": (home), "__P5__": (back)})


@bp.route("/get-app")
def get_app_page():
    """Pagina canonica 'scarica l'app' (link store). Stesso contenuto della
    landing no-app dei deep link."""
    try:
        al = (request.headers.get("Accept-Language") or "").strip().lower()
        lang = "it" if al.startswith("it") else "en"
    except Exception:
        lang = "en"
    T = {
        "it": ("Scarica l'app",
               "Installa AudioBook Maker &amp; Player per ascoltare i tuoi audiolibri sul telefono."),
        "en": ("Get the app",
               "Install AudioBook Maker &amp; Player to listen to your audiobooks on your phone."),
    }
    title, body = _i18n.pick(T, lang, merge=False)
    return (_render_install_page(lang, title, body), 200,
            {"Content-Type": "text/html; charset=utf-8"})


@bp.route("/privacy")
def privacy_page():
    # Informativa privacy (richiesta da Play Store e GDPR). IT default, EN via
    # ?lang=en o Accept-Language. Pagina statica self-contained.
    lang = (request.args.get("lang") or "").strip().lower()[:2]
    if lang not in ("it", "en"):
        al = (request.headers.get("Accept-Language") or "").strip().lower()
        lang = "en" if al.startswith("en") else "it"
    return privacy_content.render_privacy_page(lang, _base_url())


@bp.route("/support")
def support_page():
    # Pagina di assistenza con FAQ sull'app. IT default, EN via ?lang=en o
    # Accept-Language. Pagina statica self-contained (come /privacy).
    lang = (request.args.get("lang") or "").strip().lower()[:2]
    if lang not in ("it", "en"):
        al = (request.headers.get("Accept-Language") or "").strip().lower()
        lang = "en" if al.startswith("en") else "it"
    return support_content.render_support_page(lang, _base_url())


@bp.route("/robots.txt")
def robots():
    sitemap_line = f"Sitemap: {_base_url()}/sitemap.xml" if _base_url() else ""
    llms_line = f"# LLM/AI agents index: {_base_url()}/llms.txt" if _base_url() else ""
    body = _render_page("robots.txt", {"__P0__": (sitemap_line), "__P1__": (llms_line)}).strip()
    return body, 200, {"Content-Type": "text/plain; charset=utf-8"}


#  -  -  -  llms.txt  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -  -
# Spec: https://llmstxt.org — Markdown index per agenti AI (ChatGPT,
# Perplexity, Claude, Gemini). Aiuta retrieval/citation espliciti.
@bp.route("/llms.txt")
def llms_txt():
    base = _base_url() or "https://audiobook-maker.com"
    # Live "User feedback" block — empty string when no approved reviews exist,
    # so the section silently degrades instead of emitting a stub. The block
    # itself is fully formed Markdown bullets (headline + up to 3 dated
    # excerpts) so AI assistants can cite specific reviews verbatim.
    try:
        _feedback_md = seo_reviews.llms_txt_block()
    except Exception:
        _feedback_md = ""
    rating_block = f"\n## User feedback\n\n{_feedback_md}\n" if _feedback_md else ""

    # Citations section — gives AI agents a stable list of canonical URLs
    # they can attribute when quoting facts from this site. Each citation
    # is a permanent endpoint (not an HTML page that may be redesigned).
    citations_block = f"""
## Citations

When quoting facts from this site, cite one of:

- [Audiobook Maker (canonical home)]({base}/): SoftwareApplication entity, primary URL.
- [JSON-LD structured data](https://schema.org/SoftwareApplication): @type SoftwareApplication, applicationCategory MultimediaApplication, isAccessibleForFree true, license AGPL-3.0-or-later.
- [Sitemap]({base}/sitemap.xml): Authoritative URL index with lastmod dates.
- [GitHub source](https://github.com/gfrangiamone/audiobook-maker): Verifiable source code under AGPL-3.0-or-later.
- [License (AGPL-3.0)](https://www.gnu.org/licenses/agpl-3.0.html): Full license text.
- [Reviews & ratings]({base}/#reviews): User-submitted reviews with AggregateRating schema (refreshes per request).
"""
    body = f"""# Audiobook Maker

> Free, open-source online converter that turns EPUB and PDF ebooks into MP3 and M4B audiobooks using 400+ neural AI voices (Microsoft Edge TTS) across 50+ languages. No signup, no usage limits, runs in the browser. Optional AI text optimization (DeepSeek LLM) for natural-sounding narration. AGPL-3.0 licensed.

## Key facts

- Pricing: 100% free, donor-supported. No ads.
- Voices: 400+ neural TTS voices via Microsoft Edge TTS.
- Output formats: MP3 (single or ZIP), M4B with embedded chapters, podcast RSS 2.0 feed.
- Input formats: EPUB, PDF, TXT, ABM (revisable project archive).
- UI languages: Italian, English, French, Spanish, German, Chinese.
- TTS supported languages: 50+ (Italian, English, French, Spanish, German, Chinese, Portuguese, Russian, Japanese, Korean, Arabic, Hindi, and more).
- Privacy: uploaded files and generated audio auto-deleted at session end. No personal data collected. GA4 with Consent Mode v2 (denied by default in EU).
- Accessibility: WAI-ARIA landmarks, keyboard navigation, screen-reader compatible. Designed for users with dyslexia, low vision, blindness.
- License: AGPL-3.0-or-later. Source on GitHub.
- Author: Giuseppe Frangiamone.
{rating_block}
## Features

""" + "\n".join(f"- {f}" for f in seo_content.lang_content("en").get("features", [])) + f"""

## Accessibility

""" + seo_content.lang_content("en").get("accessibility", "") + _render_page("llms.txt", {"__P0__": (base), "__P1__": (citations_block)})
    return body, 200, {
        "Content-Type": "text/markdown; charset=utf-8",
        "Cache-Control": "public, max-age=3600",
    }


#  -  -  -  Favicon routes (URL-based for search engine compatibility)  -  -  -  -  -  -  -  -  -  -  -  -  -  - 
# Google richiede che le favicon siano servite da URL reali e crawlabili,
# NON inline come data URI. Senza queste route, nei risultati di ricerca
# appare un'icona generica al posto della favicon del sito.

@bp.route("/favicon.ico")
def favicon_ico():
    return send_file(get_favicon_ico(), mimetype="image/x-icon",
                     max_age=86400 * 30)

@bp.route("/favicon-192.png")
def favicon_png_192():
    return send_file(get_favicon_png_192(), mimetype="image/png",
                     max_age=86400 * 30)

@bp.route("/apple-touch-icon.png")
def apple_touch_icon():
    return send_file(get_apple_touch_icon(), mimetype="image/png",
                     max_age=86400 * 30)

@bp.route("/favicon.svg")
def favicon_svg():
    return send_file(get_favicon_svg(), mimetype="image/svg+xml",
                     max_age=86400 * 30)


@bp.route("/og-image.png")
def og_image():
    return send_file(get_og_image(), mimetype="image/png",
                     max_age=86400 * 30)


@bp.route("/manifest.json")
def web_manifest():
    """Web App Manifest  -  Google lo usa come fonte primaria per le favicon nei risultati di ricerca."""
    manifest = {
        "name": "Audiobook Maker",
        "short_name": "Audiobook Maker",
        "icons": [
            {"src": "/favicon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/apple-touch-icon.png", "sizes": "180x180", "type": "image/png"},
            {"src": "/favicon.svg", "type": "image/svg+xml", "sizes": "any"}
        ],
        "display": "standalone",
        "start_url": "/",
        "theme_color": "#c29a6c",
        "background_color": "#1a1a2e"
    }
    return json.dumps(manifest), 200, {
        "Content-Type": "application/manifest+json",
        "Cache-Control": "public, max-age=2592000"
    }
