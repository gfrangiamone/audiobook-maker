import os
import pytest
import community_store
import pending_jobs
import audiobook_app
import recovery


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
    monkeypatch.setattr(recovery, "_send_interrupted_email",
                        lambda rec, refund_code=None: sent.append((rec["id"], refund_code)))
    reenq = []
    monkeypatch.setattr(recovery, "_reenqueue_orphan",
                        lambda jid, rec: reenq.append(jid))

    pending_jobs.register("Jcap", "generate", {"notify_email": "a@x.it",
                                               "payment": {"token": "t", "total_eur": 1.0, "method": "paypal"}})
    # porta attempts oltre il cap (2): tre bump simulano tre boot
    pending_jobs.mark_running_bump("Jcap")
    pending_jobs.mark_running_bump("Jcap")  # attempts=2

    recovery._recover_orphan_jobs()  # questo boot fa attempts=3 > 2 → fallback

    assert reenq == []                       # nessun re-enqueue
    assert refunds and refunds[0][0] == "Jcap"
    assert sent and sent[0][0] == "Jcap"
    assert pending_jobs.orphans() == []      # marcato failed → fuori dagli orfani


def test_under_cap_reenqueues(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setenv("ABM_RECOVER_MAX_ATTEMPTS", "2")
    reenq = []
    monkeypatch.setattr(recovery, "_reenqueue_orphan",
                        lambda jid, rec: reenq.append(jid))
    monkeypatch.setattr(recovery, "_orphan_fallback",
                        lambda jid, rec: (_ for _ in ()).throw(AssertionError("must not fallback")))
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda *_: None)

    pending_jobs.register("Jok", "generate", {"notify_email": "a@x.it"})
    recovery._recover_orphan_jobs()  # attempts: 0→1 ≤ 2 → re-enqueue
    assert reenq == ["Jok"]


def test_clean_shutdown_does_not_count_an_attempt(tmp_path, monkeypatch):
    """Reboot del 19/11/2026: deploy + reboot ravvicinati portavano oltre il
    cap job sani. Dopo un arresto pulito (SIGTERM) il tentativo non sale."""
    _fresh(tmp_path)
    monkeypatch.setenv("ABM_RECOVER_MAX_ATTEMPTS", "2")
    reenq = []
    monkeypatch.setattr(recovery, "_reenqueue_orphan", lambda jid, rec: reenq.append(jid) or True)
    monkeypatch.setattr(recovery, "_orphan_fallback",
                        lambda jid, rec: (_ for _ in ()).throw(AssertionError("must not fallback")))
    monkeypatch.setattr(recovery.time, "sleep", lambda *_: None)

    pending_jobs.register("Jclean", "generate", {"notify_email": "a@x.it"})
    pending_jobs.mark_running_bump("Jclean")
    pending_jobs.mark_running_bump("Jclean")          # attempts=2, gia' al cap
    pending_jobs.note_clean_shutdown()

    recovery._recover_orphan_jobs()

    assert reenq == ["Jclean"]
    assert pending_jobs._store.get("Jclean")["attempts"] == 2
    # Il segnale vale un solo boot: un crash dopo torna a contare.
    assert pending_jobs.consume_clean_shutdown() is False


def test_unclean_shutdown_still_counts_and_caps(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setenv("ABM_RECOVER_MAX_ATTEMPTS", "2")
    fb = []
    monkeypatch.setattr(recovery, "_orphan_fallback", lambda jid, rec: fb.append(jid))
    monkeypatch.setattr(recovery, "_reenqueue_orphan",
                        lambda jid, rec: (_ for _ in ()).throw(AssertionError("must not reenqueue")))
    pending_jobs.register("Jcrash", "generate", {"notify_email": "a@x.it"})
    pending_jobs.mark_running_bump("Jcrash")
    pending_jobs.mark_running_bump("Jcrash")          # nessun segnale: crash
    recovery._recover_orphan_jobs()
    assert fb == ["Jcrash"]


def test_sigterm_hook_writes_clean_marker_then_terminates(tmp_path, monkeypatch):
    import signal
    _fresh(tmp_path)
    orig = signal.getsignal(signal.SIGTERM)
    killed = []
    try:
        pending_jobs.install_clean_shutdown_hook()
        handler = signal.getsignal(signal.SIGTERM)
        assert callable(handler)
        monkeypatch.setattr(pending_jobs.os, "kill", lambda pid, sig: killed.append(sig))
        handler(signal.SIGTERM, None)
        assert killed == [signal.SIGTERM]
        assert signal.getsignal(signal.SIGTERM) == signal.SIG_DFL
        assert pending_jobs.consume_clean_shutdown() is True
    finally:
        signal.signal(signal.SIGTERM, orig)


def test_reenqueue_empty_voice_falls_back_no_generation(tmp_path, monkeypatch):
    # F2: un descrittore 'generate' senza voce (es. job di traduzione orfano
    # mis-registrato) NON deve avviare una generazione muta -> fallback.
    _fresh(tmp_path)
    fb = []
    monkeypatch.setattr(recovery, "_orphan_fallback",
                        lambda jid, rec: fb.append(jid))
    # Se il guard fallisse, si arriverebbe al parsing del libro: lo rendiamo
    # esplosivo per provare che NON viene raggiunto.
    monkeypatch.setattr(audiobook_app, "_parse_book",
                        lambda src: (_ for _ in ()).throw(AssertionError("must not parse/generate")))
    rec = {"id": "Jmute", "phase": "generate", "voice": "",
           "input_path": "/nonexistent.epub"}
    recovery._reenqueue_orphan("Jmute", rec)
    assert fb == ["Jmute"]


def test_reenqueue_with_voice_passes_guard(tmp_path, monkeypatch):
    # Voce presente: il guard F2 non scatta; si prosegue e si arriva al parsing
    # (qui FileNotFoundError per input mancante), prova che il guard è superato.
    _fresh(tmp_path)
    monkeypatch.setattr(recovery, "_orphan_fallback",
                        lambda jid, rec: (_ for _ in ()).throw(AssertionError("must not fallback")))
    rec = {"id": "Jvoice", "phase": "generate", "voice": "de-DE-KatjaNeural",
           "input_path": "/nonexistent.epub"}
    with pytest.raises(FileNotFoundError):
        recovery._reenqueue_orphan("Jvoice", rec)


def test_disabled_does_nothing(tmp_path, monkeypatch):
    _fresh(tmp_path)
    monkeypatch.setenv("ABM_RECOVER_ENABLED", "0")
    monkeypatch.setattr(recovery, "_reenqueue_orphan",
                        lambda jid, rec: (_ for _ in ()).throw(AssertionError("disabled")))
    pending_jobs.register("Joff", "generate", {})
    recovery._recover_orphan_jobs()
    assert pending_jobs.orphans()[0]["id"] == "Joff"  # invariato
