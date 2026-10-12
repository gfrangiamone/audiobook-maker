"""Adapter OpenRouter: mappatura della risposta e forma della richiesta."""
import json

import pytest

import gemini_transport as gt
from gemini_transport import TransportError, _interpret_openrouter_response


class _Resp:
    def __init__(self, status_code, content=b"", headers=None, payload=None, text=None):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("corpo non JSON")
        return self._payload


def _ok(pcm=b"\x01\x02\x03\x04", gen="gen-tts-1"):
    return _Resp(200, pcm, {"Content-Type": "audio/pcm;rate=24000;channels=1",
                            "X-Generation-Id": gen})


def _err(status, message, **headers):
    return _Resp(status, headers={"Content-Type": "application/json", **headers},
                 payload={"error": {"message": message, "code": status}})


def test_200_returns_raw_pcm_without_tokens_and_with_generation_id():
    out = _interpret_openrouter_response(_ok(b"\x00" * 48))
    assert out["pcm"] == b"\x00" * 48
    assert out["input_tokens"] is None and out["output_tokens"] is None
    assert out["generation_id"] == "gen-tts-1"


def test_200_wav_is_stripped_of_its_header():
    body = b"RIFF" + b"\x00" * 40 + b"\x07\x08"
    assert _interpret_openrouter_response(_ok(body))["pcm"] == b"\x07\x08"


def test_200_without_audio_is_retryable_and_not_billed():
    with pytest.raises(TransportError) as ei:
        _interpret_openrouter_response(_ok(b""))
    assert ei.value.kind == "retryable" and ei.value.billed is False


def test_200_with_json_body_is_not_audio():
    r = _Resp(200, b'{"error": "x"}', {"Content-Type": "application/json"})
    with pytest.raises(TransportError) as ei:
        _interpret_openrouter_response(r)
    assert ei.value.kind == "retryable"


def test_402_credit_exhausted_trips_the_breaker():
    with pytest.raises(TransportError) as ei:
        _interpret_openrouter_response(_err(402, "Insufficient credits"))
    assert ei.value.kind == "backend_down" and ei.value.http_status == 402


def test_429_is_rate_limited_with_retry_after():
    with pytest.raises(TransportError) as ei:
        _interpret_openrouter_response(_err(429, "slow down", **{"Retry-After": "7"}))
    assert ei.value.kind == "rate_limited" and ei.value.retry_after_sec == 7.0


@pytest.mark.parametrize("status", [401, 403, 404])
def test_auth_and_not_found_are_fatal(status):
    with pytest.raises(TransportError) as ei:
        _interpret_openrouter_response(_err(status, "nope"))
    assert ei.value.kind == "fatal"


def test_opaque_provider_400_is_retryable_never_fatal():
    # Voce fuori enum o testo vuoto arrivano cosi' (probe 12/10/2026); non e'
    # distinguibile da un rifiuto transitorio a monte: retry, mai un trip.
    with pytest.raises(TransportError) as ei:
        _interpret_openrouter_response(_err(400, "Provider returned 400"))
    assert ei.value.kind == "retryable"


def test_unknown_model_400_is_fatal():
    with pytest.raises(TransportError) as ei:
        _interpret_openrouter_response(_err(400, "Model google/x does not exist"))
    assert ei.value.kind == "fatal"


def test_5xx_is_retryable():
    with pytest.raises(TransportError) as ei:
        _interpret_openrouter_response(_Resp(502, text="bad gateway"))
    assert ei.value.kind == "retryable" and ei.value.http_status == 502


def test_call_without_key_is_fatal(monkeypatch):
    monkeypatch.delenv("ABM_OPENROUTER_API_KEY", raising=False)
    with pytest.raises(TransportError) as ei:
        gt.openrouter_call(final_text="x", voice_name="Kore", model_key="flash38",
                           model_id="google/gemini-3.8-flash-tts", timeout_ms=1000,
                           temperature=None)
    assert ei.value.kind == "fatal"


def test_call_sends_pcm_request_with_instructions_and_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "sk-or-segreta")
    seen = {}

    def _post(url, headers=None, json=None, timeout=None):
        seen.update(url=url, headers=headers, body=json, timeout=timeout)
        return _ok(b"\x01" * 10)

    monkeypatch.setattr(gt.requests, "post", _post)
    out = gt.openrouter_call(final_text="Ciao.", voice_name="Kore", model_key="flash38",
                             model_id="google/gemini-3.8-flash-tts", timeout_ms=45000,
                             temperature=0.9, instructions="calm voice")
    assert out["pcm"] == b"\x01" * 10
    assert seen["url"] == gt.OR_API_URL
    assert seen["headers"]["Authorization"] == "Bearer sk-or-segreta"
    assert seen["body"] == {"model": "google/gemini-3.8-flash-tts", "input": "Ciao.",
                            "voice": "Kore", "response_format": "pcm",
                            "instructions": "calm voice"}
    assert seen["timeout"] == 45.0


def test_call_omits_instructions_when_absent(monkeypatch):
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    seen = {}
    monkeypatch.setattr(gt.requests, "post",
                        lambda url, headers=None, json=None, timeout=None:
                        seen.update(body=json) or _ok())
    gt.openrouter_call(final_text="[style: x] Ciao.", voice_name="Kore", model_key="flash31",
                       model_id="google/gemini-3.1-flash-tts-preview", timeout_ms=1000,
                       temperature=None)
    assert "instructions" not in seen["body"]
    assert seen["body"]["input"] == "[style: x] Ciao."


def test_network_errors_are_retryable_and_redacted(monkeypatch):
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "sk-or-segreta")

    def _boom(*a, **kw):
        raise gt.requests.ConnectionError("sk-or-segreta in the message")

    monkeypatch.setattr(gt.requests, "post", _boom)
    with pytest.raises(TransportError) as ei:
        gt.openrouter_call(final_text="x", voice_name="Kore", model_key="flash38",
                           model_id="m", timeout_ms=1000, temperature=None)
    assert ei.value.kind == "retryable"
    assert "segreta" not in str(ei.value)
