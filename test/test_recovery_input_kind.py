"""Recovery di descrittori con input_path privo di estensione (job caricati
con nome interamente non-ASCII prima del fix su _safe_upload_name): il file su
disco si chiama letteralmente 'pdf'/'epub'/'txt', esiste, ma _parse_book —
che smista per suffisso — cadeva su parse_txt e il recovery falliva sempre."""
import importlib
import io
import zipfile
import pytest


@pytest.fixture
def aa(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app


def _spy(aa, monkeypatch):
    calls = []
    monkeypatch.setattr(aa, "parse_pdf", lambda p, *a, **k: calls.append(("pdf", p)))
    monkeypatch.setattr(aa, "parse_epub", lambda p, *a, **k: calls.append(("epub", p)))
    monkeypatch.setattr(aa, "parse_txt", lambda p, *a, **k: calls.append(("txt", p)))
    monkeypatch.setattr(aa, "parse_abm", lambda p, *a, **k: (calls.append(("abm", p)), None))
    return calls


def _zip(**entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name.replace("__", "."), data)
    return buf.getvalue()


def test_extensionless_pdf_uses_pdf_parser(aa, monkeypatch, tmp_path):
    calls = _spy(aa, monkeypatch)
    p = tmp_path / "pdf"
    p.write_bytes(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    aa._parse_book(str(p))
    assert calls and calls[0][0] == "pdf"


def test_extensionless_epub_uses_epub_parser(aa, monkeypatch, tmp_path):
    calls = _spy(aa, monkeypatch)
    p = tmp_path / "epub"
    p.write_bytes(_zip(mimetype="application/epub+zip"))
    aa._parse_book(str(p))
    assert calls and calls[0][0] == "epub"


def test_extensionless_abm_uses_abm_parser(aa, monkeypatch, tmp_path):
    calls = _spy(aa, monkeypatch)
    p = tmp_path / "abm"
    p.write_bytes(_zip(manifest__json='{"title": "x"}'))
    aa._parse_book(str(p))
    assert calls and calls[0][0] == "abm"


def test_extensionless_text_falls_back_to_txt(aa, monkeypatch, tmp_path):
    calls = _spy(aa, monkeypatch)
    p = tmp_path / "txt"
    p.write_text("Capitolo primo\n", encoding="utf-8")
    aa._parse_book(str(p))
    assert calls and calls[0][0] == "txt"


def test_extension_still_wins_when_present(aa, monkeypatch, tmp_path):
    calls = _spy(aa, monkeypatch)
    p = tmp_path / "libro.epub"
    p.write_bytes(_zip(mimetype="application/epub+zip"))
    aa._parse_book(str(p))
    assert calls and calls[0][0] == "epub"
