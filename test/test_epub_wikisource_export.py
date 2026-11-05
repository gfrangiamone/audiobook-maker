"""EPUB esportati da Wikisource (ws-export): pagina dei crediti e logo.

Ogni ebook di ws-export aggiunge `about.xhtml` ("Informazioni su questa
edizione elettronica", <title>MediaWiki:Wsexport_about</title>) e porta come
unica immagine il logo di Wikisource: la prima veniva letta come ultimo
capitolo, il secondo finiva copertina del libro (catalogo gratuito, 05/11/2026).
"""
import os
import zipfile

import cover_utils
import epub_to_tts

_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

_OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
<dc:identifier id="id">x</dc:identifier><dc:title>Prova</dc:title><dc:language>it</dc:language>
<meta name="cover" content="title" />
</metadata>
<manifest>
<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
<item id="about" href="about.xhtml" media-type="application/xhtml+xml"/>
<item id="logo" href="images/Wikisource-logo.svg.png" media-type="image/png"/>
</manifest>
<spine><itemref idref="c1"/><itemref idref="about"/></spine>
</package>"""

_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>
<body><h1>{h1}</h1><p>{text}</p></body></html>"""


def _epub(path, extra_images=()):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OPS/content.opf", _OPF)
        z.writestr("OPS/c1.xhtml", _PAGE.format(
            title="I. Primo", h1="I. Primo",
            text="Era una sera d'autunno e la nebbia saliva lenta dal fiume. " * 40))
        z.writestr("OPS/about.xhtml", _PAGE.format(
            title="MediaWiki:Wsexport_about", h1="Informazioni",
            text="Informazioni su questa edizione elettronica: questo ebook proviene "
                 "da Wikisource in lingua italiana. " * 10))
        z.writestr("OPS/images/Wikisource-logo.svg.png", b"\x89PNG" + b"\x00" * 11000)
        for name, size in extra_images:
            z.writestr(name, b"\xff\xd8" + b"\x00" * size)
    return str(path)


def test_la_pagina_dei_crediti_di_ws_export_non_e_un_capitolo(tmp_path):
    info = epub_to_tts.parse_epub(_epub(tmp_path / "ws.epub"))
    assert [c.title for c in info.chapters] == ["I. Primo"]


def test_il_logo_non_diventa_copertina(tmp_path):
    with zipfile.ZipFile(_epub(tmp_path / "ws.epub")) as z:
        assert cover_utils._largest_epub_image(z) is None


def test_un_immagine_vera_resta_il_ripiego(tmp_path):
    path = _epub(tmp_path / "ws.epub", extra_images=[("OPS/images/tavola.jpg", 9000)])
    with zipfile.ZipFile(path) as z:
        assert cover_utils._largest_epub_image(z) == "OPS/images/tavola.jpg"
    assert os.path.exists(path)
