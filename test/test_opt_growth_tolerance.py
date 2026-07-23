"""Test della tolleranza di crescita del testo da ottimizzazione AI.

Un libro entro i limiti prima dell'ottimizzazione, espanso dall'LLM fino al 5%
oltre il cap, deve restare elaborabile (cap effettivo = base * 1.05 sui job
ai_optimized). I job non ottimizzati mantengono il cap base.
"""
import audiobook_app as app


def test_non_optimized_uses_base_cap():
    base = app._max_text_chars_for_voice("it-IT-ElsaNeural")
    assert app._effective_max_text_chars("it-IT-ElsaNeural", None) == base
    assert app._effective_max_text_chars("it-IT-ElsaNeural", {"ai_optimized": False}) == base


def test_optimized_gets_tolerance():
    base = app._max_text_chars_for_voice("it-IT-ElsaNeural")
    eff = app._effective_max_text_chars("it-IT-ElsaNeural", {"ai_optimized": True})
    assert eff == int(base * (1.0 + app.LLM_OPT_GROWTH_TOLERANCE))
    assert eff > base


def test_optimized_gemini_voice_tolerance():
    voice = "gemini:flash25:Charon"
    base = app._max_text_chars_for_voice(voice)
    assert base == app.MAX_GEMINI_TEXT_CHARS
    eff = app._effective_max_text_chars(voice, {"ai_optimized": True})
    assert eff == int(base * (1.0 + app.LLM_OPT_GROWTH_TOLERANCE))


def test_tolerance_boundary():
    """Crescita esattamente al 5% passa; oltre no."""
    base = app._max_text_chars_for_voice("it-IT-ElsaNeural")
    eff = app._effective_max_text_chars("it-IT-ElsaNeural", {"ai_optimized": True})
    grown_5pct = int(base * 1.05)
    assert grown_5pct <= eff           # entro tolleranza: elaborabile
    assert int(base * 1.051) > eff or app.LLM_OPT_GROWTH_TOLERANCE > 0.051
