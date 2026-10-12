"""Test that run_generation writes audit records at end (success/cancel/error)."""
import pytest

import generation_engine
import gemini_cost_audit


def test_write_gemini_audit_success_appends_record(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {
        "gemini_actual": {
            "input_tokens": 100, "output_tokens": 500, "chars": 50,
            "audio_seconds": 12.5, "google_cost_eur": 0.0012, "model_key": "flash31",
        },
        "payment": {"total_eur": 1.50},
    }
    generation_engine._write_gemini_audit(
        "job-abc", job, "gemini:flash31:Zephyr", "it", "completed"
    )
    assert len(captured) == 1
    rec = captured[0]
    assert rec["job_id"] == "job-abc"
    assert rec["model_key"] == "flash31"
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


def test_audit_gemini_riporta_iva(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {
        "gemini_actual": {
            "input_tokens": 100, "output_tokens": 500, "chars": 50,
            "audio_seconds": 12.5, "google_cost_eur": 0.0012, "model_key": "flash31",
        },
        "payment": {"total_eur": 1.50},
    }
    job["gemini_actual"]["vat_eur"] = 0.22
    job["gemini_actual"]["google_cost_eur"] = 1.22
    generation_engine._write_gemini_audit(
        "job-abc", job, "gemini:flash31:Zephyr", "it", "completed"
    )
    assert len(captured) == 1
    rec = captured[0]
    assert rec["vat_eur_actual"] == pytest.approx(0.22)
    assert rec["google_cost_eur_actual"] == pytest.approx(1.22)


def test_write_gemini_audit_skips_non_gemini(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {"gemini_actual": {}, "payment": {}}
    generation_engine._write_gemini_audit("j", job, "en-US-Neural2-A", "en", "completed")
    assert captured == []


def test_write_gemini_audit_missing_payment_uses_zero_charged(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {"gemini_actual": {"google_cost_eur": 0.001, "model_key": "flash31"}}
    generation_engine._write_gemini_audit(
        "j", job, "gemini:flash31:Zephyr", "it", "failed_refunded"
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
    generation_engine._write_gemini_audit("j", job, "gemini:flash31:Zephyr", "it", "completed")


def test_write_gemini_audit_drift_uses_real_audio_seconds_not_cost(monkeypatch):
    """Il rilevatore di deriva prezzo confronta l'incasso col LISTINO sui
    secondi di audio REALI, mai col costo del backend: su Cloudflare costo e
    listino divergono per costruzione e un confronto col costo produrrebbe un
    falso allarme sistematico."""
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    price_calls = []

    def _fake_price(audio_seconds, model_key):
        price_calls.append(audio_seconds)
        return {"user_price_eur": round(audio_seconds / 3600 * 1.90, 2),
                "list_price_eur": round(audio_seconds / 3600 * 1.90, 2)}

    monkeypatch.setattr(generation_engine.gemini_tts, "compute_user_price_eur", _fake_price)
    job = {
        "gemini_actual": {
            "input_tokens": 100, "output_tokens": 500, "chars": 50,
            "audio_seconds": 7200.0,       # 2 h -> listino 3,80
            "google_cost_eur": 0.30,       # costo reale (Cloudflare)
            "model_key": "flash31",
        },
        "payment": {"total_eur": 3.0},
    }
    generation_engine._write_gemini_audit(
        "job-cf", job, "gemini:flash31:Zephyr", "it", "completed"
    )
    assert len(captured) == 1
    rec = captured[0]
    assert price_calls == [7200.0]
    assert rec["google_cost_eur_actual"] == 0.30
    assert "pricing_cost_eur_actual" not in rec
    assert rec["margin_eur_actual"] == round(3.0 - 0.30, 4)
    assert rec["user_price_eur_should_have_been"] == 3.80
    assert rec["delta_eur"] == round(3.80 - 3.0, 4)
    # delta_pct in punti percentuali del listino dovuto: 0.80/3.80.
    assert rec["delta_pct"] == round((3.80 - 3.0) / 3.80 * 100, 2)


def test_write_gemini_audit_reconciles_listino_not_real_cost(monkeypatch):
    """record_job_completion (reconciliation mensile stima/reale, per
    calibrare la tabella car/s) confronta LISTINO quotato ex-ante con LISTINO
    sui secondi reali, mai col costo del backend."""
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    monkeypatch.setattr(generation_engine.gemini_tts, "compute_user_price_eur",
                        lambda audio_seconds, model_key: {"user_price_eur": 5.0,
                                                          "list_price_eur": 5.0})
    rjc_calls = []
    monkeypatch.setattr(
        generation_engine.gemini_tts, "record_job_completion",
        lambda model_key, estimated_eur, actual_eur, user_price_eur=0.0:
            rjc_calls.append({"model_key": model_key, "estimated_eur": estimated_eur,
                              "actual_eur": actual_eur, "user_price_eur": user_price_eur}))
    job = {
        "gemini_actual": {
            "input_tokens": 100, "output_tokens": 500, "chars": 50,
            "audio_seconds": 9000.0,
            "google_cost_eur": 0.30,       # costo reale (Cloudflare)
            "model_key": "flash31",
        },
        "gemini_estimate": {"google_cost_eur": 1.75, "list_price_eur": 4.75},
        "payment": {"total_eur": 4.75},
    }
    generation_engine._write_gemini_audit(
        "job-cf", job, "gemini:flash31:Zephyr", "it", "completed"
    )
    assert len(rjc_calls) == 1
    call = rjc_calls[0]
    assert call["estimated_eur"] == 4.75
    assert call["actual_eur"] == 5.0
    assert call["user_price_eur"] == 4.75
