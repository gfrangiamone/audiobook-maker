"""Contratto dell'eccezione di trasporto condivisa dagli adapter TTS."""
import pytest

from gemini_transport import TRANSPORT_KINDS, TransportError


def test_kinds_are_the_closed_set_from_the_spec():
    assert TRANSPORT_KINDS == frozenset({
        "retryable", "rate_limited", "quota_daily",
        "content_rejected", "backend_down", "fatal",
    })


def test_defaults_are_conservative():
    err = TransportError("boom", kind="retryable")
    assert err.kind == "retryable"
    assert err.retry_after_sec is None
    # Il default e' "non fatturato": sovrastimare la spesa e' meno dannoso che
    # sottostimarla, ma inventare un addebito che non c'e' e' peggio ancora.
    assert err.billed is False
    assert err.http_status is None
    assert err.provider_code is None


def test_carries_the_diagnostic_fields():
    err = TransportError("overload", kind="backend_down", retry_after_sec=12,
                         billed=True, http_status=503, provider_code=7003)
    assert (err.retry_after_sec, err.billed) == (12, True)
    assert (err.http_status, err.provider_code) == (503, 7003)


def test_rejects_an_unknown_kind():
    with pytest.raises(ValueError):
        TransportError("boom", kind="misterioso")


def test_is_a_runtime_error():
    # I caller storici intercettano RuntimeError: la sottoclasse preserva
    # quel comportamento se mai una TransportError sfuggisse.
    assert isinstance(TransportError("x", kind="fatal"), RuntimeError)
