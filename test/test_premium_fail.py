"""E1(d2): `_premium_fail` chiude ogni job premium fallito allo stesso modo
(audit, rimborso, avviso utente per motore, allerta admin, pending)."""
import inspect
import re

import pytest

import generation_engine as ge


@pytest.fixture
def spy(monkeypatch):
    calls = {}
    refund = {"method": "paypal", "amount_eur": 3.0, "voucher_code": "C0DE", "email": "u@x.it"}
    monkeypatch.setattr(ge, "_write_premium_audit", lambda jid, job, v, info, outcome, eng: calls.setdefault("audit", (outcome, eng)))
    monkeypatch.setattr(ge, "_refund_gemini_payment", lambda jid, job, reason, **k: calls.setdefault("refund", reason) and refund)
    monkeypatch.setattr(ge, "_notify_user_gemini_job_failed",
                        lambda jid, job, reason, is_quota=True, failure_kind=None: calls.setdefault("notify_gemini", (reason, is_quota, failure_kind)))
    monkeypatch.setattr(ge, "_notify_user_premium_job_failed", lambda jid, job, r: calls.setdefault("notify_premium", r))
    monkeypatch.setattr(ge, "_admin_alert_gemini_failure", lambda jid, job, **k: calls.setdefault("admin", k))
    monkeypatch.setattr(ge, "_mark_pending_failed", lambda jid, outcome: calls.setdefault("pending", outcome))
    calls["refund_obj"] = refund
    return calls


def test_gemini_path_uses_gemini_copy(spy):
    out = ge._premium_fail("J", {}, "gemini:flash31:Zephyr", None, "gemini", "failed_quota_refunded",
                           "quota_exhausted: rpd", kind="quota", is_quota=True, notify_reason="rpd",
                           reason_detail="rpd | retry_after=10s")
    assert out is spy["refund_obj"]
    assert spy["audit"] == ("failed_quota_refunded", "gemini") and spy["refund"] == "quota_exhausted: rpd"
    assert spy["notify_gemini"] == ("rpd", True, None) and "notify_premium" not in spy
    assert spy["admin"] == {"kind": "quota", "audit_outcome": "failed_quota_refunded",
                            "reason_detail": "rpd | retry_after=10s", "chunks_total": None, "chunks_failed": None}
    assert spy["pending"] == "failed_quota_refunded"


def test_premium_engines_use_premium_copy_with_the_refund(spy):
    ge._premium_fail("J", {}, "voxcpm:it:anna", None, "voxcpm", "failed_no_output_refunded",
                     "no_output: assembly failed", notify_reason="no_output", failure_kind="generic",
                     reason_detail="empty output", chunks_total=10, chunks_failed=3)
    assert spy["audit"] == ("failed_no_output_refunded", "voxcpm")
    assert spy["notify_premium"] is spy["refund_obj"] and "notify_gemini" not in spy
    assert spy["admin"]["chunks_total"] == 10 and spy["admin"]["chunks_failed"] == 3 and spy["admin"]["kind"] == "generic"
    assert spy["pending"] == "failed_no_output_refunded"


def test_free_job_skips_refund_and_user_mail_but_alerts_admin(spy):
    assert ge._premium_fail("J", {}, "gemini:flash31:Zephyr", None, "gemini", "failed_quality_free",
                            "quality_failed: 3/10", kind="quality", pay=False) is None
    assert "refund" not in spy and "notify_gemini" not in spy and "notify_premium" not in spy
    assert spy["admin"]["audit_outcome"] == "failed_quality_free" and spy["pending"] == "failed_quality_free"


def test_notify_override_replaces_the_standard_user_mail(spy):
    seen = []
    ge._premium_fail("J", {}, "gemini:flash31:Zephyr", None, "gemini", "preflight_blocked_refunded",
                     "preflight_block: x", kind="preflight", notify=lambda refund: seen.append(refund))
    assert seen == [spy["refund_obj"]] and "notify_gemini" not in spy and "notify_premium" not in spy


def test_preflight_mail_goes_to_the_payer(monkeypatch):
    import payment, email_service
    sent = []
    monkeypatch.setattr(payment, "_payments", {"T": {"email": "p@x.it"}}, raising=False)
    monkeypatch.setattr(email_service, "_send_gemini_overload_email", lambda *a, **k: sent.append((a, k)))
    job = {"payment": {"method": "paypal", "token": "T", "total_eur": 4.0}, "refund_llm_eur": 1.0,
           "refund_voucher_code": "V", "browser_lang": "en"}
    ge._notify_user_preflight_blocked("J", job, None, {"retry_after_sec": 3600})
    assert sent == [(("p@x.it", 5.0, ""), {"voucher_code": "V", "retry_after_sec": 3600, "lang": "en"})]
    ge._notify_user_preflight_blocked("J", {"payment": {"method": "paypal", "token": "T", "total_eur": 0}}, None, {})
    assert len(sent) == 1                                                       # gratuito: niente email


def test_every_step_is_non_fatal(monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("giu'")
    pending = []
    monkeypatch.setattr(ge, "_write_premium_audit", lambda *a: None)
    for name in ("_refund_gemini_payment", "_notify_user_premium_job_failed", "_admin_alert_gemini_failure"):
        monkeypatch.setattr(ge, name, boom)
    monkeypatch.setattr(ge, "_mark_pending_failed", lambda jid, outcome: pending.append(outcome))
    assert ge._premium_fail("J", {}, "v", None, "speechify", "failed_refunded", "failed: x") is None
    out = capsys.readouterr().out
    assert "speechify refund failed (non-fatal)" in out and "User notification failed" in out and "Admin alert failed" in out
    assert pending == ["failed_refunded"]


def test_exit_paths_of_run_generation_go_through_premium_fail():
    src = inspect.getsource(ge.run_generation)
    for name in ("_notify_user_gemini_job_failed(", "_admin_alert_gemini_failure(", "_notify_user_premium_job_failed("):
        assert name not in src, name
    # Le uscite con rimborso (quota/budget, eccezione Gemini, tutti i chunk
    # falliti, nessun output) e i wrapper passano da _premium_fail.
    assert src.count("_premium_fail(") == 5                        # + preflight
    assert '_premium_job_failed(job_id, job, voice, info, e, "voxcpm")' in src
    for fn in (ge._premium_job_failed, ge._gemini_quality_refund):
        assert "_premium_fail(" in inspect.getsource(fn)
    # _refund_gemini_payment diretto resta solo nei path di cancel (trattenuta) e nel wrapper.
    direct = re.findall(r"_refund_gemini_payment\(job_id, job, (\"[^\"]*\"|f\"[^\"]*\")", src)
    assert all("cancel" in d for d in direct), direct
