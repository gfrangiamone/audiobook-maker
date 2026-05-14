"""Test /admin/api/gemini_cost_audit/recalc-params endpoint."""
import pytest
import gemini_cost_audit


@pytest.fixture
def client(monkeypatch, tmp_path):
    import audiobook_app
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


@pytest.fixture
def admin_headers():
    return {"X-Admin-Token": "test-admin-token"}


def _add(model, lang, delta_pct, job_id):
    gemini_cost_audit.append_record({
        "job_id": job_id,
        "model_key": model,
        "language": lang,
        "outcome": "completed",
        "user_price_eur_charged": 1.0,
        "google_cost_eur_actual": 0.5,
        "delta_pct": delta_pct,
    })


def test_recalc_params_requires_auth(client):
    r = client.get("/admin/api/gemini_cost_audit/recalc-params")
    assert r.status_code in (401, 403, 404)


def test_recalc_params_empty_returns_empty_suggestions(client, admin_headers):
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    assert r.status_code == 200, r.get_data(as_text=True)
    d = r.get_json()
    assert d["suggestions"] == []


def test_recalc_params_emits_suggestion_for_full_group(client, admin_headers):
    # 3 records in same group => suggestion emitted
    for i, dp in enumerate([6.0, 7.0, 8.0]):
        _add("flash25", "it", dp, f"j{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    assert r.status_code == 200
    d = r.get_json()
    assert len(d["suggestions"]) == 1
    s = d["suggestions"][0]
    assert "flash25" in s
    assert "it" in s
    # avg = 7.0 => margine alto
    assert "margine alto" in s


def test_recalc_params_skips_small_group(client, admin_headers):
    # only 2 records => skipped
    for i, dp in enumerate([6.0, 7.0]):
        _add("flash25", "it", dp, f"j{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    assert r.status_code == 200
    d = r.get_json()
    assert d["suggestions"] == []
    assert d["groups_total"] == 1
    assert d["groups_evaluated"] == 0


def test_recalc_params_loss_suggestion(client, admin_headers):
    for i, dp in enumerate([-10.0, -8.0, -9.0]):
        _add("pro25", "en", dp, f"k{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    assert len(d["suggestions"]) == 1
    assert "perdita" in d["suggestions"][0]
    assert "pro25" in d["suggestions"][0]
    assert "en" in d["suggestions"][0]


def test_recalc_params_ok_suggestion(client, admin_headers):
    for i, dp in enumerate([1.0, 2.0, 0.5]):
        _add("flash25", "fr", dp, f"m{i}")
    r = client.get("/admin/api/gemini_cost_audit/recalc-params",
                   headers=admin_headers)
    d = r.get_json()
    assert len(d["suggestions"]) == 1
    assert "parametri OK" in d["suggestions"][0]
