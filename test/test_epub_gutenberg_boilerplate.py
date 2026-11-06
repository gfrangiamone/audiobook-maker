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


def test_documento_senza_licenza_invariato():
    html = "<html><body><p>Testo.</p></body></html>"
    assert E._strip_site_boilerplate(html) is html
