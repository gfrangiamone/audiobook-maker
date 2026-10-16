"""Ripiego di voce in edge_engine (incidente 2026-10-16).

pt-BR-ThalitaMultilingualNeural e de-DE-SeraphinaMultilingualNeural
rispondevano NoAudioReceived anche a richieste isolate: il 2% dei chunk finiva
in silenzio. Una voce Multilingual che esaurisce i tentativi con
NoAudioReceived ripiega su una voce standard della stessa lingua, e resta
segnata rotta per le frasi successive.
"""
import asyncio
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_engine
import edge_health
from edge_tts.exceptions import NoAudioReceived

CATALOG = [
    {"ShortName": "pt-BR-ThalitaMultilingualNeural", "Locale": "pt-BR", "Gender": "Female"},
    {"ShortName": "pt-BR-AntonioNeural", "Locale": "pt-BR", "Gender": "Male"},
    {"ShortName": "pt-BR-FranciscaNeural", "Locale": "pt-BR", "Gender": "Female"},
    {"ShortName": "pt-PT-RaquelNeural", "Locale": "pt-PT", "Gender": "Female"},
    {"ShortName": "en-US-AvaMultilingualNeural", "Locale": "en-US", "Gender": "Female"},
    {"ShortName": "en-US-AvaNeural", "Locale": "en-US", "Gender": "Female"},
    {"ShortName": "de-DE-SeraphinaMultilingualNeural", "Locale": "de-DE", "Gender": "Female"},
    {"ShortName": "de-DE-FlorianMultilingualNeural", "Locale": "de-DE", "Gender": "Male"},
    {"ShortName": "de-DE-ConradNeural", "Locale": "de-DE", "Gender": "Male"},
    {"ShortName": "fr-FR-VivienneMultilingualNeural", "Locale": "fr-FR", "Gender": "Female"},
]


@pytest.fixture
def edge(monkeypatch):
    """Communicate finto: le voci in `dead` non danno audio, le altre si'."""
    state = {"dead": set(), "calls": [], "silences": [], "catalog_calls": 0}

    class _Comm:
        def __init__(self, text, voice, rate):
            self.voice = voice
            state["calls"].append(voice)

        async def save(self, path):
            if self.voice in state["dead"]:
                raise NoAudioReceived("No audio was received.")
            with open(path, "wb") as f:
                f.write(b"\0" * 60000)

    async def _list_voices():
        state["catalog_calls"] += 1
        return CATALOG

    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", _Comm)
    monkeypatch.setattr(edge_engine.edge_tts, "list_voices", _list_voices)
    monkeypatch.setattr(edge_engine, "_edge_retry_wait", lambda a, e: 0)
    monkeypatch.setattr(edge_engine, "_generate_silence_mp3",
                        lambda p, duration_sec=1: state["silences"].append(p))
    monkeypatch.setattr(edge_engine, "_broken_voices", {})
    monkeypatch.setattr(edge_engine, "_voice_catalog", None)
    monkeypatch.setattr(edge_engine, "_catalog_failed_at", 0.0)
    edge_health.reset()
    yield state
    edge_health.reset()


def _call(voice, tmp_path, name="c.mp3"):
    return asyncio.run(edge_engine._edge_tts_call(
        "Presumimos que nosso casamento vai bem.", voice, "+0%",
        str(tmp_path / name), max_retries=3))


def test_pick_standard_voice_same_name_first():
    assert edge_engine._pick_standard_voice("en-US-AvaMultilingualNeural", CATALOG) == "en-US-AvaNeural"


def test_pick_standard_voice_same_locale_and_gender():
    assert edge_engine._pick_standard_voice("pt-BR-ThalitaMultilingualNeural", CATALOG) == "pt-BR-FranciscaNeural"


def test_pick_standard_voice_other_gender_when_needed():
    # nessuna voce standard femminile de-DE: si prende quella della locale
    assert edge_engine._pick_standard_voice("de-DE-SeraphinaMultilingualNeural", CATALOG) == "de-DE-ConradNeural"


