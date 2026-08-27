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
