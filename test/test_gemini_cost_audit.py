import json
import pytest
from pathlib import Path

def test_append_record_creates_monthly_file(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    rec = {"job_id":"j1","model_key":"flash31","language":"it",
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
    for k in ["flash31","other","flash31"]:
        gca.append_record({"job_id":"x","model_key":k,"outcome":"completed"})
    recs = list(gca.iter_records(model="flash31"))
    assert len(recs) == 2

def test_aggregate_returns_delta_pct(tmp_path, monkeypatch):
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    # aggregate() ricomputa delta_pct_avg dai totali euro sul listino dovuto:
    #   sum(delta_eur) / sum(should_have_been) * 100 = 0.20 / 3.2 * 100 = 6.25
    gca.append_record({"job_id":"a","model_key":"flash31","language":"it",
                       "user_price_eur_charged":1.0,"user_price_eur_should_have_been":1.10,
                       "delta_eur":0.10,"delta_pct":10.0,
                       "google_cost_eur_actual":1.0,"outcome":"completed"})
    gca.append_record({"job_id":"b","model_key":"flash31","language":"it",
                       "user_price_eur_charged":2.0,"user_price_eur_should_have_been":2.10,
                       "delta_eur":0.10,"delta_pct":5.0,
                       "google_cost_eur_actual":2.0,"outcome":"completed"})
    agg = gca.aggregate(model="flash31")
    assert agg["count"] == 2
    assert agg["delta_pct_avg"] == pytest.approx(6.25, abs=0.01)

def test_aggregate_delta_pct_uses_listino_not_real_cost(tmp_path, monkeypatch):
    """Su job serviti da un backend molto piu' economico del listino
    (Cloudflare), delta_pct_avg divide per il listino dovuto a consuntivo,
    non per il costo del backend: un denominatore sul costo gonfia ogni
    deriva genuina."""
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    gca.append_record({"job_id": "cf1", "model_key": "flash31", "language": "it",
                       "user_price_eur_charged": 1.0, "user_price_eur_should_have_been": 1.10,
                       "delta_eur": 0.10, "google_cost_eur_actual": 0.10, "outcome": "completed"})
    gca.append_record({"job_id": "cf2", "model_key": "flash31", "language": "it",
                       "user_price_eur_charged": 2.0, "user_price_eur_should_have_been": 2.10,
                       "delta_eur": 0.10, "google_cost_eur_actual": 0.10, "outcome": "completed"})
    agg = gca.aggregate(model="flash31")
    assert agg["count"] == 2
    # sum(delta_eur)=0.20, sum(should_have_been)=3.2 -> 6.25
    assert agg["delta_pct_avg"] == pytest.approx(6.25, abs=0.01)
    # Non e' il valore che si otterrebbe dividendo per il costo reale (0.20).
    assert agg["delta_pct_avg"] != pytest.approx(100.0, abs=0.01)
    # google_cost_eur (reale) resta riportato per la marginalita' effettiva.
    assert agg["google_cost_eur"] == pytest.approx(0.20, abs=0.001)
