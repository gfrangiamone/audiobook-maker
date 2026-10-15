"""Testatine, indice spezzato e sezioni corte nel parser PDF.

Ticket 2026-10-15 (libro senza outline, capitoli da "titoli"): l'audio si
apriva con un resto d'indice ("Part II: The Fall, 5. …") perche' il filtro
aveva tolto solo la prima meta' dell'indice; i piè di pagina alternati
("Fallen Shepherd: A LifeCare Guide" / "… Page 22"), a 3/4 di un foglio Letter
e quindi fuori dalla fascia dell'8%, finivano nei titoli e nel testo; i
capitoli col solo sottotitolo sparivano. PDF sintetici, niente file cliente.
"""
import re

import fitz

import pdf_to_tts as P
from epub_to_tts import is_chapter_marker_line

WORDS = ("river morning building leadership money decision elder pastor "
         "meeting letter friend family worship prayer choir garden winter "
         "summer harvest window bridge village").split()


def _body(seed: int, n: int = 40) -> str:
    """Prosa diversa per ogni pagina: righe identiche su piu' pagine
    sembrerebbero testatine."""
    out = []
    for k in range(n):
        a, b = WORDS[(seed * 7 + k) % len(WORDS)], WORDS[(seed * 3 + k * 5) % len(WORDS)]
        out.append(f"In year {seed}{k} the {a} and the {b} changed again.")
    return " ".join(out)


def _write_lines(page, y, text, size=12, font="helv", width=70):
    words, line = text.split(), ""
    for w in words:
        if len(line) + len(w) + 1 > width:
            page.insert_text((150, y), line, fontsize=size, fontname=font)
            y += size * 1.3
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        page.insert_text((150, y), line, fontsize=size, fontname=font)
        y += size * 1.3
    return y + size * 0.6


def _book(tmp_path):
    """Foglio Letter (792 pt) con corpo fino a y≈520 e piè di pagina a y≈580:
    pagine dispari "My Guide: A Life Book   Page N", pari "My Gude: A Life Book"."""
    doc = fitz.open()
    pages = [
        [("Table of Contents", 18, "hebo"),
         ("Dedication - Page 6", 12, "hebo"),
         ("Introduction - Page 9", 12, "hebo"),
         ("Part I: Before", 12, "hebo"),
         ("1. The Church We Loved - Page 23", 12, "helv"),
         ("o The growth and vision that drew people.", 12, "helv"),
         ("2. The Shepherd - Page 30", 12, "helv")],
        [("Part II: The Fall", 12, "hebo"),
         ("5. The Vision Becomes Public - Page 49", 12, "helv"),
         ("o Shock, disbelief and the first wave of grief.", 12, "helv"),
         ("6. The Crisis Meetings - Page 63", 12, "helv"),
         ("o Leadership responses and confusion.", 12, "helv")],
        [("Chapter 1: The Church We Loved", 18, "hebo"), (_body(1), 12, "helv")],
        [(_body(2), 12, "helv")],
        [("Chapter 2: The Shepherd", 18, "hebo"),
         ("Charisma and the dangers of celebrity.", 12, "helv")],
        [("Charisma, Influence and Admiration", 18, "hebo"), (_body(3), 12, "helv")],
        [(_body(4), 12, "helv")],
        [("Chapter 3: The Warning Signs", 18, "hebo"), (_body(5), 12, "helv")],
        [(_body(6), 12, "helv")],
        [(_body(7), 12, "helv")],
    ]
    for i, items in enumerate(pages, start=1):
        page = doc.new_page(width=612, height=792)
        y = 70
        for text, size, font in items:
            y = _write_lines(page, y, text, size, font)
        if i % 2:
            page.insert_text((150, 590), "My Guide: A Life Book", fontsize=11, fontname="hebo")
            page.insert_text((450, 590), f"Page {i}", fontsize=12, fontname="hebo")
        else:
            page.insert_text((150, 600), "My Gude: A Life Book", fontsize=12, fontname="hebo")
    path = tmp_path / "book.pdf"
    doc.save(str(path))
    doc.close()
    return str(path)


