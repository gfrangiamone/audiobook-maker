"""Guida «da PDF ad audiolibro»: le versioni it ed es erano «scansionate ma non
indicizzate» (Search Console, 16/11/2026) mentre le altre lingue lo erano.
Arricchite con risposta immediata, controlli prima del caricamento, confronto
con la lettura ad alta voce, durata per pagina, OCR passo per passo e FAQ."""
import re

import pytest

import audiobook_app as app
import content_store
import guide_content

GID = "pdf-to-audiobook"
RICHE = {"it": ("In breve", "Testo normale (.txt)"), "es": ("En resumen", "Texto sin formato (.txt)")}


@pytest.mark.parametrize("lang", sorted(RICHE))
def test_versione_arricchita(lang):
    body = content_store.content_text("guides", GID, f"{lang}.html")
    answer, txt_menu = RICHE[lang]
    assert body.count("<h2>") == 11, lang
    assert body.count("<details>") == 10, lang
    assert body.count("<section>") == body.count("</section>") == 11
    assert body.count('<div class="tablewrap"><table>') == 1      # niente tabelle che sforano a 375 px
    assert f"<strong>{answer}:</strong>" in body
    assert "50 MB" in body and "OCRmyPDF" in body and txt_menu in body
    assert f'href="/{lang}/"' in body


@pytest.mark.parametrize("lang", sorted(RICHE))
def test_link_interni_della_guida_rispondono(lang):
    app.app.config["TESTING"] = True
    c = app.app.test_client()
    body = content_store.content_text("guides", GID, f"{lang}.html")
    links = set(re.findall(r'href="(/[^"]*)"', body))
    assert links
    for href in links:
        assert c.get(href).status_code == 200, href


@pytest.mark.parametrize("lang", sorted(RICHE))
def test_pagina_servita_con_data_della_sitemap(lang):
    html = guide_content.build_guide_html(GID, lang, base_url="https://x.test")
    lastmod = guide_content.guide_lastmod(GID, lang)
    assert "Guide content not available" not in html
    assert f'"dateModified": "{lastmod}"' in html
    assert "OCRmyPDF" in html
