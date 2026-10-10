"""E3, seam cleanup/tiering/supervisor (2026-10-10): cleanup loop, eviction,
marker, memoria e campionatore in `cleanup`; helper e valori della app risolti
a ogni chiamata."""
import inspect
import re
import threading

import pytest

import audiobook_app
import cleanup


def test_module_owns_the_loop_and_app_keeps_no_copy():
    src = inspect.getsource(audiobook_app)
    for name in ("def _cleanup_loop(", "def _cleanup_supervisor(", "def _evict_hot_local(", "def _reconcile_cold_offload(",
                 "def _cleanup_job(", "def _email_marker_protects(", "def _log_memory_stats(", "def _malloc_trim(",
                 "def _load_metrics_sampler(", "CLEANUP_INTERVAL_SEC = "):
        assert name not in src and name in inspect.getsource(cleanup), name
    assert "cleanup.configure(" in src
    assert "target=cleanup._cleanup_supervisor" in src and "target=cleanup._load_metrics_supervisor" in src
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(cleanup), flags=re.M)
    assert "for attempt in range(" not in inspect.getsource(cleanup)          # retry via retry_util
    for n in cleanup.FUNCS:
        assert callable(getattr(audiobook_app, n)), n


def test_values_and_helpers_resolve_on_the_app(monkeypatch, tmp_path):
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(audiobook_app, "_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(audiobook_app, "ADMIN_EMAIL", "adm@x.it")
    monkeypatch.setattr(audiobook_app, "EMAIL_FILE_RETENTION_SEC", 11)
    monkeypatch.setattr(audiobook_app, "GEMINI_FILE_RETENTION_SEC", 22)
    monkeypatch.setattr(audiobook_app, "jobs", {"J": {}})
    assert cleanup._upload_dir() == tmp_path and cleanup._data_dir() == str(tmp_path)
    assert cleanup._admin_email() == "adm@x.it" and cleanup._email_file_retention_sec() == 11
    assert cleanup._gemini_file_retention_sec() == 22 and cleanup._jobs() == {"J": {}}
    assert cleanup._jobs_lock is audiobook_app._jobs_lock
    import generation_engine
    assert cleanup.generation_engine is generation_engine
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: "patched")
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 7)
    assert cleanup._smtp_available() == "patched" and cleanup._effective_retention_for_token_info({}) == 7


def test_email_marker_write_retries_then_gives_up(tmp_path, monkeypatch, capsys):
    import retry_util
    waits = []
    real = retry_util.retry_call
    monkeypatch.setattr(retry_util, "retry_call", lambda fn, **kw: real(fn, **{**kw, "sleep": waits.append}))
    cleanup._write_email_marker(tmp_path / "job")
    assert (tmp_path / "job" / cleanup.EMAIL_MARKER_FILENAME).exists() and waits == []
    calls = []

    def boom(self, *a, **k):
        calls.append(1)
        raise OSError("disco pieno")

    monkeypatch.setattr(type(tmp_path), "write_text", boom)
    cleanup._write_email_marker(tmp_path / "job2")
    out = capsys.readouterr().out
    assert len(calls) == 3 and waits == [0.2, 0.4]
    assert out.count("write failed") == 3 and "PERSISTENT FAILURE" in out
