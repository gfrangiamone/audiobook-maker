"""Voci gemini:flash25:* dopo la rimozione del modello dal catalogo (Task 1).

flash25 non e' piu' una chiave in gemini_tts.GEMINI_MODELS: una voce
'gemini:flash25:*' deve essere rifiutata agli ingressi HTTP (stesso esito di
un modello spento via env) e in recovery (job pagato -> refund standard via
_orphan_fallback, mai run_generation), senza mai far risalire il ValueError
di parse_voice_id come 500.
"""
import pytest

import community_store
import pending_jobs
import audiobook_app
import recovery
import generation_engine
from epub_to_tts import BookInfo, Chapter


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        yield c


def _info_minimo():
    ch = Chapter(index=0, title="C", text="Testo di prova. " * 10)
    return BookInfo(title="T", author="A", language="it", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)


def test_gate_http_rifiuta_modello_ritirato():
    with audiobook_app.app.test_request_context():
        resp = audiobook_app._premium_model_gate("gemini:flash25:Zephyr")
    assert resp is not None
    body, status = resp
    assert status == 400
    assert body.get_json()["error_code"] == "voice_model_disabled"


def test_recovery_rifiuta_modello_ritirato():
    with pytest.raises(recovery._RecoveryRejected) as ei:
        recovery._recovery_generate_gate(
            "J1", {"voice": "gemini:flash25:Zephyr"}, _info_minimo())
    assert "ritirato" in str(ei.value)


def test_etichette_email_senza_flash25():
    assert "flash25" not in generation_engine._EMAIL_MODEL_LABELS


def test_filtro_audit_admin_senza_flash25():
    import inspect
    src = inspect.getsource(audiobook_app)
    assert 'value="flash25"' not in src


# --- end-to-end: recovery di un job PAGATO con modello ritirato ------------

def _fresh(tmp_path, monkeypatch):
    community_store.init(str(tmp_path))
    pending_jobs._store = None
    pending_jobs.init()
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)


def _rec(tmp_path, **extra):
    src = tmp_path / "book.epub"
    src.write_bytes(b"fake")
    rec = {"id": "Jflash25", "phase": "generate", "voice": "gemini:flash25:Zephyr",
           "rate": "+0%", "input_path": str(src), "client_id": "cid-1",
           "notify_email": "a@x.it", "lang": "it", "gen_lang": "it", "payment": None}
    rec.update(extra)
    return rec


def test_recovery_job_pagato_con_modello_ritirato_va_a_refund(tmp_path, monkeypatch):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: _info_minimo())
    fb_calls = []
    monkeypatch.setattr(recovery, "_orphan_fallback",
                        lambda job_id, rec: fb_calls.append(job_id))
    rg_calls = []
    monkeypatch.setattr(audiobook_app, "run_generation",
                        lambda *a, **k: rg_calls.append((a, k)))
    rec = _rec(tmp_path, payment={"token": "ORD1", "total_eur": 5.0, "method": "paypal"})
    pending_jobs.register(rec["id"], rec["phase"], rec)
    try:
        assert recovery._reenqueue_orphan(rec["id"], rec) is False
    finally:
        audiobook_app.jobs.pop(rec["id"], None)
    assert fb_calls == ["Jflash25"], "job pagato non recuperabile -> refund standard"
    assert rg_calls == [], "mai avviare run_generation su un modello ritirato"



def test_filtro_audit_admin_con_flash38():
    # La pagina admin audit vive in templates/pages (C1).
    src = audiobook_app._page_template("admin_audit_premium")
    assert '<option value="flash38">Gemini 3.8 (PREMIUM+)</option>' in src


# --- recovery dalla fase optimize senza .abm (review finale I1c) ----------

class _NoThread:
    started = []

    def __init__(self, *a, **k):
        self.k = k

    def start(self):
        _NoThread.started.append(self.k)


def _run_optimize(tmp_path, monkeypatch, voice, payment):
    _fresh(tmp_path, monkeypatch)
    monkeypatch.setattr(audiobook_app, "_parse_book", lambda src: _info_minimo())
    _NoThread.started = []
    monkeypatch.setattr(audiobook_app.threading, "Thread", _NoThread)
    fb_calls = []
    monkeypatch.setattr(recovery, "_orphan_fallback",
                        lambda job_id, rec: fb_calls.append(job_id))
    failed = []
    monkeypatch.setattr(pending_jobs, "mark_failed", lambda jid: failed.append(jid))
    rec = _rec(tmp_path, phase="optimize", voice=voice, payment=payment)
    pending_jobs.register(rec["id"], rec["phase"], rec)
    try:
        ok = recovery._reenqueue_orphan(rec["id"], rec)
    finally:
        audiobook_app.jobs.pop(rec["id"], None)
    return ok, fb_calls, failed, list(_NoThread.started)


def test_recovery_optimize_pagato_con_modello_ritirato_va_a_refund(tmp_path, monkeypatch):
    ok, fb, failed, started = _run_optimize(
        tmp_path, monkeypatch, "gemini:flash25:Zephyr",
        {"token": "ORD2", "total_eur": 5.0, "method": "paypal"})
    assert ok is False
    assert fb == ["Jflash25"], "job pagato -> refund standard"
    assert started == [], "mai avviare l'ottimizzazione con auto-generate"


def test_recovery_optimize_non_pagato_con_modello_ritirato_chiuso(tmp_path, monkeypatch):
    ok, fb, failed, started = _run_optimize(
        tmp_path, monkeypatch, "gemini:flash25:Zephyr", None)
    assert ok is False
    assert fb == []
    assert failed == ["Jflash25"]
    assert started == []


def test_recovery_optimize_flash31_riparte(tmp_path, monkeypatch):
    ok, fb, failed, started = _run_optimize(
        tmp_path, monkeypatch, "gemini:flash31:Zephyr", None)
    assert ok is True
    assert fb == [] and failed == []
    assert len(started) == 1