def test_alternating_footers_outside_margin_are_detected(tmp_path):
    doc = fitz.open(_book(tmp_path))
    try:
        repeated = P._detect_repeated_headers_footers(doc)
    finally:
        doc.close()
    assert "My Guide: A Life Book Page N" in repeated
    assert "My Gude: A Life Book" in repeated


def test_book_has_no_toc_residue_nor_page_labels(tmp_path):
    info = P.parse_pdf(_book(tmp_path))
    titles = [c.title for c in info.chapters]
    assert titles[0] == "Chapter 1: The Church We Loved"
    for c in info.chapters:
        assert not re.search(r"\bPage \d+", c.title + "\n" + c.text), c.title
        assert "Life Book" not in c.title + c.text
        assert "Part II" not in c.title + c.text
    # Il capitolo col solo sottotitolo apre il successivo invece di sparire.
    ch2 = next(c for c in info.chapters if c.title == "Chapter 2: The Shepherd")
    assert ch2.text.startswith("Charisma and the dangers of celebrity.")
    assert "Charisma, Influence and Admiration" in ch2.text
    assert "In year 30 " in ch2.text


def test_toc_entry_line_is_not_a_heading():
    assert P._TOC_ENTRY_LINE_RE.search("Dedication – Page 6")
    assert P._TOC_ENTRY_LINE_RE.search("Introduzione ........ 12")
    assert not P._TOC_ENTRY_LINE_RE.search("Chapter 4: The Page Turner")


def test_looks_like_toc_text():
    assert P._looks_like_toc_text(
        "5. The Vision – Page 49 o Shock and grief.\n\n6. The Crisis – Page 63 o Confusion.")
    assert not P._looks_like_toc_text(_body(1) + " See the map – Page 4.")
    assert not P._looks_like_toc_text("")


def _build(raw):
    return P._build_chapters_from_raw(raw, "x.pdf")


def test_toc_chain_is_dropped_until_real_content():
    chapters = _build([
        ("Table of Contents", "Dedication – Page 6\n\nIntroduction – Page 9"),
        ("Part II: The Fall", "5. The Vision – Page 49 o Shock.\n\n6. The Crisis – Page 63 o Grief."),
        ("Part III: The Cost", "9. Shattered Trust – Page 87 o Betrayal.\n\n10. Damage – Page 94"),
        ("Chapter 1", _body(1)),
        ("Chapter 2", _body(2)),
    ])
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2"]


def test_toc_like_text_without_toc_before_is_left_to_content_filter():
    chapters = _build([("Chapter 1", _body(1)),
                       ("Reading Plan", _body(2) + " Day one – Page 4. Day two – Page 9.")])
    assert len(chapters) == 2


def test_short_section_without_marker_joins_previous():
    chapters = _build([("Chapter 1", _body(1)),
                       ("A bold line in the body", "Short paragraph under it."),
                       ("Chapter 2", _body(2))])
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2"]
    assert chapters[0].text.endswith("A bold line in the body\n\nShort paragraph under it.")
    assert chapters[0].word_count == len(chapters[0].text.split())


def test_short_chapter_heading_opens_next_section():
    chapters = _build([("Chapter 1", _body(1)),
                       ("Chapter 2: Lessons", "Humility and accountability."),
                       ("Humility and Stewardship", _body(2))])
    assert [c.title for c in chapters] == ["Chapter 1", "Chapter 2: Lessons"]
    assert chapters[1].text.startswith(
        "Humility and accountability.\n\nHumility and Stewardship\n\nIn year 20 ")


def test_short_front_matter_is_still_dropped():
    chapters = _build([("", "A Book in the Life Guide Series"), ("Chapter 1", _body(1))])
    assert len(chapters) == 1
    assert "Series" not in chapters[0].text


def test_chapter_marker_ending_with_comma_is_body_text():
    assert not is_chapter_marker_line("Chapter 18. Just as good people stay for good reasons,")
    assert is_chapter_marker_line("Chapter 18: Why Good People Stay")
