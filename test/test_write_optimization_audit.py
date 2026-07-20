import generation_engine as ge
import optimization_cost_audit
import payment


def test_write_optimization_audit_combined(monkeypatch):
    captured = {}
    monkeypatch.setattr(optimization_cost_audit, "append_record",
                        lambda rec: captured.update(rec))
    monkeypatch.setattr(payment, "_optimization_provider_cost_eur",
                        lambda p, c: 0.10)
    monkeypatch.setattr(payment, "_estimate_llm_cost_eur", lambda ch: 0.50)

    job = {
        "opt_usage": {"prompt_tokens": 1000, "completion_tokens": 500,
                      "estimated": False},
        "payment": {"total_eur": 2.00, "llm_eur": 0.50, "method": "paypal",
                    "source": "combined_optimize_autogen", "token": "ORDER123456789"},
    }
    ge._write_optimization_audit("JOB1", job, language="it",
                                 chars_total=450000, outcome="completed")
    # Revenue = quota LLM (llm_eur), NON total_eur (che è la quota TTS)
    assert captured["user_price_eur_charged"] == 0.50
    # combined_total = TTS + LLM per la ripartizione fee proporzionale
    assert captured["combined_total_eur"] == 2.50
    assert captured["google_cost_eur_actual"] == 0.10
    assert captured["margin_eur_actual"] == round(0.50 - 0.10, 4)
    assert captured["payment_method"] == "paypal"
    assert captured["outcome"] == "completed"
    assert captured["prompt_tokens"] == 1000


def test_write_optimization_audit_standalone(monkeypatch):
    captured = {}
    monkeypatch.setattr(optimization_cost_audit, "append_record",
                        lambda rec: captured.update(rec))
    monkeypatch.setattr(payment, "_optimization_provider_cost_eur",
                        lambda p, c: 0.08)
    monkeypatch.setattr(payment, "_estimate_llm_cost_eur", lambda ch: 0.70)

    job = {
        "opt_usage": {"prompt_tokens": 900, "completion_tokens": 400,
                      "estimated": False},
        # optimize standalone: nessun llm_eur → total_eur È la quota LLM
        "payment": {"total_eur": 0.70, "method": "voucher", "source": "optimize"},
    }
    ge._write_optimization_audit("JOB2", job, language="en",
                                 chars_total=640000, outcome="completed")
    assert captured["user_price_eur_charged"] == 0.70
    # standalone → combined_total == revenue
    assert captured["combined_total_eur"] == 0.70
    assert captured["payment_method"] == "voucher"
