"""Credito OpenRouter: dettaglio del 402 nel trip e sentinella della ricarica.

Incidente 05/11/2026 22:40: un 402 OpenRouter ha spostato flash38 su Gemini
API con il credito in attivo (~16,70 USD) e la ricarica automatica accesa; il
trip diceva solo "HTTP 402 code None". La sentinella legge il saldo dall'API e
avvisa sotto una soglia piu' bassa di quella di ricarica.
"""
import json

import pytest

import audiobook_app
import email_service
import gemini_transport as gt
import gemini_tts
import tts_backend_state as st
from gemini_transport import TransportError

pytestmark = pytest.mark.usefixtures("sleeps")


class _Resp:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("corpo non JSON")
        return self._payload


def _credits(total, usage):
    return _Resp(200, {"data": {"total_credits": total, "total_usage": usage}})


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    for env in ("ABM_GEMINI_BACKEND", "ABM_GEMINI_BACKEND_FLASH31",
                "ABM_GEMINI_API_KEY", "ABM_GCP_PROJECT_ID",
                "ABM_GOOGLE_CREDENTIALS_FILE", "ABM_OR_CREDIT_CHECK_SEC",
                "ABM_OR_CREDIT_ALERT_USD", "ABM_OR_TIMEOUT_MS"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "sk-or-segreta")
    monkeypatch.setattr(gemini_tts, "_data_dir", tmp_path)
    monkeypatch.setattr(gemini_tts, "_or_credit_next_at", 0.0)
    monkeypatch.setattr(gemini_tts, "_or_credit_notifier", None)
    gemini_tts.set_backend_switch_notifier(None)
    yield
    gemini_tts._BACKEND = {}
    st.reset("flash38")


# --- lettura del saldo ----------------------------------------------------------

def test_credit_left_is_credits_minus_usage_and_never_leaks_the_key(monkeypatch):
    seen = {}

    def _get(url, headers=None, timeout=None):
        seen.update(url=url, headers=headers, timeout=timeout)
        return _credits(120, 103.30280071)

    monkeypatch.setattr(gt.requests, "get", _get)
    assert gt.openrouter_credit_left() == pytest.approx(16.69719929)
    assert seen["url"] == gt.OR_CREDITS_URL
    assert seen["headers"]["Authorization"] == "Bearer sk-or-segreta"
    assert seen["timeout"] == 15.0


@pytest.mark.parametrize("resp", [
    _Resp(401, {"error": {"message": "sk-or-segreta non valida"}}),
    _Resp(200, None),
    _Resp(200, {"data": {"total_credits": "molti"}}),
    _Resp(200, {"data": {"total_credits": "nan", "total_usage": 0}}),
])
def test_bad_answers_are_transport_errors_without_the_key(monkeypatch, resp):
    monkeypatch.setattr(gt.requests, "get", lambda *a, **kw: resp)
    with pytest.raises(TransportError) as ei:
        gt.openrouter_credit_left()
    assert ei.value.kind == "retryable"
    assert "segreta" not in str(ei.value)


def test_network_error_is_redacted(monkeypatch):
    def _boom(*a, **kw):
        raise gt.requests.ConnectionError("sk-or-segreta nel messaggio")

    monkeypatch.setattr(gt.requests, "get", _boom)
    with pytest.raises(TransportError) as ei:
        gt.openrouter_credit_left()
    assert "segreta" not in str(ei.value)


def test_missing_key_is_fatal(monkeypatch):
    monkeypatch.delenv("ABM_OPENROUTER_API_KEY")
    with pytest.raises(TransportError) as ei:
        gt.openrouter_credit_left()
    assert ei.value.kind == "fatal"


# --- sentinella -----------------------------------------------------------------

def _balance(monkeypatch, *values):
    calls = []
    seq = list(values)

    def _left(**kw):
        calls.append(kw)
        v = seq.pop(0)
        if isinstance(v, Exception):
            raise v
        return v

    monkeypatch.setattr(gemini_tts._transport, "openrouter_credit_left", _left)
    return calls


def _notified():
    sent = []
    gemini_tts.set_or_credit_alert_notifier(lambda left, thr: sent.append((left, thr)))
    return sent


def _state(tmp_path):
    return json.loads((tmp_path / "openrouter_credit.json").read_text(encoding="utf-8"))


def test_fires_once_per_descent_and_rearms_above_threshold(monkeypatch, tmp_path):
    _balance(monkeypatch, 16.7, 4.0, 3.0, 50.0, 2.0)
    sent = _notified()
    t = 1000.0
    assert gemini_tts.check_openrouter_credit(now=t) == pytest.approx(16.7)
    assert sent == []
    gemini_tts.check_openrouter_credit(now=t + 900)
    assert sent == [(4.0, 5.0)]
    assert _state(tmp_path)["alerted"] is True
    gemini_tts.check_openrouter_credit(now=t + 1800)
    assert len(sent) == 1
    gemini_tts.check_openrouter_credit(now=t + 2700)
    assert _state(tmp_path)["alerted"] is False
    assert _state(tmp_path)["left_usd"] == 50.0
    gemini_tts.check_openrouter_credit(now=t + 3600)
    assert sent[-1] == (2.0, 5.0) and len(sent) == 2


