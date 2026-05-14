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
