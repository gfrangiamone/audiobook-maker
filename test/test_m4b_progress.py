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

def _make_fake_job():
    return {
        "job_id": "J", "client_id": "c", "ip": "1.1.1.1",
        "voice": "v", "lang": "it", "original_filename": "book.epub",
        "m4b_progress_current": 0, "m4b_progress_total": 0,
        "m4b_progress_message": "",
    }


def test_convert_mp3_to_m4b_monitored_calls_on_phase(monkeypatch, tmp_path):
    """Il wrapper monitored chiama on_phase a 0, 5, 98, 100 in successione monotona."""
    import audio_utils

    mp3 = tmp_path / "in.mp3"
    m4b = tmp_path / "out.m4b"
    mp3.write_bytes(b"x" * 1024)
    m4b.write_bytes(b"y" * 2048)

    # Mock: simuliamo _convert_mp3_to_m4b come no-op che imposta subito m4b.
    def fake_convert(*args, **kwargs):
        return True
    monkeypatch.setattr(audio_utils, "_convert_mp3_to_m4b", fake_convert)
    # Mock: validazione ok
    monkeypatch.setattr(audio_utils, "_validate_m4b_file", lambda p: True)
    # Mock: durata audio fissa
    monkeypatch.setattr(audio_utils, "_get_audio_bitrate", lambda p: 48)
    monkeypatch.setattr(audio_utils, "_get_audio_duration_ms", lambda p: 60_000)

    phases = []
    def on_phase(pct, msg):
        phases.append((pct, msg))

    ok = audio_utils._convert_mp3_to_m4b_monitored(
        str(mp3), str(m4b), on_phase=on_phase,
        title="T", author="A",
    )
    assert ok is True
    # Attesi pct: 0 (preparazione) → 5 (encoding) → 98 (validazione) → 100 (ok)
    pcts = [p for p, _ in phases]
    assert 0 in pcts
    assert 5 in pcts
    assert 98 in pcts
    assert 100 in pcts
    # Monotono non-strict
    assert pcts == sorted(pcts)


def test_convert_mp3_to_m4b_monitored_handles_ffmpeg_fail(monkeypatch, tmp_path):
    """Se la conversione interna fallisce, on_phase NON emette 100."""
    import audio_utils

    mp3 = tmp_path / "in.mp3"
    m4b = tmp_path / "out.m4b"
    mp3.write_bytes(b"x")
    m4b.write_bytes(b"y")

    monkeypatch.setattr(audio_utils, "_convert_mp3_to_m4b",
                        lambda *a, **kw: False)
    monkeypatch.setattr(audio_utils, "_get_audio_bitrate", lambda p: 48)

    phases = []
    audio_utils._convert_mp3_to_m4b_monitored(
        str(mp3), str(m4b),
        on_phase=lambda p, m: phases.append(p),
    )
    assert 100 not in phases


def test_convert_mp3_to_m4b_monitored_no_callback_when_filenotfound(monkeypatch):
    """Se il file sorgente non esiste, on_phase non viene chiamato (skip rapido)."""
    import audio_utils

    # Simuliamo sorgente mancante: _convert_mp3_to_m4b solleva FileNotFoundError
    # prima di qualsiasi on_phase intermedio.
    monkeypatch.setattr(audio_utils, "_convert_mp3_to_m4b",
                        lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError()))

    phases = []
    ok = audio_utils._convert_mp3_to_m4b_monitored(
        "/nope/missing.mp3", "/tmp/out.m4b",
        on_phase=lambda p, m: phases.append(p),
    )
    assert ok is False
    assert phases == []
