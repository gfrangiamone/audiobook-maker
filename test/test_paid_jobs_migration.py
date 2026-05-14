"""Test migration _paid_opt_done.json -> _paid_jobs_done.json."""
import json
import time
import pytest
from pathlib import Path


def test_migration_creates_unified_file(tmp_path, monkeypatch):
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    (tmp_path / "_paid_opt_done.json").write_text(json.dumps(["job1", "job2"]))
    payment._migrate_paid_opt_to_paid_jobs()
    new = json.loads((tmp_path / "_paid_jobs_done.json").read_text())
    assert {r["job_id"] for r in new} == {"job1", "job2"}
    assert all(r["purpose"] == "llm" for r in new)
    assert (tmp_path / "_paid_opt_done.json.pre_unify_bak").exists()


def test_migration_idempotent_skip_if_already_done(tmp_path, monkeypatch):
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    (tmp_path / "_paid_jobs_done.json").write_text(json.dumps([{"job_id": "x", "purpose": "gemini", "ts": 0}]))
    (tmp_path / "_paid_opt_done.json").write_text(json.dumps(["job1"]))
    payment._migrate_paid_opt_to_paid_jobs()
    data = json.loads((tmp_path / "_paid_jobs_done.json").read_text())
    assert len(data) == 1 and data[0]["job_id"] == "x"


def test_migration_handles_empty_legacy(tmp_path, monkeypatch):
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_OPT_DONE_FILE", tmp_path / "_paid_opt_done.json")
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    # No legacy file at all
    payment._migrate_paid_opt_to_paid_jobs()
    new = json.loads((tmp_path / "_paid_jobs_done.json").read_text())
    assert new == []


def test_mark_and_query_paid_job(tmp_path, monkeypatch):
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    payment._mark_paid_job_done("jobA", purpose="gemini")
    payment._mark_paid_job_done("jobB", purpose="llm")
    assert payment._is_paid_job_done("jobA") is True
    assert payment._is_paid_job_done("jobB") is True
    assert payment._is_paid_job_done("jobC") is False
    # File persisted
    saved = json.loads((tmp_path / "_paid_jobs_done.json").read_text())
    assert {r["job_id"] for r in saved} == {"jobA", "jobB"}
    purposes = {r["job_id"]: r["purpose"] for r in saved}
    assert purposes["jobA"] == "gemini"
    assert purposes["jobB"] == "llm"


def test_mark_paid_opt_done_shim_writes_to_unified(tmp_path, monkeypatch):
    """Old _mark_paid_opt_done shim must redirect to new unified storage as purpose=llm."""
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    payment._mark_paid_opt_done("legacyJob")
    assert payment._is_paid_job_done("legacyJob") is True
    saved = json.loads((tmp_path / "_paid_jobs_done.json").read_text())
    assert len(saved) == 1
    assert saved[0]["purpose"] == "llm"


def test_recovery_skips_completed_gemini_job(tmp_path, monkeypatch):
    """Recovery must NOT refund a voucher use whose job is recorded in _paid_jobs_done."""
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "_vouchers", {})
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    payment._voucher_consume(code, 1.0, job_id="genJob1")
    # Record as completed in unified store
    payment._mark_paid_job_done("genJob1", purpose="gemini")
    rem_before = payment._voucher_remaining(payment._vouchers[code])
    # Recovery with empty jobs dict (simulating restart)
    payment._recover_orphaned_voucher_charges({})
    rem_after = payment._voucher_remaining(payment._vouchers[code])
    assert rem_after == rem_before  # NOT refunded — gemini job is recorded as completed


def test_recovery_refunds_orphaned_gemini_job(tmp_path, monkeypatch):
    """Voucher use without record in _paid_jobs_done AND not in jobs dict → refunded."""
    import payment
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json")
    monkeypatch.setattr(payment, "_paid_jobs_done", [])
    monkeypatch.setattr(payment, "_vouchers", {})
    code, _ = payment._create_voucher("u@x.it", 5.0, kind="test", note="t")
    payment._voucher_consume(code, 1.0, job_id="orphanJob")
    rem_before = payment._voucher_remaining(payment._vouchers[code])
    payment._recover_orphaned_voucher_charges({})  # no record, not in jobs
    rem_after = payment._voucher_remaining(payment._vouchers[code])
    assert rem_after > rem_before  # refunded


def test_atomic_write_json_creates_then_replaces(tmp_path):
    import payment
    target = tmp_path / "test.json"
    payment._atomic_write_json(target, {"a": 1})
    assert target.exists()
    assert json.loads(target.read_text()) == {"a": 1}
    # No .tmp leftover
    assert not (tmp_path / "test.json.tmp").exists()
