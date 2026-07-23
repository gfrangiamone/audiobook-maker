"""Regressione: dopo l'auto-generate post-ottimizzazione, job["voice"] deve
riflettere la voce realmente usata (opt_voice), così la classificazione
is_gemini / retention non resta inchiodata su una voce di un run manuale
precedente (es. annullato).

Incidente: job PREMIUM (gemini:flash25:Charon) loggato come en-US-GuyNeural in
COMPLETE/EMAIL/DOWNLOAD e token is_gemini=False → retention 24h invece di 48h.
Causa: il path auto-gen non riallineava job["voice"] = opt_voice.
"""
import pytest
import generation_engine as ge


@pytest.fixture
def known_retention(monkeypatch):
    monkeypatch.setattr(ge, "_retention_sec", 64800)        # 18h standard
    monkeypatch.setattr(ge, "_gemini_retention_sec", 172800)  # 48h gemini
    yield


def test_stale_voice_misclassifies_premium_job(known_retention):
    """Pre-fix: voice manuale obsoleto maschera l'opt_voice Gemini → standard."""
    job = {"voice": "en-US-GuyNeural", "opt_voice": "gemini:flash25:Charon"}
    # job["voice"] truthy non-gemini vince sul fallback → retention standard (bug)
    assert ge._retention_for_job(job) == 64800
    assert ge._is_gemini_voice(job.get("voice") or job.get("opt_voice")) is False


def test_aligned_voice_classifies_premium_job(known_retention):
    """Post-fix: job["voice"] allineato a opt_voice Gemini → retention Gemini."""
    job = {"voice": "gemini:flash25:Charon", "opt_voice": "gemini:flash25:Charon"}
    assert ge._retention_for_job(job) == 172800
    assert ge._is_gemini_voice(job.get("voice") or job.get("opt_voice")) is True


def test_fallback_when_voice_empty(known_retention):
    """Optimize-only senza voice settato: il fallback su opt_voice resta valido."""
    job = {"voice": "", "opt_voice": "gemini:flash25:Charon"}
    assert ge._retention_for_job(job) == 172800


def test_autogen_path_aligns_job_voice_to_opt_voice():
    """Il sorgente del path auto-gen deve riallineare job["voice"] = voice
    (= opt_voice) prima della generazione. Guard statico anti-regressione:
    se qualcuno rimuove l'assegnazione, questo test fallisce."""
    import inspect
    src = inspect.getsource(ge.run_optimization) if hasattr(ge, "run_optimization") else ""
    if not src:
        pytest.skip("run_optimization non isolabile")
    # subito dopo la risoluzione di `voice` nel ramo auto-gen
    assert 'job["voice"] = voice' in src
