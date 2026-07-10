"""B1 (incidente jgIehwtzU2D6jog1S8f5vw, 2026-06): i path terminali di
run_generation che rimborsano il pagamento devono marcare `failed` il
descrittore in _pending_jobs.json, altrimenti il recovery al riavvio
rigenera un job gia' rimborsato (costo vivo, ricavo zero) o, oltre il cap
tentativi, emette un secondo rimborso dal fallback.
"""
import shutil
import pytest

import generation_engine
import gemini_tts
import gemini_cost_audit
import pending_jobs


ffmpeg_missing = shutil.which("ffmpeg") is None


class _Ch:
    def __init__(self, index, title, text):
        self.index = index
        self.title = title
        self.text = text


class _Info:
    def __init__(self):
        self.title = "Test Audiobook"
        self.author = "Test Author"
        self.language = "it"
        self.date = None
        self.description = None
        self.chapters = [
            _Ch(0, "Capitolo 1", "Questa e una frase di prova per il capitolo uno."),
            _Ch(1, "Capitolo 2", "E questa e una frase per il capitolo due, piu lunga."),
        ]


@pytest.fixture
def setup_engine(tmp_path, monkeypatch):
    """Harness minimale per run_generation (vedi test_gemini_pipeline)."""
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    monkeypatch.setattr("generation_engine._upload_dir", upload_dir)
    jobs = {}
    monkeypatch.setattr("generation_engine._jobs", jobs)
    monkeypatch.setattr(
        "generation_engine._set_job_status",
        lambda j, s: j.update({"status": s}),
    )
    gemini_tts.init(str(tmp_path / "gemini_data"))
    # Niente artefatti audit nel repo root
    monkeypatch.setattr(gemini_cost_audit, "_DATA_DIR", tmp_path)
    if hasattr(generation_engine, "_prepare_m4b_cover_path"):
        monkeypatch.setattr(
            "generation_engine._prepare_m4b_cover_path",
            lambda *a, **kw: None,
        )
    # Side-effect esterni (email/alert) fuori scope
    monkeypatch.setattr(generation_engine, "_notify_user_gemini_job_failed",
                        lambda *a, **kw: None)
    monkeypatch.setattr(generation_engine, "_admin_alert_gemini_failure",
                        lambda *a, **kw: None)
    return upload_dir, jobs


@pytest.fixture
def mark_failed_calls(monkeypatch):
    """Registra le chiamate a pending_jobs.mark_failed."""
    calls = []
    monkeypatch.setattr(pending_jobs, "mark_failed",
                        lambda jid: calls.append(jid))
    return calls


def test_quota_failure_marks_pending_failed(setup_engine, mark_failed_calls,
                                            monkeypatch):
    """Quota esaurita mid-run -> failed_quota_refunded -> descrittore failed."""
    upload_dir, jobs = setup_engine
    job_id = "qfail"
    jobs[job_id] = {"gen_epoch": 0, "last_poll": 0, "email_registered": True}

    def boom(text, voice_id, output_path=None, **kw):
        raise gemini_tts.GeminiQuotaExhausted(
            "Local RPD cap reached", retry_after_sec=60, reason="rpd_local_cap")

    monkeypatch.setattr("gemini_tts.synthesize", boom)

    generation_engine.run_generation(
        job_id, _Info(),
        voice="gemini:flash25:Zephyr",
        rate="+0%",
        single_file=True,
        output_format="m4b",
    )

    assert mark_failed_calls == [job_id]
    assert jobs[job_id]["status"] == "error"


