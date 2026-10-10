"""F1c: le regole di testo pre-TTS vivono in text_reflow (foglia); tts_split le
riesporta; i motori non importano piu' tts_split (niente ciclo); CHUNK_MAX_CHARS
e' definito una volta sola, in tts_engines."""
import inspect
import re

import gemini_tts
import speechify_tts
import text_reflow
import tts_engines
import tts_split
import voxcpm_tts

NAMES = ("_flatten_ws", "_strip_parenthetical", "_normalize_shouting", "_CHIUSA_RE",
         "_ensure_heading_pause", "prepare_tts_text", "_normalize_for_title_match",
         "_title_already_in_text", "_sanitize_tts_text", "spoken_title_prefix")


def test_rules_defined_once_in_text_reflow_and_reexported():
    src_split = inspect.getsource(tts_split)
    for n in NAMES:
        assert getattr(tts_split, n) is getattr(text_reflow, n), n
        assert not re.search(rf"^def {n}\(", src_split, flags=re.M), n
    assert "def _plan_chunks(" in src_split                         # il piano resta nello splitter
    reflow = inspect.getsource(text_reflow)
    assert not re.search(r"^\s*(import|from) (?!re\b|unicodedata\b)\w+", reflow, flags=re.M)


def test_engines_do_not_import_tts_split():
    for mod in (voxcpm_tts, gemini_tts, speechify_tts):
        assert not re.search(r"^\s*(import tts_split|from tts_split import)", inspect.getsource(mod), flags=re.M), mod.__name__
    assert voxcpm_tts.spoken_title_prefix is text_reflow.spoken_title_prefix


def test_chunk_max_chars_single_source():
    assert tts_engines.CHUNK_MAX_CHARS == 2000
    assert tts_split.CHUNK_MAX_CHARS is tts_engines.CHUNK_MAX_CHARS
    assert "CHUNK_MAX_CHARS = 2000" not in inspect.getsource(tts_split)
    assert voxcpm_tts.CHUNK_MIN_CHARS <= voxcpm_tts.chunk_max_chars() <= tts_engines.CHUNK_MAX_CHARS


def test_prepare_tts_text_behaviour_unchanged():
    text = "TITOLO URLATO\n\nCorpo (nota) del paragrafo [rif]."
    assert text_reflow.prepare_tts_text(text) == "Titolo urlato. Corpo del paragrafo."
    assert text_reflow.prepare_tts_text(text, flatten=False) == "Titolo urlato.\n\nCorpo del paragrafo."
    assert text_reflow._sanitize_tts_text("  ​ ") is None
    assert text_reflow._sanitize_tts_text("perché") == "perché"

    class Ch:
        title, synthetic_title = "Capitolo 1: L'inizio", False
    assert text_reflow.spoken_title_prefix(Ch(), "Era una notte buia.") == "Capitolo 1: L'inizio.\n\n"
    assert text_reflow.spoken_title_prefix(Ch(), "L'inizio. Era una notte buia.") == ""
