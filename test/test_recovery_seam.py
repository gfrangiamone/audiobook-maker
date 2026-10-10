"""E3, seam recovery orfani (2026-10-10): gate, ri-accodatura, ripiego e giro di
recupero in `recovery`; helper della app risolti a ogni chiamata."""
import inspect
import re

import pytest

import audiobook_app
import recovery


def test_module_owns_recovery_and_app_keeps_no_copy():
    src = inspect.getsource(audiobook_app)
    for name in ("class _RecoveryRejected(", "def _recovery_generate_gate(", "def _reenqueue_orphan(",
                 "def _orphan_fallback(", "def _recover_orphan_jobs(", "def _send_interrupted_email("):
        assert name not in src and name in inspect.getsource(recovery), name
    assert "recovery.configure(" in src and "recovery._recover_orphan_jobs" in src
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(recovery), flags=re.M)
    for n in recovery.FUNCS:
        assert callable(getattr(audiobook_app, n)), n


def test_helpers_resolve_on_the_app(monkeypatch):
    monkeypatch.setattr(audiobook_app, "jobs", {"J": {"status": "queued"}})
    assert recovery._jobs() == {"J": {"status": "queued"}} and recovery._jobs_lock is audiobook_app._jobs_lock
    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: "parsed:" + src)
    monkeypatch.setattr(audiobook_app, "run_generation", lambda *a, **k: "gen")
    assert recovery._parse_book("x") == "parsed:x" and recovery.run_generation() == "gen"


def test_orphan_reject_marks_descriptor_failed(monkeypatch):
    import pending_jobs
    marked = []
    monkeypatch.setattr(pending_jobs, "mark_failed", lambda jid: marked.append(jid))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    recovery._orphan_reject("J-rec", {"id": "J-rec", "phase": "generate"}, "motivo di test")
    assert marked == ["J-rec"]
