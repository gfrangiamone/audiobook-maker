"""Regressione: il chunking per voci Speechify deve usare il cap 1800 (non 2000).

L'endpoint Speechify rifiuta con HTTP 400 `input must not exceed 2000 characters`
un `input` SSML > 2000 char. Un chunk di testo fino a 2000 char + i tag SSML
(<speak>, <prosody>, <speechify:style>) aggiunti da build_ssml supera il limite
e viene silenziato (job PARTIAL). Il cap deve restare sotto 2000 con margine per
l'overhead SSML: speechify_tts.CHUNK_MAX_CHARS = 1800.
"""
import speechify_tts
import tts_split


def test_speechify_chunk_cap_is_1800():
    got = tts_split._pick_chunk_max_chars("speechify:simba-3.2:hugh_32", "en")
    assert got == speechify_tts.CHUNK_MAX_CHARS == 1800


def test_speechify_chunk_cap_leaves_ssml_headroom():
    # 1800 (testo) + overhead SSML massimo (speak+prosody+style, ~102 char) < 2000.
    cap = tts_split._pick_chunk_max_chars("speechify:simba-3.2:hugh_32", "en")
    worst_ssml_overhead = len(
        '<speak><prosody rate="+100%"><speechify:style emotion="surprised">'
        '</speechify:style></prosody></speak>'
    )
    assert cap + worst_ssml_overhead < 2000


def test_other_engines_chunk_caps_unchanged():
    # Edge/Google restano 2000; Gemini resta 700 (default).
    assert tts_split._pick_chunk_max_chars("en-US-AriaNeural", "en") == 2000
    assert tts_split._pick_chunk_max_chars("gemini:flash25:Zephyr", "en") == 700


def test_chunk_max_chars_default_matches_constant():
    # Senza env: chunk_max_chars() == default CHUNK_MAX_CHARS (1800).
    assert speechify_tts.chunk_max_chars() == speechify_tts.CHUNK_MAX_CHARS == 1800


def test_chunk_max_chars_env_override(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_CHUNK_CHARS", "1200")
    assert speechify_tts.chunk_max_chars() == 1200
    # L'override si propaga al planner del chunking.
    assert tts_split._pick_chunk_max_chars("speechify:simba-3.2:hugh_32", "en") == 1200


def test_chunk_max_chars_env_clamped_below_endpoint_limit(monkeypatch):
    # Un valore troppo alto NON deve poter far superare il limite hard 2000
    # dell'endpoint una volta aggiunto l'overhead SSML: viene clampato al max
    # sicuro, che lascia sempre margine (< 2000 con i tag SSML peggiori).
    monkeypatch.setenv("ABM_SPEECHIFY_CHUNK_CHARS", "5000")
    cap = speechify_tts.chunk_max_chars()
    assert cap == speechify_tts.SAFE_MAX_CHUNK_CHARS
    worst_ssml_overhead = len(
        '<speak><prosody rate="+100%"><speechify:style emotion="surprised">'
        '</speechify:style></prosody></speak>'
    )
    assert cap + worst_ssml_overhead < speechify_tts.ENDPOINT_MAX_INPUT_CHARS


def test_chunk_max_chars_env_invalid_falls_back(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_CHUNK_CHARS", "abc")
    assert speechify_tts.chunk_max_chars() == speechify_tts.CHUNK_MAX_CHARS
