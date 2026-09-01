"""Incidente 1rDPmro8ROjYKcGLo8Outw (31/08 -> 01/09/2026, "Freya - Buch 1").

Catena: /api/generate rifiutato (400) DOPO aver scritto job["voice"] premium
-> /api/register_email registra un descrittore 'generate' per un job mai
partito (status analyzed) -> il purge "stale analyzed" rimuove il job ma NON
marca failed il descrittore -> al boot successivo il recovery rigenera il
libro INTERO (1,6M caratteri, selected_chapters ignorati) con voce premium,
senza pagamento, senza gate quota/soglia, senza stima ex-ante persistita
-> audit "costo stimato 0.0000" e alert "gratis sotto soglia" (testo template).

Invarianti difese qui:
- il recovery applica la selezione capitoli del descrittore (fail-closed);
- una voce PREMIUM recuperata senza pagamento parte SOLO se la quota
  gratuita la copre, e in tal caso la consuma; la stima ex-ante viene
  persistita sul job per l'audit; il cap caratteri vale anche qui;
- il purge di un job mai partito chiude il descrittore;
- register_email su un job mai partito non crea alcun descrittore;
- /api/generate registra/aggiorna il descrittore al momento della partenza;
- l'alert di margine non attribuisce a "sotto soglia" un job senza stima.
"""
import inspect

import pytest

import community_store
import free_quota
import generation_engine
import pending_jobs
import audiobook_app
from epub_to_tts import BookInfo, Chapter

PREMIUM = "gemini:flash31:Achernar"
STANDARD = "de-DE-KatjaNeural"


def _fresh(tmp_path, monkeypatch):
    community_store.init(str(tmp_path))
    pending_jobs._store = None
    pending_jobs.init()
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)


def _info(n=3, chars=1000):
    chs = [Chapter(index=i, title=f"C{i}", text="x" * chars) for i in range(n)]
    return BookInfo(title="Freya", author="A", language="de", chapters=chs,
                    total_words=n * chars // 5, total_chars=n * chars,
                    estimated_duration_minutes=1.0)


@pytest.fixture
def started(monkeypatch):
    """Cattura i thread avviati dal recovery invece di eseguirli."""
    calls = []

    class _T:
        def __init__(self, *a, **k):
            self.k = k

        def start(self):
            calls.append(self.k)

    monkeypatch.setattr(audiobook_app.threading, "Thread", _T)
    return calls


def _rec(tmp_path, voice, **extra):
    src = tmp_path / "book.epub"
    src.write_bytes(b"fake")
    rec = {"id": "Jrec", "phase": "generate", "voice": voice, "rate": "+0%",
           "input_path": str(src), "client_id": "cid-1", "notify_email": "a@x.it",
           "lang": "de", "gen_lang": "de", "payment": None}
    rec.update(extra)
    return rec


def _fake_gemini(monkeypatch, list_price=8.99, google_cost=3.0):
    class _G:
        @staticmethod
        def estimate_book_cost(chs, voice, language="it", rate_pct="+0%"):
            return {"chars_total": sum(len(c.text) for c in chs),
                    "list_price_eur": list_price, "user_price_eur": list_price,
                    "google_cost_eur": google_cost, "input_tokens_est": 10,
                    "output_tokens_est": 10, "audio_seconds_est": 60.0,
                    "model_key": "flash31"}
    monkeypatch.setattr(audiobook_app, "gemini_tts", _G)
    return _G


def _run(tmp_path, monkeypatch, rec):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: _info())
    pending_jobs.register(rec["id"], rec["phase"], rec)
    try:
        return audiobook_app._reenqueue_orphan(rec["id"], rec)
    finally:
        audiobook_app.jobs.pop(rec["id"], None)


