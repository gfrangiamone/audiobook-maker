"""Testo e titoli nella lingua del libro (catalogo, 06/11/2026).

Le abbreviazioni italiane valevano per ogni lingua e senza distinzione di
maiuscole: "heißt es." diventava "heißt esempio", lo spagnolo "lo que es."
"lo que esempio", il "Sr." portoghese "Senior", "Art." (Arthur) "articolo" in
Dracula. Il testo prima del primo capitolo si chiamava "Premessa" anche in un
libro tedesco, e il frontespizio di Gutenberg dava a Der Schimmelreiter un
solo capitolo intitolato all'autore.
"""
from ebooklib import epub

import epub_to_tts as E
import plain_parsers
import text_reflow as T

_PARA = ("Da ging er hinaus, und der Wind fuhr ihm entgegen, und so hieß es. "
         "Der Sr. Hauke sah auf das Meer hinaus, wo die Wellen gegen den Deich schlugen. ")


def test_italiano_letto_in_italiano():
    assert T.expand_abbreviations("Mele, pere ecc. Il Dr. Rossi", "it") == "Mele, pere eccetera Il Dottor Rossi"
    assert T.expand_abbreviations("vedi e.g. il caso", "it") == "vedi per esempio il caso"
    assert T.expand_abbreviations("vedi cap. 3", "it-IT") == "vedi capitolo 3"
    assert T.expand_abbreviations("vedi cap. 3", "it_IT") == "vedi capitolo 3"
    assert T.expand_abbreviations("vedi cap. 3", "ita") == "vedi capitolo 3"


def test_senza_lingua_nessuna_espansione_fino_al_rilevamento():
    assert T.expand_abbreviations("Mele ecc. e il Dr. Rossi") == "Mele ecc. e il Dr. Rossi"
    assert T.expand_abbreviations("so hieß es.", "") == "so hieß es."
    info = E.BookInfo(title="Libro", language="",
                      chapters=[E.Chapter(index=1, title="Uno", text="Mele, pere ecc.")])
    info.recompute_totals()
    info.language = "it"                       # rilevata da /api/analyze
    T.expand_book_abbreviations(info)
    assert info.chapters[0].text == "Mele, pere eccetera"
    assert info.chapters[0].char_count == info.total_chars == len("Mele, pere eccetera")


def test_inglese_solo_le_inglesi():
    assert T.expand_abbreviations("Dr. Seward, apples etc.", "en") == "Doctor Seward, apples et cetera"
    assert T.expand_abbreviations("You took more from Art.", "en-GB") == "You took more from Art."


def test_altre_lingue_non_espandono():
    assert T.expand_abbreviations("so hieß es. Auf diese Art.", "de") == "so hieß es. Auf diese Art."
    assert T.expand_abbreviations("lo que es. El Sr. Santa Cruz", "es") == "lo que es. El Sr. Santa Cruz"
    assert T.expand_abbreviations("o Sr. Afonso, cap. 3", "pt-BR") == "o Sr. Afonso, cap. 3"


def test_segno_di_grado_nella_lingua_del_libro():
    X = T.expand_abbreviations
    # segno di numero (Max Havelaar: "N° 37" era "N gradi 37")
    assert X("Lauriergracht, N° 37. Het is", "nl") == "Lauriergracht, nummer 37. Het is"
    assert X("Lauriergracht N°. 37 en", "nl") == "Lauriergracht nummer 37 en"
    assert X("Encadernação N.° 2465", "pt") == "Encadernação número 2465"
    assert X("no Mercantil n.° 26 de", "pt-BR") == "no Mercantil número 26 de"
    # fino a 10 ordinale: elenchi, date, "in quarto"
    assert X("vast:\n\n1° Dat hy\n\n2° Dat ik", "nl") == "vast:\n\nten eerste Dat hy\n\nten tweede Dat ik"
    assert X("finora:\n\n1.° Una bella", "it") == "finora:\n\nprimo Una bella"
    assert X("Oggi è il 1° novembre, piano 1°, dove", "ita") == "Oggi è il primo novembre, piano primo, dove"
    assert (X("por dous motivos: 1.° porque sendo; 2.° porque", "pt")
            == "por dous motivos: primeiro porque sendo; segundo porque")
    assert X("pensava: 1. ° que essa", "pt") == "pensava: primeiro que essa"
    assert X("brochados em-4° enfileiravam", "pt") == "brochados em-quarto enfileiravam"
    assert X("Collecção in 8° a 2$000", "por") == "Collecção in oitavo a 2$000"
    assert X("cosas.\n\n1°: que", "es") == "cosas.\n\nprimero: que"
    # oltre il 10: ordinale in testa a una voce d'elenco, col punto o in portoghese
    assert X('Ziehier:\n\n"12° Over het', "nl") == 'Ziehier:\n\n"12e Over het'
    assert X('verder:\n\xa0\xa0"15°Over', "nl") == 'verder:\n\xa0\xa0"15e Over'
    assert X("vino; 35°: non", "it") == "vino; 35º: non"
    assert X("o 12° capitulo", "pt") == "o 12º capitulo"
    assert X("the 21°: rule", "en") == "the 21st: rule"
    # gradi: oltre il 10 nel testo, o con l'unita'
    assert X("a 40°. Pero los", "es") == "a 40 grados. Pero los"
    assert X("aveva 38° di febbre, N° 3", "it") == "aveva 38 gradi di febbre, numero 3"
    assert X("it was 5°C", "en") == "it was 5 degrees C"
    assert X("es waren 3 °C", "de") == "es waren 3 Grad C"
    # lingua senza voce o sconosciuta: "°" resta al TTS (si espande al rilevamento)
    assert T.expand_abbreviations("a 40° N° 3", "ru") == "a 40° N° 3"
    assert T.expand_abbreviations("a 40° N° 3") == "a 40° N° 3"
    assert "gradi" not in E.clean_text_for_tts("Lauriergracht, N° 37.", lang="nl")
    assert "gradi" not in E.clean_text_for_tts("a 40°.")


