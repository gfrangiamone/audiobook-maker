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


def test_min_chars_is_parametric():
    text = "Una frase di media lunghezza che supera i quaranta caratteri."
    assert _is_degenerate_chunk(text, min_chars=10) is False
    assert _is_degenerate_chunk(text, min_chars=200) is True
