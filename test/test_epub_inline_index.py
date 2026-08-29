"""Ri-segmentazione EPUB guidata dall'indice testuale interno al libro.

Caso: TOC EPUB vuoto o ridotto alla pagina del titolo (conversioni calibre da
TXT/RTF), corpo spezzato in file da ~200KB non allineati ai capitoli. L'unica
struttura è l'indice testuale in apertura, le cui voci ricompaiono verbatim
come righe isolate nel corpo. Regressione: "Massa e potere" (Canetti) veniva
ridotto a 3 capitoli (Premessa, EPILOGO, EPILOGO) perché il marcatore
"EPILOGO." citato nell'indice tagliava il libro.
"""
import os

import pytest

import epub_to_tts as E

BOOKS = os.path.join(os.path.dirname(__file__), "books")


def _book(name):
    path = os.path.join(BOOKS, name)
    if not os.path.exists(path):
        pytest.skip(f"file di test assente: {name}")
    return path


def _inline_index_book_text():
    idx = (
        "INDICE.\n\n"
        "PARTE UNO.\n\nSezione alfa.\n\nSezione beta.\n\n"
        "PARTE DUE.\n\nSezione gamma.\n\n"
        "EPILOGO.\n\nChiusura.\n\nNote.\n\nBibliografia.\n\n"
    )
    body = (
        "PARTE UNO.\n\nSezione alfa.\n\n" + "Prosa della sezione alfa. " * 10 + "\n\n"
        "Sezione beta.\n\n" + "Prosa della sezione beta. " * 10 + "\n\n"
        "PARTE DUE.\n\nSezione gamma.\n\n" + "Prosa della sezione gamma. " * 10 + "\n\n"
        "EPILOGO.\n\nChiusura.\n\n" + "Prosa di chiusura finale. " * 10 + "\n\n"
        "Note.\n\n1. nota uno.\n2. nota due.\n\n"
        "Bibliografia.\n\nAutore, Titolo, 1999.\n"
    )
    return idx + body


def test_inline_index_uses_top_level_entries():
    """Indice a due livelli (parti in MAIUSCOLO + sezioni): i capitoli sono le
    parti; le voci di apparato (Note, Bibliografia) tagliano e vengono scartate."""
    ch = E.Chapter(index=1, title="Sezione 1", text=_inline_index_book_text())
    out = E._resegment_chapters_by_inline_index([ch])
    assert [c.title for c in out] == ["PARTE UNO.", "PARTE DUE.", "EPILOGO."]
    assert "sezione alfa" in out[0].text.lower()
    assert "sezione beta" in out[0].text.lower()
    assert "Prosa di chiusura" in out[2].text
    joined = " ".join(c.text for c in out)
    assert "INDICE" not in joined          # il blocco indice non viene letto
    assert "nota uno" not in joined         # apparato scartato
    assert "Autore, Titolo" not in joined


def test_inline_index_flat_index():
    """Indice piatto (nessuna gerarchia): ogni voce è un capitolo."""
    idx = "Contents\n\nUno.\n\nDue.\n\nTre.\n\nQuattro.\n\n"
    body = "".join(f"{t}.\n\n" + f"Prosa del capitolo {t.lower()}. " * 10 + "\n\n"
                   for t in ("Uno", "Due", "Tre", "Quattro"))
    ch = E.Chapter(index=1, title="X", text=idx + body)
    out = E._resegment_chapters_by_inline_index([ch])
    assert [c.title for c in out] == ["Uno.", "Due.", "Tre.", "Quattro."]


def test_inline_index_requires_index_block():
    """Senza blocco indice non si fa nulla (il chiamante passa ai marcatori)."""
    ch = E.Chapter(index=1, title="X", text="Prosa qualunque. " * 200)
    assert E._resegment_chapters_by_inline_index([ch]) == []


def test_inline_index_requires_matches_in_body():
    """Indice presente ma voci assenti nel corpo → nessuna ri-segmentazione."""
    text = "INDICE.\n\nUno.\n\nDue.\n\nTre.\n\nQuattro.\n\n" + "Prosa qualunque. " * 200
    ch = E.Chapter(index=1, title="X", text=text)
    assert E._resegment_chapters_by_inline_index([ch]) == []


def test_markers_resegmentation_ignores_index_block():
    """Un marcatore ("Epilogo.") citato nell'indice non deve tagliare il libro."""
    text = (
        "INDICE.\n\nCapitolo primo.\n\nEpilogo.\n\nNote.\n\n"
        + "Prosa introduttiva lunga. " * 10 + "\n\n"
        "Capitolo primo.\n\n" + "Prosa del primo. " * 10 + "\n\n"
        "Epilogo.\n\n" + "Prosa epilogo. " * 10 + "\n"
    )
    ch = E.Chapter(index=1, title="X", text=text)
    out = E._resegment_chapters_by_markers([ch])
    assert [c.title for c in out] == ["Premessa", "Capitolo primo.", "Epilogo."]
    assert "INDICE" not in out[0].text


def test_massa_e_potere_parts_recognized():
    """Canetti — "Massa e potere": TOC EPUB con la sola voce "Avvio", corpo
    spezzato da calibre in file da ~200KB. Struttura reale solo nell'indice
    testuale iniziale (12 parti + Epilogo)."""
    info = E.parse_epub(_book("massa-e-potere.epub"))
    titles = [c.title.upper() for c in info.chapters]
    assert titles[0].startswith("LA MASSA")
    assert any(t.startswith("IL COMANDO") for t in titles)
    assert titles.count("EPILOGO.") == 1
    # 11, non 12: nel corpo la parte "ELEMENTI DEL POTERE." è scritta
    # "ELEMENTI DI POTERE." (refuso editoriale): confronto esatto per scelta,
    # il testo confluisce nella parte precedente senza perdita.
    assert 11 <= len(info.chapters) <= 16
    assert not any(t.startswith("INDICE") for t in titles)
    assert not any(t.startswith("NOTE") or t.startswith("BIBLIOGRAFIA") for t in titles)
    assert sum(c.word_count for c in info.chapters) > 150000
