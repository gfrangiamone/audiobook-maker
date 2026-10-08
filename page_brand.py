# page_brand.py
"""Marchio condiviso dalle pagine server-side fuori dalla SPA (gestione voci
campionate, area personale): il logo SVG, la tavolozza e, per le pagine
pubbliche, le mappe lingua -> hreflang / og:locale con i relativi tag
(`hreflang_links`, `og_locale_tags`). Modulo foglia (stdlib + `i18n`):
lo importano `audiobook_app`, `account_page`, `guide_content`,
`templates/index_page`, che non possono importare l'entry point.
"""
from pathlib import Path

from i18n import LANGS as SITE_LANGS

# Pagine servite da file: templates/pages/<name>.html (o <name> se ha gia'
# un'estensione), lette una volta. `render_page` sostituisce i segnaposto
# alla lettera, nell'ordine dato: nessuna interpretazione di graffe o `%`.
PAGES_DIR = Path(__file__).resolve().parent / "templates" / "pages"
_page_cache: dict = {}


def page_template(name):
    html = _page_cache.get(name)
    if html is None:
        path = PAGES_DIR / (name if "." in name else f"{name}.html")
        html = path.read_text(encoding="utf-8")
        _page_cache[name] = html
    return html


def render_page(name, values):
    html = page_template(name)
    for key, value in values.items():
        html = html.replace(key, str(value))
    return html

# Lingua dell'interfaccia -> codice hreflang / attributo lang (BCP 47) e
# locale Open Graph. L'ordine e' quello di SITE_LANGS: e' anche l'ordine
# dei tag emessi in pagina e nella sitemap.
HREFLANG = {"it": "it", "en": "en", "fr": "fr", "es": "es", "de": "de", "zh": "zh-Hans", "hi": "hi"}
OG_LOCALE = {"it": "it_IT", "en": "en_US", "fr": "fr_FR", "es": "es_ES", "de": "de_DE",
             "zh": "zh_CN", "hi": "hi_IN"}
assert tuple(HREFLANG) == SITE_LANGS and tuple(OG_LOCALE) == SITE_LANGS


def html_lang(lang):
    """Valore di `<html lang>` / `inLanguage` per la lingua ('zh' -> 'zh-Hans')."""
    return HREFLANG.get(lang, "en")


def hreflang_links(path_fn, x_default, *, sep="\n", xhtml=False):
    """Tag `<link rel="alternate" hreflang=...>` per tutte le lingue piu'
    x-default. `path_fn(lang)` da' l'URL (assoluto o relativo) della lingua,
    `x_default` quello di x-default. `xhtml=True` emette le righe
    `<xhtml:link .../>` indentate della sitemap."""
    if xhtml:
        fmt = '      <xhtml:link rel="alternate" hreflang="{hl}" href="{href}"/>'
    else:
        fmt = '<link rel="alternate" hreflang="{hl}" href="{href}">'
    lines = [fmt.format(hl=hl, href=path_fn(lc)) for lc, hl in HREFLANG.items()]
    lines.append(fmt.format(hl="x-default", href=x_default))
    return sep.join(lines)


def og_locale_tags(lang, *, sep="\n"):
    """(og:locale della lingua, blocco dei `<meta property="og:locale:alternate">`
    per tutte le altre lingue)."""
    current = OG_LOCALE.get(lang, "en_US")
    alt = sep.join(f'<meta property="og:locale:alternate" content="{loc}">'
                   for loc in OG_LOCALE.values() if loc != current)
    return current, alt


LOGO_SVG = (
    '<svg viewBox="0 0 64 64" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
    '<rect width="64" height="64" rx="14" fill="#c29a6c"/>'
    '<path d="M16 44V20c0-2 1.5-3.5 3.5-3.5C23 16.5 28 17 32 19c4-2 9-2.5 12.5-2.5 2 0 3.5 1.5 3.5 3.5v24"'
    ' fill="none" stroke="white" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>'
    '<path d="M32 19v25" stroke="white" stroke-width="2" stroke-linecap="round"/>'
    '<path d="M17 36c0-9 6.7-15 15-15s15 6 15 15" fill="none" stroke="white" stroke-width="2.8" stroke-linecap="round"/>'
    '<rect x="13" y="34" width="7" height="10" rx="3" fill="white"/>'
    '<rect x="44" y="34" width="7" height="10" rx="3" fill="white"/>'
    '<path d="M22 37.5c1.2-1 1.2-3 0-4" fill="none" stroke="#c29a6c" stroke-width="1.3" stroke-linecap="round"/>'
    '<path d="M42 37.5c-1.2-1-1.2-3 0-4" fill="none" stroke="#c29a6c" stroke-width="1.3" stroke-linecap="round"/></svg>')

