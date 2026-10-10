"""F2a: ffmpeg_tools e' l'unico punto che lancia ffmpeg/ffprobe; i moduli
audio passano dalla foglia (flag, testo leniente, timeout, probe, transcodifica)."""
import inspect
import os
import re
import shutil
import subprocess
import wave

import pytest

import ffmpeg_tools as ft

HAS_FFMPEG = bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))


def _wav(path, seconds=0.5, rate=24000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(rate)
        w.writeframes(b"\x01\x00" * int(rate * seconds))


def test_leaf_and_single_owner_of_ffmpeg_literals():
    src = inspect.getsource(ft)
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine|audio_utils)\b", src, flags=re.M)
    import audio_utils, voice_clone_audio, voice_denoise, tts_split, voxcpm_tts, voice_clone_demo
    for mod in (voice_clone_audio, voice_denoise, tts_split, voxcpm_tts, voice_clone_demo):
        s = inspect.getsource(mod)
        assert "subprocess.run(" not in s.replace("subprocess.run(\n                    [sys.executable", ""), mod.__name__
        assert '["ffmpeg"' not in s and '["ffprobe"' not in s, mod.__name__      # niente comandi costruiti a mano
    assert audio_utils._SUBPROCESS_FLAGS is ft.SUBPROCESS_FLAGS and voice_clone_audio._SUBPROCESS_FLAGS is ft.SUBPROCESS_FLAGS
    assert audio_utils._TEXT_UTF8_LENIENT is ft.TEXT_LENIENT and voice_clone_audio._TEXT is ft.TEXT_LENIENT
    assert voice_clone_audio._tool is ft.tool
    assert tts_split._PCM_SAMPLE_RATE == ft.PCM_SAMPLE_RATE == 24000


def test_run_passes_flags_lenient_text_and_timeout(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["kw"] = list(cmd), kw
        return subprocess.CompletedProcess(cmd, 0, stdout="12.5\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    r = ft.run_ffmpeg(["-i", "x"], timeout=7)
    assert r.returncode == 0 and seen["cmd"][:5] == ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y"]
    assert seen["kw"]["timeout"] == 7 and seen["kw"]["capture_output"] is True
    assert seen["kw"]["errors"] == "replace" and seen["kw"]["encoding"] == "utf-8"
    for k, v in ft.SUBPROCESS_FLAGS.items():
        assert seen["kw"][k] == v
    assert ft.ffprobe_field("f.mp3", "duration") == "12.5" and ft.probe_duration("f.mp3") == 12.5
    assert seen["cmd"][0] == "ffprobe" and "format=duration" in seen["cmd"]


def test_probe_degrades_without_raising(monkeypatch, capsys):
    def boom(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(subprocess, "run", boom)
    assert ft.ffprobe_field("f.mp3", "duration") == "" and ft.probe_duration("f.mp3") == 0.0
    assert ft.probe_bitrate_kbps("f.mp3") is None
    assert "[ffprobe]" in capsys.readouterr().out
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="999000\n", stderr=""))
    assert ft.probe_bitrate_kbps("f.mp3") == 320                                   # clamp [32, 320]
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="abc\n", stderr=""))
    assert ft.probe_duration("f.mp3") == 0.0 and ft.probe_bitrate_kbps("f.mp3") is None


def test_pcm_transcode_failure_removes_partial_and_reports(tmp_path, monkeypatch, capsys):
    dst = tmp_path / "out.pcm"

    def fake_fail(cmd, **kw):
        dst.write_bytes(b"\x00\x00")                      # parziale lasciato da ffmpeg
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="boom")

    monkeypatch.setattr(subprocess, "run", fake_fail)
    assert ft.pcm_transcode(tmp_path / "in.mp3", dst, out_rate=24000, tag="t") is False
    assert not dst.exists() and "[t] transcodifica PCM fallita: boom" in capsys.readouterr().out

    def fake_timeout(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, kw.get("timeout"))

    monkeypatch.setattr(subprocess, "run", fake_timeout)
    assert ft.pcm_transcode(tmp_path / "in.pcm", dst, in_rate=48000, out_rate=48000, filters="atempo=1.2",
                            timeout=5) is False
    assert "timeout dopo 5s" in capsys.readouterr().out


def test_silence_and_temp_wav(tmp_path):
    p = tmp_path / "s.pcm"
    ft.write_pcm_silence(p, 0.5, rate=48000)
    assert p.stat().st_size == 48000
    ft.write_pcm_silence(p, 0)
    assert p.stat().st_size == 0
    with ft.temp_wav() as tmp:
        assert tmp.endswith(".wav") and os.path.exists(tmp)
        open(tmp, "wb").write(b"x")
    assert not os.path.exists(tmp)
    with pytest.raises(RuntimeError):
        ft.tool("no-such-binary-abm")


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe non nel PATH")
def test_real_ffmpeg_roundtrip(tmp_path):
    src = tmp_path / "in.wav"
    _wav(src, seconds=0.5)
    assert abs(ft.probe_duration(src) - 0.5) < 0.05
    dst = tmp_path / "out.pcm"
    assert ft.pcm_transcode(src, dst, out_rate=48000) is True
    assert abs(dst.stat().st_size - 48000) < 200                                  # 0.5 s a 48 kHz s16 mono
    slow = tmp_path / "slow.pcm"
    assert ft.pcm_transcode(dst, slow, in_rate=48000, out_rate=48000, filters="atempo=0.5") is True
    assert slow.stat().st_size > dst.stat().st_size * 1.8
