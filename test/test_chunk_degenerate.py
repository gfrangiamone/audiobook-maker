"""Riconoscimento dei chunk degeneri (frammenti che i TTS rifiutano)."""
import pytest

from tts_split import _is_degenerate_chunk


@pytest.mark.parametrize("text", [
    "XIV.",
    "14.",
    "Capitolo XIV",
    "  III  ",
    "1793",
    "Cap. 12",
    "",
    "   ",
])
def test_degenerate_fragments(text):
    assert _is_degenerate_chunk(text) is True


@pytest.mark.parametrize("text", [
    "Nel mezzo del cammin di nostra vita mi ritrovai per una selva oscura.",
    "Il quattordicesimo giorno del mese di maggio, la nave lasciò il porto.",
    "Nel 1793 la Convenzione decise di processare il re, e la città intera trattenne il fiato.",
])
def test_regular_text_is_not_degenerate(text):
    assert _is_degenerate_chunk(text) is False


def test_short_but_wordy_is_degenerate_by_length():
    # Sotto min_chars e' un frammento anche senza numerali: il TTS lo legge male.
    assert _is_degenerate_chunk("Buongiorno.") is True


def test_a_numeral_heading_that_clears_min_chars_is_still_degenerate():
    # Il criterio della lunghezza minima da solo non basta: un'intestazione
    # composta di date e numeri di capitolo supera i 40 caratteri e arriverebbe
    # intatta al backend, che e' esattamente il chunk rifiutato con codice 2017.
    # Senza questo caso il ramo del rapporto di numerali non viene mai
    # esercitato "in positivo" e puo' essere disattivato senza rossi.
    text = "Capitolo XIV. 1789. 1790. 1791. 1792. 1793."
    assert 40 <= len(text) < 120, "il caso deve cadere nella finestra del criterio 2"
    assert _is_degenerate_chunk(text) is True


def test_enough_context_disarms_the_numeral_ratio():
    # Oltre la finestra il rapporto non conta piu': una cronologia lunga e' testo
    # da leggere, non un'intestazione. Silenziarla sarebbe un buco di audio.
    text = ("1789. 1790. 1791. 1792. 1793. 1794. 1795. 1796. 1797. 1798. "
            "1799. 1800. 1801. 1802. 1803. 1804. 1805. 1806. 1807. 1808. 1809.")
    assert len(text) >= 120
    assert _is_degenerate_chunk(text) is False


def test_min_chars_is_parametric():
    text = "Una frase di media lunghezza che supera i quaranta caratteri."
    assert _is_degenerate_chunk(text, min_chars=10) is False
    assert _is_degenerate_chunk(text, min_chars=200) is True


def test_italian_words_made_of_roman_letters_are_not_numerals():
    # Con IGNORECASE la classe [IVXLCDM] promuove a "numerale" parole italiane
    # correnti: mi, ci, vi, li, di, il, dici, vivi, lidi, vili, idilli. Una
    # frase breve che ne contenga abbastanza cadrebbe nella finestra 40-120 e
    # verrebbe marcata degenere -> il Task 3 la silenzierebbe, cioe' testo
    # cancellato dall'audiolibro senza traccia nei contatori. Caso costruito,
    # ma il meccanismo e' reale: il riconoscimento dei romani resta maiuscolo.
    text = "Mi, ci, vi, li, di, il: dici vivi lidi, dividi vili idilli."
    assert 40 <= len(text) < 120, "il caso deve cadere nella finestra del criterio 2"
    assert _is_degenerate_chunk(text) is False


def test_english_words_made_of_roman_letters_are_not_numerals():
    text = "Civil, vivid, mimic, civic, mid, dim, lid, mild, livid, illicit."
    assert 40 <= len(text) < 120
    assert _is_degenerate_chunk(text) is False


from tts_split import _merge_degenerate_chunks


def test_merges_forward_into_next_chunk():
    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 2
    out = _merge_degenerate_chunks(["XIV.", body], max_chars=2000, max_bytes=None)
    assert len(out) == 1
    assert out[0].startswith("XIV.")
    assert body.strip() in out[0]
    # Nessuna perdita/duplicazione di testo: la fusione e' esattamente titolo +
    # separatore + corpo, non una sua approssimazione. Solo lstrip sul lato
    # destro (coerente con l'implementazione: il corpo mantiene il proprio
    # eventuale spazio finale, non viene fatto anche rstrip).
    assert out[0] == f"XIV.\n\n{body.lstrip()}"