# Tavolozza e controlli della SPA (static/css/style.css): chi apre queste
# pagine dall'app deve ritrovare gli stessi bottoni e lo stesso tema.
# Le variabili portano gli stessi nomi del foglio della SPA.
# «X» di chiusura/ritorno per la testata delle pagine (aria-label lo dice il chiamante).
CLOSE_SVG = (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" '
    'stroke-linecap="round" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>'
)


def brand_bar(logo_svg, brand_text, href="/", tools_html=""):
    """Riga del marchio: logo+nome a sinistra e, se ci sono, gli strumenti
    (X di chiusura, ritorno) a destra, allineati al logo. `brand_text` e
    `tools_html` gia' escapati dal chiamante."""
    brand = f'<a class="brand" href="{href}">{logo_svg}<span>{brand_text}</span></a>'
    if not tools_html:
        return brand
    return f'<div class="brandbar">{brand}<div class="tools">{tools_html}</div></div>'

BASE_CSS = (
    ":root{--bg:#f5f3ef;--srf:#fff;--srf2:#f0ede8;--brd:#d5d0c8;--brdh:#bfb8ae;"
    "--tx:#2c2a26;--txd:#6b6760;--txm:#767676;--ac:#c47a2a;--acs:rgba(196,122,42,.10);--ach:#d4903e;"
    "--ok:#3a9e5c;--oks:rgba(58,158,92,.10);--err:#c44040;--errs:rgba(196,64,64,.08);"
    "--info:#2c4a8a;--infos:#eef3ff;--rs:8px}"
    "[data-theme=dark]{--bg:#0e0e11;--srf:#18181d;--srf2:#222228;--brd:#333340;--brdh:#4a4a5a;"
    "--tx:#e8e8ed;--txd:#9090a0;--txm:#7a7a8a;--ac:#f0a050;--acs:rgba(240,160,80,.12);--ach:#f5b570;"
    "--ok:#50c878;--oks:rgba(80,200,120,.12);--err:#e05555;--errs:rgba(224,85,85,.12);"
    "--info:#9db4ea;--infos:rgba(120,150,230,.16)}"
    "body{font-family:'DM Sans',system-ui,sans-serif;margin:3em auto;padding:0 1em;"
    "color:var(--tx);background:var(--bg);line-height:1.5}"
    "[hidden]{display:none!important}"
    "button,a.btn{font:inherit;font-weight:600;padding:.5em 1.1em;border:1px solid var(--brd);"
    "border-radius:var(--rs);background:var(--srf);color:var(--ac);cursor:pointer;text-decoration:none;"
    "display:inline-block;transition:all .2s}"
    "button:hover,a.btn:hover{background:var(--acs);border-color:var(--ac)}"
    "button:focus-visible,a.btn:focus-visible{outline:2px solid var(--ac);outline-offset:2px}"
    "button.primary{background:var(--ac);border-color:var(--ac);color:#fff}"
    "button.primary:hover{background:var(--ach);border-color:var(--ach)}"
    "button.danger,a.btn.danger{color:var(--err)}"
    "button.danger:hover,a.btn.danger:hover{background:var(--errs);border-color:var(--err)}"
    "button:disabled{opacity:.55;cursor:default}"
    ".card{border:1px solid var(--brd);border-radius:12px;padding:1em 1.2em;margin:1.2em 0 2em;"
    "background:var(--srf)}.card h2{margin:0 0 .3em;font-size:1.2em}"
    ".card p{margin:.2em 0 1em;color:var(--txd)}"
    ".meta{color:var(--txd);font-size:.9em}"
    ".actions{display:flex;gap:.6em;flex-wrap:wrap;align-items:center;margin-top:1.5em}"
    ".actions .end{margin-left:auto}"
    ".brandbar{display:flex;align-items:center;justify-content:space-between;gap:1em;margin-bottom:1.8em}"
    ".brandbar .brand{margin-bottom:0}"
    ".brandbar .tools{display:flex;align-items:center;gap:.5em}"
    ".icon-x{padding:.35em;line-height:0;color:var(--txd)}.icon-x:hover{color:var(--tx)}"
    ".icon-x svg{width:18px;height:18px;display:block}"
    ".me{font-size:.8em;background:var(--infos);color:var(--info);border-radius:1em;padding:.1em .6em;"
    "margin-left:.4em;white-space:nowrap}"
    ".brand{display:flex;align-items:center;gap:.6em;margin-bottom:1.8em;color:inherit;text-decoration:none}"
    ".brand svg{width:42px;height:42px;flex:none}"
    ".brand span{font-size:1.1em;font-weight:600}"
)

