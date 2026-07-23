"""Tests for PCM helpers in audio_utils.py."""
import shutil
import pytest
import audio_utils


ffmpeg_missing = shutil.which("ffmpeg") is None


def test_pcm_size_to_seconds_one_second_24k_mono_16bit():
    assert audio_utils.pcm_size_to_seconds(48_000) == pytest.approx(1.0, abs=0.001)


def test_pcm_size_to_seconds_zero():
    assert audio_utils.pcm_size_to_seconds(0) == 0.0


def test_pcm_size_to_seconds_custom_format():
    result = audio_utils.pcm_size_to_seconds(176_400, sample_rate=44100, channels=2, sample_width=2)
    assert result == pytest.approx(1.0, abs=0.001)


def test_pcm_concat_simple(tmp_path):
    p1 = tmp_path / "a.pcm"
    p2 = tmp_path / "b.pcm"
    p1.write_bytes(b"\x01\x02\x03\x04")
    p2.write_bytes(b"\x05\x06\x07\x08")
    out = tmp_path / "combined.pcm"
    audio_utils.pcm_concat([str(p1), str(p2)], str(out))
    assert out.read_bytes() == b"\x01\x02\x03\x04\x05\x06\x07\x08"


def test_pcm_concat_empty_list(tmp_path):
    out = tmp_path / "empty.pcm"
    audio_utils.pcm_concat([], str(out))
    assert out.exists()
    assert out.read_bytes() == b""


def test_pcm_concat_skips_missing(tmp_path):
    p1 = tmp_path / "a.pcm"
    p1.write_bytes(b"data1")
    missing = tmp_path / "missing.pcm"
    out = tmp_path / "out.pcm"
    audio_utils.pcm_concat([str(p1), str(missing)], str(out), skip_missing=True)
    assert out.read_bytes() == b"data1"


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pcm_to_mp3_produces_valid_mp3(tmp_path):
    pcm = tmp_path / "silence.pcm"
    pcm.write_bytes(b"\x00\x00" * 12_000)
    out = tmp_path / "out.mp3"
    ok = audio_utils.pcm_to_mp3([str(pcm)], str(out))
    assert ok is True
    assert out.exists()
    assert out.read_bytes()[:2] in (b"\xff\xfb", b"\xff\xfa", b"\xff\xf3", b"ID")


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pcm_to_mp3_concatenates_multiple(tmp_path):
    pcm1 = tmp_path / "a.pcm"
    pcm2 = tmp_path / "b.pcm"
    pcm1.write_bytes(b"\x00\x00" * 6_000)
    pcm2.write_bytes(b"\x00\x00" * 6_000)
    out = tmp_path / "concat.mp3"
    ok = audio_utils.pcm_to_mp3([str(pcm1), str(pcm2)], str(out))
    assert ok is True
    assert out.stat().st_size > 0


def test_pcm_to_mp3_empty_list_returns_false(tmp_path):
    out = tmp_path / "out.mp3"
    ok = audio_utils.pcm_to_mp3([], str(out))
    assert ok is False


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pcm_to_aac_m4b_basic(tmp_path):
    pcm = tmp_path / "sample.pcm"
    pcm.write_bytes(b"\x00\x00" * 24_000)
    out = tmp_path / "out.m4b"
    ok = audio_utils.pcm_to_aac_m4b([str(pcm)], str(out))
    assert ok is True
    assert out.exists()
    assert out.stat().st_size > 0
    header = out.read_bytes()[:12]
    assert b"ftyp" in header


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_pcm_to_aac_m4b_with_chapters(tmp_path):
    pcm1 = tmp_path / "ch1.pcm"
    pcm2 = tmp_path / "ch2.pcm"
    pcm1.write_bytes(b"\x00\x00" * 24_000)
    pcm2.write_bytes(b"\x00\x00" * 48_000)
    out = tmp_path / "book.m4b"
    chapters = [
        {"title": "Capitolo 1", "start": 0, "end": 1000},
        {"title": "Capitolo 2", "start": 1000, "end": 3000},
    ]
    ok = audio_utils.pcm_to_aac_m4b(
        [str(pcm1), str(pcm2)],
        str(out),
        chapters=chapters,
        title="Libro Test",
        author="Autore Test",
    )
    assert ok is True
    assert out.stat().st_size > 0


def test_pcm_to_aac_m4b_empty_returns_false(tmp_path):
    out = tmp_path / "empty.m4b"
    assert audio_utils.pcm_to_aac_m4b([], str(out)) is False
