import importlib
import audiobook_app as app
import routes_admin_audit


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
    monkeypatch.setattr(routes_admin_audit, "_synth_running_optimization_audit_records",
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


def test_quota_restituita_col_job_premium_azzera_il_ricavo(tmp_path, monkeypatch):
    # Job premium fallito con pagamento combinato: l'ottimizzazione e' stata
    # fatta (costo vero) ma la quota e' tornata all'utente col rimborso.
    c = _client(tmp_path, monkeypatch)
    import optimization_cost_audit
    righe = [
        {"job_id": "A", "language": "it", "outcome": "completed",
         "google_cost_eur_actual": 0.10, "user_price_eur_charged": 0.72,
         "combined_total_eur": 5.03, "payment_method": "paypal",
         "ts": "2026-10-04T21:50:00"},
        {"job_id": "B", "language": "it", "outcome": "completed",
         "google_cost_eur_actual": 0.05, "user_price_eur_charged": 0.50,
         "payment_method": "voucher", "ts": "2026-10-04T21:51:00"},
        {"job_id": "A", "outcome": "llm_refunded", "refund_eur": 0.72,
         "ts": "2026-10-04T23:25:00"},
    ]

    def _iter(outcome=None, **kw):
        return iter([r for r in righe
                     if not outcome or r.get("outcome") == outcome])
    monkeypatch.setattr(optimization_cost_audit, "iter_records", _iter)
    d = c.get("/admin/api/optimization_cost_audit",
              headers={"X-Admin-Token": "secret"}).get_json()
    assert d["count"] == 2          # il marker non e' una riga
    rec_a = next(r for r in d["records"] if r["job_id"] == "A")
    assert rec_a["llm_refunded_eur"] == 0.72
    assert rec_a["_eff_revenue_eur"] == 0.0
    assert rec_a["_eff_margin_eur"] == -0.10
    assert d["aggregates"]["revenue_eur"] == 0.50
    assert d["aggregates"]["provider_cost_eur"] == 0.15
