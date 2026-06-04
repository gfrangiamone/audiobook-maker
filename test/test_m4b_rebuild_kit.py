"""Test per il M4B rebuild kit (ripiego quando la conversione M4B fallisce).

Copre:
  - _build_ffmetadata_text: formato ;FFMETADATA1 (tag globali + capitoli)
  - build_m4b_rebuild_kit: struttura dello ZIP consegnato all'utente
"""
import json
import os
import zipfile

import audio_utils


def test_ffmetadata_text_chapters_and_meta():
    chapters = [
        {"title": "Capitolo 1", "start": 0, "end": 1000},
        {"title": "Capitolo 2", "start": 1000, "end": 3500},
    ]
    txt = audio_utils._build_ffmetadata_text(
        chapters=chapters, title="Titolo", author="Autore",
        year="2024", genre="Audiobook", description="Una descrizione")
    assert txt.startswith(";FFMETADATA1\n")
    assert "title=Titolo" in txt
    assert "album=Titolo" in txt
    assert "artist=Autore" in txt
    assert "album_artist=Autore" in txt
    assert "date=2024" in txt
    assert "genre=Audiobook" in txt
    assert "comment=Una descrizione" in txt
    # Due blocchi capitolo
    assert txt.count("[CHAPTER]") == 2
    assert "START=0" in txt and "END=1000" in txt
    assert "START=1000" in txt and "END=3500" in txt
    assert "title=Capitolo 2" in txt


def test_ffmetadata_escapes_special_chars():
    txt = audio_utils._build_ffmetadata_text(title="A=B;C#D")
    # I caratteri speciali del formato devono essere escapati
    assert "title=A\\=B\\;C\\#D" in txt


def test_ms_to_hms():
    assert audio_utils._ms_to_hms(0) == "00:00:00.000"
    assert audio_utils._ms_to_hms(3_661_500) == "01:01:01.500"


def _make_fake_mp3(path):
    # Non serve un MP3 reale: la funzione lo copia soltanto nello ZIP.
    # _get_audio_bitrate fallisce su file non audio e usa il fallback 48 kbps.
    with open(path, "wb") as f:
        f.write(b"\x00" * 4096)


def test_build_kit_structure(tmp_path):
    mp3 = tmp_path / "audio.mp3"
    _make_fake_mp3(str(mp3))
    cover = tmp_path / "cover.jpg"
    cover.write_bytes(b"\xff\xd8\xff\xe0jpegdata")
    out_zip = tmp_path / "kit.zip"

    chapters = [
        {"title": "Intro", "start": 0, "end": 2000},
        {"title": "Fine", "start": 2000, "end": 5000},
    ]
    ok = audio_utils.build_m4b_rebuild_kit(
        str(mp3), str(out_zip), chapters=chapters,
        title="Mio Libro", author="Tizio", cover_path=str(cover),
        language="it", description="desc")
    assert ok is True
    assert out_zip.exists()
    # Nessun file temporaneo lasciato indietro
    assert not (tmp_path / "kit.zip.tmp").exists()

    with zipfile.ZipFile(str(out_zip)) as zf:
        names = set(zf.namelist())
        assert "audiolibro.mp3" in names
        assert "chapters.json" in names
        assert "chapters.ffmetadata" in names
        assert "cover.jpg" in names
        assert "build_m4b.sh" in names
        assert "build_m4b.bat" in names
        assert "README.txt" in names

        meta = json.loads(zf.read("chapters.json").decode("utf-8"))
        assert meta["title"] == "Mio Libro"
        assert len(meta["chapters"]) == 2
        assert meta["chapters"][0]["start_ms"] == 0
        assert meta["chapters"][1]["end_ms"] == 5000

        sh = zf.read("build_m4b.sh").decode("utf-8")
        # Lo script include la cover e i metadati capitoli
        assert "cover.jpg" in sh
        assert "chapters.ffmetadata" in sh
        assert "-f ipod" in sh


def test_build_kit_missing_mp3_returns_false(tmp_path):
    out_zip = tmp_path / "kit.zip"
    ok = audio_utils.build_m4b_rebuild_kit(
        str(tmp_path / "nope.mp3"), str(out_zip), chapters=[])
    assert ok is False
    assert not out_zip.exists()


def test_build_kit_without_cover_uses_vn(tmp_path):
    mp3 = tmp_path / "audio.mp3"
    _make_fake_mp3(str(mp3))
    out_zip = tmp_path / "kit.zip"
    ok = audio_utils.build_m4b_rebuild_kit(
        str(mp3), str(out_zip), chapters=[{"title": "C1", "start": 0, "end": 1000}],
        title="X")
    assert ok is True
    with zipfile.ZipFile(str(out_zip)) as zf:
        assert "cover.jpg" not in zf.namelist()
        sh = zf.read("build_m4b.sh").decode("utf-8")
        assert "-vn" in sh
        assert "cover.jpg" not in sh
