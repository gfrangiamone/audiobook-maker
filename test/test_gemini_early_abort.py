"""Early-abort Gemini (fix 1) + logging/persistenza per-chunk (fix 2/3).

Copre: parametri early-abort, helper di refund qualità unico, recorder del
fallimento per-chunk (persistito in work_dir → incluso nel bundle forense),
e la propagazione del motivo di fallimento da tts_split.
"""
import json
import os
import pytest
import generation_engine as ge
import tts_split


# --------------------------- _early_abort_params ---------------------------

def test_early_abort_params_defaults(monkeypatch):
    monkeypatch.delenv("ABM_GEMINI_EARLY_ABORT_RATIO", raising=False)
    monkeypatch.delenv("ABM_GEMINI_EARLY_ABORT_MIN_CHUNKS", raising=False)
    ratio, mn = ge._early_abort_params()
    assert ratio == 0.30 and mn == 15


def test_early_abort_params_env(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_EARLY_ABORT_RATIO", "0,25")  # virgola decimale
    monkeypatch.setenv("ABM_GEMINI_EARLY_ABORT_MIN_CHUNKS", "20")
    ratio, mn = ge._early_abort_params()
    assert abs(ratio - 0.25) < 1e-9 and mn == 20


def test_early_abort_params_disabled_and_malformed(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_EARLY_ABORT_RATIO", "2.0")   # >1 = disabilitato
    monkeypatch.setenv("ABM_GEMINI_EARLY_ABORT_MIN_CHUNKS", "xx")
    ratio, mn = ge._early_abort_params()
    assert ratio == 2.0 and mn == 15  # min_chunks malformato -> default


# ------------------------ _record_gemini_chunk_failure ----------------------

def test_record_chunk_failure_persists_and_accumulates(tmp_path):
    job = {}
    fi = {"reason": "synthesize_failed", "detail": "boom 500"}
    block = {"text": "コンテンツ explicit text", "chapter_index": 3}
    ge._record_gemini_chunk_failure(job, "jobX", tmp_path, 7, block, fi)
    # accumulo in memoria
    assert len(job["failed_chunk_details"]) == 1
    rec = job["failed_chunk_details"][0]
    assert rec["chunk_index"] == 7 and rec["reason"] == "synthesize_failed"
    assert rec["chapter_index"] == 3
    # persistenza su disco (→ entra nello zip forense via os.walk della work_dir)
    p = tmp_path / "gemini_failures.jsonl"
    assert p.exists()
    line = json.loads(p.read_text(encoding="utf-8").strip())
    assert line["reason"] == "synthesize_failed" and line["detail"] == "boom 500"


def test_record_chunk_failure_appends(tmp_path):
    job = {}
    for i in range(3):
        ge._record_gemini_chunk_failure(
            job, "jobX", tmp_path, i, {"text": "x", "chapter_index": 1},
            {"reason": "empty_after_sanitize"})
    lines = (tmp_path / "gemini_failures.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    assert len(job["failed_chunk_details"]) == 3


# ------------------- tts_split failure_info propagation --------------------

def test_failure_info_empty_after_sanitize(tmp_path):
    fi = {}
    out = str(tmp_path / "c.pcm")
    # testo che si sanitizza a vuoto -> False + reason, senza toccare Gemini
    res = tts_split.generate_chunk_pcm_gemini("   ", "gemini:flash25:Charon", out,
                                              failure_info=fi)
    assert res is False
    assert fi.get("reason") == "empty_after_sanitize"


# -------------------------- _gemini_quality_refund -------------------------

def test_quality_refund_unico_path(monkeypatch):
    calls = {}
    monkeypatch.setattr(ge, "_set_job_status", lambda job, st: job.__setitem__("status", st))
    monkeypatch.setattr(ge, "_audit_language", lambda job, info: "en")
    monkeypatch.setattr(ge, "_write_gemini_audit", lambda *a, **k: calls.setdefault("audit", a))
    monkeypatch.setattr(ge, "_refund_gemini_payment",
                        lambda jid, job, reason, **k: calls.setdefault("refund", reason))
    monkeypatch.setattr(ge, "_notify_user_gemini_job_failed",
                        lambda *a, **k: calls.setdefault("notify", (a, k)))
    monkeypatch.setattr(ge, "_admin_alert_gemini_failure",
                        lambda *a, **k: calls.setdefault("admin", k))
    monkeypatch.setattr(ge, "_mark_pending_failed",
                        lambda jid, reason: calls.setdefault("pending", reason))

    # Job PAGATO: l'esito e' `failed_quality_refunded` e il refund viene eseguito.
    job = {"payment": {"token": "tok1", "total_eur": 2.0, "method": "paypal"}}
    ge._gemini_quality_refund("jobQ", job, "gemini:flash25:Charon", None,
                              failed_chunks=10, total_chunks=20, early=True)
    assert job["status"] == "error"
    assert abs(job["failed_chunks_ratio"] - 0.5) < 1e-9
    assert "refund" in calls and "10/20" in calls["refund"]
    assert calls["admin"]["chunks_failed"] == 10 and calls["admin"]["chunks_total"] == 20
    assert "[early-abort]" in calls["admin"]["reason_detail"]
    assert calls["admin"]["audit_outcome"] == "failed_quality_refunded"
    assert calls["pending"] == "failed_quality_refunded"


def test_quality_refund_free_no_refund(monkeypatch):
    """Job GRATUITO (nessun token/addebito): l'esito e' `failed_quality_free`,
    NON viene eseguito alcun refund ne' notifica-utente (nulla e' dovuto), ma
    l'alert admin resta. Vedi incidente J60AttINoOwjJZyIpBX3IA."""
    calls = {}
    monkeypatch.setattr(ge, "_set_job_status", lambda job, st: job.__setitem__("status", st))
    monkeypatch.setattr(ge, "_audit_language", lambda job, info: "de")
    monkeypatch.setattr(ge, "_write_gemini_audit",
                        lambda *a, **k: calls.setdefault("audit", a))
    monkeypatch.setattr(ge, "_refund_gemini_payment",
                        lambda jid, job, reason, **k: calls.setdefault("refund", reason))
    monkeypatch.setattr(ge, "_notify_user_gemini_job_failed",
                        lambda *a, **k: calls.setdefault("notify", (a, k)))
    monkeypatch.setattr(ge, "_admin_alert_gemini_failure",
                        lambda *a, **k: calls.setdefault("admin", k))
    monkeypatch.setattr(ge, "_mark_pending_failed",
                        lambda jid, reason: calls.setdefault("pending", reason))

    job = {}  # nessun payment -> gratuito
    ge._gemini_quality_refund("jobFree", job, "gemini:flash31:Puck", None,
                              failed_chunks=1, total_chunks=3)
    assert job["status"] == "error"
    # Nessun rimborso ne' email all'utente
    assert "refund" not in calls
    assert "notify" not in calls
    # Esito distinto, non `*_refunded`, in audit / admin / pending
    assert calls["audit"][-1] == "failed_quality_free"
    assert calls["admin"]["audit_outcome"] == "failed_quality_free"
    assert calls["pending"] == "failed_quality_free"
    # Messaggio utente senza claim di rimborso
    assert "rimborso" not in job["user_facing_error"].lower()


# --------------------- guard statico: early-abort presente -----------------

def test_run_generation_has_early_abort():
    import inspect
    src = inspect.getsource(ge.run_generation)
    assert "_GeminiQualityAbort" in src
    assert "_record_gemini_chunk_failure" in src
    assert "_gemini_quality_refund" in src
