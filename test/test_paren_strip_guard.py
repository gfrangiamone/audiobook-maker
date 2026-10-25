"""Guardia sugli span tolti da _strip_parenthetical (incidente 25/10/2026).

Con un PDF OCR una parentesi letta male apre uno span che la regex chiude
migliaia di caratteri dopo: la forma quadra ("[hr" per "Ihr" ... "Pal]" per
"Fall") e la forma tonda (`("Kommandos` senza chiusa ... `sinnvol)`), che si
accoppiava solo dopo che la prima era stata tolta. Uno span piu' lungo della
soglia, o che attraversa una riga vuota, resta nel testo parentesi comprese.
Testi sintetici: nessun libro reale.
"""
import pytest

from text_reflow import _strip_parenthetical, prepare_tts_text
from tts_split import _plan_chunks


class _FakeCh:
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text


class _FakeInfo:
    def __init__(self, chapters):
        self.chapters = chapters


@pytest.fixture(autouse=True)
def _default_threshold(monkeypatch):
    monkeypatch.delenv("ABM_PAREN_STRIP_MAX_CHARS", raising=False)


def _filler(n_par, tag):
    sent = f"Die Geschichte {tag} geht weiter und niemand weiss warum. "
    return "\n\n".join(f"Absatz {tag}{i}. " + sent * 4 for i in range(n_par))


# ── le due forme reali ──

def test_ocr_square_span_kept_with_brackets():
    txt = ("Sehr geehrte Frau, [hr Brief kam heute an.\n\n"
           + _filler(6, "q") + "\n\nIm Pal] stimmt das nicht. Ende.")
    out = _strip_parenthetical(txt)
    assert "[hr Brief" in out and "Pal] stimmt" in out
    assert out.count("Absatz q") == 6
    assert len(out) > 0.95 * len(" ".join(txt.split()))


def test_ocr_round_span_without_closure_kept():
    # Gli incisi brevi dentro lo span lungo restano incisi: si tolgono.
    body = _filler(5, "r").replace("Absatz r2.", "Absatz r2 (kurz).")
    txt = 'Er sagte ("Kommandos sind wichtig.\n\n' + body + "\n\nDas ist sinnvol) und ging."
    out = _strip_parenthetical(txt)
    assert '("Kommandos' in out and "sinnvol)" in out
    assert "kurz" not in out
    assert out.count("Absatz r") == 5


def test_ocr_round_span_does_not_pair_across_kept_square_span():
    # La sequenza dell'incidente: prima la quadra lunga, poi la tonda che la
    # contiene. La quadra resta, quindi anche la tonda e' lunga e resta.
    txt = ('Vorher ("Kommandos ohne Ende.\n\n' + _filler(2, "a")
           + "\n\n[hr Brief.\n\n" + _filler(4, "b") + "\n\nIm Pal] gut.\n\n"
           + _filler(2, "c") + "\n\nDas ist sinnvol) und Schluss.")
    out = _strip_parenthetical(txt)
    for tag, n in (("a", 2), ("b", 4), ("c", 2)):
        assert out.count(f"Absatz {tag}") == n
    assert "Schluss" in out and "Vorher" in out


def test_prepare_tts_text_and_plan_keep_ocr_span():
    txt = ("Anfang [hr Brief.\n\n" + _filler(8, "p") + "\n\nIm Pal] Ende.")
    out = prepare_tts_text(txt, strip_round=True, strip_square=True)
    assert out.count("Absatz p") == 8
    plan = _plan_chunks(_FakeInfo([_FakeCh(0, "Kapitel", txt)]))
    planned = sum(b["chars"] for b in plan)
    assert planned >= len(" ".join(txt.split())) * 0.95


# ── lo span tenuto non fa da ancora ──

def test_kept_span_does_not_anchor_outer_pairs():
    long_aside = "(" + "lang " * 120 + ")"
    txt = f"Eins (kurz) zwei ( offen {long_aside} drei (auch kurz) vier."
    out = _strip_parenthetical(txt)
    assert long_aside.strip("()").split()[0] in out
    assert out.count("lang") == 120
    assert "kurz" not in out
    assert "( offen (" in out


def test_long_pair_between_short_pairs():
    long_aside = "(" + "wort " * 100 + ")"
    txt = f"A (x) B {long_aside} C [y] D"
    out = _strip_parenthetical(txt)
    assert out.startswith("A B (wort")
    assert out.endswith(") C D")


# ── criterio del paragrafo ──

def test_short_span_across_blank_line_kept():
    txt = "Siehe (Abb. 3\n\n1) Erster Punkt der Liste."
    out = _strip_parenthetical(txt, flatten=False)
    assert out == txt


def test_span_with_single_newline_still_removed():
    txt = "Alfa (inciso su\ndue righe) beta."
    assert _strip_parenthetical(txt) == "Alfa beta."


# ── soglia ──

def test_threshold_boundary(monkeypatch):
    monkeypatch.setenv("ABM_PAREN_STRIP_MAX_CHARS", "20")
    at = "(" + "x" * 18 + ")"       # 20 caratteri: si toglie
    over = "(" + "y" * 19 + ")"     # 21 caratteri: resta
    assert _strip_parenthetical(f"a {at} b") == "a b"
    assert _strip_parenthetical(f"a {over} b") == f"a {over} b"


def test_length_measured_on_original_text(monkeypatch):
    # La coppia interna tolta conta nella lunghezza di quella esterna.
    monkeypatch.setenv("ABM_PAREN_STRIP_MAX_CHARS", "20")
    out = _strip_parenthetical("X (aaaa (bbbbbbbbbbbb) cccc) Y")
    assert out == "X (aaaa cccc) Y"


def test_threshold_zero_disables_length_guard(monkeypatch):
    monkeypatch.setenv("ABM_PAREN_STRIP_MAX_CHARS", "0")
    txt = "a (" + "z " * 400 + ") b"
    assert _strip_parenthetical(txt) == "a b"


def test_default_threshold_keeps_long_aside():
    long_aside = "(" + "n" * 399 + ")"   # 401 caratteri
    assert long_aside in _strip_parenthetical(f"a {long_aside} b")
    short_aside = "(" + "n" * 398 + ")"  # 400 caratteri
    assert _strip_parenthetical(f"a {short_aside} b") == "a b"


# ── casi normali invariati ──

@pytest.mark.parametrize("txt, expected", [
    ("Alfa (tonda) e beta [quadra] fine.", "Alfa e beta fine."),
    ("Alfa (a (b) c) beta.", "Alfa beta."),
    ("Alfa (a [b] c) beta.", "Alfa beta."),
    ("Alfa [a (b) c] beta.", "Alfa beta."),
    ("Alfa ((x)) beta.", "Alfa beta."),
    ("Alfa (aperta e mai chiusa beta.", "Alfa (aperta e mai chiusa beta."),
    ("Alfa chiusa) beta (x).", "Alfa chiusa) beta."),
    ("Nota [1] e nota [2].", "Nota e nota."),
])
def test_normal_cases_unchanged(txt, expected):
    assert _strip_parenthetical(txt) == expected


def test_flags_still_select_bracket_type():
    txt = "Alfa (tonda) e beta [quadra] fine."
    assert _strip_parenthetical(txt, strip_round=False) == "Alfa (tonda) e beta fine."
    assert _strip_parenthetical(txt, strip_square=False) == "Alfa e beta [quadra] fine."
    assert _strip_parenthetical(txt, False, False) == txt


def test_private_use_chars_in_text_survive():
    txt = "Alfa  (x) beta ."
    assert _strip_parenthetical(txt) == "Alfa  beta ."
