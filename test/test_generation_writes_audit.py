"""Test that run_generation writes audit records at end (success/cancel/error)."""
import generation_engine
import gemini_cost_audit


def test_write_gemini_audit_success_appends_record(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {
        "gemini_actual": {
            "input_tokens": 100, "output_tokens": 500, "chars": 50,
            "audio_seconds": 12.5, "google_cost_eur": 0.0012, "model_key": "flash25",
        },
        "payment": {"total_eur": 1.50},
    }
    generation_engine._write_gemini_audit(
        "job-abc", job, "gemini:flash25:Zephyr", "it", "completed"
    )
    assert len(captured) == 1
    rec = captured[0]
    assert rec["job_id"] == "job-abc"
    assert rec["model_key"] == "flash25"
    assert rec["language"] == "it"
    assert rec["chars_total"] == 50
    assert rec["input_tokens_actual"] == 100
    assert rec["output_tokens_actual"] == 500
    assert rec["audio_seconds_actual"] == 12.5
    assert rec["google_cost_eur_actual"] == 0.0012
    assert rec["user_price_eur_charged"] == 1.50
    assert rec["outcome"] == "completed"
    # should_have_been computed from compute_user_price_eur
    assert rec["user_price_eur_should_have_been"] >= 0.0
    # delta_eur = should - charged
    assert abs(rec["delta_eur"] - (rec["user_price_eur_should_have_been"] - 1.50)) < 0.01
    # margin_eur_actual = charged - google_cost
    assert abs(rec["margin_eur_actual"] - (1.50 - 0.0012)) < 0.01


def test_write_gemini_audit_skips_non_gemini(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {"gemini_actual": {}, "payment": {}}
    generation_engine._write_gemini_audit("j", job, "en-US-Neural2-A", "en", "completed")
    assert captured == []


def test_write_gemini_audit_missing_payment_uses_zero_charged(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {"gemini_actual": {"google_cost_eur": 0.001, "model_key": "flash25"}}
    generation_engine._write_gemini_audit(
        "j", job, "gemini:flash25:Zephyr", "it", "failed_refunded"
    )
    assert len(captured) == 1
    assert captured[0]["user_price_eur_charged"] == 0.0
    assert captured[0]["delta_pct"] == 0.0  # no charge -> no pct
    assert captured[0]["outcome"] == "failed_refunded"


def test_write_gemini_audit_swallows_internal_errors(monkeypatch, capsys):
    # If compute_user_price_eur raises and append_record raises, the helper must not crash
    def bad_append(r):
        raise RuntimeError("disk full")
    monkeypatch.setattr(gemini_cost_audit, "append_record", bad_append)
    job = {"gemini_actual": {"google_cost_eur": 0.001}, "payment": {"total_eur": 1.0}}
    # Must not raise
    generation_engine._write_gemini_audit("j", job, "gemini:flash25:Zephyr", "it", "completed")
