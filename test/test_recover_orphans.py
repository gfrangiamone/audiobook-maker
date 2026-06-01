import os
import community_store
import pending_jobs
import audiobook_app


def _fresh(tmp_path):
    community_store.init(str(tmp_path))
    pending_jobs._store = None
    pending_jobs.init()


def test_fallback_after_cap_marks_failed_and_refunds(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setenv("ABM_RECOVER_MAX_ATTEMPTS", "2")
    refunds = []
    monkeypatch.setattr(audiobook_app, "_refund_payment_on_orphan",
                        lambda jid, job, reason: refunds.append((jid, reason)) or "VCODE")
    sent = []
    monkeypatch.setattr(audiobook_app, "_send_interrupted_email",
                        lambda rec, refund_code=None: sent.append((rec["id"], refund_code)))
    reenq = []
    monkeypatch.setattr(audiobook_app, "_reenqueue_orphan",
                        lambda jid, rec: reenq.append(jid))

    pending_jobs.register("Jcap", "generate", {"notify_email": "a@x.it",
                                               "payment": {"token": "t", "total_eur": 1.0, "method": "paypal"}})
    # porta attempts oltre il cap (2): tre bump simulano tre boot
    pending_jobs.mark_running_bump("Jcap")
    pending_jobs.mark_running_bump("Jcap")  # attempts=2

    audiobook_app._recover_orphan_jobs()  # questo boot fa attempts=3 > 2 → fallback

    assert reenq == []                       # nessun re-enqueue
    assert refunds and refunds[0][0] == "Jcap"
    assert sent and sent[0][0] == "Jcap"
    assert pending_jobs.orphans() == []      # marcato failed → fuori dagli orfani


def test_under_cap_reenqueues(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setenv("ABM_RECOVER_MAX_ATTEMPTS", "2")
    reenq = []
    monkeypatch.setattr(audiobook_app, "_reenqueue_orphan",
                        lambda jid, rec: reenq.append(jid))
    monkeypatch.setattr(audiobook_app, "_orphan_fallback",
                        lambda jid, rec: (_ for _ in ()).throw(AssertionError("must not fallback")))
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda *_: None)

    pending_jobs.register("Jok", "generate", {"notify_email": "a@x.it"})
    audiobook_app._recover_orphan_jobs()  # attempts: 0→1 ≤ 2 → re-enqueue
    assert reenq == ["Jok"]


def test_disabled_does_nothing(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setenv("ABM_RECOVER_ENABLED", "0")
    monkeypatch.setattr(audiobook_app, "_reenqueue_orphan",
                        lambda jid, rec: (_ for _ in ()).throw(AssertionError("disabled")))
    pending_jobs.register("Joff", "generate", {})
    audiobook_app._recover_orphan_jobs()
    assert pending_jobs.orphans()[0]["id"] == "Joff"  # invariato
