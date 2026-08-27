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


def test_write_speechify_audit_cost_est_from_estimate(tmp_path, monkeypatch):
    # Parita' con l'audit Gemini: google_cost_eur_est va popolato dallo snapshot
    # pre-generazione (job["speechify_estimate"]), non lasciato a 0.
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    metered = 120_000
    est = speechify_tts.estimate_book_cost(
        [type("C", (), {"text": "a" * 121_000})()], language="en")
    job = {
        "speechify_actual": {"chars": 118_000, "billable_chars": metered,
                             "audio_seconds": 640.0, "model_key": "simba-3.2"},
        "payment": {"total_eur": 2.0, "method": "paypal", "token": "ORDER-123456789"},
        "speechify_estimate": est,
        "rate": "+0%",
    }
    generation_engine._write_speechify_audit("Jest", job, VOICE, "en", "completed")
    rec = next(r for r in gemini_cost_audit.iter_records(outcome="completed")
               if r.get("job_id") == "Jest")
    exp_est = round(est["cost_usd"] * speechify_tts.usd_eur_rate(), 4)
    assert exp_est > 0
    assert rec["google_cost_eur_est"] == exp_est


def test_write_speechify_audit_cost_est_zero_without_estimate(tmp_path, monkeypatch):
    # Nessuno snapshot -> il campo resta 0.0 (comportamento invariato).
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    job = {
        "speechify_actual": {"chars": 5000, "billable_chars": 5000,
                             "audio_seconds": 30.0, "model_key": "simba-3.2"},
        "payment": {"total_eur": 1.5, "method": "voucher", "token": "V-ABCDEF"},
        "rate": "+0%",
    }
    generation_engine._write_speechify_audit("Jnoest", job, VOICE, "en", "completed")
    rec = next(r for r in gemini_cost_audit.iter_records(outcome="completed")
               if r.get("job_id") == "Jnoest")
    assert rec["google_cost_eur_est"] == 0.0


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


# ---------------------------------------------------------------------------
# _apply_cancel_effective: base della deriva % preferisce il listino Gemini
# ---------------------------------------------------------------------------
def test_apply_cancel_effective_uses_pricing_cost_actual_as_drift_base_when_present():
    """Su un record Gemini con listino/costo reale separati (Cloudflare), la
    percentuale di deriva post-rimborso deve usare il listino come
    denominatore, non il costo reale: stesso principio di D1 applicato al
    ricalcolo effettivo dopo un rimborso parziale."""
    rec = {
        "outcome": "cancelled_partial",
        "user_price_eur_charged": 5.0,
        "cancel_retained_eur": 5.0,
        "google_cost_eur_actual": 0.30,
        "pricing_cost_eur_actual": 1.80,
        "user_price_eur_should_have_been": 5.0,
    }
    audiobook_app._apply_cancel_effective(rec)
    assert rec["_eff_revenue_eur"] == 5.0
    # margine resta sul costo reale (contabilita', non deriva prezzo)
    assert rec["_eff_margin_eur"] == round(5.0 - 0.30, 4)
    # delta% deve dividere per il listino (1.80), non per il costo reale (0.30)
    assert rec["_eff_delta_pct"] == 0.0


def test_apply_cancel_effective_falls_back_to_cost_when_pricing_cost_absent():
    """Record non-Gemini (Speechify) o Gemini legacy: nessun campo
    pricing_cost_eur_actual, il ripiego sul costo reale preserva il
    comportamento storico (invariato da questa correzione)."""
    rec = {
        "outcome": "completed",
        "user_price_eur_charged": 1.0,
        "google_cost_eur_actual": 0.4,
        "user_price_eur_should_have_been": 1.2,
    }
    audiobook_app._apply_cancel_effective(rec)
    assert rec["_eff_delta_pct"] == round(((1.2 - 1.0) / 0.4) * 100, 2)
