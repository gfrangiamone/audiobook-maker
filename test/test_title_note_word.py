""""Note" seguita da un'altra parola e' un titolo vero (catalogo gratuito, 11/11/2026).

In Notre-Dame de Paris (EPUB di Wikisource) la "Note ajoutée à l'édition
définitive (1832)" di Victor Hugo, 1.500 parole dell'autore, spariva dal
libro: la parola "note" scartava qualunque titolo la contenesse.
"""
import zipfile

import book_model
import epub_to_tts

_CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

_PAGE = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>
<body><h1>{title}</h1>{body}</body></html>"""

_PROSE = ("<p>" + "C'est par erreur qu'on a annoncé cette édition comme devant être "
          "augmentée de plusieurs chapitres nouveaux, il fallait dire inédits. " * 20 + "</p>")
_NOTES = "".join(f"<p>{n}. Voir l'édition de 1831, page {n * 7}.</p>" for n in range(1, 30))


def _epub(path, sections):
    items = "".join(f'<item id="s{i}" href="s{i}.xhtml" media-type="application/xhtml+xml"/>'
                    for i in range(len(sections)))
    spine = "".join(f'<itemref idref="s{i}"/>' for i in range(len(sections)))
    opf = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:identifier id="id">x</dc:identifier>'
           '<dc:title>Prova</dc:title><dc:language>fr</dc:language></metadata>'
           f"<manifest>{items}</manifest><spine>{spine}</spine></package>")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OPS/content.opf", opf)
        for i, (title, body) in enumerate(sections):
            z.writestr(f"OPS/s{i}.xhtml", _PAGE.format(title=title, body=body))
    return str(path)


def test_note_seguita_da_una_parola_e_un_titolo_vero():
    for t in ("Note ajoutée à l'édition définitive (1832)", "Notes from Underground",
              "Notebook", "Una scoperta notevole"):
        assert not book_model.title_is_non_content(t), t


def test_note_da_apparato_restano_fuori():
    for t in ("Note", "NOTES.", "Notes de cette édition", "Note al testo", "A Note on the Text",
              "Translator's note", "Note finali", "Notes explicatives", "Notes 1-20",
              "Note dell'autore", "Notes and References", "Notes:", "Capitolo 3 — Note",
              "Mix: note", "Note legali"):
        assert book_model.title_is_non_content(t), t


def test_nota_di_hugo_resta_nel_libro(tmp_path):
    info = epub_to_tts.parse_epub(_epub(tmp_path / "n.epub", [
        ("Préface", _PROSE),
        ("Note ajoutée à l'édition définitive (1832)", _PROSE),
        ("Livre premier", _PROSE),
        ("Notes", _NOTES),
    ]))
    assert [c.title for c in info.chapters] == [
        "Préface", "Note ajoutée à l'édition définitive (1832)", "Livre premier"]
