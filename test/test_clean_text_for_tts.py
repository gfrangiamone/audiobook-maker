"""clean_text_for_tts: i NOISE_PATTERNS devono ripulire porzioni di riga,
non scartare l'intera riga.

Bug originale: il loop usava re.match()+break e, quando un pattern di
rumore matchava a INIZIO riga, scartava l'intera riga (replacement vuoto)
o la sostituiva col replacement. Conseguenza: un paragrafo narrativo che
inizia con "[1] ", un URL, "(vedi ...)", "pp. 12" o un marker heading
veniva eliminato per intero. LINE_SKIP_PATTERNS (skip riga intera) era
definito ma mai usato.
"""
from epub_to_tts import clean_text_for_tts


def _clean(s):
    # expand_abbr=False per isolare il comportamento dei pattern di rumore.
    return clean_text_for_tts(s, expand_abbr=False)


def test_footnote_marker_at_line_start_keeps_narrative():
    out = _clean("[1] Questo e' testo narrativo importante.")
    assert "Questo e' testo narrativo importante." in out
    assert "[1]" not in out


def test_see_reference_at_line_start_keeps_narrative():
    out = _clean("(vedi capitolo 3) il protagonista parte.")
    assert "il protagonista parte." in out
    assert "vedi capitolo 3" not in out


def test_url_at_line_start_keeps_rest_of_line():
    out = _clean("https://example.com e poi la storia continua.")
    assert "e poi la storia continua." in out
    assert "https://example.com" not in out


def test_page_ref_at_line_start_keeps_narrative():
    out = _clean("pp. 12-15 segue il racconto vero e proprio.")
    assert "segue il racconto vero e proprio." in out


def test_heading_marker_stripped_but_text_kept():
    out = _clean("## Capitolo Primo")
    assert "Capitolo Primo" in out
    assert "##" not in out


def test_noise_in_middle_still_removed():
    out = _clean("Il testo[1] continua qui.")
    assert "[1]" not in out
    assert "Il testo" in out
    assert "continua qui." in out


def test_pure_page_number_line_is_skipped():
    # LINE_SKIP_PATTERNS: una riga che e' solo un numero di pagina sparisce.
    out = _clean("Prima riga.\n42\nSeconda riga.")
    lines = [l for l in out.split("\n") if l.strip()]
    assert "Prima riga." in lines
    assert "Seconda riga." in lines
    assert "42" not in lines


def test_separator_line_is_skipped():
    out = _clean("Testo prima.\n-----\nTesto dopo.")
    assert "-----" not in out
    assert "Testo prima." in out
    assert "Testo dopo." in out


def test_normal_narrative_untouched():
    src = "Era una notte buia e tempestosa, e il vento ululava."
    out = _clean(src)
    assert "Era una notte buia e tempestosa" in out
    assert "il vento ululava" in out


def test_multiple_noise_patterns_same_line():
    # Sia marker nota sia simbolo § sulla stessa riga: entrambi rimossi,
    # narrativa preservata (prima il break applicava solo il primo pattern).
    out = _clean("[1] Paragrafo § con due rumori.")
    assert "Paragrafo" in out
    assert "con due rumori." in out
    assert "[1]" not in out
    assert "§" not in out
