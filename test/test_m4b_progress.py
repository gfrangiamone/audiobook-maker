"""Test per la feature M4B progress (vedi spec 2026-06-02-m4b-progress-design.md)."""
import time
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Task 1 — _log_m4b_progress
# ---------------------------------------------------------------------------

def test_log_m4b_progress_emits_start_line(tmp_path, monkeypatch):
    """_log_m4b_progress con event=START deve scrivere 1 riga M4B_START."""
    import audiobook_app

    captured = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: captured.append((a, kw)))
    job = {"job_id": "J1", "client_id": "c1", "ip": "1.2.3.4",
           "voice": "it-IT-Isola", "lang": "it"}

    audiobook_app._log_m4b_progress(job, "START", size_mb=12.3, msg="start")

    assert len(captured) == 1
    args, kwargs = captured[0]
    assert args[0] == "J1"
    assert args[2] == "M4B_START"


def test_log_m4b_progress_throttles_progress_lines(monkeypatch):
    """Chiamate ravvicinate M4B_PROGRESS: solo la prima emette riga."""
    import audiobook_app

    captured = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: captured.append((a, kw)))
    job = {"job_id": "J2", "_m4b_last_log_ts": 0.0}

    for pct in (10, 20, 30):
        audiobook_app._log_m4b_progress(job, "PROGRESS", pct=pct, msg="enc")

    # Solo la prima passa (timestamp=0.0 < now-10). Le altre 2 sono filtrate
    # solo se nel frattempo _m4b_last_log_ts è stato aggiornato.
    # Però qui il throttling controlla `now - last >= 10`: a 0.0 la prima passa,
    # poi la seconda chiama throttling=False (now-last < 10) e viene filtrata.
    # Verifichiamo che in 3 chiamate ravvicinate ci sia <= 1 emissione.
    assert len(captured) <= 1


def test_log_m4b_progress_end_no_throttle(monkeypatch):
    """M4B_END non è soggetto a throttling."""
    import audiobook_app

    captured = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: captured.append((a, kw)))
    job = {"job_id": "J3", "_m4b_last_log_ts": time.time()}

    audiobook_app._log_m4b_progress(job, "END", status="ok", pct=100, size_mb=50.0)

    assert len(captured) == 1
    assert captured[0][0][2] == "M4B_END"


# ---------------------------------------------------------------------------
# Task 2 — _convert_mp3_to_m4b_monitored
# ---------------------------------------------------------------------------

def test_convert_mp3_to_m4b_monitored_calls_on_phase(monkeypatch, tmp_path):
    """Il wrapper monitored chiama on_phase esattamente a 0, 5, 98, 100 in ordine."""
    import audio_utils

    mp3 = tmp_path / "in.mp3"
    m4b = tmp_path / "out.m4b"
    mp3.write_bytes(b"x" * 1024)
    m4b.write_bytes(b"y" * 2048)

    # Mock: simuliamo _convert_mp3_to_m4b come no-op che ritorna True.
    monkeypatch.setattr(audio_utils, "_convert_mp3_to_m4b", lambda *a, **kw: True)
    monkeypatch.setattr(audio_utils, "_validate_m4b_file", lambda p: True)

    phases = []
    status_out = {}
    ok = audio_utils._convert_mp3_to_m4b_monitored(
        str(mp3), str(m4b),
        on_phase=lambda p, m: phases.append((p, m)),
        status_out=status_out,
        title="T", author="A",
    )
    assert ok is True
    assert len(phases) == 4
    assert phases[0] == (0, "Conversione M4B — preparazione metadati…")
    assert phases[1] == (5, "Conversione M4B — encoding AAC…")
    assert phases[2] == (98, "Conversione M4B — validazione finale…")
    assert phases[3] == (100, "Conversione M4B completata")
    assert status_out == {"status": "ok", "pct": 100, "msg": "Conversione M4B completata"}


def test_convert_mp3_to_m4b_monitored_handles_ffmpeg_fail(monkeypatch, tmp_path):
    """Se la conversione interna fallisce, status_out riceve 'fail' e pct non è 100."""
    import audio_utils

    mp3 = tmp_path / "in.mp3"
    m4b = tmp_path / "out.m4b"
    mp3.write_bytes(b"x")
    m4b.write_bytes(b"y")

    monkeypatch.setattr(audio_utils, "_convert_mp3_to_m4b", lambda *a, **kw: False)

    phases = []
    status_out = {}
    ok = audio_utils._convert_mp3_to_m4b_monitored(
        str(mp3), str(m4b),
        on_phase=lambda p, m: phases.append(p),
        status_out=status_out,
    )
    assert ok is False
    assert 100 not in phases
    assert status_out.get("status") == "fail"


def test_convert_mp3_to_m4b_monitored_no_callback_when_source_missing(tmp_path):
    """Se il file sorgente non esiste, on_phase non viene chiamato e status='fail'."""
    import audio_utils

    phases = []
    status_out = {}
    ok = audio_utils._convert_mp3_to_m4b_monitored(
        "/nope/missing.mp3", "/tmp/out.m4b",
        on_phase=lambda p, m: phases.append(p),
        status_out=status_out,
    )
    assert ok is False
    assert phases == []
    assert status_out.get("status") == "fail"


def test_convert_mp3_to_m4b_monitored_handles_timeout(monkeypatch, tmp_path):
    """Se FFmpeg va in timeout, status_out riceve 'timeout'."""
    import subprocess
    import audio_utils

    mp3 = tmp_path / "in.mp3"
    m4b = tmp_path / "out.m4b"
    mp3.write_bytes(b"x")
    m4b.write_bytes(b"y")

    def raise_timeout(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="ffmpeg", timeout=3600)
    monkeypatch.setattr(audio_utils, "_convert_mp3_to_m4b", raise_timeout)

    status_out = {}
    ok = audio_utils._convert_mp3_to_m4b_monitored(
        str(mp3), str(m4b),
        on_phase=lambda p, m: None,
        status_out=status_out,
    )
    assert ok is False
    assert status_out.get("status") == "timeout"


def test_convert_mp3_to_m4b_monitored_handles_invalid_file(monkeypatch, tmp_path):
    """Se la validazione ffprobe fallisce, status_out riceve 'invalid'."""
    import audio_utils

    mp3 = tmp_path / "in.mp3"
    m4b = tmp_path / "out.m4b"
    mp3.write_bytes(b"x")
    m4b.write_bytes(b"y")

    monkeypatch.setattr(audio_utils, "_convert_mp3_to_m4b", lambda *a, **kw: True)
    monkeypatch.setattr(audio_utils, "_validate_m4b_file", lambda p: False)

    status_out = {}
    ok = audio_utils._convert_mp3_to_m4b_monitored(
        str(mp3), str(m4b),
        on_phase=lambda p, m: None,
        status_out=status_out,
    )
    assert ok is False
    assert status_out.get("status") == "invalid"
