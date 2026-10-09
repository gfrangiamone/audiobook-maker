"""D3 (2026-10-09): i tre motori premium fatturano corpo + titolo parlato con
una sola regola, `pricing_common.billable_chars` su `tts_split.spoken_title_prefix`.
Prima solo VoxCPM contava i titoli letti."""
import types

import pytest

import pricing_common
from tts_split import spoken_title_prefix


def _ch(title, text, synthetic=False):
    return types.SimpleNamespace(title=title, text=text, synthetic_title=synthetic)


def test_billable_text_rules():
    ch = _ch("Capitolo uno", "Era una notte buia.")
    assert pricing_common.billable_text(ch) == "Era una notte buia."
    assert pricing_common.billable_text(ch, spoken_title_prefix) == "Capitolo uno.\n\nEra una notte buia."
    norm = lambda s: " ".join(s.split())
    assert pricing_common.billable_text(ch, spoken_title_prefix, norm) == "Capitolo uno. Era una notte buia."
    assert pricing_common.billable_text(_ch("T", ""), spoken_title_prefix) == ""          # senza testo: niente
    assert pricing_common.billable_text(_ch("Section 3", "x", synthetic=True), spoken_title_prefix) == "x"
    assert pricing_common.billable_text(_ch("Prologo", "Prologo\nTesto"), spoken_title_prefix) == "Prologo\nTesto"  # dedup


def test_billable_chars_totals():
    chs = [_ch("Uno", "aaaa"), _ch("", "bb"), _ch("Tre", "")]
    per, total, texts = pricing_common.billable_chars(chs, spoken_title_prefix)
    assert texts == ["Uno.\n\naaaa", "bb", ""] and per == [10, 2, 0] and total == 12
    per, total, _ = pricing_common.billable_chars(chs)
    assert per == [4, 2, 0] and total == 6


def test_three_engines_count_the_spoken_title():
    import gemini_tts, speechify_tts, voxcpm_tts
    chs = [_ch("Un incontro inatteso", "Era una notte buia. " * 40),
           _ch("La lettera", "Il mattino dopo.\n\n   Con a capo. " * 30)]
    body = sum(len(c.text) for c in chs)
    titles = sum(len(spoken_title_prefix(c, c.text)) for c in chs)
    assert titles == len("Un incontro inatteso.\n\n") + len("La lettera.\n\n")
    vx =voxcpm_tts.estimate_book_cost(chs, "it")
    sp = speechify_tts.estimate_book_cost(chs, "en")
    ge = gemini_tts.estimate_book_cost(chs, "gemini:flash31:Zephyr", language="it")
    assert vx["chars_total"] == sp["chars_total"] == body + titles
    assert vx["chars_per_chapter"] == sp["chars_per_chapter"]
    # Gemini normalizza (whitespace collassato) l'intero testo letto, titolo compreso.
    expected = [len(gemini_tts._normalize_text(spoken_title_prefix(c, c.text) + c.text)) for c in chs]
    assert ge["chars_per_chapter"] == expected and ge["chars_total"] == sum(expected)
    assert all(g > len(gemini_tts._normalize_text(c.text)) for g, c in zip(expected, chs))


def test_titles_change_price_on_every_premium_engine():
    import gemini_tts, speechify_tts, voxcpm_tts
    with_t = [_ch("Un titolo lungo da leggere", "Corpo. " * 100)]
    without = [_ch("", "Corpo. " * 100)]
    est = {"voxcpm": lambda c: voxcpm_tts.estimate_book_cost(c, "it"),
           "speechify": lambda c: speechify_tts.estimate_book_cost(c, "en"),
           "gemini": lambda c: gemini_tts.estimate_book_cost(c, "gemini:flash31:Zephyr", language="it")}
    for name, fn in est.items():
        a, b = fn(with_t), fn(without)
        assert a["chars_total"] > b["chars_total"], name
