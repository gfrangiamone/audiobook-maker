"""Il nome con cui l'upload finisce su disco deve SEMPRE conservare
l'estensione validata: secure_filename() su nomi interamente non-ASCII
(es. '姑妄言.pdf') restituisce 'pdf' — stringa non vuota ma senza punto — e il
file veniva salvato come '<jobdir>/pdf'. Conseguenze in produzione: descrittori
di recovery con input_path troncato e dispatch del parser sbagliato
(_parse_book cade su parse_txt quando manca il suffisso)."""
import importlib
import pytest


@pytest.fixture
def aa(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app


def test_nonascii_name_keeps_extension(aa):
    for original in ("那山,那人,那情.pdf", "姑妄言.pdf", "本の題名.epub"):
        ext = original.rsplit(".", 1)[1]
        safe = aa._safe_upload_name(original, ext)
        assert safe.endswith("." + ext), f"{original!r} -> {safe!r}"
        assert safe[: -len(ext) - 1], "manca lo stem prima dell'estensione"
        assert safe.isascii() and "/" not in safe and "\\" not in safe


def test_ascii_name_is_preserved(aa):
    assert aa._safe_upload_name("My Book.epub", "epub") == "My_Book.epub"
    assert aa._safe_upload_name("my.book.v2.pdf", "pdf") == "my.book.v2.pdf"


def test_missing_or_wrong_extension_is_restored(aa):
    assert aa._safe_upload_name("libro", "txt") == "libro.txt"
    assert aa._safe_upload_name("", "abm").endswith(".abm")
    assert aa._safe_upload_name("../../etc/passwd.pdf", "pdf") == "etc_passwd.pdf"


def test_names_are_unique_when_stem_is_lost(aa):
    a = aa._safe_upload_name("姑妄言.pdf", "pdf")
    b = aa._safe_upload_name("姑妄言.pdf", "pdf")
    assert a != b, "stem ricostruito deve essere unico per non collidere"
