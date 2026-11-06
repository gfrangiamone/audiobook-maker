"""Marcatori di capitolo degli M4B: verificati dopo la scrittura, e scritti con
una scala dei tempi che regge i capitoli lunghi.

Il 06/11/2026 sei audiolibri del catalogo uscivano con l'audio giusto e i
capitoli ammucchiati a durata zero: rimuxando un M4B con la copertina copiata
(traccia 1/90000) accanto all'audio a 48 kHz, la traccia dei capitoli prendeva
1/720000 e ogni capitolo oltre ~49,7 minuti sforava i 32 bit.
"""
import json
import shutil
import subprocess

import pytest

import audio_utils

requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe non disponibili")


def _ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def _starts(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-print_format", "json", "-show_chapters", str(path)],
                       capture_output=True, check=True)
    return [round(float(c["start_time"])) for c in json.loads(r.stdout)["chapters"]]


def _cover(tmp_path):
    p = tmp_path / "c.jpg"
    _ff("-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(p))
    return str(p)


@requires_ffmpeg
def test_pcm_m4b_con_copertina_ha_i_capitoli_verificati(tmp_path, capsys):
    pcm = tmp_path / "a.pcm"
    pcm.write_bytes(b"\x00\x00" * 24000 * 6)
    out = str(tmp_path / "out.m4b")
    chapters = [{"title": "Capitolo I", "start": 0, "end": 2000},
                {"title": "Capitolo II", "start": 2000, "end": 4000},
                {"title": "Capitolo I", "start": 4000, "end": 6000}]
    assert audio_utils.pcm_to_aac_m4b([str(pcm)], out, chapters=chapters, title="Libro",
                                      cover_path=_cover(tmp_path))
    assert _starts(out) == [0, 2, 4]
    assert "non conformi" not in capsys.readouterr().out
    assert audio_utils._m4b_chapters_ok(out, chapters, "test")


@requires_ffmpeg
def test_capitoli_diversi_da_quelli_attesi_finiscono_nel_log(tmp_path, capsys):
    pcm = tmp_path / "a.pcm"
    pcm.write_bytes(b"\x00\x00" * 24000 * 4)
    out = str(tmp_path / "out.m4b")
    chapters = [{"title": "A", "start": 0, "end": 2000}, {"title": "B", "start": 2000, "end": 4000}]
    assert audio_utils.pcm_to_aac_m4b([str(pcm)], out, chapters=chapters, title="Libro")
    wrong = chapters + [{"title": "C", "start": 3000, "end": 4000}]
    assert not audio_utils._m4b_chapters_ok(out, wrong, "test")
    assert "capitoli dell'M4B non conformi: attesi 3, letti 2" in capsys.readouterr().out


@requires_ffmpeg
def test_capitolo_lungo_con_copertina_copiata_resta_al_suo_posto(tmp_path):
    cover, meta, src, dst = (tmp_path / n for n in ("c.jpg", "m.txt", "src.m4b", "dst.m4b"))
    _ff("-f", "lavfi", "-i", "color=c=red:s=64x64", "-frames:v", "1", str(cover))
    meta.write_text(";FFMETADATA1\n" + "".join(
        f"[CHAPTER]\nTIMEBASE=1/1000\nSTART={a}\nEND={b}\ntitle={t}\n"
        for t, a, b in (("Introduzione", 0, 2000), ("Lungo", 2000, 3102000), ("Corto", 3102000, 3112000))),
        encoding="utf-8")
    _ff("-f", "lavfi", "-t", "3112", "-i", "anullsrc=r=48000:cl=mono", "-i", str(cover), "-i", str(meta),
        "-map", "0:a", "-map", "1:v", "-map_chapters", "2", "-c:a", "aac", "-b:a", "16k", "-c:v", "copy",
        "-disposition:v:0", "attached_pic", "-f", "ipod", str(src))
    # Rimontaggio con la copertina presa dall'M4B: e' qui che i capitoli saltavano.
    _ff("-i", str(src), "-map", "0:a", "-map", "0:v:0", "-c", "copy", "-map_chapters", "0",
        "-disposition:v:0", "attached_pic", *audio_utils.M4B_MOVIE_TIMESCALE, "-f", "ipod", str(dst))
    assert _starts(dst) == [0, 2, 3102]
