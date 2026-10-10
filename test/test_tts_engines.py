"""E1(d1): registro tts_engines; tts_split, generation_engine e i dispatch di
stima di audiobook_app passano da li'; VoxcpmUnavailable."""
import inspect
import re
import types

import pytest

import tts_engines
import tts_split
import generation_engine as ge
import gemini_tts, speechify_tts, voxcpm_tts


def test_engine_for_voice_and_registry_shape():
    assert tts_engines.engine_for_voice("gemini:flash31:Zephyr") == "gemini"
    assert tts_engines.engine_for_voice("speechify:simba-3.2:harper_32") == "speechify"
    assert tts_engines.engine_for_voice("voxcpm:it:anna") == "voxcpm"
    assert tts_engines.engine_for_voice("it-IT-ElsaNeural") == "edge" and tts_engines.engine_for_voice("") == "edge"
    assert tts_engines.premium_for_voice("it-IT-ElsaNeural") is None
    assert set(tts_engines.ENGINES) == set(tts_engines.PREMIUM) == {"gemini", "speechify", "voxcpm"}
    for name, eng in tts_engines.ENGINES.items():
        assert eng.name == name and eng.mod().__name__ == eng.module
        assert eng.estimate_key == f"{name}_estimate" and eng.audit_writer == f"_write_{name}_audit"
        assert issubclass(eng.unavailable(), RuntimeError)
    assert ge._engine_for_voice("voxcpm:it:anna") == "voxcpm" and ge._engine_for_voice(None) == "edge"


def test_chunk_caps_pre_split_and_slack_match_the_modules(monkeypatch):
    E = tts_engines.ENGINES
    assert E["gemini"].chunk_max_chars("it-IT") == gemini_tts.get_max_chunk_chars("it")
    assert E["speechify"].chunk_max_chars() == speechify_tts.chunk_max_chars()
    assert E["voxcpm"].chunk_max_chars() == voxcpm_tts.chunk_max_chars()
    assert E["gemini"].chunk_max_bytes() == int(gemini_tts.MAX_BYTES_PER_CALL)
    assert E["speechify"].chunk_max_bytes() is None and E["voxcpm"].pre_split() is voxcpm_tts.prepara_capitolo
    assert E["gemini"].pre_split() is None and E["voxcpm"].sentence_slack == 0.15 == tts_split._VOXCPM_SENTENCE_SLACK
    # tts_split delega (nomi conservati: i test li sostituiscono)
    assert tts_split._pick_chunk_max_chars("voxcpm:it:anna", "it") == voxcpm_tts.chunk_max_chars()
    assert tts_split._pick_chunk_max_chars("gemini:flash31:Zephyr", "en") == gemini_tts.get_max_chunk_chars("en")
    assert tts_split._pick_chunk_max_chars("it-IT-ElsaNeural", "it") == tts_split.CHUNK_MAX_CHARS
    assert tts_split._pick_chunk_max_bytes("it-IT-ElsaNeural") is None
    assert tts_split._pick_pre_split("speechify:simba-3.2:harper_32") is None
    assert tts_split._pick_sentence_slack("voxcpm:it:anna") == 0.15 and tts_split._pick_sentence_slack("x") == 0.0
    # Un modulo che non risponde: fallback storici
    monkeypatch.setattr(voxcpm_tts, "chunk_max_chars", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert E["voxcpm"].chunk_max_chars() == 300
    # Le sostituzioni sul modulo motore sono viste dal registro (import tardivo)
    monkeypatch.setattr(speechify_tts, "chunk_max_chars", lambda: 123)
    assert tts_split._pick_chunk_max_chars("speechify:simba-3.2:harper_32", "en") == 123


def test_sample_rate_from_registry():
    E = tts_engines.ENGINES
    assert E["gemini"].sample_rate({}) == 24000 and E["voxcpm"].sample_rate({"speechify_sample_rate": 1}) == 48000
    assert E["speechify"].sample_rate({}) == 48000 and E["speechify"].sample_rate({"speechify_sample_rate": 44100}) == 44100
    assert ge._pcm_sample_rate({"speechify_sample_rate": 44100}, True, False) == 44100
    assert ge._pcm_sample_rate({}, False, True) == 48000 and ge._pcm_sample_rate({}, False, False) == 24000


def test_estimate_dispatch_passes_each_engine_its_signature(monkeypatch):
    calls = []
    monkeypatch.setattr(gemini_tts, "estimate_book_cost", lambda *a, **k: calls.append(("g", a, k)) or {"g": 1})
    monkeypatch.setattr(speechify_tts, "estimate_book_cost", lambda *a, **k: calls.append(("s", a, k)) or {"s": 1})
    monkeypatch.setattr(voxcpm_tts, "estimate_book_cost", lambda *a, **k: calls.append(("v", a, k)) or {"v": 1})
    chs = [types.SimpleNamespace(text="x")]
    assert tts_engines.estimate("gemini", chs, "gemini:flash31:Zephyr", language="fr", rate_pct="+10%") == {"g": 1}
    assert tts_engines.estimate("speechify", chs, language="it") == {"s": 1}      # solo inglese
    assert tts_engines.estimate("voxcpm", chs, language="de") == {"v": 1}
    assert tts_engines.estimate("voxcpm", chs) == {"v": 1}
    assert calls == [("g", (chs, "gemini:flash31:Zephyr"), {"language": "fr", "rate_pct": "+10%"}),
                     ("s", (chs,), {"language": "en"}),
                     ("v", (chs,), {"language": "de"}),
                     ("v", (chs,), {"language": "it"})]


def test_no_direct_estimate_dispatch_left_in_app_and_engine():
    import audiobook_app as app
    import recovery                                   # E3: il gate di recupero vive li'
    for mod in (app, ge, recovery):
        src = inspect.getsource(mod)
        assert not re.search(r"\b(gemini_tts|_gemini_tts_mod|speechify_tts|voxcpm_tts)\.estimate_book_cost\(", src), mod.__name__
    assert sum(inspect.getsource(m).count('tts_engines.estimate("') for m in (app, recovery)) >= 14
    assert inspect.getsource(ge).count('_tts_engines.estimate("') == 3        # auto-gen: stima mancante


def test_premium_audit_names_and_unavailable_exceptions(monkeypatch):
    assert ge._PREMIUM_AUDIT == {"gemini": "_write_gemini_audit", "speechify": "_write_speechify_audit",
                                 "voxcpm": "_write_voxcpm_audit"}
    excs = tts_engines.unavailable_exceptions()
    assert set(excs) == {gemini_tts.GeminiUnavailable, speechify_tts.SpeechifyUnavailable, voxcpm_tts.VoxcpmUnavailable}
    assert issubclass(voxcpm_tts.VoxcpmUnavailable, voxcpm_tts.VoxcpmJobError)
    monkeypatch.setattr(voxcpm_tts, "endpoint_id", lambda: "")
    with pytest.raises(voxcpm_tts.VoxcpmUnavailable):
        voxcpm_tts._base()
    src = inspect.getsource(ge.run_generation)
    assert "_tts_engines.unavailable_exceptions()" in src and "GeminiUnavailable" not in src.split("unavailable_exceptions()")[1][:400]


def test_availability_is_read_from_the_module(monkeypatch):
    monkeypatch.setattr(voxcpm_tts, "is_available", lambda: True)
    monkeypatch.setattr(speechify_tts, "is_available", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert tts_engines.ENGINES["voxcpm"].is_available() is True
    assert tts_engines.ENGINES["speechify"].is_available() is False
