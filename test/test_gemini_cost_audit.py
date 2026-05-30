import json
import pytest
from pathlib import Path

def test_append_record_creates_monthly_file(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    rec = {"job_id":"j1","model_key":"flash25","language":"it",
           "user_price_eur_charged":1.0,"google_cost_eur_actual":0.5,
           "delta_eur":0.0,"outcome":"completed"}
    gca.append_record(rec)
    files = list(tmp_path.glob("gemini_cost_audit_*.jsonl"))
    assert len(files) == 1
    content = files[0].read_text(encoding="utf-8").strip().split("\n")
    assert json.loads(content[0])["job_id"] == "j1"

def test_iter_records_filters_by_model(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    for k in ["flash25","flash31","flash25"]:
        gca.append_record({"job_id":"x","model_key":k,"outcome":"completed"})
    recs = list(gca.iter_records(model="flash25"))
    assert len(recs) == 2

def test_aggregate_returns_delta_pct(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    # delta_pct = delta_eur / google_cost * 100:
    #   a: 0.10 / 1.0 * 100 = 10.0
    #   b: 0.10 / 2.0 * 100 = 5.0
    # aggregate() ricomputa delta_pct_avg dai totali euro:
    #   sum(delta_eur) / sum(google_cost) * 100 = 0.20 / 3.0 * 100 = 6.67
    gca.append_record({"job_id":"a","model_key":"flash25","language":"it",
                       "user_price_eur_charged":1.0,"user_price_eur_should_have_been":1.10,
                       "delta_eur":0.10,"delta_pct":10.0,
                       "google_cost_eur_actual":1.0,"outcome":"completed"})
    gca.append_record({"job_id":"b","model_key":"flash25","language":"it",
                       "user_price_eur_charged":2.0,"user_price_eur_should_have_been":2.10,
                       "delta_eur":0.10,"delta_pct":5.0,
                       "google_cost_eur_actual":2.0,"outcome":"completed"})
    agg = gca.aggregate(model="flash25")
    assert agg["count"] == 2
    assert agg["delta_pct_avg"] == pytest.approx(6.67, abs=0.1)
