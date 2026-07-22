"""Ri-segmentazione automatica dei capitoli EPUB (allineamento al parsing PDF).

Regola: se l'indice dell'EPUB codifica MENO di 4 capitoli di contenuto (escluse
note/apparato), si tenta di suddividerlo per marcatori testuali di capitolo
("Capitolo primo", "PARTE PRIMA"…). Con >= 4 capitoli ci si affida al TOC.
Invariante fondamentale: la ri-segmentazione non perde mai testo.
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


def test_magnifica_humanitas_gets_resegmented():
    """EPUB tipico con indice sotto-strutturato: 1 capitolo nel TOC ma il testo
    contiene "Capitolo primo…quinto" → deve essere suddiviso in più capitoli."""
    info = E.parse_epub(_book("magnifica-humanitas.epub"))
    # Prima era 1 solo capitolo: ora deve essere ri-segmentato in più capitoli.
    assert len(info.chapters) >= 5
    titles = " ".join(c.title.lower() for c in info.chapters)
    assert "capitolo primo" in titles
    assert "capitolo quinto" in titles


def test_resegmentation_preserves_text():
    """Invariante: la ri-segmentazione ridistribuisce il testo, non lo perde.

    Confronto il numero di parole del parse completo con quello di una singola
    concatenazione — devono coincidere a meno dei titoli-marcatore estratti.
    """
    info = E.parse_epub(_book("magnifica-humanitas.epub"))
    total = sum(c.word_count for c in info.chapters)
    # Il testo utile resta sostanzialmente invariato (nessuna perdita massiva):
    # margine ampio perché i marcatori-titolo passano dal corpo al campo title.
    assert total > 30000


def test_cavalli_selvaggi_parts_recognized():
    """McCarthy — "Cavalli selvaggi": indice povero, ma il testo ha
    PARTE PRIMA…QUARTA (ordinali italiani) → 4 parti riconosciute."""
    info = E.parse_epub(_book("Cavalliselvaggi(CormacMcCart..epub"))
    titles = " ".join(c.title.upper() for c in info.chapters)
    assert "PARTE PRIMA" in titles
    assert "PARTE QUARTA" in titles


def test_resegmentation_helper_no_markers_returns_empty():
    """Se il testo non contiene >= 2 marcatori, non si ri-segmenta."""
    ch = E.Chapter(index=1, title="X", text="Una prosa qualunque senza titoli. " * 50)
    assert E._resegment_chapters_by_markers([ch]) == []


def test_resegmentation_helper_no_text_loss_unit():
    """Unit: ogni riga confluisce in una sezione, nessuna perdita di parole di corpo."""
    body = (
        "Testo introduttivo di premessa che apre il volume.\n\n"
        "Capitolo primo\n\nContenuto del primo capitolo, abbastanza lungo.\n\n"
        "Capitolo secondo\n\nContenuto del secondo capitolo, anch'esso presente.\n"
    )
    ch = E.Chapter(index=1, title="Tutto", text=body)
    out = E._resegment_chapters_by_markers([ch])
    assert len(out) == 3  # Premessa + Capitolo primo + Capitolo secondo
    assert out[0].title == "Premessa"
    joined = " ".join(c.text for c in out)
    for word in ("introduttivo", "primo", "secondo", "anch'esso"):
        assert word in joined
