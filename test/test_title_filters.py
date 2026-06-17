"""Filtri titolo non-contenuto: match per parola intera, non substring.

Bug originale: `any(skip in title_lower for skip in skip_titles)` faceva
match di substring -> token corti come "note", "toc", "cover", "index"
scartavano capitoli legittimi ("Notevole...", "Autocrazia", "Discovering",
qualunque parola contenente "index"). Il fix usa confini di parola.
"""
import epub_to_tts
import pdf_to_tts

# Testo narrativo abbastanza lungo da superare le soglie length-based di
# is_content_chapter (>=100 char, >=30 parole).
NARRATIVE = (
    "Era una notte buia e tempestosa quando il protagonista decise di "
    "lasciare la città per sempre, portando con sé soltanto un vecchio "
    "diario e la promessa fatta a sua madre molti anni prima di tornare. "
    "Il vento soffiava forte tra gli alberi spogli del viale deserto."
)


# ── Falsi positivi che NON devono piu' essere scartati ──

def test_notevole_is_content():
    # "note" non deve matchare "Notevole"
    assert epub_to_tts._is_title_content("Una scoperta notevole") is True
    assert epub_to_tts.is_content_chapter(NARRATIVE, "Una scoperta notevole") is True


def test_autocrazia_is_content():
    # "toc" non deve matchare "Autocrazia"
    assert epub_to_tts._is_title_content("L'autocrazia moderna") is True
    assert epub_to_tts.is_content_chapter(NARRATIVE, "L'autocrazia moderna") is True


def test_discovering_is_content():
    # "cover" non deve matchare "Discovering"
    assert epub_to_tts._is_title_content("Discovering the New World") is True


def test_indexed_is_content():
    # "index" non deve matchare "Indexed memories"
    assert epub_to_tts._is_title_content("Indexed Memories") is True


def test_pdf_notevole_is_content():
    assert pdf_to_tts._is_non_content_section("Una scoperta notevole", NARRATIVE) is False


def test_pdf_autocrazia_is_content():
    assert pdf_to_tts._is_non_content_section("L'autocrazia moderna", NARRATIVE) is False


# ── Veri titoli di apparato critico che DEVONO restare scartati ──

def test_real_note_is_skipped():
    assert epub_to_tts._is_title_content("Note") is False
    assert epub_to_tts._is_title_content("Note al testo") is False


def test_real_index_is_skipped():
    assert epub_to_tts._is_title_content("Index") is False
    assert epub_to_tts._is_title_content("Table of Contents") is False


def test_real_cover_is_skipped():
    assert epub_to_tts._is_title_content("Cover") is False
    assert epub_to_tts._is_title_content("Copertina") is False


def test_real_bibliografia_is_skipped():
    assert epub_to_tts._is_title_content("Bibliografia") is False
    assert epub_to_tts._is_title_content("Indice analitico") is False


def test_pdf_real_note_is_skipped():
    assert pdf_to_tts._is_non_content_section("Note", "qualunque") is True


def test_pdf_real_toc_is_skipped():
    assert pdf_to_tts._is_non_content_section("Indice", "qualunque") is True


def test_pdf_chinese_toc_is_skipped():
    # La voce "目录" (sommario) deve restare riconosciuta.
    assert pdf_to_tts._is_non_content_section("目录", "qualunque") is True
