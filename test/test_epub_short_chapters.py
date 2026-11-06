"""Capitoli brevi non scartati come frontespizi (catalogo gratuito, 05/11/2026).

In Storia di una capinera (EPUB di Wikisource) le lettere XLIII e XLIV sono
di una riga: `is_content_chapter` le toglieva per lunghezza (< 100 caratteri,
< 30 parole) e il libro usciva senza, nessun avviso.
"""
import zipfile

import epub_to_tts

_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>
<body><h1>{title}</h1>{body}</body></html>"""

_LONG = "<p>" + "Cara Marianna, ti scrivo dalla finestra della mia cella e il mare e' calmo. " * 30 + "</p>"


def _epub(path, sections):
    items = "".join(f'<item id="s{i}" href="s{i}.xhtml" media-type="application/xhtml+xml"/>'
                    for i in range(len(sections)))
    spine = "".join(f'<itemref idref="s{i}"/>' for i in range(len(sections)))
    opf = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>'
           '<dc:title>Prova</dc:title><dc:language>it</dc:language></metadata>'
           f"<manifest>{items}</manifest><spine>{spine}</spine></package>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OPS/content.opf", opf)
        for i, (title, body) in enumerate(sections):
            z.writestr(f"OPS/s{i}.xhtml", _PAGE.format(title=title, body=body))
    return str(path)


def test_lettere_di_una_riga_fra_i_capitoli_restano(tmp_path):
    info = epub_to_tts.parse_epub(_epub(tmp_path / "c.epub", [
        ("Storia di una capinera", "<p>G. Verga</p>"),           # frontespizio: fuori
        ("XLII", _LONG),
        ("XLIII", "<p>13 Settembre.</p><p>Oh! pieta'! pieta'! Non reggo piu'!</p>"),
        ("XLIV", "<p>10 Settembre.</p><p>Dio! fatemi morire!</p>"),
        ("XLV", _LONG),
    ]))
    assert [c.title for c in info.chapters] == ["XLII", "XLIII", "XLIV", "XLV"]
    assert "Non reggo" in info.chapters[1].text and "fatemi morire" in info.chapters[2].text


def test_sezioni_brevi_senza_titolo_da_capitolo_o_prima_del_libro_restano_fuori():
    f = epub_to_tts.is_short_numbered_chapter
    assert f("XLIII\n13 Settembre. Non reggo piu'!", "XLIII", True)
    assert f("Capitolo 12\nE fu notte.", "Capitolo 12", True)
    assert f("IV. Gli altarini\nTesto breve.", "IV. Gli altarini", True)
    assert not f("XLIII\nNon reggo piu'!", "XLIII", False)        # prima del primo capitolo
    assert not f("XLIII", "XLIII", True)                         # solo il titolo
    assert not f("Milano, Treves 1894", "Colophon", True)        # titolo da apparato
    assert not f("Indice\nI II III", "Indice", True)
    assert not f("Ringrazio mia moglie.", "Dedica a mia moglie", True)


def test_numero_di_capitolo_nella_prima_riga_del_testo():
    """ws-export di Memorias Posthumas de Braz Cubas: la voce d'indice e' il
    sottotitolo ("Inutilidade") e il numero apre il testo (06/11/2026)."""
    f = epub_to_tts.is_short_numbered_chapter
    assert f("CAPITULO CXXXVI\nInutilidade\nMas, ou muito me engano, ou acabo de escrever um capitulo inutil.",
             "Inutilidade", True)
    assert f("CAPITULO LV\nO velho dialogo de Adão e Eva\nBRAZ CUBAS . . . . ?", "O velho dialogo de Adão e Eva", True)
    assert not f("CAPITULO CXXXVI", "Inutilidade", True)                 # solo il numero
    assert not f("CAPITULO CXXXVI\nInutilidade\nMas...", "Inutilidade", False)  # prima del libro
    assert not f("AO VERME QUE PRIMEIRO ROEU AS FRIAS CARNES", "Dedicatoria", True)
