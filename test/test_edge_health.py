"""edge_health: finestra scorrevole degli errori edge-tts e allerta admin.

Incidente 10/10/2026: 403 su un quarto delle richieste, migliaia di chunk in
silenzio, scoperto per caso dai log. Questi test fissano quando l'allerta
parte, quante volte, e che edge_engine alimenti davvero il contatore.
"""
import asyncio
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_engine
import edge_health
import email_service

T0 = 1_800_000_000.0


@pytest.fixture
def eh(monkeypatch):
    for k in ("ABM_EDGE_ALERT", "ABM_EDGE_ALERT_WINDOW_SEC", "ABM_EDGE_ALERT_MIN_CALLS",
              "ABM_EDGE_ALERT_FAIL_PCT", "ABM_EDGE_ALERT_RETRY_PCT", "ABM_EDGE_ALERT_COOLDOWN_SEC"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("ABM_EDGE_ALERT_MIN_CALLS", "10")
    sent = []
    done = threading.Event()

    def _notifier(snap):
        sent.append(snap)
        done.set()

    prev = edge_health._notifier
    edge_health.reset()
    edge_health.set_notifier(_notifier)
    yield sent, done
    edge_health.set_notifier(prev)
    edge_health.reset()


def _calls(n, ok, now=T0):
    fired = 0
    for i in range(n):
        edge_health.record_attempt("" if ok else "HTTP 403", now=now + i * 0.01)
        fired += edge_health.record_call(ok, now=now + i * 0.01)
    return fired


def test_healthy_traffic_never_alerts(eh):
    sent, _ = eh
    assert _calls(200, True) == 0
    assert sent == []


def test_silence_over_threshold_alerts_once(eh):
    sent, done = eh
    _calls(20, True)
    assert _calls(5, False, now=T0 + 1) == 1          # 1/21 > 2%: scatta subito
    assert done.wait(2)
    snap = sent[0]
    assert snap["reason"] == "silence"
    assert snap["top_errors"][0] == ("HTTP 403", 1)
    assert (snap["failed"], snap["calls"]) == (1, 21)
    assert _calls(50, False, now=T0 + 2) == 0          # cooldown: niente spam
    assert len(sent) == 1


def test_below_min_calls_no_alert(eh):
    sent, _ = eh
    assert _calls(9, False) == 0
    assert sent == []


def test_retry_pressure_alerts_before_silence(eh):
    sent, done = eh
    for i in range(20):
        edge_health.record_attempt("HTTP 403", now=T0 + i)
        edge_health.record_attempt("", now=T0 + i)
        edge_health.record_call(True, now=T0 + i)
    assert done.wait(2)
    assert sent[0]["reason"] == "retries"
    assert sent[0]["failed"] == 0


def test_cooldown_expires(eh, monkeypatch):
    sent, _ = eh
    monkeypatch.setenv("ABM_EDGE_ALERT_COOLDOWN_SEC", "3600")
    assert _calls(10, False) == 1
    assert _calls(10, False, now=T0 + 3599) == 0
    assert _calls(10, False, now=T0 + 3601) == 1


def test_window_forgets_old_failures(eh):
    sent, _ = eh
    edge_health.set_notifier(None)
    _calls(10, False)                                  # nessun notifier: nessuna allerta
    edge_health.set_notifier(lambda s: sent.append(s))
    assert _calls(30, True, now=T0 + 3600) == 0       # i fallimenti di un'ora fa sono fuori
    snap = edge_health.snapshot(now=T0 + 3600)
    assert snap["failed"] == 0 and snap["calls"] == 30


def test_kill_switch(eh, monkeypatch):
    monkeypatch.setenv("ABM_EDGE_ALERT", "0")
    assert _calls(30, False) == 0


def test_notifier_exception_is_swallowed(eh):
    def _boom(snap):
        raise RuntimeError("smtp giu'")
    edge_health.set_notifier(_boom)
    edge_health._notify(_boom, {})                     # non solleva


def test_error_signature():
    class _Hs(Exception):
        status = 403
    assert edge_health.error_signature(_Hs("Invalid response status, url=wss://x?id=1")) == "HTTP 403"
    assert edge_health.error_signature(asyncio.TimeoutError()) == "timeout"
    assert edge_health.error_signature(ValueError("a\n  b")) == "ValueError: a b"
    assert edge_health.error_signature(ValueError()) == "ValueError"


def test_edge_engine_feeds_counters(eh, monkeypatch, tmp_path):
    class _Forbidden(Exception):
        status = 403

    class _Comm:
        def __init__(self, text, voice, rate):
            pass

        async def save(self, path):
            raise _Forbidden("403")

    async def _no_sleep(_s):
        return None

    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", _Comm)
    monkeypatch.setattr(edge_engine, "_generate_silence_mp3", lambda p, duration_sec=1: None)
    monkeypatch.setattr(edge_engine, "_edge_retry_wait", lambda a, e: 0)
    ok = asyncio.run(edge_engine._edge_tts_call("ciao", "it-IT-DiegoNeural", "+0%",
                                                str(tmp_path / "c.mp3"), max_retries=3))
    assert ok is False
    snap = edge_health.snapshot()
    assert (snap["calls"], snap["failed"], snap["attempts"], snap["attempt_errors"]) == (1, 1, 3, 3)
    assert snap["top_errors"] == [("HTTP 403", 3)]


def test_admin_email_escapes_and_flags_new_release(monkeypatch):
    captured = {}
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subj, body: captured.update(subj=subj, body=body))
    monkeypatch.setattr(edge_health, "latest_release", lambda timeout=5.0: "7.3.0")
    snap = {"reason": "silence", "calls": 100, "failed": 25, "fail_pct": 25.0,
            "attempts": 300, "attempt_errors": 200, "retry_pct": 66.67,
            "top_errors": [("HTTP 403", 180), ("Err: <script>", 20)],
            "window_sec": 900, "fail_threshold_pct": 2.0, "retry_threshold_pct": 20.0,
            "cooldown_sec": 21600, "library_version": "7.2.8"}
    email_service.admin_notify_edge_tts_degraded(snap)
    assert "URGENTE" in captured["subj"]
    assert "7.3.0" in captured["body"] and "7.2.8" in captured["body"]
    assert "<script>" not in captured["body"]
