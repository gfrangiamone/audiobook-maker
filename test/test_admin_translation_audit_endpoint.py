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
