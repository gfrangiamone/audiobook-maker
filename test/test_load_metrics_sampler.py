"""Campionatore di carico e agganci dei contatori in audiobook_app."""
from unittest.mock import patch

import pytest

import audiobook_app as app
import cleanup
import assembly_queue as aq
import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def test_collect_sample_reports_jobs_and_queue():
    with patch.dict(app.jobs, {
        "a": {"status": "generating", "voice": "it-IT-ElsaNeural"},
        "b": {"status": "generating",
              "voice": "gemini:gemini-2.5-flash-preview-tts:Kore"},
        "c": {"status": "done", "voice": "it-IT-ElsaNeural"},
    }, clear=True):
        g = cleanup._collect_load_sample()
    assert g["gen"] == 2
    assert g["gen_p"] == 1
    assert g["jobs"] == 3
    assert "asm_h" in g and "asm_q" in g


def test_collect_sample_works_without_proc(monkeypatch):
    """Fuori da Linux le metriche di macchina mancano, il resto no."""
    monkeypatch.setattr(cleanup, "_read_proc_kv", lambda _p: {})
    monkeypatch.setattr(cleanup, "_cpu_percent", lambda: (None, None))
    with patch.dict(app.jobs, {}, clear=True):
        g = cleanup._collect_load_sample()
    assert g["gen"] == 0
    assert "ram" not in g and "swap" not in g


def test_collect_sample_includes_disk():
    with patch.dict(app.jobs, {}, clear=True):
        g = cleanup._collect_load_sample()
    assert 0 <= g["disk"] <= 100
    assert g["disk_free_gb"] >= 0


def test_cleanup_heartbeat_age_is_reported():
    import time
    cleanup._cleanup_heartbeat[0] = time.time() - 120
    with patch.dict(app.jobs, {}, clear=True):
        g = cleanup._collect_load_sample()
    assert 115 <= g["hb"] <= 130


def test_assembly_observer_records_wait_and_encode(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "observe",
                        lambda h, s, premium=False, now=None: seen.append((h, s, premium)))
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append((c, n, None)))
    cleanup._assembly_metrics_observer("release", "j1", aq.PRIORITY_PREMIUM, 12.0, 30.0)
    assert ("asm_wait", 12.0, True) in seen
    assert ("enc", 30.0, False) in seen


def test_assembly_observer_records_timeout(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "observe",
                        lambda h, s, premium=False, now=None: seen.append(("obs", h)))
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append(("inc", c)))
    cleanup._assembly_metrics_observer("timeout", "j2", aq.PRIORITY_NORMAL, 1800.0, 0.0)
    assert ("inc", "asm_timeout") in seen
    assert ("obs", "asm_wait") in seen


def test_server_busy_counts_the_rejection(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append(c))
    monkeypatch.setattr(app, "_server_at_capacity", lambda: (True, 6, 6))
    with app.app.test_request_context("/api/generate"):
        resp = app._server_busy_response("j3", "/api/generate", premium=True)
    assert resp[1] == 429
    assert seen == ["rej_busy_p"]


def test_server_busy_does_not_count_when_not_at_capacity(monkeypatch):
    seen = []
    monkeypatch.setattr(lm, "incr", lambda c, n=1, now=None: seen.append(c))
    monkeypatch.setattr(app, "_server_at_capacity", lambda: (False, 1, 6))
    with app.app.test_request_context("/api/generate"):
        assert app._server_busy_response("j4", "/api/generate") is None
    assert seen == []


def test_voxcpm_workers_in_running_are_sampled(monkeypatch):
    monkeypatch.setattr(app.voxcpm_tts, "worker_health",
                        lambda: {"running": 2, "idle": 1})
    with patch.dict(app.jobs, {}, clear=True):
        g = cleanup._collect_load_sample()
    assert g["vx_run"] == 2 and g["vx_busy"] == 1


def test_voxcpm_idle_workers_do_not_count_as_busy(monkeypatch):
    monkeypatch.setattr(app.voxcpm_tts, "worker_health",
                        lambda: {"running": 0, "idle": 3})
    with patch.dict(app.jobs, {}, clear=True):
        g = cleanup._collect_load_sample()
    assert g["vx_run"] == 0 and g["vx_busy"] == 0


def test_voxcpm_failed_probe_leaves_the_gauge_out(monkeypatch):
    monkeypatch.setattr(app.voxcpm_tts, "worker_health", lambda: None)
    with patch.dict(app.jobs, {}, clear=True):
        g = cleanup._collect_load_sample()
    assert "vx_busy" not in g and "vx_run" not in g
