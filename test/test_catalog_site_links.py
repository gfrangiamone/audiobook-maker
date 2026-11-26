"""Link interni al catalogo degli audiolibri gratuiti (06/11/2026): nel footer
della home (in testata stonava, tolto su richiesta) e in quello di guide, FAQ,
contenuti, privacy e supporto, con l'etichetta nella lingua della pagina. Il catalogo cresce di
libri nuovi e sono i link interni a farne scansionare le pagine; le pagine
del catalogo non linkano se stesse nel footer."""
import page_brand

LINK = 'href="/free-audiobooks/it/"'


def _client():
    import audiobook_app
    return audiobook_app.app.test_client()


def test_etichetta_nella_lingua_della_pagina():
    assert page_brand.catalog_link("it") == '<a href="/free-audiobooks/it/">Audiolibri gratis</a>'
    assert page_brand.catalog_link("de") == '<a href="/free-audiobooks/de/">Kostenlose Hörbücher</a>'
    assert page_brand.catalog_label("xx") == "Free audiobooks"         # lingua ignota: inglese


def test_link_alla_lingua_della_pagina_se_il_catalogo_la_ha():
    # Search Console 26/11/2026: «audiolibri gratis» porta su /free-audiobooks/it/,
    # in posizione 11,8: i link interni puntano all'indice della lingua.
    assert page_brand.catalog_href("it") == "/free-audiobooks/it/"
    assert page_brand.catalog_href("fr") == "/free-audiobooks/fr/"
    assert page_brand.catalog_href("zh") == "/free-audiobooks/"     # niente libri cinesi
    assert page_brand.catalog_href("hi") == "/free-audiobooks/"
    import free_catalog
    assert free_catalog.LANGS is page_brand.CATALOG_LANGS


def test_footer_della_home_per_lingua():
    client = _client()
    for lang, href in (("it", "/free-audiobooks/it/"), ("es", "/free-audiobooks/es/"),
                       ("zh", "/free-audiobooks/")):
        body = client.get(f"/{lang}/").get_data(as_text=True)
        assert f'<a href="{href}" data-t="nav_catalog">' in body, lang
        assert "__CATALOG_HREF__" not in body, lang


def test_home_ha_il_link_nel_footer():
    body = _client().get("/it/").get_data(as_text=True)
    assert '<a href="/free-audiobooks/it/" data-t="nav_catalog">Audiolibri gratis</a>' in body
    assert 'class="hdr-cat"' not in body
    assert "__NAV_CATALOG__" not in body


def test_pagine_pubbliche_linkano_il_catalogo():
    client = _client()
    for url in ("/faq/it/", "/content/it/", "/guide/epub-to-audiobook/it/", "/privacy", "/support"):
        r = client.get(url)
        if r.status_code in (301, 302, 308):
            r = client.get(r.headers["Location"])
        body = r.get_data(as_text=True)
        assert LINK in body, url


def test_pagine_del_catalogo_senza_link_a_se_stesse_nel_footer(monkeypatch):
    html = page_brand.public_page(lang="it", title="T", crumb="C", body="", footer="F", catalog=False)
    assert 'class="site-links"' not in html
    html = page_brand.public_page(lang="it", title="T", crumb="C", body="", footer="F")
    assert '<p class="site-links"><a href="/free-audiobooks/it/">Audiolibri gratis</a></p>' in html