def test_the_alert_survives_a_restart(monkeypatch, tmp_path):
    _balance(monkeypatch, 4.0, 4.0)
    sent = _notified()
    gemini_tts.check_openrouter_credit(now=1000.0)
    monkeypatch.setattr(gemini_tts, "_or_credit_next_at", 0.0)
    gemini_tts.check_openrouter_credit(now=1001.0)
    assert len(sent) == 1


def test_not_read_before_its_cadence(monkeypatch):
    calls = _balance(monkeypatch, 20.0, 20.0)
    gemini_tts.check_openrouter_credit(now=1000.0)
    assert gemini_tts.check_openrouter_credit(now=1899.0) is None
    assert len(calls) == 1


def test_threshold_and_cadence_come_from_env(monkeypatch):
    monkeypatch.setenv("ABM_OR_CREDIT_ALERT_USD", "8")
    monkeypatch.setenv("ABM_OR_CREDIT_CHECK_SEC", "60")
    calls = _balance(monkeypatch, 7.0, 7.0)
    sent = _notified()
    gemini_tts.check_openrouter_credit(now=1000.0)
    gemini_tts.check_openrouter_credit(now=1060.0)
    assert sent == [(7.0, 8.0)] and len(calls) == 2


def test_zero_cadence_turns_it_off(monkeypatch):
    monkeypatch.setenv("ABM_OR_CREDIT_CHECK_SEC", "0")
    calls = _balance(monkeypatch, 1.0)
    assert gemini_tts.check_openrouter_credit(now=1000.0) is None
    assert calls == []


def test_no_openrouter_model_no_read(monkeypatch):
    monkeypatch.delenv("ABM_OPENROUTER_API_KEY")
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "apikey")
    calls = _balance(monkeypatch, 1.0)
    assert gemini_tts.check_openrouter_credit(now=1000.0) is None
    assert calls == []


def test_the_alert_is_not_burned_without_a_notifier(monkeypatch, tmp_path):
    _balance(monkeypatch, 1.0, 1.0)
    gemini_tts.check_openrouter_credit(now=1000.0)
    assert not _state(tmp_path).get("alerted")
    sent = _notified()
    gemini_tts.check_openrouter_credit(now=2000.0)
    assert sent == [(1.0, 5.0)]


def test_a_failed_read_changes_nothing(monkeypatch, tmp_path):
    _balance(monkeypatch, TransportError("saldo OpenRouter: HTTP 500", kind="retryable"))
    sent = _notified()
    assert gemini_tts.check_openrouter_credit(now=1000.0) is None
    assert sent == []
    assert not (tmp_path / "openrouter_credit.json").exists()


# --- collegamento e email ---------------------------------------------------------

def test_the_app_wires_email_and_activity_log(monkeypatch):
    sent, logged = [], []
    monkeypatch.setattr(email_service, "admin_notify_or_credit_low",
                        lambda *a, **kw: sent.append(a))
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: logged.append((a, kw)))
    audiobook_app._on_or_credit_alert(3.5, 5.0)
    assert sent == [(3.5, 5.0)]
    assert logged[0][0][2] == "TTS_OR_CREDIT_LOW"
    assert logged[0][1].get("epoch") is not None


def test_the_email_states_balance_threshold_and_what_to_do(monkeypatch):
    captured = {}
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subject, body: captured.update(
                            subject=subject, body=body) or True)
    email_service.admin_notify_or_credit_low(3.25, 5.0)
    assert "3.25" in captured["subject"]
    assert "3.25" in captured["body"] and "5.00" in captured["body"]
    assert "ricarica automatica" in captured["body"]
    assert "ABM_OR_CREDIT_CHECK_SEC=0" in captured["body"]
    assert "ABM_OPENROUTER_API_KEY" not in captured["body"]


# --- dettaglio del 402 nel trip ----------------------------------------------------

def test_the_402_message_reaches_the_trip_detail(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "g")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    resp = _Resp(402, {"error": {"message": "Insufficient credits", "code": 402}})
    resp.headers, resp.text = {"Content-Type": "application/json"}, ""

    def _or(**kw):
        return gt._interpret_openrouter_response(resp)

    monkeypatch.setattr(gemini_tts._transport, "openrouter_call", _or)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": b"\x01" * 48, "input_tokens": 10,
                                      "output_tokens": 200})
    out = gemini_tts.synthesize("ciao mondo", "gemini:flash38:Kore",
                                output_path=str(tmp_path / "o.pcm"), job_id="j1")
    assert out["success"] and out["backend"] == "apikey"
    detail = st.state("flash38")["trip_detail"]
    assert detail.startswith("HTTP 402 code None: ")
    assert "OpenRouter rifiuta per credito (HTTP 402): Insufficient credits" in detail
