"""Regressioni dell'incidente 2026-06-03 (release sotto-barra M4B + recover).

Tre difetti che uccidevano i job in silenzio:
  1. `from audiobook_app import _log_m4b_progress` dentro generation_engine
     ri-esegue l'entry-point come secondo modulo (app girata come __main__) ->
     cleanup/recover duplicati. Il fix sposta il helper in generation_engine.
  2. `os.path.getsize(final_mp3)` non protetto nel log M4B START -> FileNotFoundError
     se l'MP3 e' rimosso da un thread gemello.
  3. `job = _jobs[job_id]` (prima riga di run_generation) -> KeyError se la entry
     e' rimossa dal cleanup tra l'avvio del thread e il lookup. Il fix usa .get().
"""
import os
import pytest


# ---------------------------------------------------------------------------
# Difetto 1 — nessun import runtime di audiobook_app dal sub-modulo
# ---------------------------------------------------------------------------

def test_generation_engine_non_importa_audiobook_app():
    """generation_engine NON deve importare l'entry-point a runtime.

    Importare 'audiobook_app' da un sub-modulo, quando l'app gira come
    `python audiobook_app.py` (modulo == '__main__'), lo ri-esegue da zero
    come secondo modulo -> doppio cleanup loop + doppio recover.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "generation_engine.py")
    with open(os.path.abspath(path), "r", encoding="utf-8") as f:
        src = f.read()
    assert "from audiobook_app import" not in src, \
        "generation_engine ri-importa audiobook_app: ri-esegue l'entry-point"
    assert "import audiobook_app" not in src, \
        "generation_engine importa audiobook_app: ri-esegue l'entry-point"


def test_log_m4b_progress_definito_in_generation_engine():
    """Il helper deve vivere in generation_engine e usare il log iniettato."""
    import generation_engine
    assert hasattr(generation_engine, "_log_m4b_progress")

    captured = []
    # _log_activity e' iniettato via configure(); qui lo sostituiamo diretto.
    orig = generation_engine._log_activity
    generation_engine._log_activity = lambda *a, **kw: captured.append((a, kw))
    try:
        job = {"job_id": "R1", "client_id": "c", "ip": "1.1.1.1", "lang": "it"}
        generation_engine._log_m4b_progress(job, "START", size_mb=0.0)
    finally:
        generation_engine._log_activity = orig

    assert len(captured) == 1
    assert captured[0][0][0] == "R1"
    assert captured[0][0][2] == "M4B_START"


# ---------------------------------------------------------------------------
# Difetto 3 — run_generation non crasha se il job_id e' assente da _jobs
# ---------------------------------------------------------------------------

def test_run_generation_job_assente_non_solleva(monkeypatch):
    """run_generation con job_id non in _jobs deve uscire pulito (no KeyError)."""
    import generation_engine
    monkeypatch.setattr(generation_engine, "_jobs", {})
    # Non deve sollevare: ritorna None al guard iniziale.
    result = generation_engine.run_generation(
        "job-inesistente", None, "it-IT-Isola", "+0%", True,
    )
    assert result is None


# ---------------------------------------------------------------------------
# Batch implicito per job pagati — email_for_token (protezione heartbeat)
# ---------------------------------------------------------------------------

def test_email_for_token_voucher(monkeypatch):
    """email_for_token ritorna l'email del voucher."""
    import payment
    monkeypatch.setitem(payment._vouchers, "VCODE",
                        {"email": "Payer@Example.com ", "amount_eur": 5})
    assert payment.email_for_token("VCODE") == "payer@example.com"


def test_email_for_token_paypal(monkeypatch):
    """email_for_token ritorna l'email dell'ordine PayPal (post-capture)."""
    import payment
    monkeypatch.setitem(payment._payments, "ORD1",
                        {"email": "buyer@x.io", "amount_eur": 3, "used": True})
    assert payment.email_for_token("ORD1") == "buyer@x.io"


def test_email_for_token_sconosciuto():
    """Token non noto -> stringa vuota (no raise)."""
    import payment
    assert payment.email_for_token("nope-xyz") == ""
    assert payment.email_for_token("") == ""


def test_mask_email():
    """_mask_email mostra solo iniziale locale + dominio, robusto a input strani."""
    import audiobook_app
    assert audiobook_app._mask_email("john.doe@example.com") == "j***@example.com"
    assert audiobook_app._mask_email("a@b.io") == "a***@b.io"
    # Input malformato / vuoto -> invariato, niente eccezioni.
    assert audiobook_app._mask_email("notanemail") == "notanemail"
    assert audiobook_app._mask_email("") == ""
    assert audiobook_app._mask_email(None) == ""
