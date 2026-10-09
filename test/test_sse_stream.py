"""E2(b): le SSE di avanzamento condividono loop, heartbeat e risposta (_sse_stream)."""
import inspect
import json

import audiobook_app as app


def _events(resp):
    body = resp.get_data(as_text=True)
    return [json.loads(chunk[len("data: "):]) for chunk in body.split("\n\n") if chunk.startswith("data: ")]


def test_sse_stream_heartbeat_terminal_and_missing_job(monkeypatch):
    monkeypatch.setattr(app, "jobs", {"j1": {"status": "generating", "n": 0}})
    sleeps = []
    monkeypatch.setattr(app.time, "sleep", lambda s: sleeps.append(s))

    def build(job):
        job["n"] += 1
        return {"status": job["status"], "n": job["n"]}, job["n"] >= 3

    with app.app.test_request_context("/"):
        resp = app._sse_stream("j1", build, sleep_sec=0.25)
        assert resp.mimetype == "text/event-stream"
        assert resp.headers["Cache-Control"] == "no-cache" and resp.headers["X-Accel-Buffering"] == "no"
        assert _events(resp) == [{"status": "generating", "n": 1}, {"status": "generating", "n": 2},
                                 {"status": "generating", "n": 3}]
    assert sleeps == [0.25, 0.25] and app.jobs["j1"]["last_poll"] > 0
    with app.app.test_request_context("/"):
        assert _events(app._sse_stream("manca", build)) == [{"status": "error", "error": "Job not found"}]
    assert app._sse_event({"a": 1}) == 'data: {"a": 1}\n\n'


def test_progress_routes_build_and_terminate(monkeypatch):
    app.app.config["TESTING"] = True
    monkeypatch.setattr(app, "_check_job_owner", lambda jid: (app.jobs.get(jid), None, None))
    monkeypatch.setattr(app.time, "sleep", lambda s: None)
    monkeypatch.setattr(app, "jobs", {
        "opt": {"status": "optimized", "opt_progress_current": 3, "opt_progress_total": 3},
        "tr": {"status": "translated", "tr_progress_current": 1, "translated_name": "x.abm"},
        "gen": {"status": "error", "gemini_preflight_block": {"retry_after_sec": 60},
                "payment": {"method": "paypal", "total_eur": 2.5}, "refund_voucher_code": "V-1"},
    })
    c = app.app.test_client()
    ev = _events(c.get("/api/optimize_progress/opt"))
    assert ev == [dict(ev[0], ai_optimized=True)] and ev[0]["status"] == "optimized" and ev[0]["opt_progress_current"] == 3
    ev = _events(c.get("/api/translate_progress/tr"))
    assert len(ev) == 1 and ev[0]["status"] == "translated" and ev[0]["translated_name"] == "x.abm"
    ev = _events(c.get("/api/progress/gen"))
    assert len(ev) == 1 and ev[0]["status"] == "error" and ev[0]["error"] == "generation_failed"
    assert ev[0]["error_kind"] == "gemini_overload" and ev[0]["refund_voucher_code"] == "V-1" and ev[0]["paid_eur"] == 2.5
    for jid in ("opt", "tr", "gen"):
        assert app.jobs[jid]["last_poll"] > 0


def test_single_sse_loop_in_app():
    src = inspect.getsource(app)
    assert src.count('mimetype="text/event-stream"') == 1
    assert 'yield f"data: {json.dumps(' not in src
    assert src.count("_sse_stream(job_id, _build") == 3 and src.count("_sse_response(") == 3
