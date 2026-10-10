"""F1b: parser TXT/ABM in plain_parsers (foglia), abbreviazioni in text_reflow
e applicate anche a TXT e ABM (cambio voluto)."""
import inspect
import json
import re
import zipfile

import epub_to_tts
import generation_engine
import plain_parsers
import text_reflow
from book_model import BookInfo


def test_plain_parsers_is_a_leaf_and_the_engine_keeps_only_aliases():
    src = inspect.getsource(plain_parsers)
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine|epub_to_tts|tts_split)\b", src, flags=re.M)
    ge = inspect.getsource(generation_engine)
    assert "def parse_txt" not in ge and "def parse_abm" not in ge
    assert generation_engine.parse_txt is plain_parsers.parse_txt
    assert generation_engine.parse_abm is plain_parsers.parse_abm
    import audiobook_app
    assert audiobook_app.parse_txt is plain_parsers.parse_txt and audiobook_app.parse_abm is plain_parsers.parse_abm
    assert ge.count("import llm_client\n") == 1                      # residuo triplicato di D2a rimosso


def test_abbreviations_live_in_text_reflow():
    assert epub_to_tts.ABBREVIATIONS is text_reflow.ABBREVIATIONS
    assert "ABBREVIATIONS = {" not in inspect.getsource(epub_to_tts)
    # ordine: la forma lunga prima della corta, confini di parola, case-insensitive
    assert text_reflow.expand_abbreviations("vedi op. cit. e cit. ECC. decit.") == \
        "vedi opera citata e citato eccetera decit."
    assert text_reflow.expand_abbreviations("Il Dr. Rossi") == "Il Doctor Rossi"
    assert epub_to_tts.clean_text_for_tts("Mele, pere ecc.").startswith("Mele, pere eccetera")
    assert "ecc." in epub_to_tts.clean_text_for_tts("Mele, pere ecc.", expand_abbr=False)


def test_txt_and_abm_expand_abbreviations(tmp_path):
    p = tmp_path / "Il_mio-libro.txt"
    p.write_text("Frutta: mele, pere ecc.\n\nFine.", encoding="utf-8")
    info = plain_parsers.parse_txt(str(p))
    assert isinstance(info, BookInfo) and info.title == "Il mio libro"
    assert info.chapters[0].text == "Frutta: mele, pere eccetera\n\nFine."
    abm = tmp_path / "libro.abm"
    with zipfile.ZipFile(abm, "w") as zf:
        zf.writestr("manifest.json", json.dumps({
            "format": "audiobook-maker-project", "title": "T", "author": "A", "language": "it",
            "chapters": [{"index": 1, "title": "Uno", "filename": "001.txt"}]}))
        zf.writestr("chapters/001.txt", "Vedi pag. 3 e fig. 2.")
    info, cover = plain_parsers.parse_abm(str(abm))
    assert cover is None and info.language == "it"
    assert info.chapters[0].text == "Vedi pagina 3 e figura 2."
    assert info.total_chars == len(info.chapters[0].text)


def test_abm_errors_are_value_errors(tmp_path):
    bad = tmp_path / "x.abm"
    bad.write_bytes(b"not a zip")
    try:
        plain_parsers.parse_abm(str(bad))
    except ValueError as e:
        assert "not a valid ZIP" in str(e)
    else:
        raise AssertionError("atteso ValueError")