def _no_fallback(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_orphan_fallback",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("nessun refund/email 'interrotto' per un job mai partito")))


# --- selezione capitoli -----------------------------------------------------

def test_recovery_applies_selected_chapters(tmp_path, monkeypatch, started):
    rec = _rec(tmp_path, STANDARD, selected_chapters=[1])
    assert _run(tmp_path, monkeypatch, rec) is True
    assert len(started) == 1
    info = started[0]["args"][1]
    assert [ch.index for ch in info.chapters] == [1]


def test_recovery_selection_without_match_is_rejected(tmp_path, monkeypatch, started):
    _no_fallback(monkeypatch)
    rec = _rec(tmp_path, STANDARD, selected_chapters=[99])
    assert _run(tmp_path, monkeypatch, rec) is False
    assert started == []
    assert pending_jobs.orphans() == []


# --- gate premium -----------------------------------------------------------

def test_premium_unpaid_over_quota_is_rejected_without_generation(tmp_path, monkeypatch, started):
    _fake_gemini(monkeypatch, list_price=8.99)
    _no_fallback(monkeypatch)
    monkeypatch.setattr(audiobook_app, "_premium_quota_decision",
                        lambda cid, voice, lst, job_id=None: {
                            "due_eur": lst, "is_free": False, "quota_exhausted": False,
                            "threshold_eur": 0.20, "list_total_eur": lst})
    rec = _rec(tmp_path, PREMIUM, selected_chapters=[0, 1])
    assert _run(tmp_path, monkeypatch, rec) is False
    assert started == []
    assert pending_jobs.orphans() == [], "descrittore chiuso: niente terzo boot"
    assert "Jrec" not in audiobook_app.jobs


def test_premium_unpaid_within_quota_starts_consumes_and_persists_estimate(tmp_path, monkeypatch, started):
    _fake_gemini(monkeypatch, list_price=0.15)
    _no_fallback(monkeypatch)
    monkeypatch.setattr(audiobook_app, "_premium_quota_decision",
                        lambda cid, voice, lst, job_id=None: {
                            "due_eur": 0.0, "is_free": True, "quota_exhausted": False,
                            "threshold_eur": 0.20, "list_total_eur": lst})
    consumed = []
    monkeypatch.setattr(free_quota, "consume",
                        lambda cid, eur, jid: consumed.append((cid, eur, jid)) or eur)
    rec = _rec(tmp_path, PREMIUM, selected_chapters=[0])
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: _info())
    pending_jobs.register(rec["id"], rec["phase"], rec)
    try:
        assert audiobook_app._reenqueue_orphan(rec["id"], rec) is True
        job = audiobook_app.jobs["Jrec"]
        assert job["gemini_estimate"]["list_price_eur"] == 0.15
        assert job["gemini_estimate"]["chars_total"] == 1000  # solo il capitolo 0
    finally:
        audiobook_app.jobs.pop("Jrec", None)
    assert len(started) == 1
    assert consumed == [("cid-1", 0.15, "Jrec")]


def test_premium_paid_starts_and_persists_estimate_without_quota_gate(tmp_path, monkeypatch, started):
    _fake_gemini(monkeypatch, list_price=8.99)
    _no_fallback(monkeypatch)
    monkeypatch.setattr(audiobook_app, "_premium_quota_decision",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("job pagato: la quota non c'entra")))
    rec = _rec(tmp_path, PREMIUM, selected_chapters=[0, 1],
               payment={"token": "ORD", "total_eur": 8.99, "method": "paypal"})
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: _info())
    try:
        assert audiobook_app._reenqueue_orphan(rec["id"], rec) is True
        assert audiobook_app.jobs["Jrec"]["gemini_estimate"]["list_price_eur"] == 8.99
    finally:
        audiobook_app.jobs.pop("Jrec", None)
    assert len(started) == 1


def test_premium_over_char_cap_is_rejected(tmp_path, monkeypatch, started):
    _fake_gemini(monkeypatch, list_price=8.99)
    _no_fallback(monkeypatch)
    monkeypatch.setattr(audiobook_app, "_effective_max_text_chars",
                        lambda voice, job=None: 500)
    rec = _rec(tmp_path, PREMIUM, selected_chapters=None)
    assert _run(tmp_path, monkeypatch, rec) is False
    assert started == []
    assert pending_jobs.orphans() == []


def test_premium_paid_but_not_runnable_falls_back_to_refund_policy(tmp_path, monkeypatch, started):
    """Pagato e non eseguibile alle condizioni originali (qui: cap): NON si
    chiude in silenzio, vale la policy 'non recuperabile' (refund + email)."""
    _fake_gemini(monkeypatch, list_price=8.99)
    monkeypatch.setattr(audiobook_app, "_effective_max_text_chars",
                        lambda voice, job=None: 500)
    fb = []
    monkeypatch.setattr(audiobook_app, "_orphan_fallback",
                        lambda job_id, rec: fb.append(job_id))
    rec = _rec(tmp_path, PREMIUM, selected_chapters=None,
               payment={"token": "ORD", "total_eur": 8.99, "method": "paypal"})
    assert _run(tmp_path, monkeypatch, rec) is False
    assert started == []
    assert fb == ["Jrec"]


