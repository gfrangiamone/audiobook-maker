# Hardening locali 2026-06-06: console Windows cp1252 + preflight ffmpeg
# nella preview PREMIUM (vedi incidente UnicodeEncodeError '→' / preview 500).
import time
import pytest
from unittest.mock import patch

import audiobook_app


# ── Hardening 1: console encoding ──────────────────────────────────────


class _StreamWithReconfigure:
    def __init__(self):
        self.calls = []

    def reconfigure(self, **kw):
        self.calls.append(kw)


class _StreamWithoutReconfigure:
    pass


def test_harden_console_encoding_reconfigures_streams():
    s1, s2 = _StreamWithReconfigure(), _StreamWithReconfigure()
    audiobook_app._harden_console_encoding(s1, s2)
    assert s1.calls == [{"errors": "replace"}]
    assert s2.calls == [{"errors": "replace"}]


def test_harden_console_encoding_tolerates_streams_without_reconfigure():
    # pytest/capture e stream esotici non hanno reconfigure: mai sollevare.
    audiobook_app._harden_console_encoding(
        _StreamWithoutReconfigure(), None)


# ── Hardening 2: preflight ffmpeg nella preview PREMIUM ────────────────


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def _seed_preview_job(job_id="PVJ1"):
    audiobook_app.jobs[job_id] = {
        "status": "analyzed",
        "client_id": "c1",
        "client_ip": "127.0.0.1",
        "preview_text": "Testo di prova per anteprima audio.",
        "original_filename": "x.txt",
        "last_poll": time.time(),
    }
    return audiobook_app.jobs[job_id]


def test_premium_preview_503_when_ffmpeg_missing(client, monkeypatch):
    _seed_preview_job()
    # Gemini "configurato" ma ffmpeg assente: deve fallire PRIMA di
    # consumare token/cap, con errore chiaro.
    monkeypatch.setattr(audiobook_app.gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(
        audiobook_app, "_preview_ffmpeg_ok", lambda: False)
    with patch("audiobook_app._check_job_owner",
               return_value=(audiobook_app.jobs["PVJ1"], None, None)):
        r = client.get("/api/preview_audio/PVJ1?voice=gemini:flash25:Zephyr")
    assert r.status_code == 503
    d = r.get_json()
    assert d["code"] == "ffmpeg_missing"
    audiobook_app.jobs.pop("PVJ1", None)
