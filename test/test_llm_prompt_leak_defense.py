"""Difese contro echo del system prompt nell'output LLM.

Vedi piano: docs/superpowers/plans/2026-05-29-llm-prompt-leak-defense.md
"""
import json
from pathlib import Path

import pytest

import generation_engine as ge


def test_optimize_chapter_skips_llm_on_trivial_input(monkeypatch):
    """Input < 80 char di prosa non-narrativa non deve chiamare l'LLM."""
    calls = []

    def _fake_call_llm(user_content, job=None, max_retries=None):
        calls.append(user_content)
        return "MAI CHIAMATO"

    monkeypatch.setattr(ge, "_call_llm", _fake_call_llm)

    # Title-like: corto, senza punto finale
    result = ge._optimize_chapter_text("Prima meditazione")
    assert result == "Prima meditazione"
    assert calls == []


def test_optimize_chapter_skips_llm_on_single_short_line(monkeypatch):
    """Una sola riga di < 80 char senza punteggiatura terminale → pass-through."""
    calls = []
    monkeypatch.setattr(
        ge, "_call_llm",
        lambda *a, **kw: calls.append(a) or "MAI CHIAMATO"
    )
    result = ge._optimize_chapter_text("Emmanuele Silanos")
    assert result == "Emmanuele Silanos"
    assert calls == []


def test_optimize_chapter_calls_llm_on_real_prose(monkeypatch):
    """Prosa con punto fermo e > 80 char → l'LLM viene chiamato normalmente."""
    calls = []

    def _fake_call_llm(user_content, job=None, max_retries=None):
        calls.append(user_content)
        return "ottimizzato"

    monkeypatch.setattr(ge, "_call_llm", _fake_call_llm)

    text = ("Era una giornata particolarmente piovosa. "
            "Il cielo era coperto da nuvole grigie. "
            "Camminava lentamente verso casa.")
    result = ge._optimize_chapter_text(text)
    assert result == "ottimizzato"
    assert len(calls) == 1


def test_optimize_chapter_calls_llm_on_long_single_line_no_punct(monkeypatch):
    """Single-line > 2*soglia senza punteggiatura terminale → NON trivial.
    Probabile prosa mal-estratta (PDF), va comunque ottimizzata."""
    calls = []

    def _fake_call_llm(user_content, job=None, max_retries=None):
        calls.append(user_content)
        return "ottimizzato"

    monkeypatch.setattr(ge, "_call_llm", _fake_call_llm)

    # 200 char, single line, niente punteggiatura terminale
    text = "Questo e' un caso limite di prosa molto lunga estratta male da un PDF senza il punto finale che potrebbe essere stata mal-tagliata ma resta comunque prosa da ottimizzare in TTS naturalmente"
    assert len(text) > 2 * ge.LLM_TRIVIAL_INPUT_MIN_CHARS
    assert "\n" not in text
    result = ge._optimize_chapter_text(text)
    assert result == "ottimizzato"
    assert len(calls) == 1


def test_is_trivial_input_short_single_line_no_punct():
    """Direct unit test: short single-line senza punct → trivial."""
    assert ge._is_trivial_input("Capitolo primo") is True


def test_is_trivial_input_empty_and_whitespace():
    """Direct unit test: vuoto e whitespace → trivial."""
    assert ge._is_trivial_input("") is True
    assert ge._is_trivial_input(None) is True
    assert ge._is_trivial_input("   \n\t  ") is True


def test_is_trivial_input_below_threshold_with_punct():
    """Sotto soglia anche con punct → trivial (lunghezza domina)."""
    assert ge._is_trivial_input("Frase breve.") is True


def test_is_trivial_input_above_threshold_with_punct():
    """Sopra soglia con punct → NON trivial."""
    text = ("Era una giornata particolarmente piovosa quando arrivai a casa "
            "e trovai il giardino in disordine totale, una scena inattesa.")
    assert len(text) > ge.LLM_TRIVIAL_INPUT_MIN_CHARS
    assert ge._is_trivial_input(text) is False
