import importlib


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_ADMIN_TOKEN", "secret")
    monkeypatch.setenv("ABM_TRANSLATE_COST_IN_EUR_PER_MTOK", "1.0")
    monkeypatch.setenv("ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK", "1.0")
    import translation_cost_audit, payment, audiobook_app
    importlib.reload(translation_cost_audit)
    importlib.reload(payment)
    importlib.reload(audiobook_app)
    return audiobook_app


def test_synth_running_translation(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    app.jobs["LIVE1"] = {
        "status": "translating",
        "tr_params": {"source_lang": "it", "target_lang": "en", "optimize": False},
        "tr_total_chars": 100_000,
        "tr_usage": {"prompt_tokens": 300_000, "completion_tokens": 100_000,
                     "estimated": True},
        "payment": {"total_eur": 3.0, "method": "voucher", "token": "V123456789"},
        "started_at": "2026-07-16T10:00:00+00:00",
    }
    recs = app._synth_running_translation_audit_records()
    app.jobs.pop("LIVE1", None)
    assert len(recs) == 1
    r = recs[0]
    assert r["job_id"] == "LIVE1" and r["outcome"] == "running" and r["_live"] is True
    assert r["source_lang"] == "it" and r["target_lang"] == "en"
    assert r["google_cost_eur_actual"] == 0.4  # 0.4M @1.0
    assert r["user_price_eur_charged"] == 3.0


def test_synth_ignores_non_translating(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    app.jobs["G1"] = {"status": "generating", "voice": "edge:it-IT-X"}
    recs = app._synth_running_translation_audit_records()
    app.jobs.pop("G1", None)
    assert all(r["job_id"] != "G1" for r in recs)


def _client(app):
    app.app.config["TESTING"] = True
    return app.app.test_client()


def _seed(app):
    import translation_cost_audit
    translation_cost_audit.append_record({
        "job_id": "C1", "backend": "vertex", "model_key": "gemini-2.5-flash",
        "source_lang": "it", "target_lang": "en", "optimize": False,
        "chars_total": 100_000, "google_cost_eur_actual": 1.0,
        "user_price_eur_charged": 3.0, "user_price_eur_should_have_been": 3.0,
        "delta_eur": 0.0, "margin_eur_actual": 2.0, "payment_method": "voucher",
        "outcome": "completed", "ts": "2026-07-16T09:00:00+00:00"})
    translation_cost_audit.append_record({
        "job_id": "R1", "backend": "apikey", "model_key": "deepseek-chat",
        "source_lang": "fr", "target_lang": "de", "optimize": True,
        "chars_total": 50_000, "google_cost_eur_actual": 0.5,
        "user_price_eur_charged": 2.0, "user_price_eur_should_have_been": 2.0,
        "delta_eur": 0.0, "margin_eur_actual": 1.5, "payment_method": "paypal",
        "outcome": "failed_refunded", "ts": "2026-07-16T09:30:00+00:00"})


def test_endpoint_requires_admin(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    c = _client(app)
    assert c.get("/admin/api/translation_cost_audit").status_code == 401
    assert c.get("/admin/api/translation_cost_audit",
                 headers={"X-Admin-Token": "wrong"}).status_code == 401


def test_endpoint_records_and_aggregates(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    _seed(app)
    c = _client(app)
    r = c.get("/admin/api/translation_cost_audit",
              headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    d = r.get_json()
    ids = {rec["job_id"] for rec in d["records"]}
    assert {"C1", "R1"} <= ids
    agg = d["aggregates"]
    # solo "completed" nell'aggregato: revenue 3.0, cost 1.0
    assert agg["revenue_eur"] == 3.0
    assert agg["google_cost_eur"] == 1.0
    assert agg["margin_eur"] == 2.0
    # R1 e' failed_refunded -> ricavo effettivo 0
    r1 = next(rec for rec in d["records"] if rec["job_id"] == "R1")
    assert r1["_eff_revenue_eur"] == 0.0


def test_endpoint_filter_target_lang(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    _seed(app)
    c = _client(app)
    d = c.get("/admin/api/translation_cost_audit?target_lang=en",
              headers={"X-Admin-Token": "secret"}).get_json()
    assert [rec["job_id"] for rec in d["records"]] == ["C1"]


def test_languages_endpoint(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    _seed(app)
    c = _client(app)
    d = c.get("/admin/api/translation_cost_audit/languages",
              headers={"X-Admin-Token": "secret"}).get_json()
    assert d["source_langs"] == ["fr", "it"]
    assert d["target_langs"] == ["de", "en"]
    assert "gemini-2.5-flash" in d["models"] and "deepseek-chat" in d["models"]
