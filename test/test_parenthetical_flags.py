"""Tests per la lettura opzionale del testo tra parentesi (tonde/quadre).

_strip_parenthetical accetta i flag strip_round/strip_square (default True =
comportamento storico). _plan_chunks li propaga. Regressione: il default deve
restare identico al comportamento pre-feature.
"""
import tts_split
from tts_split import _strip_parenthetical, _plan_chunks


class _FakeCh:
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text


class _FakeInfo:
    def __init__(self, chapters):
        self.chapters = chapters


# ── _strip_parenthetical: matrice dei 4 modi ──

def test_strip_both_default_removes_all():
    txt = "Alfa (tonda) e beta [quadra] fine."
    out = _strip_parenthetical(txt)
    assert "tonda" not in out
    assert "quadra" not in out
    assert "Alfa" in out and "beta" in out and "fine" in out


def test_read_round_keeps_round_strips_square():
    txt = "Alfa (tonda) e beta [quadra] fine."
    out = _strip_parenthetical(txt, strip_round=False, strip_square=True)
    assert "(tonda)" in out
    assert "quadra" not in out


def test_read_square_keeps_square_strips_round():
    txt = "Alfa (tonda) e beta [quadra] fine."
    out = _strip_parenthetical(txt, strip_round=True, strip_square=False)
    assert "[quadra]" in out
    assert "tonda" not in out


def test_read_both_keeps_all_content():
    txt = "Alfa (tonda) e beta [quadra] fine."
    out = _strip_parenthetical(txt, strip_round=False, strip_square=False)
    assert "(tonda)" in out
    assert "[quadra]" in out


def test_read_both_still_normalizes_whitespace():
    # Anche senza rimozione, la normalizzazione whitespace resta applicata:
    # unica differenza tra i modi = presenza/assenza del contenuto tra parentesi.
    txt = "Alfa   (x)    beta"
    out = _strip_parenthetical(txt, strip_round=False, strip_square=False)
    assert "   " not in out
    assert "(x)" in out


# ── _plan_chunks: propagazione dei flag ──

def test_plan_chunks_default_strips_parentheses():
    info = _FakeInfo([_FakeCh(0, "Cap", "Uno (due tre quattro cinque) sei.")])
    plan = _plan_chunks(info)
    joined = " ".join(b["text"] for b in plan)
    assert "due tre" not in joined


def test_plan_chunks_read_round_keeps_content_and_grows_chars():
    text = "Uno (contenuto abbastanza lungo da contare) sei."
    info = _FakeInfo([_FakeCh(0, "Cap", text)])
    stripped = _plan_chunks(info)  # default: rimuove
    kept = _plan_chunks(info, strip_round=False)  # legge le tonde
    chars_stripped = sum(b["chars"] for b in stripped)
    chars_kept = sum(b["chars"] for b in kept)
    assert chars_kept > chars_stripped
    assert "contenuto abbastanza lungo" in " ".join(b["text"] for b in kept)


def test_plan_chunks_flags_independent():
    text = "A (tonda) B [quadra] C."
    info = _FakeInfo([_FakeCh(0, "Cap", text)])
    only_square_read = _plan_chunks(info, strip_round=True, strip_square=False)
    joined = " ".join(b["text"] for b in only_square_read)
    assert "[quadra]" in joined
    assert "tonda" not in joined
