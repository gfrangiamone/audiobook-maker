"""S7 (2026-10-13): uno stream SSE di avanzamento su un job fermo (stato
`analyzed`, mai terminale per il builder) restava aperto per sempre e teneva
un thread del dev server. Ora `_sse_stream` chiude dopo `SSE_MAX_SEC`
(ABM_SSE_MAX_SEC, default 1800); il client EventSource riapre da solo."""
import time

import audiobook_app


def _events(resp):
    out = []
    for chunk in resp.response:
        if isinstance(chunk, bytes):
            chunk = chunk.decode("utf-8")
        out.append(chunk)
    return out


def test_stream_closes_at_the_deadline_even_without_a_terminal_event(monkeypatch):
    monkeypatch.setattr(audiobook_app, "SSE_MAX_SEC", 0.15)
    audiobook_app.jobs["s7-job"] = {"status": "analyzed", "client_id": "c"}
    try:
        with audiobook_app.app.test_request_context("/"):
            resp = audiobook_app._sse_stream("s7-job", lambda job: ({"status": job["status"]}, False), sleep_sec=0.01)
            t0 = time.time()
            events = _events(resp)
    finally:
        audiobook_app.jobs.pop("s7-job", None)
    assert 1 <= len(events) <= 40 and time.time() - t0 < 2
    assert all('"status": "analyzed"' in e for e in events)


def test_terminal_event_still_closes_immediately(monkeypatch):
    monkeypatch.setattr(audiobook_app, "SSE_MAX_SEC", 1800)
    audiobook_app.jobs["s7-job"] = {"status": "done", "client_id": "c"}
    try:
        with audiobook_app.app.test_request_context("/"):
            resp = audiobook_app._sse_stream("s7-job", lambda job: ({"status": "done"}, True), sleep_sec=0.01)
            events = _events(resp)
    finally:
        audiobook_app.jobs.pop("s7-job", None)
    assert len(events) == 1


def test_default_is_half_an_hour_with_a_floor():
    assert audiobook_app.SSE_MAX_SEC == 1800
