"""F1d: tts_split = solo splitting e piano; edge_engine = edge-tts (MP3);
premium_chunk = Gemini/Speechify (PCM). Nessun alias in tts_split, nessun
motore importato da tts_split; i chiamanti e i test usano i moduli nuovi."""
import inspect
import re

import edge_engine
import generation_engine
import premium_chunk
import tts_split

EDGE = ("EDGE_TTS_CHUNK_TIMEOUT", "_edge_output_looks_truncated", "_EdgeTruncated", "_edge_tts_call", "generate_chunk_mp3")
PREMIUM = ("_gemini_fatal", "_generate_silence_pcm", "_pick_edge_fallback_voice", "_edge_fallback_to_pcm",
           "_synthesize_pcm_pieces_and_concat", "generate_chunk_pcm_gemini", "generate_chunk_pcm_speechify")


def test_tts_split_keeps_only_splitting_and_plan():
    src = inspect.getsource(tts_split)
    for n in EDGE + PREMIUM:
        assert not hasattr(tts_split, n), n
    for n in ("split_text_into_chunks", "_split_sentences_for_tts", "_plan_chunks", "_pick_chunk_max_chars",
              "_pick_chunk_max_bytes", "_pick_pre_split", "_pick_sentence_slack", "_is_multilingual_voice"):
        assert re.search(rf"^def {n}\(", src, flags=re.M), n
    assert not re.search(r"^\s*(import|from) (edge_tts|edge_engine|premium_chunk|audio_utils|ffmpeg_tools|gemini_tts|speechify_tts|voxcpm_tts)\b", src, flags=re.M)
    assert "os.environ" not in src


def test_new_modules_hold_the_engines_and_call_tts_split_qualified():
    for n in EDGE:
        assert hasattr(edge_engine, n), n
    for n in PREMIUM:
        assert hasattr(premium_chunk, n), n
    edge = inspect.getsource(edge_engine)
    prem = inspect.getsource(premium_chunk)
    # qualificati: cosi' una monkeypatch su tts_split / edge_engine resta visibile da qui
    assert "tts_split._split_sentences_for_tts(" in edge and "tts_split._is_multilingual_voice(" in edge
    assert "tts_split._pick_chunk_max_bytes(" in prem and "tts_split.split_text_into_chunks(" in prem
    assert "edge_engine.generate_chunk_mp3(" in prem
    assert "os.environ" not in edge and "os.environ" not in prem
    assert edge_engine.EDGE_TTS_CHUNK_TIMEOUT == 120


def test_generation_engine_binds_the_new_modules():
    assert generation_engine.generate_chunk_mp3 is edge_engine.generate_chunk_mp3
    assert generation_engine.generate_chunk_pcm_gemini is premium_chunk.generate_chunk_pcm_gemini
    assert generation_engine.generate_chunk_pcm_speechify is premium_chunk.generate_chunk_pcm_speechify
    assert generation_engine._generate_silence_pcm is premium_chunk._generate_silence_pcm


def test_patch_on_tts_split_is_seen_by_premium_chunk(monkeypatch):
    seen = []
    monkeypatch.setattr(tts_split, "_pick_chunk_max_bytes", lambda v: seen.append(v) or 999)
    # la funzione premium la legge attraverso il modulo, non per nome importato
    assert "tts_split._pick_chunk_max_bytes(" in inspect.getsource(premium_chunk.generate_chunk_pcm_gemini)
    assert tts_split._pick_chunk_max_bytes("gemini:flash31:Zephyr") == 999 and seen
