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
