"""E1(c): i tre writer di audit premium condividono pagamento, rate, coda e chiusura."""
import inspect

import generation_engine as ge


def test_payment_audit_fields_normal_and_legacy_fallback():
    pay = ge._payment_audit_fields({"payment": {"total_eur": "3.5", "method": "paypal", "source": "generate",
                                                "token": "PAYPAL-ORDER-1234567890", "llm_eur": 1.25}})
    assert pay == {"charged": 3.5, "payment_method": "paypal", "payment_source": "generate",
                   "payment_token_short": "PAYPAL-O...", "combined_total_eur": 4.75}
    pay = ge._payment_audit_fields({"payment": {"total_eur": 2, "token": "short"}})
    assert pay["payment_token_short"] == "short" and pay["combined_total_eur"] == 2.0
    assert ge._payment_audit_fields({}) == {"charged": 0.0, "payment_method": "", "payment_source": "",
                                            "payment_token_short": "", "combined_total_eur": 0.0}
    legacy = ge._payment_audit_fields({"payment": {"llm_eur": 1.0}, "payment_amount_eur": 4.0,
                                       "payment_type": "voucher", "payment_token": "LEGACY-TOKEN-0000000"})
    assert legacy["charged"] == 3.0 and legacy["payment_method"] == "voucher"
    assert legacy["payment_source"] == "legacy_fallback" and legacy["payment_token_short"] == "LEGACY-T..."
    assert legacy["combined_total_eur"] == 4.0


def test_rate_fields_and_common_tail():
    assert ge._rate_audit_fields({"rate": "+10%"}) == {"rate_pct": 10, "rate_step": ge._rate_step("+10%")}
    assert ge._rate_audit_fields({})["rate_pct"] == 0
    rec = ge._common_audit_tail({"a": 1}, {"chunks_reused": "3", "cancel_meta": {
        "paid_eur": "5.5", "retained_eur": 2.256, "refund_eur": None, "progress_pct": 42.9,
        "partial_audio_delivered": None}})
    assert rec == {"a": 1, "chunks_reused": 3, "cancel_paid_eur": 5.5, "cancel_retained_eur": 2.26,
                   "cancel_refund_eur": 0.0, "cancel_progress_pct": 42, "cancel_partial_audio_delivered": False}
    assert ge._common_audit_tail({}, {"chunks_reused": 0, "cancel_meta": "no"}) == {}


def test_finish_audit_writes_clears_checks_and_warns(monkeypatch, capsys):
    recs, carries, checks = [], [], []
    monkeypatch.setattr(ge.gemini_cost_audit, "append_record", lambda r: recs.append(r))
    monkeypatch.setattr(ge, "_clear_cost_carry", lambda jid, eng: carries.append((jid, eng)))
    monkeypatch.setattr(ge, "_check_margin_anomalies", lambda *a: checks.append(a[4:]))
    pay = {"charged": 0.0, "payment_method": ""}
    rec = {"outcome": "completed"}
    ge._finish_audit("J1", {"payment_token": "tok"}, rec, "speechify", {"x": 1}, 0.5,
                     should_have_been=0.8, pay=pay, label="Speechify")
    assert recs == [rec] and carries == [("J1", "speechify")] and checks == [("speechify", 0.5)]
    out = capsys.readouterr().out
    assert "AUDIT WARNING: completed Speechify job sopra soglia (0.80" in out and "payment_token_in_job=YES" in out
    ge._finish_audit("J2", {}, {"outcome": "completed"}, "gemini", {}, 0.5,
                     should_have_been=0.3, pay=pay, label="Gemini")
    ge._finish_audit("J3", {}, {"outcome": "cancelled"}, "voxcpm", {}, 0.5,
                     should_have_been=9.0, pay=pay, label="VoxCPM")
    assert "AUDIT WARNING" not in capsys.readouterr().out and len(recs) == 3


def test_writers_share_the_helpers():
    for fn in (ge._write_gemini_audit, ge._write_speechify_audit, ge._write_voxcpm_audit):
        src = inspect.getsource(fn)
        for helper in ("_payment_audit_fields(job)", "_rate_audit_fields(job)", "_common_audit_tail(rec, job)",
                       "_finish_audit("):
            assert helper in src, (fn.__name__, helper)
        assert "legacy_fallback" not in src and "append_record(" not in src and "AUDIT WARNING" not in src
