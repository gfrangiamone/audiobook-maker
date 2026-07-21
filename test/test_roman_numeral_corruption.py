"""Regressione: clean_text_for_tts corrompeva il testo attorno a
"capitolo i..." / "parte i...".

Il passo sui numeri romani usava m.group(1) (il prefisso) al posto di
m.group(2) (il numerale) e li scambiava. Il match, case-insensitive anche
sul numerale, prendeva per numero romano la "i" iniziale di una parola
comune: "capitolo intendo" diventava "i capitolontendo". Il difetto
colpiva qualunque libro italiano contenente quelle sequenze.
"""
import epub_to_tts


def test_lowercase_word_after_capitolo_is_not_a_roman_numeral():
    testo = "17. In questo primo capitolo intendo ripercorrere il cammino."

    out = epub_to_tts.clean_text_for_tts(testo, expand_abbr=False)

    assert "capitolo intendo ripercorrere" in out
    assert "capitolontendo" not in out


def _pulito(testo):
    """clean_text_for_tts chiude con un punto per la prosodia TTS: qui
    interessa il testo, non quella normalizzazione."""
    return epub_to_tts.clean_text_for_tts(testo, expand_abbr=False).strip().rstrip(".")


def test_other_common_words_after_a_chapter_marker_survive():
    casi = [
        "nella parte iniziale del discorso",
        "un capitolo importante della storia",
        "la parte introduttiva del testo",
        "questo capitolo illustra il metodo",
    ]
    for testo in casi:
        out = _pulito(testo)
        assert out == testo, f"testo alterato: {testo!r} -> {out!r}"


def test_real_roman_numeral_keeps_prefix_before_numeral():
    # "Capitolo IV" deve restare tale: il numerale non va anteposto.
    assert _pulito("Capitolo IV") == "Capitolo IV"
    assert _pulito("Chapter XIV") == "Chapter XIV"


def test_real_roman_numeral_with_extra_spaces_is_normalised():
    assert _pulito("Parte   XII") == "Parte XII"
