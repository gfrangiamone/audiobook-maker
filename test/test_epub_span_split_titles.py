"""
Regressione: titoli di capitolo spezzati in <span> adiacenti (export Word/Kobo).

EPUB reale di riferimento: "L'Eternel Adolescent - Anas Guessous.epub".
Ogni file-capitolo apre con heading tipo:
    <h1><span>Chapitre </span><span>1</span></h1>
    <h1>Victoria, Canada, juillet 1987.</h1>

Bug originale: `get_text(strip=True)` concatenava gli span SENZA spazio
("Chapitre1"), così l'heading NON matchava la voce TOC "Chapitre 1". Con un
solo heading valido per file, `_split_html_by_headings` ritornava [] e il file
finiva come capitolo unico titolato con la sola data ("Victoria, Canada…"): la
struttura "Chapitre N" spariva e l'utente vedeva capitoli senza il marcatore.

Fix: matching heading↔TOC con separatore " " + merge del marcatore vuoto nel
titolo reale via `is_chapter_marker_line` (multilingua). I capitoli "Chapitre N"
tornano riconosciuti, uniti al sottotitolo e col corpo integro. Nessun testo
viene perso (invariante di copertura).
"""
import os
import re

import pytest

import epub_to_tts as E

EPUB = os.path.join(
    os.path.dirname(__file__), "books", "L'Eternel Adolescent - Anas Guessous.epub"
)


@pytest.fixture(scope="module")
def info():
    if not os.path.exists(EPUB):
        pytest.skip("file EPUB di riferimento non disponibile")
    return E.parse_epub(EPUB)


def test_marcatori_chapitre_riconosciuti(info):
    """I titoli 'Chapitre N' devono comparire (spezzati in span nel sorgente)."""
    titles = [c.title for c in info.chapters]
    for n in (1, 2, 10, 20):
        assert any(re.search(rf"\bChapitre {n}\b", t) for t in titles), (
            f"'Chapitre {n}' non riconosciuto; titoli: {titles}"
        )


def test_chapitre_uniti_al_sottotitolo_con_corpo(info):
    """'Chapitre 1' deve essere unito al sottotitolo-data e avere il corpo reale."""
    ch1 = [c for c in info.chapters if re.search(r"\bChapitre 1\b", c.title)]
    assert ch1, "capitolo 'Chapitre 1' assente"
    c = ch1[0]
    assert "Victoria" in c.title, f"sottotitolo non unito al marcatore: {c.title!r}"
    assert c.char_count > 1000, f"corpo del capitolo mancante: {c.char_count} char"
    assert "Ziyad" in c.text, "incipit reale del capitolo assente dal corpo"


def test_nessuna_perdita_di_testo(info):
    """La somma dei char di output deve eguagliare il testo estratto per file."""
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(EPUB, options={"ignore_ncx": False})
    total_src = 0
    for item_id, _ in book.spine:
        it = book.get_item_with_id(item_id)
        if not it or it.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        total_src += len(
            E.clean_text_for_tts(
                E.html_to_text(it.get_content().decode("utf-8", "replace"))
            )
        )
    total_out = sum(c.char_count for c in info.chapters)
    # Tolleranza minima: front-matter brevissimo (<200 char) può essere scartato.
    assert total_out >= total_src - 200, (
        f"perdita di testo: src={total_src} out={total_out}"
    )
