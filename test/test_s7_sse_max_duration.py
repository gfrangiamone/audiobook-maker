"""S7 (2026-10-13): uno stream SSE di avanzamento su un job fermo (stato
`analyzed`, mai terminale per il builder) restava aperto per sempre e teneva
un thread del dev server. Ora `_sse_stream` chiude dopo `SSE_MAX_SEC`
(ABM_SSE_MAX_SEC, default 1800); il client EventSource riapre da solo."""
import os
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


def test_rollover_gives_the_client_time_to_reopen(monkeypatch):
    """16/11/2026: con la scheda in background il browser riapriva lo stream
    con piu' di 60 s di ritardo e il cleanup uccideva il job gratuito senza
    email a 30, 60, 90... minuti dall'avvio. Alla chiusura per scadenza
    `last_poll` va avanti del margine di riapertura."""
    monkeypatch.setattr(audiobook_app, "SSE_MAX_SEC", 0.05)
    monkeypatch.setattr(audiobook_app, "SSE_ROLLOVER_GRACE_SEC", 180)
    audiobook_app.jobs["s7-job"] = {"status": "generating", "client_id": "c"}
    try:
        with audiobook_app.app.test_request_context("/"):
            resp = audiobook_app._sse_stream("s7-job", lambda job: ({"status": "generating"}, False), sleep_sec=0.01)
            _events(resp)
            t_end = time.time()
        last_poll = audiobook_app.jobs["s7-job"]["last_poll"]
    finally:
        audiobook_app.jobs.pop("s7-job", None)
    assert t_end + 170 <= last_poll <= t_end + 181


def test_terminal_close_does_not_extend_the_heartbeat(monkeypatch):
    monkeypatch.setattr(audiobook_app, "SSE_MAX_SEC", 1800)
    audiobook_app.jobs["s7-job"] = {"status": "done", "client_id": "c"}
    try:
        with audiobook_app.app.test_request_context("/"):
            resp = audiobook_app._sse_stream("s7-job", lambda job: ({"status": "done"}, True), sleep_sec=0.01)
            _events(resp)
        last_poll = audiobook_app.jobs["s7-job"]["last_poll"]
    finally:
        audiobook_app.jobs.pop("s7-job", None)
    assert last_poll <= time.time()


def test_progress_page_reports_a_vanished_job():
    """Dopo il 404 la pagina restava ferma sull'ultima percentuale: ora chiede
    lo status e mostra il messaggio, e a tentativi esauriti dice che il
    collegamento e' perso."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "static", "js", "app.js"), encoding="utf-8") as f:
        js = f.read()
    start = js.index("function listenProgress(){")
    body = js[start:js.index("\nfunction ", start + 10)]
    assert "_progressJobGone(myJobId)" in body
    assert "_stopProgressJobGone(myJobId)" in body
    assert "t('sse_lost')" in body
    assert "async function _progressJobGone(id)" in js
    assert "r.status===404" in js[js.index("async function _progressJobGone(id)"):]
    with open(os.path.join(root, "templates", "_fragments", "i18n_data.js"), encoding="utf-8") as f:
        i18n = f.read()
    for lang in ("it", "en", "fr", "es", "de", "zh", "hi"):
        assert f"Object.assign(L.{lang},{{gen_job_gone:" in i18n
