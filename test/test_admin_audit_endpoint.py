"""Test /admin/api/gemini_cost_audit endpoint."""
import os
import json
import pytest
import gemini_cost_audit


@pytest.fixture
def client(monkeypatch, tmp_path):
    # Set admin token directly on the loaded module (avoid reload, which
    # would mutate global state shared with other test modules).
    import audiobook_app
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


@pytest.fixture
def admin_headers():
    return {"X-Admin-Token": "test-admin-token"}


def test_admin_audit_endpoint_returns_records(client, admin_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    for i in range(3):
        gemini_cost_audit.append_record({
            "job_id": f"j{i}", "model_key": "flash25",
            "language": "it", "outcome": "completed",
            "user_price_eur_charged": 1.0,
            "google_cost_eur_actual": 0.5,
            "delta_pct": 2.0,
        })
    r = client.get("/admin/api/gemini_cost_audit?model=flash25&limit=10",
                   headers=admin_headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["count"] == 3
    assert d["aggregates"]["count"] == 3
    assert len(d["records"]) == 3


def test_admin_audit_requires_auth(client):
    r = client.get("/admin/api/gemini_cost_audit")
    # No token -> 401 (or 404 if admin disabled)
    assert r.status_code in (401, 403, 404)


def test_admin_audit_filter_by_outcome(client, admin_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    gemini_cost_audit.append_record({"job_id": "g1", "model_key": "flash25",
                                      "outcome": "completed", "language": "it"})
    gemini_cost_audit.append_record({"job_id": "g2", "model_key": "flash25",
                                      "outcome": "failed_refunded", "language": "it"})
    r = client.get("/admin/api/gemini_cost_audit?outcome=completed",
                   headers=admin_headers)
    d = r.get_json()
    assert d["count"] == 1
    assert d["records"][0]["job_id"] == "g1"


def test_admin_audit_pagination(client, admin_headers, monkeypatch, tmp_path):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    for i in range(5):
        gemini_cost_audit.append_record({"job_id": f"p{i}", "model_key": "flash25",
                                          "outcome": "completed", "language": "it"})
    r = client.get("/admin/api/gemini_cost_audit?limit=2&offset=1",
                   headers=admin_headers)
    d = r.get_json()
    assert d["count"] == 5  # total
    assert len(d["records"]) == 2  # page size


def test_admin_audit_live_rerun_row_visible(client, admin_headers, monkeypatch, tmp_path):
    """B2 (incidente jgIehwtzU2D6jog1S8f5vw, 2026-06): un job ri-lanciato dal
    recovery dopo un esito terminale persistito deve comparire come riga live
    `running` marcata `_rerun`, NON essere soppresso dalla dedup per job_id."""
    import audiobook_app
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    gemini_cost_audit.append_record({
        "job_id": "rr1", "model_key": "flash25",
        "outcome": "failed_quality_refunded", "language": "it",
        "user_price_eur_charged": 2.0, "google_cost_eur_actual": 0.4,
    })
    audiobook_app.jobs["rr1"] = {
        "status": "generating",
        "voice": "gemini:flash25:Puck",
        "rate": "+0%",
        "gemini_actual": {"chars": 100, "google_cost_eur": 0.01,
                          "audio_seconds": 5.0},
        "payment": {"total_eur": 2.0},
    }
    try:
        r = client.get("/admin/api/gemini_cost_audit", headers=admin_headers)
        assert r.status_code == 200
        d = r.get_json()
        by_outcome = {(rec["job_id"], rec["outcome"]) for rec in d["records"]}
        # Il record storico resta visibile...
        assert ("rr1", "failed_quality_refunded") in by_outcome
        # ...e la riga live del re-run e' presente e marcata
        live = [rec for rec in d["records"]
                if rec["job_id"] == "rr1" and rec["outcome"] == "running"]
        assert len(live) == 1
        assert live[0].get("_rerun") is True
        assert live[0].get("_live") is True
    finally:
        audiobook_app.jobs.pop("rr1", None)


def test_running_gemini_row_uses_pricing_cost_not_real_cost_for_drift(monkeypatch):
    """Mirror di test_write_gemini_audit_drift_uses_pricing_cost_not_actual_cost
    (generation_engine.py) ma per la riga LIVE del pannello: senza questo fix
    ogni job Cloudflare in corso mostrerebbe una falsa deriva prezzo per
    l'intera durata della generazione (D1)."""
    import audiobook_app
    captured = []

    def _fake_price(cost_eur, model_key):
        captured.append(cost_eur)
        return {"user_price_eur": 5.0}

    monkeypatch.setattr(audiobook_app.gemini_tts, "compute_user_price_eur", _fake_price)
    audiobook_app.jobs["Jliveposit"] = {
        "status": "generating",
        "voice": "gemini:flash25:Puck",
        "rate": "+0%",
        "gemini_actual": {"chars": 100, "google_cost_eur": 0.30,
                          "pricing_cost_eur": 1.80, "audio_seconds": 5.0,
                          "model_key": "flash25"},
        "payment": {"total_eur": 5.0},
    }
    try:
        recs = audiobook_app._synth_running_gemini_audit_records()
        rec = next(r for r in recs if r["job_id"] == "Jliveposit")
        # compute_user_price_eur deve ricevere il LISTINO (1.80), non il
        # costo reale (0.30) accumulato finora.
        assert captured == [1.80]
        assert rec["google_cost_eur_actual"] == 0.30
        assert rec["pricing_cost_eur_actual"] == 1.80
        assert rec["margin_eur_actual"] == round(5.0 - 0.30, 4)
        assert rec["user_price_eur_should_have_been"] == 5.0
        assert rec["delta_eur"] == 0.0
    finally:
        audiobook_app.jobs.pop("Jliveposit", None)