def test_merges_backward_when_no_next_chunk():
    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 2
    out = _merge_degenerate_chunks([body, "XIV."], max_chars=2000, max_bytes=None)
    assert len(out) == 1
    assert out[0].rstrip().endswith("XIV.")
    assert out[0] == f"{body.rstrip()}\n\nXIV."


def test_does_not_merge_when_it_would_break_max_chars():
    # "XIV." (4) + separatore "\n\n" (2) + body (1995) = 2001: 1 char oltre il
    # cap. Valore scelto sul confine esatto (non un margine ampio a caso) cosi'
    # il test cade davvero se il merge smette di contare il separatore.
    body = "a" * 1995
    out = _merge_degenerate_chunks(["XIV.", body], max_chars=2000, max_bytes=None)
    assert out == ["XIV.", body]


def test_does_not_merge_when_it_would_break_max_bytes():
    # Ogni ideogramma pesa 3 byte UTF-8: body = 900 byte. "XIV." (4) +
    # separatore "\n\n" (2, ASCII) + 900 = 906 byte: 6 oltre il cap di 900,
    # esattamente l'overhead del separatore/titolo. max_chars resta largo
    # apposta, cosi' a rifiutare il merge e' solo il cap sui byte.
    body = "書" * 300
    out = _merge_degenerate_chunks(["XIV.", body], max_chars=2000, max_bytes=900)
    assert out == ["XIV.", body]


def test_cascading_forward_merge_of_two_consecutive_degenerate_chunks():
    # Due frammenti degeneri consecutivi (es. "XIV." e un rimando "3.") devono
    # fondersi entrambi nel corpo, senza che il while si areni sull'indice o
    # perda uno dei due frammenti lungo il percorso.
    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 2
    out = _merge_degenerate_chunks(["XIV.", "3.", body], max_chars=2000, max_bytes=None)
    assert len(out) == 1
    assert out[0] == f"XIV.\n\n3.\n\n{body.lstrip()}"


def test_single_irreducible_chunk_survives_untouched():
    out = _merge_degenerate_chunks(["XIV."], max_chars=2000, max_bytes=None)
    assert out == ["XIV."]


def test_regular_chunks_are_returned_unchanged():
    a = "Prima frase lunga abbastanza da non essere un frammento qualunque."
    b = "Seconda frase lunga abbastanza da non essere un frammento qualunque."
    assert _merge_degenerate_chunks([a, b], max_chars=2000, max_bytes=None) == [a, b]


def test_plan_chunks_marks_irreducible_degenerate():
    from types import SimpleNamespace
    from tts_split import _plan_chunks

    ch = SimpleNamespace(index=0, title="XIV", text="XIV.", synthetic_title=False)
    info = SimpleNamespace(chapters=[ch], language="it")
    plan = _plan_chunks(info)
    assert len(plan) == 1
    assert plan[0]["degenerate"] is True


def test_plan_chunks_marks_regular_chapter_as_not_degenerate():
    from types import SimpleNamespace
    from tts_split import _plan_chunks

    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 5
    ch = SimpleNamespace(index=0, title="Capitolo I", text=body, synthetic_title=False)
    info = SimpleNamespace(chapters=[ch], language="it")
    plan = _plan_chunks(info)
    assert all(b["degenerate"] is False for b in plan)


def test_merge_never_loses_text_a_chapter_worth_of_content():
    # Invariante di sicurezza della fase di merge: qualunque fusione avvenga,
    # nessun frammento di testo puo' sparire. Confronto sui token normalizzati
    # (whitespace collassato) perche' il merge inserisce separatori "\n\n" tra i
    # chunk fusi.
    from types import SimpleNamespace
    from tts_split import _plan_chunks

    body = "Il mattino dopo la nave lasciò il porto con il vento a favore. " * 3
    ch = SimpleNamespace(index=0, title="XIV", text=body, synthetic_title=False)
    info = SimpleNamespace(chapters=[ch], language="it")
    plan = _plan_chunks(info)

    concatenated = " ".join(b["text"] for b in plan)
    normalized_out = " ".join(concatenated.split())
    # Il testo atteso e' titolo + corpo, cosi' come lo costruisce _plan_chunks
    # prima dello split (titolo non gia' presente nel body -> viene prependuto).
    expected = f"{ch.title}.\n\n{body}"
    normalized_expected = " ".join(expected.split())
    assert normalized_out == normalized_expected
