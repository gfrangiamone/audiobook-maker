import importlib
import audiobook_app as app


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(app, "ADMIN_TOKEN", "secret", raising=False)
    monkeypatch.setattr(app, "_admin_auth_ok", lambda tok: tok == "secret")
    import optimization_cost_audit
    importlib.reload(optimization_cost_audit)
    monkeypatch.setattr(optimization_cost_audit, "iter_records",
                        lambda **kw: iter([
                            {"job_id": "A", "language": "it", "outcome": "completed",
                             "google_cost_eur_actual": 0.10,
                             "user_price_eur_charged": 0.50,
                             "combined_total_eur": 2.50,
                             "payment_method": "paypal"},
                        ]))
    monkeypatch.setattr(app, "_synth_running_optimization_audit_records",
                        lambda: [])
    app.app.config["TESTING"] = True
    return app.app.test_client()


def test_endpoint_requires_auth(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/admin/api/optimization_cost_audit")
    assert r.status_code == 401


def test_endpoint_returns_records_and_aggregates(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.get("/admin/api/optimization_cost_audit",
              headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["count"] == 1
    assert d["records"][0]["job_id"] == "A"
    agg = d["aggregates"]
    assert agg["revenue_eur"] == 0.50
    assert agg["provider_cost_eur"] == 0.10
    assert "net_margin_eur" in agg and "margin_pct_avg" in agg