def test_unavailable_aborts_job_no_mass_silence(setup_engine, mark_failed_calls,
                                                monkeypatch, tmp_path):
    """B4 (incidente 2026-06): is_available()=False non deve silenziare
    l'intero libro chunk per chunk — GeminiUnavailable aborta il job al primo
    chunk (failed_refunded + descrittore failed + messaggio utente generico
    senza nominare il provider)."""
    upload_dir, jobs = setup_engine
    job_id = "unavail"
    jobs[job_id] = {"gen_epoch": 0, "last_poll": 0, "email_registered": True}

    calls = {"n": 0}

    def boom(text, voice_id, output_path=None, **kw):
        calls["n"] += 1
        raise gemini_tts.GeminiUnavailable(
            "Gemini TTS not available (admin_disabled=True, ...)")

    monkeypatch.setattr("gemini_tts.synthesize", boom)

    generation_engine.run_generation(
        job_id, _Info(),
        voice="gemini:flash25:Zephyr",
        rate="+0%",
        single_file=True,
        output_format="m4b",
    )

    # Abort al PRIMO chunk: niente loop di silenziamento di massa
    assert calls["n"] == 1
    assert mark_failed_calls == [job_id]
    job = jobs[job_id]
    assert job["status"] == "error"
    # Messaggio utente: generico, senza provider ne' dettagli tecnici
    msg = job.get("user_facing_error", "")
    assert "PREMIUM" in msg
    assert "Gemini" not in msg
    assert "API_KEY" not in msg
    # Audit: esito failed_refunded
    recs = list(gemini_cost_audit.iter_records(outcome="failed_refunded"))
    assert any(r.get("job_id") == job_id for r in recs)


def test_generate_chunk_pcm_reraises_unavailable(monkeypatch, tmp_path):
    """tts_split non deve degradare GeminiUnavailable a silenzio."""
    import tts_split

    def boom(*a, **kw):
        raise gemini_tts.GeminiUnavailable("not available")

    monkeypatch.setattr("gemini_tts.synthesize", boom)
    out = tmp_path / "chunk.pcm"
    with pytest.raises(gemini_tts.GeminiUnavailable):
        tts_split.generate_chunk_pcm_gemini(
            "Frase di prova sufficientemente lunga per la sintesi.",
            "gemini:flash25:Zephyr", str(out))


@pytest.mark.skipif(ffmpeg_missing, reason="ffmpeg not in PATH")
def test_quality_failure_marks_pending_failed(setup_engine, mark_failed_calls,
                                              monkeypatch):
    """Chunk silenziati da errori generici/transient su un job PAGATO ->
    failed_quality_refunded -> descrittore failed. (L'unavailability ha ora
    un percorso dedicato che aborta al primo chunk: vedi test sopra. Il job
    gratuito ha invece esito `failed_quality_free`: vedi test dedicato.)"""
    upload_dir, jobs = setup_engine
    job_id = "quafail"
    jobs[job_id] = {"gen_epoch": 0, "last_poll": 0, "email_registered": True,
                    "payment": {"token": "tokq", "total_eur": 2.0, "method": "paypal"}}

    def boom(text, voice_id, output_path=None, **kw):
        raise RuntimeError("transient synth error")

    monkeypatch.setattr("gemini_tts.synthesize", boom)
    # v3.35.0: quando Gemini fallisce, generate_chunk_pcm_gemini tenta un
    # fallback edge-tts prima di silenziare (recupero chunk). Qui testiamo il
    # path in cui ANCHE l'edge fallback fallisce -> il chunk resta silenziato ->
    # scatta il quality-gate/refund. Senza questo, i chunk verrebbero recuperati
    # e il job completerebbe (comportamento coperto da test_gemini_edge_fallback).
    monkeypatch.setattr("tts_split._edge_fallback_to_pcm", lambda *a, **k: False)

    generation_engine.run_generation(
        job_id, _Info(),
        voice="gemini:flash25:Zephyr",
        rate="+0%",
        single_file=True,
        output_format="m4b",
    )

    assert mark_failed_calls == [job_id]
    assert jobs[job_id]["status"] == "error"
    # L'esito deve essere il quality-gate, non un errore generico
    recs = list(gemini_cost_audit.iter_records(outcome="failed_quality_refunded"))
    assert any(r.get("job_id") == job_id for r in recs)
