"""Pagine /content/<lang>/: una lingua per URL, FAQ solo su /faq/<lang>/,
hreflang come la sitemap e link dalla home della stessa lingua.

Prima ogni /content/<lang>/ conteneva il testo di tutte e 7 le lingue (6
nascoste) e le FAQ intere: Google vedeva 7 URL quasi identici e la FAQ hindi
su 8 URL, e lasciava fuori /content/hi/ e /faq/hi/ ("Scansionata, ma
attualmente non indicizzata").
"""
from html import escape
from pathlib import Path

import page_brand
import seo_content

LANGS = page_brand.SITE_LANGS


def _client():
    import audiobook_app
    return audiobook_app.app.test_client()


def test_content_page_una_sola_lingua():
    client = _client()
    for lang in LANGS:
        body = client.get(f"/content/{lang}/").get_data(as_text=True)
        assert escape(seo_content.lang_content(lang)["text"]) in body, lang
        for other in LANGS:
            if other != lang:
                assert escape(seo_content.lang_content(other)["text"]) not in body, (lang, other)
        assert body.count("data-seo-lang=") == 1 and "switchSeoLang" not in body


def test_content_page_rimanda_alle_faq_senza_copiarle():
    client = _client()
    for lang in LANGS:
        body = client.get(f"/content/{lang}/").get_data(as_text=True)
        assert f'href="/faq/{lang}/"' in body, lang
        for q, _a in seo_content.lang_content(lang)["faqs"]:
            assert escape(q) not in body, (lang, q)


def test_content_page_hreflang_come_sitemap():
    client = _client()
    body = client.get("/content/hi/").get_data(as_text=True)
    for lang, hl in page_brand.HREFLANG.items():
        assert f'hreflang="{hl}" href="' in body and f'/content/{lang}/">' in body
    assert 'hreflang="x-default"' in body
    assert body.count('rel="alternate" hreflang=') == len(LANGS) + 1


def test_faq_jsonld_della_home_invariato():
    # Le FAQ escono dal corpo di /content/, non dal JSON-LD della home.
    faq_ld, _howto, _app = seo_content.get_schema_ld("hi")
    q0 = seo_content.lang_content("hi")["faqs"][0][0]
    assert '"FAQPage"' in faq_ld and q0 in faq_ld


def test_home_linka_la_pagina_content_della_sua_lingua():
    head = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
    assert 'href="/content/__LANG_CODE__/"' in head and 'data-t="guide_overview"' in head
    i18n = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    assert i18n.count("guide_overview:") == len(LANGS)
    client = _client()
    for lang in LANGS:
        assert f'href="/content/{lang}/"' in client.get(f"/{lang}/").get_data(as_text=True), lang
