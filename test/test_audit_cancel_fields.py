"""Verifica che _write_gemini_audit accetti e persista i campi cancel_*."""
from unittest.mock import patch

import generation_engine


def _make_job(cancel_meta=None):
    j = {
        "payment": {"token": "X", "total_eur": 2.00, "method": "paypal"},
        "gemini_actual": {"google_cost_eur": 0.30, "chars": 1000,
                          "input_tokens": 100, "output_tokens": 200,
                          "audio_seconds": 30.0},
        "rate": "+0%",
    }
    if cancel_meta is not None:
        j["cancel_meta"] = cancel_meta
    return j


def test_audit_includes_cancel_fields_when_present():
    job = _make_job(cancel_meta={
        "paid_eur": 2.00,
        "retained_eur": 0.71,
        "refund_eur": 1.29,
        "progress_pct": 28,
        "partial_audio_delivered": True,
    })
    captured = {}
    with patch("generation_engine.gemini_cost_audit.append_record",
               side_effect=lambda r: captured.update(r)):
        generation_engine._write_gemini_audit(
            "job1", job, "gemini:flash25:Zephyr", "it", "cancelled_partial")
    assert captured["outcome"] == "cancelled_partial"
    assert captured["cancel_paid_eur"] == 2.00
    assert captured["cancel_retained_eur"] == 0.71
    assert captured["cancel_refund_eur"] == 1.29
    assert captured["cancel_progress_pct"] == 28
    assert captured["cancel_partial_audio_delivered"] is True


def test_audit_no_cancel_fields_when_absent():
    job = _make_job(cancel_meta=None)
    captured = {}
    with patch("generation_engine.gemini_cost_audit.append_record",
               side_effect=lambda r: captured.update(r)):
        generation_engine._write_gemini_audit(
            "job1", job, "gemini:flash25:Zephyr", "it", "completed")
    assert captured["outcome"] == "completed"
    assert "cancel_paid_eur" not in captured
    assert "cancel_retained_eur" not in captured