def test_pick_standard_voice_none_without_candidates():
    assert edge_engine._pick_standard_voice("fr-FR-VivienneMultilingualNeural", CATALOG) is None
    assert edge_engine._pick_standard_voice("pt-BR-ThalitaMultilingualNeural", []) is None


def test_multilingual_no_audio_falls_back(edge, tmp_path):
    edge["dead"].add("pt-BR-ThalitaMultilingualNeural")
    assert _call("pt-BR-ThalitaMultilingualNeural", tmp_path) is True
    assert edge["calls"] == ["pt-BR-ThalitaMultilingualNeural"] * 3 + ["pt-BR-FranciscaNeural"]
    assert edge["silences"] == []
    snap = edge_health.snapshot()
    assert (snap["calls"], snap["failed"], snap["attempts"], snap["attempt_errors"]) == (1, 0, 4, 3)


def test_broken_voice_goes_straight_to_fallback(edge, tmp_path):
    edge["dead"].add("pt-BR-ThalitaMultilingualNeural")
    _call("pt-BR-ThalitaMultilingualNeural", tmp_path, "a.mp3")
    edge["calls"].clear()
    assert _call("pt-BR-ThalitaMultilingualNeural", tmp_path, "b.mp3") is True
    assert edge["calls"] == ["pt-BR-FranciscaNeural"]
    assert edge["catalog_calls"] == 1


def test_broken_voice_expires(edge):
    edge_engine._mark_voice_broken("pt-BR-ThalitaMultilingualNeural", now=0.0)
    assert not edge_engine._voice_is_broken("pt-BR-ThalitaMultilingualNeural",
                                            now=edge_engine._EDGE_BROKEN_VOICE_SEC + 1)


def test_fallback_failing_too_writes_silence(edge, tmp_path):
    edge["dead"].update({"pt-BR-ThalitaMultilingualNeural", "pt-BR-FranciscaNeural"})
    assert _call("pt-BR-ThalitaMultilingualNeural", tmp_path) is False
    assert len(edge["calls"]) == 6
    assert len(edge["silences"]) == 1
    snap = edge_health.snapshot()
    assert (snap["calls"], snap["failed"]) == (1, 1)


def test_standard_voice_never_falls_back(edge, tmp_path):
    edge["dead"].add("pt-BR-AntonioNeural")
    assert _call("pt-BR-AntonioNeural", tmp_path) is False
    assert edge["calls"] == ["pt-BR-AntonioNeural"] * 3
    assert edge["catalog_calls"] == 0


def test_other_errors_do_not_switch_voice(edge, tmp_path, monkeypatch):
    class _Forbidden(Exception):
        status = 403

    class _Comm:
        def __init__(self, text, voice, rate):
            edge["calls"].append(voice)

        async def save(self, path):
            raise _Forbidden("403")

    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", _Comm)
    assert _call("pt-BR-ThalitaMultilingualNeural", tmp_path) is False
    assert edge["calls"] == ["pt-BR-ThalitaMultilingualNeural"] * 3
    assert edge_engine._broken_voices == {}


def test_catalog_unreachable_keeps_original_voice(edge, tmp_path, monkeypatch):
    async def _down():
        raise OSError("offline")

    monkeypatch.setattr(edge_engine.edge_tts, "list_voices", _down)
    edge["dead"].add("pt-BR-ThalitaMultilingualNeural")
    assert _call("pt-BR-ThalitaMultilingualNeural", tmp_path, "a.mp3") is False
    assert edge_engine._broken_voices == {}
    # il catalogo fallito non si riscarica subito: la voce si riprova com'e'
    edge["calls"].clear()
    edge["dead"].clear()
    assert _call("pt-BR-ThalitaMultilingualNeural", tmp_path, "b.mp3") is True
    assert edge["calls"] == ["pt-BR-ThalitaMultilingualNeural"]
