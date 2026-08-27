"""Test that run_generation writes audit records at end (success/cancel/error)."""
import generation_engine
import gemini_cost_audit


def test_write_gemini_audit_success_appends_record(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {
        "gemini_actual": {
            "input_tokens": 100, "output_tokens": 500, "chars": 50,
            "audio_seconds": 12.5, "google_cost_eur": 0.0012, "model_key": "flash25",
        },
        "payment": {"total_eur": 1.50},
    }
    generation_engine._write_gemini_audit(
        "job-abc", job, "gemini:flash25:Zephyr", "it", "completed"
    )
    assert len(captured) == 1
    rec = captured[0]
    assert rec["job_id"] == "job-abc"
    assert rec["model_key"] == "flash25"
    assert rec["language"] == "it"
    assert rec["chars_total"] == 50
    assert rec["input_tokens_actual"] == 100
    assert rec["output_tokens_actual"] == 500
    assert rec["audio_seconds_actual"] == 12.5
    assert rec["google_cost_eur_actual"] == 0.0012
    assert rec["user_price_eur_charged"] == 1.50
    assert rec["outcome"] == "completed"
    # should_have_been computed from compute_user_price_eur
    assert rec["user_price_eur_should_have_been"] >= 0.0
    # delta_eur = should - charged
    assert abs(rec["delta_eur"] - (rec["user_price_eur_should_have_been"] - 1.50)) < 0.01
    # margin_eur_actual = charged - google_cost
    assert abs(rec["margin_eur_actual"] - (1.50 - 0.0012)) < 0.01


def test_write_gemini_audit_skips_non_gemini(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {"gemini_actual": {}, "payment": {}}
    generation_engine._write_gemini_audit("j", job, "en-US-Neural2-A", "en", "completed")
    assert captured == []


def test_write_gemini_audit_missing_payment_uses_zero_charged(monkeypatch):
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    job = {"gemini_actual": {"google_cost_eur": 0.001, "model_key": "flash25"}}
    generation_engine._write_gemini_audit(
        "j", job, "gemini:flash25:Zephyr", "it", "failed_refunded"
    )
    assert len(captured) == 1
    assert captured[0]["user_price_eur_charged"] == 0.0
    assert captured[0]["delta_pct"] == 0.0  # no charge -> no pct
    assert captured[0]["outcome"] == "failed_refunded"


def test_write_gemini_audit_swallows_internal_errors(monkeypatch, capsys):
    # If compute_user_price_eur raises and append_record raises, the helper must not crash
    def bad_append(r):
        raise RuntimeError("disk full")
    monkeypatch.setattr(gemini_cost_audit, "append_record", bad_append)
    job = {"gemini_actual": {"google_cost_eur": 0.001}, "payment": {"total_eur": 1.0}}
    # Must not raise
    generation_engine._write_gemini_audit("j", job, "gemini:flash25:Zephyr", "it", "completed")


def test_write_gemini_audit_drift_uses_pricing_cost_not_actual_cost(monkeypatch):
    """Su un job servito da un backend piu' economico del listino (Cloudflare),
    il rilevatore di deriva prezzo deve confrontare l'incasso col costo di
    LISTINO, non col costo reale sostenuto: altrimenti ogni job su quel
    backend genererebbe un falso allarme sistematico (D1).

    Numeratore (delta_eur) e denominatore (pricing_cost_actual di delta_pct)
    sono qui DELIBERATAMENTE non nulli e reciprocamente incoerenti fra
    listino/reale: se should_have_been o delta_pct venissero calcolati sul
    costo REALE anziche' sul listino, sia price_calls sia delta_pct
    risulterebbero visibilmente diversi da quanto atteso (a differenza di un
    caso a numeratore zero, dove 0/qualsiasi_cosa resta 0 e la regressione
    passerebbe inosservata)."""
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    price_calls = []

    def _fake_price(cost_eur, model_key):
        price_calls.append(cost_eur)
        # Il prezzo "dovuto" scala col costo passato: se venisse passato il
        # costo reale (0.30) invece del listino (1.80) il risultato sarebbe
        # 1.05, non 6.30 - la differenza si propaga fino a delta_eur/pct.
        return {"user_price_eur": round(cost_eur * 3.5, 2)}

    monkeypatch.setattr(generation_engine.gemini_tts, "compute_user_price_eur", _fake_price)
    job = {
        "gemini_actual": {
            "input_tokens": 100, "output_tokens": 500, "chars": 50,
            "audio_seconds": 12.5,
            "google_cost_eur": 0.30,       # costo reale (Cloudflare, piu' economico)
            "pricing_cost_eur": 1.80,      # costo di listino sugli stessi token
            "model_key": "flash25",
        },
        "payment": {"total_eur": 5.0},
    }
    generation_engine._write_gemini_audit(
        "job-cf", job, "gemini:flash25:Zephyr", "it", "completed"
    )
    assert len(captured) == 1
    rec = captured[0]
    # compute_user_price_eur deve ricevere il LISTINO, mai il costo reale.
    assert price_calls == [1.80]
    assert rec["google_cost_eur_actual"] == 0.30
    assert rec["pricing_cost_eur_actual"] == 1.80
    assert rec["margin_eur_actual"] == round(5.0 - 0.30, 4)
    # should_have_been = 1.80 * 3.5 = 6.30 (mai 0.30 * 3.5 = 1.05)
    assert rec["user_price_eur_should_have_been"] == 6.30
    assert rec["delta_eur"] == round(6.30 - 5.0, 4)
    # delta_pct deve dividere per il LISTINO (1.80), non per il reale (0.30):
    # 1.30/1.80*100 = 72.22, ben distinguibile da 1.30/0.30*100 = 433.33.
    assert rec["delta_pct"] == round((6.30 - 5.0) / 1.80 * 100, 2)


def test_write_gemini_audit_pricing_cost_eur_defaults_to_actual_when_absent(monkeypatch):
    """Job legacy senza pricing_cost_eur (pre-esistenti a questa correzione, o
    job non-Cloudflare dove i due numeri coincidono comunque): il ripiego
    sul costo reale deve preservare il comportamento storico."""
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    price_calls = []

    def _fake_price(cost_eur, model_key):
        price_calls.append(cost_eur)
        return {"user_price_eur": 2.0}

    monkeypatch.setattr(generation_engine.gemini_tts, "compute_user_price_eur", _fake_price)
    job = {
        "gemini_actual": {
            "chars": 50, "google_cost_eur": 1.0, "model_key": "flash25",
            # niente pricing_cost_eur
        },
        "payment": {"total_eur": 2.0},
    }
    generation_engine._write_gemini_audit(
        "job-legacy", job, "gemini:flash25:Zephyr", "it", "completed"
    )
    assert len(captured) == 1
    rec = captured[0]
    assert price_calls == [1.0]
    assert rec["pricing_cost_eur_actual"] == 1.0


def test_write_gemini_audit_reconciles_listino_not_real_cost(monkeypatch):
    """F6: record_job_completion (reconciliation mensile stima/reale usata per
    calibrare l'errore dell'estimatore token/durata) deve confrontare
    LISTINO ex-ante con LISTINO ex-post sugli stessi token, mai col costo
    REALE del backend che ha eseguito - altrimenti su Cloudflare l'errore
    dell'estimatore sarebbe confuso col rumore di infrastruttura (D1)."""
    captured = []
    monkeypatch.setattr(gemini_cost_audit, "append_record", lambda r: captured.append(r))
    monkeypatch.setattr(generation_engine.gemini_tts, "compute_user_price_eur",
                        lambda cost_eur, model_key: {"user_price_eur": 5.0})
    rjc_calls = []
    monkeypatch.setattr(
        generation_engine.gemini_tts, "record_job_completion",
        lambda model_key, estimated_eur, actual_eur, user_price_eur=0.0:
            rjc_calls.append({"model_key": model_key, "estimated_eur": estimated_eur,
                              "actual_eur": actual_eur, "user_price_eur": user_price_eur}))
    job = {
        "gemini_actual": {
            "input_tokens": 100, "output_tokens": 500, "chars": 50,
            "audio_seconds": 12.5,
            "google_cost_eur": 0.30,       # costo reale (Cloudflare)
            "pricing_cost_eur": 1.80,      # listino sugli stessi token
            "model_key": "flash25",
        },
        "gemini_estimate": {"google_cost_eur": 1.75},  # listino ex-ante
        "payment": {"total_eur": 5.0},
    }
    generation_engine._write_gemini_audit(
        "job-cf", job, "gemini:flash25:Zephyr", "it", "completed"
    )
    assert len(rjc_calls) == 1
    call = rjc_calls[0]
    assert call["estimated_eur"] == 1.75
    # actual_eur deve essere il LISTINO (1.80), mai il costo reale (0.30).
    assert call["actual_eur"] == 1.80
