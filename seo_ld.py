"""seo_ld — blocchi JSON-LD delle pagine pubbliche.

Modulo foglia (stdlib + `page_brand`). Prima: FAQPage costruito in tre
posti, HowTo in due, autore/organizzazione/sameAs copiati in tre moduli,
`inLanguage` senza "hi" nella home e solo una pagina escapava `</`.

- `ld_json(obj)`: serializzazione per `<script type="application/ld+json">`
  (UTF-8, `</` escapato: chiuderebbe il tag).
- `faq_ld(pairs)`, `howto_ld(name, description, steps)`: oggetti pronti.
- `AUTHOR`, `ORG_NAME`, `SITE_URL`, `SAME_AS`, `LICENSE`, `IN_LANGUAGES`,
  `publisher(base)`: dati E-E-A-T in un posto solo.
"""
import json

from page_brand import HREFLANG, SITE_LANGS, html_lang

SITE_URL = "https://audiobook-maker.com"
ORG_NAME = "Audiobook Maker"
AUTHOR = {"@type": "Person", "name": "Giuseppe Frangiamone", "url": "https://github.com/gfrangiamone"}
SAME_AS = ["https://github.com/gfrangiamone/audiobook-maker",
           "https://alternativeto.net/software/audiobook-maker/"]
LICENSE = "https://www.gnu.org/licenses/agpl-3.0.html"
IN_LANGUAGES = [HREFLANG[lc] for lc in SITE_LANGS]


def ld_json(obj):
    """JSON per un tag `<script type="application/ld+json">`: niente escape
    ASCII (il testo e' multilingue), `</` escapato perche' chiuderebbe il tag."""
    return json.dumps(obj, ensure_ascii=False).replace("</", "<\\/")


def in_language(lang):
    """Valore `inLanguage` della lingua (BCP 47, 'zh' -> 'zh-Hans')."""
    return html_lang(lang)


def publisher(base=SITE_URL, *, logo_size=None):
    """`Organization` editore; con `logo_size` il logo e' un `ImageObject`
    con dimensioni (Article), altrimenti il solo nome e URL (WebSite)."""
    org = {"@type": "Organization", "name": ORG_NAME, "url": base}
    if logo_size:
        org["logo"] = {"@type": "ImageObject", "url": f"{base}/favicon-192.png",
                       "width": logo_size, "height": logo_size}
    return org


def author_block():
    """Autore (`Person`) come dict nuovo: i chiamanti possono estenderlo."""
    return dict(AUTHOR)


def faq_ld(pairs, *, in_lang=None, date_modified=None):
    """`FAQPage` da coppie (domanda, risposta) gia' in testo semplice."""
    ld = {"@context": "https://schema.org", "@type": "FAQPage"}
    if in_lang:
        ld["inLanguage"] = in_lang
    ld["mainEntity"] = [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}}
        for q, a in pairs]
    if date_modified:
        ld["dateModified"] = date_modified
    return ld


def howto_ld(name, description, steps, *, in_lang=None, before_steps=None, date_modified=None):
    """`HowTo`. `steps`: coppie (nome, testo) -> `HowToStep`, oppure dict
    gia' pronti (passano invariati). `before_steps`: chiavi aggiuntive
    (totalTime, supply, tool...) emesse prima di `step`."""
    ld = {"@context": "https://schema.org", "@type": "HowTo", "name": name, "description": description}
    if in_lang:
        ld["inLanguage"] = in_lang
    ld.update(before_steps or {})
    ld["step"] = [s if isinstance(s, dict) else {"@type": "HowToStep", "name": s[0], "text": s[1]}
                  for s in steps]
    if date_modified:
        ld["dateModified"] = date_modified
    return ld


def breadcrumb_ld(items):
    """`BreadcrumbList` da coppie (nome, url) in ordine."""
    return {"@context": "https://schema.org", "@type": "BreadcrumbList",
            "itemListElement": [{"@type": "ListItem", "position": i, "name": name, "item": url}
                                for i, (name, url) in enumerate(items, 1)]}
