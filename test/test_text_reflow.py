"""Ricomposizione di paragrafi spezzati, comune a PDF, EPUB e TXT.

Confronto su 254 EPUB di produzione (01/10/2026): 31 libri convertiti da PDF
con un <p> per ogni riga stampata (oltre il 20% dei paragrafi spezzato a metà
frase), sillabazioni fra due paragrafi ("ac-" / "cepted"), trattini morbidi
U+00AD letti dal TTS. I libri ben composti, i versi e i dialoghi non vanno
toccati.
"""
import text_reflow as R
from generation_engine import parse_txt


_LINES = [
    "It was the best of times, it was the worst of times, it was the age",
    "of wisdom, it was the age of foolishness, it was the epoch of belief,",
    "it was the epoch of incredulity, it was the season of Light, it was the",
    "season of Darkness, it was the spring of hope, it was the winter of de-",
    "spair, we had everything before us, we had nothing before us.",
]


def _converted_book(n=20):
    # Un paragrafo per riga stampata, come nelle conversioni da PDF.
    return "\n\n".join(_LINES * n)


def _wellformed_book(n=60):
    return "\n\n".join(["He came home late.", "\"Where were you?\" she asked.",
                        "Nobody answered."] * n)


# ── Primitive ──

def test_strip_soft_hyphens():
    assert R.strip_soft_hyphens("bri\u00adlhante") == "brilhante"


def test_dehyphenate_single_newline():
    assert R.dehyphenate_breaks("zurück-\nkehren") == "zurückkehren"
    assert R.dehyphenate_breaks("Ost-\nBerlin") == "Ost-Berlin"
    assert R.dehyphenate_breaks("Hin-\nund Rückfahrt") == "Hin- und Rückfahrt"


def test_dehyphenate_across_paragraphs_only_before_lowercase():
    assert R.dehyphenate_breaks("ac-\n\ncepted") == "accepted"
    assert R.dehyphenate_breaks("Ende Ost-\n\nBerlin.") == "Ende Ost-\n\nBerlin."
    assert R.dehyphenate_breaks("1990-\n\n1995") == "1990-\n\n1995"


def test_is_mid_sentence_break():
    assert R.is_mid_sentence_break("it was the age", "of wisdom")
    assert not R.is_mid_sentence_break("it was the age.", "of wisdom")
    assert not R.is_mid_sentence_break("Chapter One", "It was")


# ── Libro intero ──

def test_converted_book_is_reflowed():
    out = R.reflow_book([_converted_book()])
    assert out is not None
    paras = out[0].split("\n\n")
    assert len(paras) == 20
    assert paras[0] == (
        "It was the best of times, it was the worst of times, it was the age "
        "of wisdom, it was the age of foolishness, it was the epoch of belief, "
        "it was the epoch of incredulity, it was the season of Light, it was the "
        "season of Darkness, it was the spring of hope, it was the winter of "
        "despair, we had everything before us, we had nothing before us.")


def test_wellformed_book_untouched():
    assert R.reflow_book([_wellformed_book()]) is None


def test_occasional_break_in_wellformed_book_untouched():
    # Un solo a-capo sbagliato in un libro sano: sotto soglia, nessun reflow.
    text = _wellformed_book() + "\n\nit was the age\n\nof wisdom."
    assert R.reflow_book([text]) is None


def test_lowercase_verse_untouched():
    # Poesia moderna: versi corti, minuscoli, senza punteggiatura.
    verse = ["the rain falls", "on the quiet roofs", "and nobody listens",
             "to the old songs", "of the river"] * 30
    assert R.reflow_book(["\n\n".join(verse)]) is None


def test_short_book_untouched():
    assert R.reflow_book(["\n\n".join(_LINES)]) is None


# ── TXT ──

def test_txt_converted_from_pdf_is_reflowed(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text(_converted_book().replace("\n", "\r\n"), encoding="utf-8")
    text = parse_txt(str(p)).chapters[0].text
    assert "the age of wisdom" in text
    assert "winter of despair" in text
    assert len(text.split("\n\n")) == 20


def test_txt_soft_hyphen_and_wellformed_layout(tmp_path):
    p = tmp_path / "book.txt"
    p.write_text("Una frase bri\u00adllante.\n\nSecondo paragrafo.", encoding="utf-8")
    assert parse_txt(str(p)).chapters[0].text == "Una frase brillante.\n\nSecondo paragrafo."


# ── EPUB ──

def _write_epub(path, chapters):
    from ebooklib import epub
    book = epub.EpubBook()
    book.set_identifier("reflow-test")
    book.set_title("Reflow")
    book.set_language("en")
    items = []
    for i, (title, paras) in enumerate(chapters, 1):
        body = "".join(f"<p>{p}</p>" for p in paras)
        it = epub.EpubHtml(title=title, file_name=f"c{i}.xhtml", lang="en")
        it.content = f"<html><body><h1>{title}</h1>{body}</body></html>"
        book.add_item(it)
        items.append(it)
    book.toc = items
    book.spine = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    epub.write_epub(str(path), book)


def test_epub_converted_from_pdf_is_reflowed(tmp_path):
    import epub_to_tts as E
    p = tmp_path / "conv.epub"
    _write_epub(p, [(f"Chapter {i}", _LINES * 6) for i in range(1, 5)])
    info = E.parse_epub(str(p))
    text = info.chapters[0].text
    assert "the age of wisdom" in text
    assert "winter of despair" in text
    assert "\u00ad" not in text


def test_epub_wellformed_keeps_paragraphs_and_strips_soft_hyphen(tmp_path):
    import epub_to_tts as E
    p = tmp_path / "ok.epub"
    paras = ["He came home late.", "\"Where were you?\" she asked.",
             "The bri\u00adlliant moon was up."] * 30
    _write_epub(p, [(f"Chapter {i}", paras) for i in range(1, 5)])
    text = E.parse_epub(str(p)).chapters[0].text
    assert "brilliant" in text
    assert text.count("\n\n") >= 80


def test_sanitize_strips_soft_hyphen_keeps_typography():
    from tts_split import _sanitize_tts_text
    src = "Bri" + chr(0xAD) + "lliant " + chr(0x2014) + " " + chr(0x201C) + "yes" + chr(0x201D) + chr(0x2026)
    out = _sanitize_tts_text(src)
    assert chr(0xAD) not in out
    assert "Brilliant" in out
    for ch in (0x2014, 0x201C, 0x201D, 0x2026):
        assert chr(ch) in out
