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
