"""Testi che edge-tts non puo' leggere (indagine 2026-10-13).

Un testo senza lettere ne' cifre non produce mai audio: niente chiamata,
che fallirebbe a ogni tentativo. U+FFFD (PDF estratti male) si toglie.
"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_engine
from text_reflow import _sanitize_tts_text


def test_testo_senza_lettere_non_chiama(monkeypatch, tmp_path):
    def _boom(*a, **k):
        raise AssertionError("non deve chiamare il servizio")

    silenzi = []
    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", _boom)
    monkeypatch.setattr(edge_engine, "_generate_silence_mp3",
                        lambda p, duration_sec=1: silenzi.append(p))
    for t in (".", "· · · ·", "— … —"):
        out = str(tmp_path / "s.mp3")
        assert asyncio.run(edge_engine._edge_tts_call(t, "ru-RU-SvetlanaNeural", "+0%", out)) is True
    assert len(silenzi) == 3


def test_cifre_e_lettere_sono_pronunciabili():
    assert edge_engine._has_speakable("1914.")
    assert edge_engine._has_speakable("Лайла")
    assert not edge_engine._has_speakable("· · ·")


def test_sanitize_toglie_u_fffd():
    assert _sanitize_tts_text("ab��c") == "abc"
    assert _sanitize_tts_text("���") is None