# --- cleanup di un job mai partito ------------------------------------------

def test_cleanup_stale_analyzed_closes_descriptor(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(audiobook_app, "_reconcile_unused_capture_for_job",
                        lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "_delete_cold_for_job", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path / "data")
    pending_jobs.register("Jst", "generate", {"voice": PREMIUM, "notify_email": "a@x.it"})
    audiobook_app.jobs["Jst"] = {"status": "analyzed", "voice": PREMIUM}
    audiobook_app._cleanup_job("Jst", "stale analyzed")
    assert "Jst" not in audiobook_app.jobs
    assert pending_jobs.orphans() == []


# --- register_email ---------------------------------------------------------

@pytest.fixture
def email_client(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_write_email_pending_marker", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "UPLOAD_DIR", tmp_path / "data")
    yield audiobook_app.app.test_client()
    audiobook_app.jobs.pop("Jre", None)


def _register(client):
    return client.post("/api/register_email",
                       json={"job_id": "Jre", "email": "a@x.it", "download_type": "chapters"})


def test_register_email_on_never_started_job_creates_no_descriptor(email_client):
    audiobook_app.jobs["Jre"] = {"status": "analyzed", "voice": PREMIUM}
    r = _register(email_client)
    assert r.status_code == 200
    assert audiobook_app.jobs["Jre"]["email_registered"] is True
    assert pending_jobs.orphans() == []


def test_register_email_during_generation_registers_descriptor(email_client):
    audiobook_app.jobs["Jre"] = {"status": "generating", "voice": STANDARD}
    assert _register(email_client).status_code == 200
    assert [o["id"] for o in pending_jobs.orphans()] == ["Jre"]


def test_generate_registers_descriptor_when_the_job_actually_starts():
    """Il descrittore va (ri)scritto alla partenza, con i parametri reali di
    QUESTA generazione: quello scritto da register_email puo' essere vecchio
    (voce/selezione di un tentativo precedente rifiutato)."""
    src = inspect.getsource(audiobook_app.api_generate)
    consume_at = src.find('_fq_charge = job.pop("_free_quota_charge", None)')
    assert consume_at > 0
    tail = src[consume_at:]
    reg_at = tail.find('pending_jobs.register(job_id, "generate"')
    assert reg_at > 0, "register del descrittore atteso dopo il consumo quota"
    assert reg_at < tail.find("thread.start()")


# --- alert di margine -------------------------------------------------------

def test_margin_alert_without_estimate_does_not_claim_below_threshold(monkeypatch):
    calls = []
    monkeypatch.setattr(generation_engine.email_service, "admin_notify_margin_anomaly",
                        lambda job_id, kind, provider, **kw: calls.append(kw))
    monkeypatch.delenv("ABM_MARGIN_ALERT", raising=False)
    job = {"info": _info(), "recovered": True}
    rec = {"user_price_eur_charged": 0.0, "google_cost_eur_est": 0.0,
           "google_cost_eur_actual": 2.2942, "user_price_eur_should_have_been": 5.0,
           "chars_total": 119507, "outcome": "cancelled_refunded"}
    generation_engine._check_margin_anomalies("J", job, rec, {}, "gemini", 0.20)
    assert len(calls) == 1
    detail = calls[0]["detail"]
    assert "sotto soglia" not in detail
    assert "nessuna stima ex-ante" in detail
    assert "recuperato" in detail


def test_margin_alert_free_by_monthly_quota_says_so(monkeypatch):
    calls = []
    monkeypatch.setattr(generation_engine.email_service, "admin_notify_margin_anomaly",
                        lambda job_id, kind, provider, **kw: calls.append(kw))
    monkeypatch.delenv("ABM_MARGIN_ALERT", raising=False)
    rec = {"user_price_eur_charged": 0.0, "google_cost_eur_est": 0.30,
           "google_cost_eur_actual": 1.5, "user_price_eur_should_have_been": 3.0,
           "chars_total": 50000, "outcome": "completed"}
    est = {"list_price_eur": 1.20, "user_price_eur": 1.20, "google_cost_eur": 0.30}
    generation_engine._check_margin_anomalies("J", {"info": _info()}, rec, est, "gemini", 0.20)
    assert len(calls) == 1
    assert "quota" in calls[0]["detail"]
    assert "sotto soglia" not in calls[0]["detail"]
