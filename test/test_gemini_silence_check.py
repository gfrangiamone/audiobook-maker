"""Scarto dell'audio Gemini (quasi) muto.

Caso reale (prod, 28/09/2026): flash38 a temperatura 0.3 risponde 200 OK con
~1,5 s di voce e poi silenzio fino al limite di token. Senza scarto il chunk
entrava nel libro come buco muto, senza retry ne' ripiego.
"""
import array

import pytest

import gemini_tts
import tts_backend_state as st

SR = 24000


def _pcm(*segments):
    """segments: (secondi, ampiezza). Onda quadra a 200 Hz di quell'ampiezza."""
    out = array.array("h")
    for sec, amp in segments:
        n = int(sec * SR)
        out.extend((amp if (i // 60) % 2 else -amp) for i in range(n))
    return out.tobytes()


VOCE_OK = _pcm((6, 8000), (1.0, 0), (6, 8000))
VOCE_POI_MUTO = _pcm((1.5, 8000), (40, 0))
BUCO_CENTRALE = _pcm((1.4, 8000), (21, 0), (9, 8000))


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.delenv("ABM_GEMINI_SILENCE_MAX_GAP_SEC", raising=False)
    monkeypatch.delenv("ABM_GEMINI_SILENCE_MIN_VOICED", raising=False)
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts.time, "sleep", lambda s: None)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    yield
    gemini_tts._BACKEND = {}
    st.reset("flash31")


def _fake_transport(monkeypatch, *responses):
    calls = []

    def call(**kw):
        calls.append(kw)
        pcm = responses[min(len(calls), len(responses)) - 1]
        return {"pcm": pcm, "input_tokens": None, "output_tokens": None}

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", call)
    return calls


def _synth(tmp_path, **kw):
    return gemini_tts.synthesize("frase di prova", "gemini:flash31:Kore",
                                 output_path=str(tmp_path / "o.pcm"), **kw)


def test_voce_normale_non_scartata():
    assert gemini_tts.mostly_silent_reason(VOCE_OK) is None


def test_voce_poi_muto_scartata():
    assert "silent gap" in gemini_tts.mostly_silent_reason(VOCE_POI_MUTO)


def test_buco_centrale_scartato():
    assert "silent gap" in gemini_tts.mostly_silent_reason(BUCO_CENTRALE)


def test_audio_breve_non_giudicato():
    # Un titolo di 2 s letto piano non ha profilo significativo.
    assert gemini_tts.mostly_silent_reason(_pcm((2, 0))) is None


def test_quota_udibile_minima(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_SILENCE_MAX_GAP_SEC", "100")
    # Tanti silenzi da 3 s: nessun tratto oltre soglia, ma 14% udibile.
    pcm = _pcm(*([(0.5, 8000), (3, 0)] * 5))
    assert "audible" in gemini_tts.mostly_silent_reason(pcm)


def test_soglia_zero_disattiva(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_SILENCE_MAX_GAP_SEC", "0")
    assert gemini_tts.mostly_silent_reason(VOCE_POI_MUTO) is None


def test_synthesize_ritenta_e_consegna_la_risposta_buona(tmp_path, monkeypatch):
    calls = _fake_transport(monkeypatch, VOCE_POI_MUTO, VOCE_OK)
    out = _synth(tmp_path)
    assert len(calls) == 2
    assert out["attempts_used"] == 2
    assert (tmp_path / "o.pcm").read_bytes() == VOCE_OK


def test_synthesize_esauriti_i_tentativi_solleva(tmp_path, monkeypatch):
    calls = _fake_transport(monkeypatch, VOCE_POI_MUTO)
    with pytest.raises(RuntimeError, match="mostly silent"):
        _synth(tmp_path, max_attempts=2)
    assert len(calls) == 2
    assert not (tmp_path / "o.pcm").exists()


def test_audio_muto_non_fa_scattare_il_breaker(tmp_path, monkeypatch):
    _fake_transport(monkeypatch, VOCE_POI_MUTO)
    with pytest.raises(RuntimeError):
        _synth(tmp_path, max_attempts=5)
    assert gemini_tts._resolve_backend("flash31") == "cloudflare"
