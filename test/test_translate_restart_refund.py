# test/test_translate_restart_refund.py
"""Traduzione pagata interrotta da un restart (incidente ikTsMP5GoVKELM3hgU5_1A,
18/10/2026): il thread muore senza except, il pagamento e' gia' used=True.

- /api/translate registra un descrittore di fase "translate" se c'e' pagamento;
- il recovery al boot non lo rilancia: rimborsa e chiude (mark failed);
- il completamento chiude solo il descrittore translate (finalize_phase);
- una traduzione gia' consegnata (TR_COMPLETE) non si rimborsa.
"""
import threading
import time
from unittest.mock import patch


import audiobook_app
import community_store
import pending_jobs
import recovery


def _fresh(tmp_path):
    community_store.init(str(tmp_path))
    pending_jobs._store = None
    pending_jobs.init()


def _get(job_id):
    return next((r for r in pending_jobs._require().all(include_archived=True)
                 if r.get("id") == job_id), None)


class _Ch:
    def __init__(self, index, title, text):
        self.index, self.title, self.text = index, title, text
        self.char_count = len(text)
        self.word_count = len(text.split())


class _Info:
    title = "Libro"
    author = "A"
    language = "it"

    def __init__(self):
        self.chapters = [_Ch(1, "Uno", "x" * 400_000)]


def test_paid_translate_registers_translate_descriptor(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setattr(audiobook_app.translation_core, "is_available",
                        lambda: True, raising=False)
    monkeypatch.setattr(audiobook_app, "_save_payments", lambda: None)
    monkeypatch.setattr(audiobook_app, "run_translation", lambda jid: None,
                        raising=False)
    real_thread = threading.Thread
    monkeypatch.setattr(threading, "Thread",
                        lambda target, args, daemon: real_thread(
                            target=lambda: None, daemon=True))
    audiobook_app.jobs.clear()
    job = {"status": "analyzed", "client_id": "c1", "client_ip": "127.0.0.1",
           "info": _Info(), "original_filename": "libro.epub",
           "last_poll": time.time()}
    audiobook_app.jobs["TRJ"] = job
    audiobook_app.payment._payments["ORDTR"] = {
        "order_id": "ORDTR", "amount_eur": 50.0, "email": "u@x.it",
        "captured_at": time.time(), "used": False}
    try:
        with patch("audiobook_app._check_job_owner",
                   return_value=(job, None, None)):
            r = audiobook_app.app.test_client().post("/api/translate", json={
                "job_id": "TRJ", "source_lang": "it", "target_lang": "en",
                "output_format": "abm", "payment_token": "ORDTR"})
        assert r.status_code == 200
        rec = _get("TRJ")
        assert rec is not None and rec["phase"] == "translate"
        assert rec["payment"] == {"token": "ORDTR", "method": "paypal",
                                  "total_eur": 0.0, "llm_eur": 50.0}
        assert rec["notify_download_type"] == "translated"
    finally:
        audiobook_app.payment._payments.pop("ORDTR", None)
        audiobook_app.jobs.clear()


def test_recovery_refunds_translate_without_rerun(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setattr(recovery.activity_log, "delivered_ids",
                        lambda: {"complete": set(), "opt_complete": set(),
                                 "tr_complete": set()})
    refunds = []
    monkeypatch.setattr(audiobook_app, "_refund_payment_on_orphan",
                        lambda jid, job, reason: refunds.append((jid, job["payment"])) or "VCODE")
    sent = []
    monkeypatch.setattr(recovery, "_send_interrupted_email",
                        lambda rec, refund_code=None: sent.append((rec["id"], refund_code)))
    monkeypatch.setattr(recovery, "_reenqueue_orphan",
                        lambda jid, rec: (_ for _ in ()).throw(AssertionError("must not rerun")))
    pay = {"token": "ORD", "method": "paypal", "total_eur": 0.0, "llm_eur": 1.35}
    pending_jobs.register("Jtr", "translate", {"payment": pay})

    recovery._recover_orphan_jobs()

    assert refunds == [("Jtr", pay)]
    assert sent == [("Jtr", "VCODE")]
    assert pending_jobs.orphans() == []
    assert _get("Jtr")["attempts"] == 0  # nessun bump: non e' un rilancio


def test_recovery_delivered_translate_not_refunded(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setattr(recovery.activity_log, "delivered_ids",
                        lambda: {"complete": set(), "opt_complete": set(),
                                 "tr_complete": {"Jdone"}})
    monkeypatch.setattr(audiobook_app, "_refund_payment_on_orphan",
                        lambda *a: (_ for _ in ()).throw(AssertionError("no refund")))
    pending_jobs.register("Jdone", "translate", {"payment": {"token": "t"}})
    recovery._recover_orphan_jobs()
    assert _get("Jdone") is None  # descrittore chiuso


def test_translate_refund_email_only_with_voucher_code(monkeypatch):
    calls = []
    monkeypatch.setattr(recovery.email_service, "_send_voucher_email",
                        lambda *a, **k: calls.append((a, k)))
    monkeypatch.setattr(recovery.payment, "voucher_info",
                        lambda code: {"email": "u@x.it", "amount_eur": 1.49})
    rec = {"id": "J", "phase": "translate", "original_filename": "b.epub",
           "notify_lang": "en"}
    recovery._send_interrupted_email(rec, refund_code=None)  # voucher: silenzio
    assert calls == []
    recovery._send_interrupted_email(rec, refund_code="ABCD")
    (args, kw), = calls
    assert args[:4] == ("ABCD", "u@x.it", 1.49, "b.epub")
    assert kw["kind"] == "translation" and kw["lang"] == "en"


def test_finalize_phase_only_matching(tmp_path):
    _fresh(tmp_path)
    pending_jobs.register("Jg", "generate", {})
    pending_jobs.finalize_phase("Jg", "translate")
    assert _get("Jg") is not None
    pending_jobs.register("Jt", "translate", {})
    pending_jobs.finalize_phase("Jt", "translate")
    assert _get("Jt") is None
