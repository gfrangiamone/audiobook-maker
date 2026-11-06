"""EPUB con piu' voci di indice per file: capitoli divisi sulle ancore del TOC.

Gli EPUB di Project Gutenberg spezzano i file a misura, non a capitolo: un file
comincia col seguito del capitolo precedente e porta due o tre titoli, ognuno
con un id a cui punta la sua voce d'indice. ABM spezzava confrontando i titoli:
le voci corte ("—I—", "VI") non si confrontano e il loro capitolo si fondeva col
precedente, il testo prima del primo titolo di un file andava perso (un quinto
del Grande Gatsby, l'incipit compreso) e il finale di La Regenta finiva in un
capitolo "FIN DE LA NOVELA" (catalogo, 06/11/2026).
"""
from ebooklib import epub

import epub_to_tts as E

_PARA = ("La heroica ciudad dormía la siesta mientras el viento del sur empujaba "
         "las nubes blanquecinas que se rasgaban al correr hacia el norte.")


def _p(tag):
    return f"<p>{tag} {_PARA}</p>" * 4


def _write_epub(path, files, toc):
    """files: {nome: corpo html}; toc: [(nome#ancora, titolo)] nell'ordine."""
    book = epub.EpubBook()
    book.set_identifier("toc-anchors-test")
    book.set_title("La Regenta")
    book.set_language("es")
    items = []
    for name, body in files.items():
        it = epub.EpubHtml(title=name, file_name=f"{name}.xhtml", lang="es")
        it.content = f"<html><body>{body}</body></html>"
        book.add_item(it)
        items.append(it)
    book.toc = [epub.Link(f"{href.replace('#', '.xhtml#', 1)}", title, href.replace("#", "-"))
                for href, title in toc]
    book.spine = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def _gutenberg_like(tmp_path):
    p = tmp_path / "gutenberg.epub"
    files = {
        "h0": ('<h1 id="t0">La Regenta</h1><h3 id="t1">por</h3>'
               '<h2 id="c1">—I—</h2>' + _p("UNO-A")),
        "h1": _p("UNO-B") + '<h2 id="c2">—II—</h2>' + _p("DOS") + '<h2 id="c3">—III—</h2>' + _p("TRES-A"),
        "h2": _p("TRES-B") + '<h3 id="fin">FIN DE LA NOVELA</h3>',
    }
    toc = [("h0#t0", "La Regenta"), ("h0#t1", "por"), ("h0#c1", "—I—"),
           ("h1#c2", "—II—"), ("h1#c3", "—III—"), ("h2#fin", "FIN DE LA NOVELA")]
    _write_epub(p, files, toc)
    return E.parse_epub(str(p))


def test_capitoli_divisi_sulle_ancore_dell_indice(tmp_path):
    info = _gutenberg_like(tmp_path)
    text = {c.title: c.text for c in info.chapters if c.text.strip()}
    assert list(text) == ["—I—", "—II—", "—III—"]
    assert "UNO-A" in text["—I—"] and "UNO-B" in text["—I—"]
    assert "DOS" in text["—II—"] and "UNO-B" not in text["—II—"]
    assert "TRES-A" in text["—III—"] and "TRES-B" in text["—III—"]


def test_nessun_paragrafo_perso_o_ripetuto(tmp_path):
    info = _gutenberg_like(tmp_path)
    full = "\n".join(c.text for c in info.chapters)
    for tag in ("UNO-A", "UNO-B", "DOS", "TRES-A", "TRES-B"):
        assert full.count(tag) == 4, tag
    assert "FIN DE LA NOVELA" not in full


def test_ancora_dentro_il_titolo():
    html = ('<p>seguito del capitolo prima</p><h2><a id="x"></a>—I—</h2><p>primo</p>'
            '<h2 id="y">—II—</h2><p>secondo</p>')
    lead, sections = E._split_html_by_anchors(html, [("—I—", "x"), ("—II—", "y")])
    assert "seguito" in lead
    assert [t for t, _ in sections] == ["—I—", "—II—"]
    assert "primo" in sections[0][1] and "—I—" not in sections[0][1]
    assert "secondo" in sections[1][1] and "primo" not in sections[1][1]


def test_ancore_mancanti_o_fuori_ordine_lasciano_il_confronto_dei_titoli():
    html = '<h2 id="a">Uno</h2><p>uno</p><h2 id="b">Due</h2><p>due</p>'
    assert E._split_html_by_anchors(html, [("Uno", "a"), ("Tre", "c")]) is None
    assert E._split_html_by_anchors(html, [("Due", "b"), ("Uno", "a")]) is None
    assert E._split_html_by_anchors(html, [("Uno", "a"), ("Due", "")]) is None


def test_colophon_di_gutenberg_con_le_sottosezioni_non_si_legge(tmp_path):
    # Don Quichot: dopo l'ultimo capitolo, "Colofon" con figlie Beschikbaarheid,
    # Codering, Verbeteringen nell'indice, e un "Inhoudsopgave".
    p = tmp_path / "colofon.epub"
    book = epub.EpubBook()
    book.set_identifier("colofon-test")
    book.set_title("Don Quichot")
    book.set_language("nl")
    h0 = epub.EpubHtml(title="h0", file_name="h0.xhtml", lang="nl")
    h0.content = '<html><body><h2 id="c1">Hoofdstuk I.</h2>' + _p("EEN") + "</body></html>"
    h1 = epub.EpubHtml(title="h1", file_name="h1.xhtml", lang="nl")
    h1.content = ('<html><body><h2 id="c2">Hoofdstuk II.</h2>' + _p("TWEE")
                  + '<h2 id="toc">Inhoudsopgave</h2><p>Hoofdstuk I. Hoofdstuk II.</p>'
                  + '<h2 id="col">Colofon</h2><h3 id="b">Beschikbaarheid</h3>'
                  + "<p>Dit eBoek is voor kosteloos gebruik door iedereen overal (BESCHIKBAAR).</p>"
                  + '<h3 id="cod">Codering</h3><p>Dit bestand is in een verouderde spelling (CODERING).</p>'
                  + '<h3 id="v">Verbeteringen</h3><p>De volgende verbeteringen (VERBETERD).</p>'
                  + "</body></html>")
    for it in (h0, h1):
        book.add_item(it)
    book.toc = [epub.Link("h0.xhtml#c1", "Hoofdstuk I.", "c1"),
                epub.Link("h1.xhtml#c2", "Hoofdstuk II.", "c2"),
                epub.Link("h1.xhtml#toc", "Inhoudsopgave", "toc"),
                (epub.Link("h1.xhtml#col", "Colofon", "col"),
                 [epub.Link("h1.xhtml#b", "Beschikbaarheid", "b"),
                  epub.Link("h1.xhtml#cod", "Codering", "cod"),
                  epub.Link("h1.xhtml#v", "Verbeteringen", "v")])]
    book.spine = [h0, h1]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(p), book)
    info = E.parse_epub(str(p))
    assert [c.title for c in info.chapters] == ["Hoofdstuk I.", "Hoofdstuk II."]
    full = "\n".join(c.text for c in info.chapters)
    assert full.count("TWEE") == 4
    for tag in ("BESCHIKBAAR", "CODERING", "VERBETERD"):
        assert tag not in full, tag
