"""Note con il ritorno al testo (Liber Liber): il rimando in <sup> e la nota in
coda al capitolo che rimanda indietro con "[Torna]". ABM toglieva il rimando
ma leggeva la nota: "nota 1 – dei titoli nobiliari. [Torna]" in Dorian Gray e
la nota redazionale in coda all'introduzione dell'Idiota, il cui titolo
d'indice era "Introduzionenota" (catalogo, 13/11/2026)."""
from ebooklib import epub

import epub_to_tts as E

_PROSA = ("Il principe scese le scale del palazzo senza voltarsi, mentre la servitu' "
          "raccolta nel cortile commentava a bassa voce la lettura del testamento.")


def test_nota_con_ritorno_in_un_blocco_a_parte():
    html = ("<html><body><h1>CAPITOLO XVIII.</h1>"
            "<p>— Sono stanca di foglie di fragola<sup><a href=\"../Text/S24.xhtml#nota_1\" "
            "id=\"nota_1_ritorno\">nota&#160;1</a></sup>.</p><p>Egli sapeva di esser salvo.</p>"
            "<hr/><div class=\"testo_nota\"><p id=\"nota_1\">nota 1 – dei titoli nobiliari.</p>"
            "<p class=\"testo_nota_torna\"><a href=\"../Text/S24.xhtml#nota_1_ritorno\">[Torna]</a></p>"
            "</div></body></html>")
    text = E.html_to_text(html)
    assert "foglie di fragola." in text and "Egli sapeva di esser salvo." in text
    assert "nota" not in text and "Torna" not in text and "titoli nobiliari" not in text


def test_nota_con_ritorno_dentro_la_nota():
    html = ("<html><body><h1>Introduzione<sup class=\"testo_piccolo\"><a id=\"nota_ritorno\" "
            "href=\"#nota\">nota</a></sup></h1><p>Quattro grandi romanzi.</p>"
            "<p class=\"testo_destra\">N. Moscardelli</p><hr/>"
            "<p id=\"nota\">nota - [La presente introduzione è tratta da: L’idiota. "
            "Nota della red. di Liber Liber] [<a href=\"#nota_ritorno\">Torna</a>]</p></body></html>")
    text = E.html_to_text(html)
    assert "Quattro grandi romanzi." in text and "N. Moscardelli" in text
    assert "Liber Liber" not in text and "Torna" not in text


def test_rimando_numerico_fuori_dagli_apici_e_ancora_vuota():
    html = ("<html><body><p>Il testo<a id=\"r1\" href=\"#n1\">[1]</a> continua.</p>"
            "<p><a id=\"n1\"></a>1. Spiegazione della nota. <a href=\"#r1\">↩</a></p></body></html>")
    text = E.html_to_text(html)
    assert "Il testo continua." in text
    assert "[1]" not in text and "Spiegazione" not in text


def test_link_che_non_sono_note_restano():
    # Indice con i titoli che tornano all'indice: il rimando non e' una nota,
    # il titolo del capitolo resta (la voce d'indice la toglievano gia' altre regole).
    toc = ("<html><body><p><a id=\"toc1\" href=\"#ch1\">Il viaggio</a></p>"
           "<h2 id=\"ch1\"><a href=\"#toc1\">Il viaggio</a></h2><p>Partirono all'alba.</p></body></html>")
    text = E.html_to_text(toc)
    assert "Il viaggio" in text and "Partirono all'alba." in text
    # Rimando senza ritorno: la "nota" puo' essere un paragrafo qualunque.
    oneway = ("<html><body><p>Vedi<sup><a id=\"r2\" href=\"#p2\">2</a></sup> sotto.</p>"
              "<p id=\"p2\">Un paragrafo del racconto.</p></body></html>")
    assert "Un paragrafo del racconto." in E.html_to_text(oneway)
    # La nota che contiene il proprio rimando non si toglie.
    selfref = ("<html><body><p id=\"p3\">Testo<sup><a id=\"r3\" href=\"#p3\">3</a></sup> "
               "e ritorno <a href=\"#r3\">qui</a>.</p></body></html>")
    assert "Testo" in E.html_to_text(selfref)


def test_titolo_d_indice_senza_rimando_dell_heading():
    html = ("<html><body><h1>Introduzione<sup><a id=\"nota_ritorno\" href=\"#nota\">nota</a></sup></h1>"
            "<p>Testo.</p></body></html>")
    assert E._strip_heading_note_ref("Introduzionenota", html) == "Introduzione"
    assert E._strip_heading_note_ref("Introduzione nota", html) == "Introduzione"
    ignota = "<html><body><h1>Terra ignota</h1><p>Testo<sup>1</sup>.</p></body></html>"
    assert E._strip_heading_note_ref("Terra ignota", ignota) == "Terra ignota"
    altro = ("<html><body><h1>Capitolo<sup><a href=\"#n\">nota</a></sup></h1></body></html>")
    assert E._strip_heading_note_ref("Prefazionenota", altro) == "Prefazionenota"
    ordinale = "<html><body><h1>Chapitre 1<sup>er</sup></h1><p>Texte.</p></body></html>"
    assert E._strip_heading_note_ref("Chapitre 1er", ordinale) == "Chapitre 1er"
    entrambi = ("<html><body><h1>Chapitre 1<sup>er</sup><sup><a href=\"#n1\">1</a></sup></h1></body></html>")
    assert E._strip_heading_note_ref("Chapitre 1er1", entrambi) == "Chapitre 1er"
    assert E._strip_heading_note_ref(None, html) is None
    assert E._strip_heading_note_ref("Titolo", "<html><body><h1>Titolo</h1></body></html>") == "Titolo"


def test_epub_di_liber_liber(tmp_path):
    book = epub.EpubBook()
    book.set_identifier("ll-note-test")
    book.set_title("Note")
    book.set_language("it")
    intro = epub.EpubHtml(title="Introduzionenota", file_name="intro.xhtml", lang="it")
    intro.content = ("<html><body><h1>Introduzione<sup><a id=\"nota_ritorno\" href=\"#nota\">nota</a></sup></h1>"
                     + f"<p>{_PROSA}</p>" * 6
                     + "<p id=\"nota\">nota - [Nota della red. di Liber Liber] "
                       "[<a href=\"#nota_ritorno\">Torna</a>]</p></body></html>")
    cap = epub.EpubHtml(title="Capitolo I.", file_name="c1.xhtml", lang="it")
    cap.content = (f"<html><body><h1>Capitolo I.</h1><p>{_PROSA}<sup><a href=\"c1.xhtml#nota_1\" "
                   "id=\"nota_1_ritorno\">nota 1</a></sup></p>" + f"<p>{_PROSA}</p>" * 6
                   + "<div class=\"testo_nota\"><p id=\"nota_1\">nota 1 – dei titoli nobiliari.</p>"
                     "<p><a href=\"c1.xhtml#nota_1_ritorno\">[Torna]</a></p></div></body></html>")
    for it in (intro, cap):
        book.add_item(it)
    book.toc = [intro, cap]
    book.spine = [intro, cap]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    p = tmp_path / "ll.epub"
    epub.write_epub(str(p), book)
    info = E.parse_epub(str(p))
    assert [c.title for c in info.chapters] == ["Introduzione", "Capitolo I."]
    for c in info.chapters:
        assert "Torna" not in c.text and "Liber Liber" not in c.text and "nobiliari" not in c.text
