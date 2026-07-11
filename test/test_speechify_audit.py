"""Audit TTS per i job Speechify/Simba: i job premium char-based devono
comparire nel prospetto /admin/audit-tts con la stessa logica costo/prezzo/
margine di Gemini (record persistito su gemini_cost_audit + riga live).
"""
import speechify_tts
import gemini_cost_audit
import generation_engine
import audiobook_app


VOICE = "speechify:simba-3.2:harper_32"


class _Info:
    language = "en"
    title = "Test Book"


# ---------------------------------------------------------------------------
# _accumulate_speechify_actual
# ---------------------------------------------------------------------------
def test_accumulate_speechify_actual_sums_chars_and_seconds():
    job = {"speechify_actual": {"chars": 0, "billable_chars": 0,
                                "audio_seconds": 0.0, "model_key": None}}
    block = {"text": "Hello world."}
    result = {"billable_chars": 30, "bytes_written": 48000 * 2, "sample_rate": 48000}
    generation_engine._accumulate_speechify_actual(job, block, result)
    sa = job["speechify_actual"]
    assert sa["chars"] == len("Hello world.")
    assert sa["billable_chars"] == 30
    # 48000*2 bytes / (48000 * 2) = 1.0 secondo
    assert abs(sa["audio_seconds"] - 1.0) < 1e-6
    assert sa["model_key"] == speechify_tts.MODEL_ID


def test_accumulate_speechify_actual_ignores_failed_chunk():
    job = {"speechify_actual": {"chars": 0, "billable_chars": 0,
                                "audio_seconds": 0.0, "model_key": None}}
    # result False = chunk fallito -> nessun accumulo
    generation_engine._accumulate_speechify_actual(job, {"text": "x"}, False)
    assert job["speechify_actual"]["chars"] == 0
    assert job["speechify_actual"]["billable_chars"] == 0


# ---------------------------------------------------------------------------
# _write_speechify_audit
# ---------------------------------------------------------------------------
def test_write_speechify_audit_completed(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    metered = 120_000
    job = {
        "speechify_actual": {"chars": 118_000, "billable_chars": metered,
                             "audio_seconds": 640.0, "model_key": "simba-3.2"},
        "payment": {"total_eur": 2.0, "method": "paypal", "token": "ORDER-123456789"},
        "rate": "+0%",
    }
    generation_engine._write_speechify_audit(
        "Jspe", job, VOICE, "en", "completed")

    recs = list(gemini_cost_audit.iter_records(outcome="completed"))
    rec = next(r for r in recs if r.get("job_id") == "Jspe")
    assert rec["provider"] == "speechify"
    assert rec["model_key"] == "simba-3.2"
    assert rec["billable_chars"] == metered
    assert rec["user_price_eur_charged"] == 2.0
    # costo provider = cost_usd * usd_eur_rate, > 0 per 120k char
    price = speechify_tts.compute_user_price_eur(metered)
    exp_cost = round(price["cost_usd"] * speechify_tts.usd_eur_rate(), 4)
    assert rec["google_cost_eur_actual"] == exp_cost
    assert rec["user_price_eur_should_have_been"] == round(price["user_price_eur"], 2)
    # token mascherato, mai in chiaro
    assert rec["payment_token_short"] == "ORDER-12..."
    # filtro per modello simba-3.2 lo intercetta
    assert any(r.get("job_id") == "Jspe"
               for r in gemini_cost_audit.iter_records(model="simba-3.2"))


def test_write_speechify_audit_skips_non_speechify_voice(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    job = {"speechify_actual": {"chars": 10, "billable_chars": 10,
                                "audio_seconds": 1.0, "model_key": "simba-3.2"}}
    generation_engine._write_speechify_audit(
        "Jgem", job, "gemini:flash25:Zephyr", "en", "completed")
    assert list(gemini_cost_audit.iter_records()) == []


def test_write_speechify_audit_refunded_outcome(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    job = {
        "speechify_actual": {"chars": 5000, "billable_chars": 5000,
                             "audio_seconds": 30.0, "model_key": "simba-3.2"},
        "payment": {"total_eur": 1.5, "method": "voucher", "token": "V-ABCDEF"},
        "rate": "+0%",
    }
    generation_engine._write_speechify_audit(
        "Jref", job, VOICE, "en", "failed_all_chunks_refunded")
    rec = next(r for r in gemini_cost_audit.iter_records(
        outcome="failed_all_chunks_refunded") if r.get("job_id") == "Jref")
    assert rec["outcome"] == "failed_all_chunks_refunded"
    # rimborso totale -> revenue effettivo 0 nell'aggregato
    audiobook_app._apply_cancel_effective(rec)
    assert float(rec.get("_eff_revenue_eur", 0)) == 0.0


# ---------------------------------------------------------------------------
# _FULL_REFUND_OUTCOMES aggiornato
# ---------------------------------------------------------------------------
def test_full_refund_outcomes_include_speechify_terminals():
    assert "failed_no_output_refunded" in audiobook_app._FULL_REFUND_OUTCOMES
    assert "failed_all_chunks_refunded" in audiobook_app._FULL_REFUND_OUTCOMES


# ---------------------------------------------------------------------------
# riga live per job Speechify in corso
# ---------------------------------------------------------------------------
def test_running_speechify_job_appears_in_live_records(monkeypatch):
    jid = "Jlive"
    job = {
        "status": "generating",
        "voice": VOICE,
        "info": _Info(),
        "speechify_actual": {"chars": 40_000, "billable_chars": 40_000,
                             "audio_seconds": 200.0, "model_key": "simba-3.2"},
        "payment": {"total_eur": 0.9, "method": "paypal"},
        "rate": "+0%",
    }
    monkeypatch.setitem(audiobook_app.jobs, jid, job)
    try:
        rows = audiobook_app._synth_running_gemini_audit_records()
        row = next(r for r in rows if r.get("job_id") == jid)
        assert row["model_key"] == "simba-3.2"
        assert row["outcome"] == "running"
        assert row["chars_total"] == 40_000
        assert row["user_price_eur_charged"] == 0.9
        assert row["google_cost_eur_actual"] > 0
    finally:
        audiobook_app.jobs.pop(jid, None)
