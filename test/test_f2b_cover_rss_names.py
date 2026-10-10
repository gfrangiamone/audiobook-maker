"""F2b: copertine in cover_utils, RSS in podcast_rss, nomi file sicuri in fileio
(regola unica, anche per translation_core)."""
import inspect
import re

import pytest

import audio_utils
import cover_utils
import fileio
import podcast_rss
import translation_core


def test_modules_are_leaves_and_audio_utils_keeps_no_copy():
    for mod in (cover_utils, podcast_rss):
        src = inspect.getsource(mod)
        assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine|audio_utils)\b", src, flags=re.M), mod.__name__
    au = inspect.getsource(audio_utils)
    for name in ("def _extract_cover_from_epub(", "def _generate_fallback_cover(", "def _include_cover_in_dir(",
                 "def _generate_podcast_rss(", "def _safe_filename(", "def truncate_filename(", "MAX_FILENAME_BYTES = "):
        assert name not in au, name
    assert "def _extract_cover_from_epub(" in inspect.getsource(cover_utils)
    assert "def _generate_podcast_rss(" in inspect.getsource(podcast_rss)
    assert "ffmpeg_tools.probe_duration(" in inspect.getsource(podcast_rss)
    assert "fileio.safe_filename(" in au and "fileio.safe_filename(" in inspect.getsource(translation_core)
    import audiobook_app, generation_engine
    assert audiobook_app._safe_filename is fileio.safe_filename and generation_engine._safe_filename is fileio.safe_filename
    assert audiobook_app._generate_podcast_rss is podcast_rss._generate_podcast_rss
    assert generation_engine._include_cover_in_dir is cover_utils._include_cover_in_dir


def test_safe_filename_keeps_the_two_historical_forms():
    # forma audio (storica di audio_utils._safe_filename)
    assert fileio.safe_filename("Il mio: libro? v1.2") == "Il_mio_libro_v12"
    assert fileio.safe_filename("-rf tutto") == "_-rf_tutto"
    assert fileio.safe_filename("\x00Titolo\x1f") == "Titolo"
    assert len(fileio.safe_filename("x" * 300)) == 100
    assert len(fileio.safe_filename("é" * 200).encode("utf-8")) <= fileio.MAX_FILENAME_BYTES
    # forma traduzione (storica di translation_core._safe_filename)
    assert translation_core._safe_filename('Libro: "due" / tre.epub') == "Libro_ _due_ _ tre.epub"
    assert translation_core._safe_filename(" .. ") == "untitled"
    assert translation_core._safe_filename("x" * 300) == "x" * 300          # nessun limite qui
    assert translation_core._safe_filename("-a") == "-a"


def test_fallback_cover_and_rss_still_work(tmp_path):
    out = tmp_path / "cover.jpg"
    ok = cover_utils._generate_fallback_cover(str(out), title="Titolo", author="Autore")
    assert ok is False or out.exists()                                # senza PIL: False, pulito
    mp3 = tmp_path / "001.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 6000)
    rss = tmp_path / "feed.xml"
    import types
    info = types.SimpleNamespace(title="Libro", author="A", language="it", chapters=[], description="")
    podcast_rss._generate_podcast_rss(info, [str(mp3)], str(rss), base_url="https://x", cover_filename="")
    text = rss.read_text(encoding="utf-8")
    assert "<rss" in text and "001.mp3" in text and "itunes:duration" in text