def test_indice_e_colophon_in_olandese_e_tedesco():
    from book_model import title_is_non_content
    for t in ("Inhoud", "Inhoudsopgave", "Colofon", "Kolophon", "Colofón"):
        assert title_is_non_content(t), t
    assert not title_is_non_content("De inhoud van den brief")


def test_epub_tedesco_non_legge_esempio(tmp_path):
    book = epub.EpubBook()
    book.set_identifier("abbr-de")
    book.set_title("Der Schimmelreiter")
    book.set_language("de")
    it = epub.EpubHtml(title="Kapitel", file_name="c1.xhtml", lang="de")
    it.content = f"<html><body><h1>Erstes Kapitel</h1>{('<p>' + _PARA + '</p>') * 6}</body></html>"
    book.add_item(it)
    book.toc = [it]
    book.spine = [it]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    p = tmp_path / "de.epub"
    epub.write_epub(str(p), book)
    text = "\n".join(c.text for c in E.parse_epub(str(p)).chapters)
    assert "hieß es." in text and "esempio" not in text and "Senior" not in text


def test_abm_usa_la_lingua_del_manifest(tmp_path):
    import json
    import zipfile
    p = tmp_path / "libro.abm"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("manifest.json", json.dumps({
            "format": "audiobook-maker-project", "title": "Niebla", "language": "es",
            "chapters": [{"index": 1, "title": "I", "filename": "001.txt"}]}))
        z.writestr("chapters/001.txt", "Augusto no sabía qué hacer, y así es. El Sr. Pérez salió.")
    info, _ = plain_parsers.parse_abm(str(p))
    assert info.chapters[0].text == "Augusto no sabía qué hacer, y así es. El Sr. Pérez salió."


def test_premessa_nella_lingua_del_libro():
    from book_model import lead_section_title
    assert lead_section_title("it-IT") == "Premessa"
    assert lead_section_title("") == "Premessa"
    assert lead_section_title("de") == "Vorbemerkung"
    assert lead_section_title("pt_BR") == "Preâmbulo"
    assert lead_section_title("sv") == "Preface"
    info = E.BookInfo(title="Der Tod in Venedig", language="de",
                      chapters=[E.Chapter(index=1, title="Premessa", text="Vorwort."),
                                E.Chapter(index=2, title="Erstes Kapitel", text="Gustav Aschenbach.")])
    E._localize_lead_titles(info)
    assert [c.title for c in info.chapters] == ["Vorbemerkung", "Erstes Kapitel"]


def test_capitolo_intitolato_all_autore_prende_il_titolo_del_libro(tmp_path):
    book = epub.EpubBook()
    book.set_identifier("author-title")
    book.set_title("Der Schimmelreiter")
    book.add_author("Theodor Storm")
    book.set_language("de")
    it = epub.EpubHtml(title="Theodor Storm", file_name="c1.xhtml", lang="de")
    it.content = f"<html><body><h2>Theodor Storm</h2>{('<p>' + _PARA + '</p>') * 12}</body></html>"
    book.add_item(it)
    book.toc = [it]
    book.spine = [it]
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    p = tmp_path / "storm.epub"
    epub.write_epub(str(p), book)
    assert [c.title for c in E.parse_epub(str(p)).chapters] == ["Der Schimmelreiter"]
