"""Rilevatore di suddivisioni per pattern testuale (`_line_is_chapter_marker`).

Necessario per i PDF in cui, dopo i primi capitoli, i titoli collassano alla
dimensione del corpo e non sono più distinguibili tipograficamente: l'unico
segnale rimasto è il testo del marcatore ("Chapter Four", "Capitolo III"…).
Deve riconoscere i marcatori multilingua su riga isolata SENZA scambiare per
titolo un inizio di frase di corpo.

Il rilevatore è condiviso: definito in epub_to_tts (`is_chapter_marker_line`)
e riesportato da pdf_to_tts (`_line_is_chapter_marker`).
"""
import pdf_to_tts as P
import epub_to_tts as E


def test_pdf_and_epub_share_same_detector():
    # pdf_to_tts riusa il rilevatore di epub_to_tts (nessuna divergenza).
    assert P._line_is_chapter_marker is E.is_chapter_marker_line


# ── Marcatori validi (multilingua, vari formati di numero) ──

def test_english_chapter_word_number():
    assert P._line_is_chapter_marker("Chapter Four") is True
    assert P._line_is_chapter_marker("Chapter Ten") is True
    assert P._line_is_chapter_marker("CHAPTER ONE") is True


def test_arabic_and_roman_numbers():
    assert P._line_is_chapter_marker("Chapter 4") is True
    assert P._line_is_chapter_marker("Part IV") is True
    assert P._line_is_chapter_marker("PART VI") is True


def test_multilingual_keywords():
    assert P._line_is_chapter_marker("Capitolo III") is True
    assert P._line_is_chapter_marker("Kapitel 5") is True
    assert P._line_is_chapter_marker("Chapitre 2") is True
    assert P._line_is_chapter_marker("Capítulo 7") is True


def test_portuguese_russian_hindi_keywords():
    # Copertura allineata alle lingue con prompt di ottimizzazione dedicato.
    assert P._line_is_chapter_marker("Livro II") is True          # pt
    assert P._line_is_chapter_marker("Глава 1") is True           # ru (arabo)
    assert P._line_is_chapter_marker("Глава первая") is True      # ru (ordinale)
    assert P._line_is_chapter_marker("Часть вторая") is True      # ru
    assert P._line_is_chapter_marker("अध्याय 1") is True          # hi (arabo)
    assert P._line_is_chapter_marker("अध्याय १") is True          # hi (devanagari)
    assert P._line_is_chapter_marker("भाग 2") is True             # hi


def test_portuguese_russian_hindi_standalone():
    assert P._line_is_chapter_marker("Introdução") is True        # pt
    assert P._line_is_chapter_marker("Prefácio") is True          # pt
    assert P._line_is_chapter_marker("Пролог") is True            # ru
    assert P._line_is_chapter_marker("Введение") is True          # ru
    assert P._line_is_chapter_marker("प्रस्तावना") is True         # hi
    assert P._line_is_chapter_marker("उपसंहार") is True           # hi


def test_russian_body_sentence_not_a_marker():
    # "Глава семьи собралась…" (la testa della famiglia) non è un capitolo.
    assert P._line_is_chapter_marker("Глава семьи собралась за столом") is False


def test_ordinals_and_word_order():
    # Ordinali a parola (non solo cifre) e ordine numero+keyword.
    assert P._line_is_chapter_marker("PARTE PRIMA") is True         # it ordinale
    assert P._line_is_chapter_marker("Capitolo terzo") is True      # it
    assert P._line_is_chapter_marker("Première partie") is True     # fr numero+keyword
    assert P._line_is_chapter_marker("Erstes Kapitel") is True      # de numero+keyword
    assert P._line_is_chapter_marker("Capítulo primero") is True    # es
    assert P._line_is_chapter_marker("अध्याय पहला") is True         # hi ordinale


def test_ordinal_body_sentence_not_a_marker():
    # "Parte prima di ogni cosa" (frase) non è un marcatore: prosegue minuscolo.
    assert P._line_is_chapter_marker("Parte prima di ogni cosa") is False
    assert P._line_is_chapter_marker("La sesta strada era deserta") is False


def test_standalone_markers():
    assert P._line_is_chapter_marker("Prologue") is True
    assert P._line_is_chapter_marker("Epilogo") is True
    assert P._line_is_chapter_marker("Introduzione") is True


def test_chinese_marker():
    assert P._line_is_chapter_marker("第1章") is True
    assert P._line_is_chapter_marker("第三章") is True


def test_marker_with_short_title_on_same_line():
    # Marcatore seguito da titolo breve sulla stessa riga.
    assert P._line_is_chapter_marker("Chapter Three - The Hidden Path") is True


# ── Falsi positivi da evitare: frasi di corpo che iniziano col keyword ──

def test_body_sentence_not_a_marker():
    # Frase di corpo lunga: niente numero subito dopo, o troppe parole.
    assert P._line_is_chapter_marker(
        "Chapter four introduced a concept that changed the whole industry"
    ) is False
    assert P._line_is_chapter_marker(
        "Part of the reason lies in the way portfolios are evaluated today"
    ) is False


def test_empty_and_plain_text():
    assert P._line_is_chapter_marker("") is False
    assert P._line_is_chapter_marker("Every portfolio answers a question.") is False


def test_keyword_without_number_is_not_marker():
    # "Chapter" da solo (senza numero) non è un marcatore riconosciuto.
    assert P._line_is_chapter_marker("Chapter") is False
