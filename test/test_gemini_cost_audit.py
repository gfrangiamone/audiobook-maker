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

def test_aggregate_delta_pct_uses_pricing_cost_not_real_cost(tmp_path, monkeypatch):
    """F3: su job serviti da un backend piu' economico del listino
    (Cloudflare), delta_pct_avg deve dividere per il costo di LISTINO
    accumulato, non per il costo REALE sostenuto: un denominatore sul costo
    reale non crea un falso allarme dal nulla, ma gonfia ogni deriva
    genuina (D1)."""
    import gemini_cost_audit as gca
    monkeypatch.setattr(gca, "_DATA_DIR", tmp_path)
    # Reale molto piu' basso del listino (Cloudflare): se il denominatore
    # fosse il reale (0.20 totali) invece del listino (2.0 totali),
    # delta_pct_avg risulterebbe 0.20/0.20*100=100.0 invece di 10.0.
    gca.append_record({"job_id": "cf1", "model_key": "flash25", "language": "it",
                       "user_price_eur_charged": 1.0, "user_price_eur_should_have_been": 1.10,
                       "delta_eur": 0.10, "google_cost_eur_actual": 0.10,
                       "pricing_cost_eur_actual": 1.0, "outcome": "completed"})
    gca.append_record({"job_id": "cf2", "model_key": "flash25", "language": "it",
                       "user_price_eur_charged": 2.0, "user_price_eur_should_have_been": 2.10,
                       "delta_eur": 0.10, "google_cost_eur_actual": 0.10,
                       "pricing_cost_eur_actual": 1.0, "outcome": "completed"})
    agg = gca.aggregate(model="flash25")
    assert agg["count"] == 2
    # sum(delta_eur)=0.20, sum(pricing_cost_eur_actual)=2.0 -> 10.0
    assert agg["delta_pct_avg"] == pytest.approx(10.0, abs=0.01)
    # Non e' il valore che si otterrebbe dividendo per il costo reale (0.20).
    assert agg["delta_pct_avg"] != pytest.approx(100.0, abs=0.01)
    # google_cost_eur (reale) resta riportato per la marginalita' effettiva.
    assert agg["google_cost_eur"] == pytest.approx(0.20, abs=0.001)
