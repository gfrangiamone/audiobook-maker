"""E1(a): _run_m4b_conversion, l'orchestrazione unica delle tre conversioni M4B."""
import os
import threading

import generation_engine as ge


def _quiet_sim(monkeypatch):
    started = []

    def sim(job, dur, stop):
        started.append(dur)
        stop.wait(2.0)

    monkeypatch.setattr(ge, "_m4b_progress_simulator", sim)
    return started


def test_success_first_attempt_sets_output_and_logs(monkeypatch, tmp_path):
    started = _quiet_sim(monkeypatch)
    logs = []
    monkeypatch.setattr(ge, "_log_m4b_progress", lambda jid, job, ev, **f: logs.append((ev, f)))
    final = str(tmp_path / "out.m4b")
    calls = []

    def convert(on_phase, status_out):
        on_phase(42, "encoding")
        status_out["status"] = "ok"
        calls.append(1)
        return True

    job = {}
    assert ge._run_m4b_conversion(job, "J1", final, convert, audio_dur_sec=0, size_mb=1.2345) is True
    assert job["output_m4b"] == final and job["m4b_failed"] is False
    assert job["m4b_progress_current"] == 42 and job["m4b_progress_message"] == "encoding"
    assert job["m4b_progress_total"] == 100 and started == [60.0]           # 0 -> 60 s di default
    assert [ev for ev, _ in logs] == ["START", "END"]
    assert logs[0][1] == {"size_mb": 1.23} and logs[1][1]["status"] == "ok" and logs[1][1]["pct"] == 42
    assert len(calls) == 1


def test_two_failures_then_cleanup(monkeypatch, tmp_path):
    _quiet_sim(monkeypatch)
    logs = []
    monkeypatch.setattr(ge, "_log_m4b_progress", lambda jid, job, ev, **f: logs.append((ev, f)))
    final = tmp_path / "out.m4b"
    final.write_bytes(b"partial")
    attempts = []

    def convert(on_phase, status_out):
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("ffmpeg died")
        return False

    job = {"output_m4b": None}
    assert ge._run_m4b_conversion(job, "J2", str(final), convert, audio_dur_sec=12.5, size_mb=3) is False
    assert len(attempts) == 2 and job["m4b_failed"] is True and not job.get("output_m4b")
    assert job["m4b_progress_total"] == 0 and not final.exists()
    assert logs[-1][0] == "END" and logs[-1][1]["status"] == "fail"


def test_retry_after_exception_then_success(monkeypatch, tmp_path):
    _quiet_sim(monkeypatch)
    monkeypatch.setattr(ge, "_log_m4b_progress", lambda *a, **k: None)
    final = str(tmp_path / "out.m4b")
    seq = iter([RuntimeError("boom"), True])

    def convert(on_phase, status_out):
        v = next(seq)
        if isinstance(v, Exception):
            raise v
        return v

    job = {}
    assert ge._run_m4b_conversion(job, "J3", final, convert, audio_dur_sec=5, size_mb=0) is True
    assert job["output_m4b"] == final and job["m4b_failed"] is False


def test_simulator_thread_is_stopped(monkeypatch, tmp_path):
    stops = []

    def sim(job, dur, stop):
        stops.append(stop)
        stop.wait(5.0)

    monkeypatch.setattr(ge, "_m4b_progress_simulator", sim)
    monkeypatch.setattr(ge, "_log_m4b_progress", lambda *a, **k: None)
    ge._run_m4b_conversion({}, "J4", str(tmp_path / "x.m4b"), lambda p, s: True, audio_dur_sec=1, size_mb=0)
    assert len(stops) == 1 and stops[0].is_set()


def test_engine_has_a_single_m4b_loop():
    import pathlib
    src = pathlib.Path(ge.__file__).read_text(encoding="utf-8")
    assert src.count("range(1, 3)") == 1 and src.count("target=_m4b_progress_simulator") == 1
    assert "_m4b_phase_cb" not in src and src.count("_run_m4b_conversion(") == 4
