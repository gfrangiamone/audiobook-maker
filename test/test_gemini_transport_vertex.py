"""L'adapter Vertex rispetta il contratto di trasporto."""
import pytest

import gemini_tts
from gemini_transport import TRANSPORT_KINDS, TransportError


class _Usage:
    prompt_token_count = 11
    candidates_token_count = 250


class _FakeModels:
    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self._behaviour(kwargs)


class _FakeClient:
    def __init__(self, behaviour):
        self.models = _FakeModels(behaviour)


def _install(monkeypatch, behaviour, pcm=b"\x01\x02"):
    client = _FakeClient(behaviour)
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: client)
    monkeypatch.setattr(gemini_tts, "_extract_audio_pcm", lambda resp, mk: pcm)
    return client


def _call(**over):
    kwargs = dict(final_text="ciao", voice_name="Kore", model_key="flash31",
                  model_id="gemini-3.1-flash-tts-preview", timeout_ms=60000,
                  temperature=0.75)
    kwargs.update(over)
    return gemini_tts._vertex_transport_call(**kwargs)


def test_returns_pcm_and_usage(monkeypatch):
    class _Resp:
        usage_metadata = _Usage()

    _install(monkeypatch, lambda kw: _Resp(), pcm=b"\x00" * 48)
    out = _call()
    assert out["pcm"] == b"\x00" * 48
    assert out["input_tokens"] == 11
    assert out["output_tokens"] == 250


def test_missing_usage_metadata_yields_zero_not_crash(monkeypatch):
    class _Resp:
        usage_metadata = None

    _install(monkeypatch, lambda kw: _Resp())
    out = _call()
    assert out["input_tokens"] == 0
    assert out["output_tokens"] == 0


def test_passes_voice_and_model_through(monkeypatch):
    class _Resp:
        usage_metadata = _Usage()

    client = _install(monkeypatch, lambda kw: _Resp())
    _call(voice_name="Zephyr", model_id="modello-x")
    sent = client.models.calls[0]
    assert sent["model"] == "modello-x"
    assert "Zephyr" in repr(sent["config"])


def test_non_retryable_empty_response_becomes_content_rejected(monkeypatch):
    def _boom(kw):
        raise gemini_tts.GeminiEmptyResponse(
            "safety", block_reason="SAFETY", finish_reason="SAFETY",
            retryable=False)

    _install(monkeypatch, _boom)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "content_rejected"


def test_retryable_empty_response_becomes_retryable(monkeypatch):
    def _boom(kw):
        raise gemini_tts.GeminiEmptyResponse("vuota", finish_reason="OTHER",
                                             retryable=True)

    _install(monkeypatch, _boom)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "retryable"


def test_daily_quota_becomes_quota_daily_with_retry_after(monkeypatch):
    def _boom(kw):
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota per day")

    _install(monkeypatch, _boom)
    monkeypatch.setattr(gemini_tts, "_is_429", lambda e: True)
    monkeypatch.setattr(gemini_tts, "_is_daily_quota_error", lambda e: True)
    monkeypatch.setattr(gemini_tts, "_parse_retry_after", lambda e: 3600)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "quota_daily"
    assert ei.value.retry_after_sec == 3600


def test_plain_429_becomes_rate_limited(monkeypatch):
    def _boom(kw):
        raise RuntimeError("429 too many requests")

    _install(monkeypatch, _boom)
    monkeypatch.setattr(gemini_tts, "_is_429", lambda e: True)
    monkeypatch.setattr(gemini_tts, "_is_daily_quota_error", lambda e: False)
    monkeypatch.setattr(gemini_tts, "_parse_retry_after", lambda e: 7)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "rate_limited"
    assert ei.value.retry_after_sec == 7


def test_unknown_error_becomes_retryable(monkeypatch):
    _install(monkeypatch, lambda kw: (_ for _ in ()).throw(RuntimeError("boh")))
    monkeypatch.setattr(gemini_tts, "_is_429", lambda e: False)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "retryable"


def test_every_raised_kind_is_in_the_closed_set(monkeypatch):
    _install(monkeypatch, lambda kw: (_ for _ in ()).throw(RuntimeError("boh")))
    monkeypatch.setattr(gemini_tts, "_is_429", lambda e: False)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind in TRANSPORT_KINDS