# Va nel <head> PRIMA del foglio di stile: applica il tema scelto nella SPA
# (stessa chiave localStorage `abm_th` di applyTheme in static/js/app.js)
# senza lampo di pagina chiara. Senza scelta salvata vale il tema di sistema.
THEME_SCRIPT = (
    "<script>(function(){var t=null;try{t=localStorage.getItem('abm_th')}catch(e){}"
    "if(!t&&window.matchMedia&&window.matchMedia('(prefers-color-scheme:dark)').matches)t='dark';"
    "if(t==='dark')document.documentElement.setAttribute('data-theme','dark');})();</script>"
)



def seo_head(*, desc="", keywords="", canonical="", hreflang="", og_type="", og_title="",
             og_desc="", og_url="", og_image="", lang=None, twitter=False, ld=()):
    """Righe del <head> di una pagina pubblica: description, keywords,
    canonical, blocco hreflang, Open Graph (con og:locale e alternates se
    `lang`), Twitter card, blocchi JSON-LD gia' serializzati (`seo_ld.ld_json`).
    Valori gia' escapati dal chiamante."""
    lines = []
    if desc:
        lines.append(f'<meta name="description" content="{desc}">')
    if keywords:
        lines.append(f'<meta name="keywords" content="{keywords}">')
    if canonical:
        lines.append(f'<link rel="canonical" href="{canonical}">')
    if hreflang:
        lines.append(hreflang)
    if og_type:
        lines += [f'<meta property="og:type" content="{og_type}">',
                  f'<meta property="og:title" content="{og_title}">',
                  f'<meta property="og:description" content="{og_desc}">',
                  '<meta property="og:site_name" content="Audiobook Maker">',
                  f'<meta property="og:url" content="{og_url}">']
        if og_image:
            lines += [f'<meta property="og:image" content="{og_image}">',
                      '<meta property="og:image:width" content="1200">',
                      '<meta property="og:image:height" content="630">']
        if lang:
            cur, alt = og_locale_tags(lang)
            lines += [f'<meta property="og:locale" content="{cur}">', alt]
    if twitter:
        lines += ['<meta name="twitter:card" content="summary_large_image">',
                  f'<meta name="twitter:title" content="{og_title}">',
                  f'<meta name="twitter:description" content="{og_desc}">',
                  f'<meta name="twitter:image" content="{og_image}">']
    lines += [f'<script type="application/ld+json">{block}</script>' for block in ld]
    return "\n".join(lines)


def public_page(*, lang, title, crumb, body, footer, home="/", head="", css=""):
    """Pagina pubblica (guide, privacy, supporto) sulla shell unica
    templates/pages/public_shell.html: head SEO da `seo_head`, breadcrumb
    «Audiobook Maker › crumb», corpo, footer, CSS aggiuntivo della pagina.
    `title`, `crumb`, `body`, `footer` sono HTML gia' pronto."""
    return render_page("public_shell", {
        "__LANG__": html_lang(lang), "__TITLE__": title, "__HEAD__": head, "__CSS__": css,
        "__HOME__": home, "__CRUMB__": crumb, "__BODY__": body, "__FOOTER__": footer,
    })
