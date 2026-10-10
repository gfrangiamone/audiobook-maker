"""F1a: book_model e' l'unico modello del libro (Chapter/BookInfo, totali,
titoli di apparato) per EPUB, PDF, TXT e ABM."""
import inspect
import re

import book_model
import epub_to_tts
import generation_engine
import pdf_to_tts
from book_model import BookInfo, Chapter


def test_book_model_is_a_leaf_and_the_only_definition():
    src = inspect.getsource(book_model)
    assert not re.search(r"^\s*(import|from) (?!re\b|dataclasses\b)\w+", src, flags=re.M)
    for mod in (epub_to_tts, pdf_to_tts, generation_engine):
        s = inspect.getsource(mod)
        assert "class Chapter" not in s and "class BookInfo" not in s, mod.__name__
        assert "_SimpleBookInfo" not in s and "_SimpleChapter" not in s, mod.__name__
        assert "/ 150" not in s, mod.__name__                      # WORDS_PER_MINUTE e' unico
    assert "def print_book_info" not in inspect.getsource(pdf_to_tts)


def test_aliases_point_to_book_model():
    assert epub_to_tts.Chapter is Chapter and epub_to_tts.BookInfo is BookInfo
    assert pdf_to_tts.Chapter is Chapter and pdf_to_tts.BookInfo is BookInfo
    assert epub_to_tts._title_is_non_content is book_model.title_is_non_content
    assert epub_to_tts._synthetic_section_title is book_model.synthetic_section_title
    assert epub_to_tts._is_backnote_toc_title is book_model.is_backnote_toc_title
    assert pdf_to_tts.NON_CONTENT_TITLES is book_model.NON_CONTENT_TITLE_PHRASES
    assert epub_to_tts.print_book_info is pdf_to_tts.print_book_info is book_model.print_book_info
    import audiobook_app
    assert audiobook_app.WORDS_PER_MINUTE == book_model.WORDS_PER_MINUTE == 150


def test_chapter_counts_and_totals():
    ch = Chapter(index=1, title="Uno", text="tre parole qui")
    assert (ch.word_count, ch.char_count, ch.synthetic_title) == (3, 14, False)
    info = BookInfo(title="T", chapters=[ch, Chapter(index=2, title="Due", text="a b")])
    assert info.total_words == 0
    assert info.recompute_totals() is info
    assert (info.total_words, info.total_chars) == (5, 17)
    assert info.estimated_duration_minutes == 5 / 150
    one = BookInfo.from_text("Titolo", "Autore", "x y z")
    assert [c.title for c in one.chapters] == ["Titolo"] and one.total_words == 3 and one.author == "Autore"


def test_parse_txt_returns_a_book_info(tmp_path):
    p = tmp_path / "libro.txt"
    p.write_text("Prima riga.\n\nSeconda riga.", encoding="utf-8")
    info = generation_engine.parse_txt(str(p))
    assert isinstance(info, BookInfo) and len(info.chapters) == 1
    assert info.total_chars == info.chapters[0].char_count > 0


def test_non_content_titles_union_and_synthetic_labels():
    assert book_model.title_is_non_content("目录")                  # lista storica PDF
    assert book_model.title_is_non_content("Note al testo")         # lista storica EPUB
    assert book_model.title_is_non_content("Trama")                 # solo titolo intero
    assert not book_model.title_is_non_content("La trama del destino")
    assert not book_model.title_is_non_content("Notevole scoperta")
    assert book_model.is_backnote_toc_title("←7") and not book_model.is_backnote_toc_title("Capitolo 7")
    assert book_model.synthetic_section_title(3, "it-IT") == "Sezione 3"
    assert book_model.synthetic_section_title(3, "xx") == "Section 3"


def test_print_book_info_accepts_every_parser_output(capsys):
    info = BookInfo.from_text("T", "A", "ciao mondo")
    book_model.print_book_info(info)
    out = capsys.readouterr().out
    assert "Capitoli:   1" in out and "Parole:     2" in out
