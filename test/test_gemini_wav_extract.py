"""PCM estratto da WAV (flash38) o grezzo (flash31)."""
import io
import types
import wave

import pytest

import gemini_tts
from gemini_transport import TransportError


def _wav(rate=24000, ch=1, width=2, frames=b"\x01\x00" * 480):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(frames)
    return buf.getvalue()


def _resp(data, mime="audio/wav"):
    part = types.SimpleNamespace(inline_data=types.SimpleNamespace(data=data, mime_type=mime))
    cand = types.SimpleNamespace(content=types.SimpleNamespace(parts=[part]),
                                 finish_reason=None, safety_ratings=None)
    return types.SimpleNamespace(candidates=[cand], prompt_feedback=None)


def test_wav_24k_mono_16bit_restituisce_solo_frame():
    frames = b"\x01\x00" * 480
    assert gemini_tts._extract_audio_pcm(_resp(_wav(frames=frames)), "flash38") == frames


def test_riff_riconosciuto_anche_con_mime_pcm():
    frames = b"\x02\x00" * 10
    out = gemini_tts._extract_audio_pcm(_resp(_wav(frames=frames), mime="audio/L16;rate=24000"), "flash38")
    assert out == frames


def test_pcm_grezzo_invariato():
    raw = b"\x03\x00" * 100
    assert gemini_tts._extract_audio_pcm(_resp(raw, mime="audio/L16;codec=pcm;rate=24000"), "flash31") == raw


@pytest.mark.parametrize("kw", [{"rate": 44100}, {"ch": 2, "frames": b"\x00" * 8}, {"width": 1, "frames": b"\x00" * 4}])
def test_formato_diverso_rifiutato(kw):
    with pytest.raises(gemini_tts.GeminiAudioFormatError):
        gemini_tts._extract_audio_pcm(_resp(_wav(**kw)), "flash38")


def test_wav_malformato_rifiutato():
    with pytest.raises(gemini_tts.GeminiAudioFormatError):
        gemini_tts._extract_audio_pcm(_resp(b"RIFF\x00\x00garbage"), "flash38")


class _Err(Exception):
    def __init__(self, code, msg):
        super().__init__(msg)
        self.code = code


@pytest.mark.parametrize("code", [401, 403, 404])
def test_apikey_errori_permanenti_fatali(monkeypatch, code):
    monkeypatch.setattr(gemini_tts, "_resolve_backend", lambda mk=None: "apikey")

    class _Models:
        def generate_content(self, **kw):
            raise _Err(code, f"{code} PERMISSION_DENIED")

    monkeypatch.setattr(gemini_tts, "_get_client",
                        lambda mk: types.SimpleNamespace(models=_Models()))
    with pytest.raises(TransportError) as ei:
        gemini_tts._vertex_transport_call(final_text="ciao", voice_name="Zephyr",
                                          model_key="flash38", model_id="gemini-3.8-flash-tts",
                                          timeout_ms=1000, temperature=None)
    assert ei.value.kind == "fatal"


def test_vertex_404_resta_ritentabile(monkeypatch):
    monkeypatch.setattr(gemini_tts, "_resolve_backend", lambda mk=None: "vertex")

    class _Models:
        def generate_content(self, **kw):
            raise _Err(404, "404 NOT_FOUND")

    monkeypatch.setattr(gemini_tts, "_get_client",
                        lambda mk: types.SimpleNamespace(models=_Models()))
    with pytest.raises(TransportError) as ei:
        gemini_tts._vertex_transport_call(final_text="ciao", voice_name="Zephyr",
                                          model_key="flash31", model_id="x",
                                          timeout_ms=1000, temperature=None)
    assert ei.value.kind == "retryable"


def test_formato_audio_errato_fatale(monkeypatch):
    monkeypatch.setattr(gemini_tts, "_resolve_backend", lambda mk=None: "apikey")
    bad = _resp(_wav(rate=44100))
    bad.usage_metadata = None

    class _Models:
        def generate_content(self, **kw):
            return bad

    monkeypatch.setattr(gemini_tts, "_get_client",
                        lambda mk: types.SimpleNamespace(models=_Models()))
    with pytest.raises(TransportError) as ei:
        gemini_tts._vertex_transport_call(final_text="ciao", voice_name="Zephyr",
                                          model_key="flash38", model_id="gemini-3.8-flash-tts",
                                          timeout_ms=1000, temperature=None)
    assert ei.value.kind == "fatal"


def test_wav_senza_frame_e_risposta_vuota_ritentabile():
    with pytest.raises(gemini_tts.GeminiEmptyResponse) as ei:
        gemini_tts._extract_audio_pcm(_resp(_wav(frames=b"")), "flash38")
    assert ei.value.retryable is True


def _transport_429(monkeypatch, backend, msg, model_key="flash38"):
    monkeypatch.setattr(gemini_tts, "_resolve_backend", lambda mk=None: backend)

    class _Models:
        def generate_content(self, **kw):
            raise _Err(429, msg)

    monkeypatch.setattr(gemini_tts, "_get_client",
                        lambda mk: types.SimpleNamespace(models=_Models()))
    with pytest.raises(TransportError) as ei:
        gemini_tts._vertex_transport_call(final_text="ciao", voice_name="Zephyr",
                                          model_key=model_key, model_id="m",
                                          timeout_ms=1000, temperature=None)
    return ei.value


@pytest.mark.parametrize("msg", [
    "429 RESOURCE_EXHAUSTED. Your prepayment credits are depleted. Please go to AI Studio to manage your project and billing.",
    "429 RESOURCE_EXHAUSTED. Your project has exceeded its monthly spending cap.",
    "429 RESOURCE_EXHAUSTED. Spend cap reached for this project.",
])
def test_apikey_429_di_credito_esaurito_e_fatale(monkeypatch, msg):
    assert _transport_429(monkeypatch, "apikey", msg).kind == "fatal"


def test_apikey_429_di_rate_limit_resta_ritentabile(monkeypatch):
    msg = ("429 RESOURCE_EXHAUSTED. You exceeded your current quota, please check "
           "your plan and billing details. For more information on this error, "
           "head to: https://ai.google.dev/gemini-api/docs/rate-limits.")
    assert _transport_429(monkeypatch, "apikey", msg).kind == "rate_limited"


def test_vertex_429_con_marker_credito_resta_rate_limited(monkeypatch):
    msg = "429 RESOURCE_EXHAUSTED prepayment credits are depleted"
    assert _transport_429(monkeypatch, "vertex", msg, "flash31").kind == "rate_limited"
