"""EPUB di Project Gutenberg: intestazione e licenza (div.pg-boilerplate) non si
leggono. Finivano nel primo capitolo e come ultimo capitolo da 17 mila
caratteri ("THE FULL PROJECT GUTENBERG LICENSE"), catalogo gratuito 06/11/2026."""
from ebooklib import epub

import epub_to_tts as E

_PARA = "It is a truth universally acknowledged, that a single man in possession of a good fortune must be in want of a wife."
HEADER = ('<div class="pg-boilerplate pgheader header" id="pg-header"><h2 id="pg-header-heading">'
          'The Project Gutenberg eBook of Libro</h2><p>This eBook is for the use of anyone anywhere.</p>'
          '<div id="pg-start-separator">*** START OF THE PROJECT GUTENBERG EBOOK LIBRO ***</div></div>')
FOOTER = ('<div class="pg-boilerplate pgheader footer" id="pg-footer">'
          '<div id="pg-end-separator">*** END OF THE PROJECT GUTENBERG EBOOK LIBRO ***</div>'
          '<h2 id="pg-footer-heading">THE FULL PROJECT GUTENBERG LICENSE</h2>'
          + "<p>To protect the Project Gutenberg mission of promoting the free distribution.</p>" * 30 + "</div>")


def _write(path):
    book = epub.EpubBook()
    book.set_identifier("pg-test")
    book.set_title("Libro")
    book.set_language("en")
    docs = []
    for n, (title, before, after) in enumerate([("Chapter I", HEADER, ""), ("Chapter II", "", FOOTER)], 1):
        it = epub.EpubHtml(title=title, file_name=f"c{n}.xhtml", lang="en")
        it.content = (f"<html><body>{before}<h2>{title}</h2>"
                      + f"<p>{_PARA}</p>" * 8 + f"{after}</body></html>")
        book.add_item(it)
        docs.append(it)
    book.toc = docs
    book.spine = docs
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def test_licenza_e_intestazione_di_gutenberg_non_si_leggono(tmp_path):
    p = tmp_path / "pg.epub"
    _write(p)
    info = E.parse_epub(str(p))
    assert [c.title for c in info.chapters] == ["Chapter I", "Chapter II"]
    text = " ".join(c.text for c in info.chapters)
    assert "Gutenberg" not in text and "START OF" not in text
    assert "universally acknowledged" in text


def test_voce_d_indice_della_licenza_non_ruba_il_titolo_all_ultimo_capitolo(tmp_path):
    p = tmp_path / "pg2.epub"
    book = epub.EpubBook()
    book.set_identifier("pg-test-2")
    book.set_title("Libro")
    book.set_language("en")
    first = epub.EpubHtml(title="Chapter I", file_name="c1.xhtml", lang="en")
    first.content = "<html><body><h2>Chapter I</h2>" + f"<p>{_PARA}</p>" * 8 + "</body></html>"
    last = epub.EpubHtml(title="Chapter II", file_name="c2.xhtml", lang="en")
    last.content = ("<html><body><h2 id='c2'>Chapter II</h2>" + f"<p>{_PARA}</p>" * 8 + FOOTER
                    + "</body></html>")
    for it in (first, last):
        book.add_item(it)
    # Come in ws-export di Gutenberg: la licenza ha una voce d'indice nello stesso file.
    book.toc = [first, epub.Link("c2.xhtml#c2", "Chapter II", "c2"),
                epub.Link("c2.xhtml#pg-footer-heading", "THE FULL PROJECT GUTENBERG™ LICENSE", "lic")]
    book.spine = [first, last]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(p), book)
    titles = [c.title for c in E.parse_epub(str(p)).chapters]
    assert titles == ["Chapter I", "Chapter II"]


def test_riga_di_chiusura_dei_vecchi_testi_di_gutenberg_non_si_legge():
    # Amor de Perdição (catalogo, 08/11/2026): letta in inglese in coda al libro.
    html = ("<html><body><p>Vá para casa, que o mais desgraçado é elle.</p>"
            '<p style="margin-top: 5em">End of Project Gutenberg\'s Amor de Perdição, by Camillo Castello Branco</p>'
            + FOOTER + "<p>Em Project Gutenberg ha outros livros.</p></body></html>")
    text = E.html_to_text(E._strip_site_boilerplate(html))
    assert "desgraçado" in text and "End of" not in text and "outros livros" in text


def test_segnaposto_delle_illustrazioni_di_ebookmaker_non_si_leggono():
    # Die Judenbuche (catalogo, 08/11/2026): 28 "Abbildung: ..." lette.
    html = ('<html><body><p>Er war ein ordentlicher Mann.</p>'
            '<p class="center"><span id="img_images_p53.jpg">Abbildung: Hochzeitsfeier</span></p>'
            '<p>Allgemeiner Aufruhr.</p><p><span id="intro">Ein Satz.</span></p></body></html>')
    text = E.html_to_text(html)
    assert "Abbildung" not in text and "Aufruhr" in text and "Ein Satz" in text


_NOVELLA = "„Vierundzwanzig braune Sklaven ruderten die prächtige Galeere“, las die Kleine. " * 4


def test_frontespizio_con_copyright_in_testa_al_libro_non_si_legge():
    # Traumnovelle (catalogo, 08/11/2026): letti editore e "Alle Rechte vorbehalten".
    text = ("TRAUMNOVELLE\n\nVON\n\nARTHUR SCHNITZLER\n\nS. FISCHER VERLAG / BERLIN 1926\n\n"
            "TITELBILD VON HANS MEID / IN HOLZ\n\n"
            "1. bis 25. Auflage / Alle Rechte vorbehalten\n\n" + _NOVELLA)
    assert E._strip_leading_imprint(text) == _NOVELLA


def test_un_solo_segno_di_frontespizio_non_basta():
    text = "Der Verlag hatte geschrieben.\n\n" + _NOVELLA
    assert E._strip_leading_imprint(text) == text


def test_frontespizio_senza_testo_dopo_resta_alle_regole_sui_capitoli():
    text = "S. FISCHER VERLAG\n\nAlle Rechte vorbehalten\n\nTRAUMNOVELLE"
    assert E._strip_leading_imprint(text) == text


def test_documento_senza_licenza_invariato():
    html = "<html><body><p>Testo.</p></body></html>"
    assert E._strip_site_boilerplate(html) is html
