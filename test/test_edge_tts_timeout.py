"""Test timeout su _edge_tts_call (incidente 2026-06-11: websocket half-open).

edge-tts non applica receive_timeout alla websocket (ws_connect senza timeout
in aiohttp): se il server droppa la connessione senza FIN/RST, communicate.save()
resta sospeso per sempre e il job si blocca senza errori. _edge_tts_call deve
imporre un timeout applicativo cosi' che la catena retry/fallback esistente
gestisca anche l'hang.
"""

import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import tts_split


class _HangingCommunicate:
    """Simula una websocket half-open: save() non ritorna mai."""

    calls = 0

    def __init__(self, text, voice, rate):
        type(self).calls += 1

    async def save(self, output_path):
        await asyncio.sleep(3600)


@pytest.fixture
def hanging_edge_tts(monkeypatch, tmp_path):
    _HangingCommunicate.calls = 0
    monkeypatch.setattr(
        tts_split.edge_tts, "Communicate",
        lambda text, voice, rate: _HangingCommunicate(text, voice, rate),
    )
    # Timeout corto per il test (la costante deve esistere ed essere usata)
    monkeypatch.setattr(tts_split, "EDGE_TTS_CHUNK_TIMEOUT", 0.1, raising=False)
    silences = []
    monkeypatch.setattr(
        tts_split, "_generate_silence_mp3",
        lambda path, duration_sec=1: silences.append(path),
    )
    return silences


def test_hanging_save_falls_back_to_silence(hanging_edge_tts, tmp_path):
    """Un save() appeso deve scadere, non bloccare il thread per sempre."""
    out = str(tmp_path / "chunk.mp3")

    async def _run():
        # Guardia esterna: col bug il test fallisce qui invece di appendersi
        return await asyncio.wait_for(
            tts_split._edge_tts_call("testo", "en-GB-RyanNeural", "+0%", out,
                                     max_retries=1),
            timeout=5,
        )

    result = asyncio.run(_run())
    assert result is False
    assert hanging_edge_tts == [out]


def test_hanging_save_retries_before_fallback(hanging_edge_tts, tmp_path):
    """Il timeout deve attivare il retry esistente (nuova connessione)."""
    out = str(tmp_path / "chunk.mp3")

    async def _run():
        return await asyncio.wait_for(
            tts_split._edge_tts_call("testo", "en-GB-RyanNeural", "+0%", out,
                                     max_retries=2),
            timeout=5,
        )

    result = asyncio.run(_run())
    assert result is False
    assert _HangingCommunicate.calls == 2


def test_timeout_env_default():
    """Default 120s, override via ABM_EDGE_TTS_TIMEOUT a import time."""
    assert isinstance(tts_split.EDGE_TTS_CHUNK_TIMEOUT, int)
    assert tts_split.EDGE_TTS_CHUNK_TIMEOUT > 0
