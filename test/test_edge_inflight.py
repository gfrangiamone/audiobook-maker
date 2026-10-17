"""Tetto globale alle chiamate edge-tts in volo (ABM_EDGE_MAX_INFLIGHT).

Ogni job ha il suo event loop in un thread: il tetto deve valere fra loop
diversi, liberarsi anche quando la chiamata fallisce, e non tenere il
permesso durante le pause fra i tentativi.
"""

import asyncio
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_engine
from slot_gate import SlotGate


def _fake_communicate(monkeypatch, state, fail=False):
    lock = threading.Lock()

    class _C:
        def __init__(self, text, voice, rate):
            pass

        async def save(self, path):
            with lock:
                state["now"] += 1
                state["max"] = max(state["max"], state["now"])
            try:
                await asyncio.sleep(0.15)
                if fail:
                    raise RuntimeError("boom")
                with open(path, "wb") as f:
                    f.write(b"\0" * 60000)
            finally:
                with lock:
                    state["now"] -= 1

    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", _C)


def _run_jobs(n, tmp_path, max_retries=1):
    results = []

    def _job(i):
        out = str(tmp_path / f"c{i}.mp3")
        ok, _ = asyncio.run(edge_engine._edge_tts_attempts(
            "Testo di prova abbastanza lungo.", "it-IT-ElsaNeural", "+0%", out,
            max_retries=max_retries))
        results.append(ok)

    ths = [threading.Thread(target=_job, args=(i,)) for i in range(n)]
    for t in ths:
        t.start()
    for t in ths:
        t.join(timeout=10)
    return results


def setup_function():
    edge_engine._edge_gate.reset()


def test_cap_holds_across_job_loops(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_EDGE_MAX_INFLIGHT", "2")
    state = {"now": 0, "max": 0}
    _fake_communicate(monkeypatch, state)
    assert _run_jobs(5, tmp_path) == [True] * 5
    assert state["max"] == 2
    assert edge_engine._edge_gate.active() == 0


def test_zero_means_no_cap(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_EDGE_MAX_INFLIGHT", "0")
    state = {"now": 0, "max": 0}
    _fake_communicate(monkeypatch, state)
    assert _run_jobs(4, tmp_path) == [True] * 4
    assert state["max"] == 4


def test_slot_released_on_failure(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_EDGE_MAX_INFLIGHT", "1")
    monkeypatch.setattr(edge_engine, "_edge_retry_wait", lambda a, e: 0)
    state = {"now": 0, "max": 0}
    _fake_communicate(monkeypatch, state, fail=True)
    assert _run_jobs(2, tmp_path, max_retries=2) == [False, False]
    assert state["max"] == 1
    assert edge_engine._edge_gate.active() == 0


def test_default_is_above_measured_peak(monkeypatch):
    monkeypatch.delenv("ABM_EDGE_MAX_INFLIGHT", raising=False)
    assert edge_engine.edge_max_inflight() == 64


def test_gate_stats_and_unlimited():
    cap = [1]
    g = SlotGate(lambda: cap[0])
    assert g.acquire(timeout=0) is True
    assert g.acquire(timeout=0.05) is False
    assert g.free() == 0
    cap[0] = 0
    assert g.free() is None
    assert g.acquire(timeout=0) is True
    peak, waits, _ = g.take_stats()
    assert (peak, waits) == (2, 0)
    g.release()
    g.release()
    # il picco riparte dalle chiamate in volo al momento della lettura
    assert g.take_stats()[0] == 2
    assert g.take_stats()[0] == 0


def test_gate_counts_waits():
    g = SlotGate(lambda: 1)
    assert g.acquire() is True
    threading.Timer(0.1, g.release).start()
    t0 = time.monotonic()
    assert g.acquire(timeout=2) is True
    assert time.monotonic() - t0 >= 0.05
    _, waits, wait_sec = g.take_stats()
    assert waits == 1 and wait_sec > 0
    g.release()
