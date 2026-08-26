"""Failover automatico da Cloudflare a Vertex."""
import pytest

import gemini_tts
import tts_backend_state as st
from gemini_transport import TransportError


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    gemini_tts.set_backend_switch_notifier(None)
    yield
    gemini_tts._BACKEND = {}
    gemini_tts.set_backend_switch_notifier(None)


def _pcm(n=48):
    return {"pcm": b"\x00" * n, "input_tokens": None, "output_tokens": None}


def _synth(tmp_path, **kw):
    return gemini_tts.synthesize(
        "ciao mondo", "gemini:flash31:Kore",
        output_path=str(tmp_path / "o.pcm"), **kw)


def test_credit_exhausted_trips_and_continues_on_vertex(tmp_path, monkeypatch):
    vertex_calls = []

    def _cf(**kw):
        raise TransportError("credito esaurito", kind="backend_down",
                             http_status=402, provider_code=2021)

    def _vx(**kw):
        vertex_calls.append(kw)
        return {"pcm": b"\x01" * 48, "input_tokens": 10, "output_tokens": 200}

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _vx)

    out = _synth(tmp_path, job_id="j42")

    assert out["success"] is True
    assert len(vertex_calls) == 1
    assert st.is_tripped("flash31") is True
    assert st.state("flash31")["trip_job_id"] == "j42"
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_the_notifier_fires_once_at_the_trip(tmp_path, monkeypatch):
    seen = []
    gemini_tts.set_backend_switch_notifier(
        lambda model_key, reason, detail, job_id: seen.append(
            (model_key, reason, job_id)))

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    _synth(tmp_path, job_id="j1")
    _synth(tmp_path, job_id="j2")

    assert len(seen) == 1
    assert seen[0][0] == "flash31"


def test_transient_failures_trip_only_at_the_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_CF_TRIP_FAILURES", "3")
    monkeypatch.setattr(gemini_tts, "_synth_max_attempts", lambda: 1)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("glitch", kind="retryable")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    for _ in range(2):
        with pytest.raises(RuntimeError):
            _synth(tmp_path)
    assert st.is_tripped("flash31") is False

    # Il terzo fallimento consecutivo fa scattare il breaker: la chiamata
    # prosegue su Vertex invece di fallire.
    out = _synth(tmp_path)
    assert out["success"] is True
    assert st.is_tripped("flash31") is True


def test_a_success_resets_the_failure_counter(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_CF_TRIP_FAILURES", "3")
    monkeypatch.setattr(gemini_tts, "_synth_max_attempts", lambda: 1)
    outcomes = [TransportError("glitch", kind="retryable"), None,
                TransportError("glitch", kind="retryable")]

    def _cf(**kw):
        exc = outcomes.pop(0)
        if exc:
            raise exc
        return _pcm()

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(RuntimeError):
        _synth(tmp_path)
    _synth(tmp_path)  # successo: azzera
    with pytest.raises(RuntimeError):
        _synth(tmp_path)
    assert st.state("flash31")["consecutive_failures"] == 1


def test_content_rejected_does_not_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("moderazione", kind="content_rejected",
                                           provider_code=2017)))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(Exception):
        _synth(tmp_path)
    # Un chunk sbagliato non deve buttare giu' il backend per tutti.
    assert st.is_tripped("flash31") is False


def test_fatal_does_not_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("voce inesistente", kind="fatal",
                                           provider_code=7003)))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(Exception):
        _synth(tmp_path)
    assert st.is_tripped("flash31") is False


def test_trip_without_a_ready_vertex_raises_unavailable(tmp_path, monkeypatch):
    def _vx(**kw):
        raise gemini_tts.GeminiUnavailable("Vertex non configurato")

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _vx)

    with pytest.raises(gemini_tts.GeminiUnavailable):
        _synth(tmp_path)


def test_a_tripped_model_goes_straight_to_vertex(tmp_path, monkeypatch):
    st.trip("flash31", reason="cf_credit_exhausted", detail="d", job_id="j0")
    gemini_tts._set_backend("flash31", "vertex")
    cf_calls = []

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: cf_calls.append(kw) or _pcm())
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    _synth(tmp_path)
    assert cf_calls == []
