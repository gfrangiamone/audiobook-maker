# test/test_translation_audit_write.py
import importlib


def test_write_completed_record(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_TRANSLATE_COST_IN_EUR_PER_MTOK", "1.0")
    monkeypatch.setenv("ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK", "2.0")
    import translation_cost_audit, payment, generation_engine
    importlib.reload(translation_cost_audit)
    importlib.reload(payment)
    importlib.reload(generation_engine)

    job = {"payment": {"total_eur": 3.5, "method": "voucher",
                       "token": "VOUCHER-XYZ-123456789", "source": ""}}
    generation_engine._write_translation_audit(
        "JOB1", job, backend="vertex", model="gemini-2.5-flash",
        source_lang="it", target_lang="en", optimize=False,
        chars_total=100_000,
        usage_report={"prompt_tokens": 1_000_000, "completion_tokens": 500_000,
                      "estimated": False},
        outcome="completed")

    recs = list(translation_cost_audit.iter_records())
    assert len(recs) == 1
    r = recs[0]
    assert r["job_id"] == "JOB1"
    assert r["outcome"] == "completed"
    assert r["source_lang"] == "it" and r["target_lang"] == "en"
    assert r["backend"] == "vertex" and r["model_key"] == "gemini-2.5-flash"
    assert r["user_price_eur_charged"] == 3.5
    # costo = 1M@1.0 + 0.5M@2.0 = 2.0 (chiave provider-agnostica)
    assert r["google_cost_eur_actual"] == 2.0
    assert r["margin_eur_actual"] == round(3.5 - 2.0, 4)
    assert r["payment_method"] == "voucher"
    assert r["payment_token_short"] == "VOUCHER-..."


def test_write_failed_record_uses_partial_usage(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_TRANSLATE_COST_IN_EUR_PER_MTOK", "1.0")
    monkeypatch.setenv("ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK", "1.0")
    import translation_cost_audit, payment, generation_engine
    importlib.reload(translation_cost_audit)
    importlib.reload(payment)
    importlib.reload(generation_engine)

    job = {"payment": {"total_eur": 2.0, "method": "paypal", "token": "PPORDER123"}}
    generation_engine._write_translation_audit(
        "JOB2", job, backend="apikey", model="deepseek-chat",
        source_lang="fr", target_lang="de", optimize=True,
        chars_total=50_000,
        usage_report={"prompt_tokens": 200_000, "completion_tokens": 0,
                      "estimated": True},
        outcome="failed_refunded")
    r = list(translation_cost_audit.iter_records())[0]
    assert r["outcome"] == "failed_refunded"
    assert r["google_cost_eur_actual"] == 0.2  # 0.2M @1.0
    assert r["tokens_estimated"] is True


def test_write_is_non_fatal(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import generation_engine
    importlib.reload(generation_engine)
    # usage_report None non deve sollevare
    generation_engine._write_translation_audit(
        "JOB3", {"payment": {}}, backend="", model="", source_lang="it",
        target_lang="en", optimize=False, chars_total=0,
        usage_report=None, outcome="completed")
