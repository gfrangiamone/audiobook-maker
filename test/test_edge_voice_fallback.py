"""Ripiego di voce in edge_engine (incidente 2026-10-16).

pt-BR-ThalitaMultilingualNeural e de-DE-SeraphinaMultilingualNeural
rispondevano NoAudioReceived anche a richieste isolate: il 2% dei chunk finiva
in silenzio. Una voce Multilingual che esaurisce i tentativi con
NoAudioReceived ripiega su una voce standard della stessa lingua, e resta
segnata rotta per le frasi successive. Lo stesso giorno le voci standard
cs-CZ/ru-RU: NoAudioReceived ha piu' tentativi, poi la voce standard ripiega
prima sulla stessa locale (Multilingual o standard), poi su una Multilingual.
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
    {"ShortName": "en-US-AndrewMultilingualNeural", "Locale": "en-US", "Gender": "Male"},
    {"ShortName": "cs-CZ-VlastaNeural", "Locale": "cs-CZ", "Gender": "Female"},
    {"ShortName": "cs-CZ-AntoninNeural", "Locale": "cs-CZ", "Gender": "Male"},
    {"ShortName": "en-US-EmmaNeural", "Locale": "en-US", "Gender": "Female"},
    {"ShortName": "fr-FR-HenriNeural", "Locale": "fr-FR", "Gender": "Male"},
    {"ShortName": "fr-FR-AlainNeural", "Locale": "fr-FR", "Gender": "Male"},
]
N = edge_engine._EDGE_NOAUDIO_ATTEMPTS


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
    no_fr = [v for v in CATALOG if v["Locale"] != "fr-FR" or "Multilingual" in v["ShortName"]]
    assert edge_engine._pick_standard_voice("fr-FR-VivienneMultilingualNeural", no_fr) is None
    assert edge_engine._pick_standard_voice("pt-BR-ThalitaMultilingualNeural", []) is None


def test_multilingual_no_audio_falls_back(edge, tmp_path):
    edge["dead"].add("pt-BR-ThalitaMultilingualNeural")
    assert _call("pt-BR-ThalitaMultilingualNeural", tmp_path) is True
    assert edge["calls"] == ["pt-BR-ThalitaMultilingualNeural"] * N + ["pt-BR-FranciscaNeural"]
    assert edge["silences"] == []
    snap = edge_health.snapshot()
    assert (snap["calls"], snap["failed"], snap["attempts"], snap["attempt_errors"]) == (1, 0, N + 1, N)


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
    assert len(edge["calls"]) == 2 * N
    assert len(edge["silences"]) == 1
    snap = edge_health.snapshot()
    assert (snap["calls"], snap["failed"]) == (1, 1)


def test_pick_standard_replacement_order():
    pick = edge_engine._pick_standard_replacement
    # stessa locale e stesso genere, la Multilingual prima della standard
    assert pick("pt-BR-FranciscaNeural", CATALOG) == "pt-BR-ThalitaMultilingualNeural"
    assert pick("en-US-EmmaNeural", CATALOG) == "en-US-AvaMultilingualNeural"
    assert pick("de-DE-ConradNeural", CATALOG) == "de-DE-FlorianMultilingualNeural"
    # stessa locale: la standard dello stesso genere batte la Multilingual dell'altro
    assert pick("fr-FR-HenriNeural", CATALOG) == "fr-FR-AlainNeural"
    # nessuna Multilingual cs: la madrelingua dell'altro genere prima di en-US
    assert pick("cs-CZ-VlastaNeural", CATALOG) == "cs-CZ-AntoninNeural"
    assert pick("cs-CZ-AntoninNeural", CATALOG) == "cs-CZ-VlastaNeural"
    assert pick("cs-CZ-VlastaNeural", []) is None


def test_pick_standard_replacement_skips_broken(edge):
    edge_engine._mark_voice_broken("cs-CZ-AntoninNeural")
    assert edge_engine._pick_standard_replacement("cs-CZ-VlastaNeural", CATALOG) == "en-US-AvaMultilingualNeural"
    edge_engine._mark_voice_broken("en-US-AvaMultilingualNeural")
    assert edge_engine._pick_standard_replacement("cs-CZ-VlastaNeural", CATALOG) == "en-US-AndrewMultilingualNeural"


def test_pick_standard_replacement_no_standard_of_other_locale():
    only = [v for v in CATALOG
            if v["ShortName"] in ("cs-CZ-VlastaNeural", "pt-BR-FranciscaNeural")]
    assert edge_engine._pick_standard_replacement("cs-CZ-VlastaNeural", only) is None


def test_standard_voice_falls_back_to_same_locale(edge, tmp_path):
    edge["dead"].add("cs-CZ-VlastaNeural")
    assert _call("cs-CZ-VlastaNeural", tmp_path) is True
    assert edge["calls"] == ["cs-CZ-VlastaNeural"] * N + ["cs-CZ-AntoninNeural"]
    assert edge_engine._voice_is_broken("cs-CZ-VlastaNeural")


def test_standard_voice_without_replacement_writes_silence(edge, tmp_path, monkeypatch):
    edge["dead"].add("cs-CZ-VlastaNeural")
    monkeypatch.setattr(edge_engine, "_voice_catalog",
                        [v for v in CATALOG if v["ShortName"] == "cs-CZ-VlastaNeural"])
    assert _call("cs-CZ-VlastaNeural", tmp_path) is False
    assert edge["calls"] == ["cs-CZ-VlastaNeural"] * N
    assert len(edge["silences"]) == 1


def test_no_audio_retried_beyond_max_retries(edge, tmp_path, monkeypatch):
    left = {"fails": N - 1}

    class _Comm:
        def __init__(self, text, voice, rate):
            edge["calls"].append(voice)

        async def save(self, path):
            if left["fails"]:
                left["fails"] -= 1
                raise NoAudioReceived("No audio was received.")
            with open(path, "wb") as f:
                f.write(b"\0" * 60000)

    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", _Comm)
    assert _call("cs-CZ-VlastaNeural", tmp_path) is True
    assert edge["calls"] == ["cs-CZ-VlastaNeural"] * N
    assert edge_engine._broken_voices == {}


def test_broken_standard_voice_uses_sentence_split(edge, tmp_path, monkeypatch):
    # ripiego Multilingual: passa dallo split per frase
    edge["dead"].add("pt-BR-FranciscaNeural")
    edge_engine._mark_voice_broken("pt-BR-FranciscaNeural")
    concat = []
    monkeypatch.setattr(edge_engine, "_concatenate_mp3",
                        lambda parts, out: concat.append(len(parts)))
    text = ("A primeira frase esta aqui e e bastante longa para nao se juntar a outra. " * 3
            + "A segunda frase esta ali e tambem e longa o suficiente para ficar sozinha.")
    n = len(edge_engine.tts_split._split_sentences_for_tts(text))
    assert n >= 2
    asyncio.run(edge_engine.generate_chunk_mp3(
        text, "pt-BR-FranciscaNeural", "+0%", str(tmp_path / "s.mp3"), max_retries=3))
    assert edge["calls"] == ["pt-BR-ThalitaMultilingualNeural"] * n
    assert concat == [n]


def test_broken_standard_voice_standard_replacement_single_call(edge, tmp_path, monkeypatch):
    # ripiego standard della stessa locale: chiamata unica, niente split
    edge["dead"].add("cs-CZ-VlastaNeural")
    edge_engine._mark_voice_broken("cs-CZ-VlastaNeural")
    concat = []
    monkeypatch.setattr(edge_engine, "_concatenate_mp3",
                        lambda parts, out: concat.append(len(parts)))
    text = ("Prvni veta je tady a je docela dlouha, aby se nespojila s dalsi. " * 3
            + "Druha veta je tam a take je dost dlouha na to, aby zustala samostatna.")
    asyncio.run(edge_engine.generate_chunk_mp3(
        text, "cs-CZ-VlastaNeural", "+0%", str(tmp_path / "s.mp3"), max_retries=3))
    assert edge["calls"] == ["cs-CZ-AntoninNeural"]
    assert concat == []


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
