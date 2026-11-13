"""Anteprima voce edge (/api/preview_audio) con i tentativi dei chunk (13/11/2026).

Dal 22/09 al 13/11/2026 nginx ha registrato 2.265 risposte 500 e 891 risposte
504 sull'anteprima. Il ramo edge chiamava edge-tts a mano: un solo tentativo,
sull'endpoint di `ABM_EDGE_TTS_ENDPOINT` (in prod il legacy, che risponde
NoAudioReceived a centinaia di richieste l'ora), 30 s di tempo e l'MP3 scritto
direttamente nel file della cache. Ora l'anteprima passa da
`edge_engine.synthesize_preview`: tentativi alternati fra gli endpoint come per
i chunk dei job, timeout per tentativo corto, budget totale, e il file in cache
nasce solo se c'e' audio.
"""
import asyncio
import os
import shutil
import sys
import time

import pytest
from edge_tts.exceptions import NoAudioReceived

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import edge_engine
import edge_health

MSEDGE = edge_engine._EDGE_WSS_MSEDGE
LEGACY = edge_engine._EDGE_WSS_LEGACY
TESTO = "Era una notte buia e tempestosa, e il vento soffiava forte sulle colline."


@pytest.fixture
def fake_edge(monkeypatch):
    """Communicate finto: a ogni tentativo prende il prossimo esito della lista
    (eccezione, secondi di attesa o None = audio) e registra l'endpoint."""
    state = {"urls": [], "steps": []}

    class _Comm:
        def __init__(self, text, voice, rate):
            pass

        async def save(self, path):
            state["urls"].append(f"{edge_engine._edge_communicate.WSS_URL}")
            step = state["steps"].pop(0) if state["steps"] else None
            if isinstance(step, BaseException):
                raise step
            if isinstance(step, (int, float)):
                await asyncio.sleep(step)
            with open(path, "wb") as f:
                f.write(b"\0" * 60000)

    async def _no_catalog():
        return []

    monkeypatch.setattr(edge_engine.edge_tts, "Communicate", _Comm)
    monkeypatch.setattr(edge_engine, "_edge_retry_wait", lambda a, e: 0)
    monkeypatch.setattr(edge_engine, "_edge_voice_catalog", _no_catalog)
    monkeypatch.setattr(edge_engine, "_edge_paused_until", {})
    monkeypatch.setattr(edge_engine, "_broken_voices", {})
    monkeypatch.setenv("ABM_EDGE_TTS_ENDPOINT", "legacy")
    edge_health.reset()
    yield state
    edge_health.reset()


def test_noaudio_sul_legacy_si_ritenta_su_msedge(fake_edge, tmp_path):
    out = tmp_path / "preview_x.mp3"
    fake_edge["steps"] = [NoAudioReceived("No audio was received.")]
    edge_engine.synthesize_preview(TESTO, "it-IT-IsabellaNeural", "+0%", str(out))
    assert out.stat().st_size == 60000
    assert fake_edge["urls"] == [LEGACY, MSEDGE]


def test_senza_audio_nessun_file_in_cache(fake_edge, tmp_path):
    out = tmp_path / "preview_x.mp3"
    fake_edge["steps"] = [NoAudioReceived("No audio was received.")] * 20
    with pytest.raises(edge_engine.EdgePreviewFailed):
        edge_engine.synthesize_preview(TESTO, "it-IT-IsabellaNeural", "+0%", str(out))
    # il secondo di silenzio di ripiego non diventa l'anteprima servita dopo
    assert not out.exists()
    assert list(tmp_path.iterdir()) == []


def test_tentativo_lento_lascia_tempo_all_altro_endpoint(fake_edge, tmp_path, monkeypatch):
    monkeypatch.setattr(edge_engine, "preview_attempt_timeout_sec", lambda: 0.2)
    out = tmp_path / "preview_x.mp3"
    fake_edge["steps"] = [5.0]          # legacy a velocita' di parlato
    t0 = time.monotonic()
    edge_engine.synthesize_preview(TESTO, "it-IT-IsabellaNeural", "+0%", str(out))
    assert time.monotonic() - t0 < 3.0
    assert out.exists()
    assert fake_edge["urls"] == [LEGACY, MSEDGE]


def test_budget_esaurito_timeout_senza_file(fake_edge, tmp_path, monkeypatch):
    monkeypatch.setattr(edge_engine, "preview_budget_sec", lambda: 0.3)
    out = tmp_path / "preview_x.mp3"
    fake_edge["steps"] = [5.0, 5.0, 5.0]
    t0 = time.monotonic()
    with pytest.raises(TimeoutError):
        edge_engine.synthesize_preview(TESTO, "it-IT-IsabellaNeural", "+0%", str(out))
    assert time.monotonic() - t0 < 3.0
    assert not out.exists()


def test_il_timeout_corto_vale_solo_per_l_anteprima(fake_edge, tmp_path, monkeypatch):
    monkeypatch.setattr(edge_engine, "preview_attempt_timeout_sec", lambda: 0.2)
    edge_engine.synthesize_preview(TESTO, "it-IT-IsabellaNeural", "+0%",
                                   str(tmp_path / "preview_x.mp3"))
    assert edge_engine._edge_attempt_timeout_ctx.get() is None
    # un chunk di job aspetta oltre i 0,2 s dell'anteprima
    fake_edge["urls"].clear()
    fake_edge["steps"] = [0.5]
    ok, _ = asyncio.run(edge_engine._edge_tts_attempts(
        TESTO, "it-IT-IsabellaNeural", "+0%", str(tmp_path / "c.mp3")))
    assert ok and fake_edge["urls"] == [LEGACY]


def test_default_dei_tempi(monkeypatch):
    monkeypatch.delenv("ABM_EDGE_PREVIEW_TIMEOUT", raising=False)
    monkeypatch.delenv("ABM_EDGE_PREVIEW_ATTEMPT_TIMEOUT", raising=False)
    assert edge_engine.preview_budget_sec() == 45.0
    assert edge_engine.preview_attempt_timeout_sec() == 15.0
    monkeypatch.setenv("ABM_EDGE_PREVIEW_TIMEOUT", "60")
    monkeypatch.setenv("ABM_EDGE_PREVIEW_ATTEMPT_TIMEOUT", "0")
    assert edge_engine.preview_budget_sec() == 60.0
    assert edge_engine.preview_attempt_timeout_sec() == 1.0


# ------------------------------------------------------------------ route

@pytest.fixture
def preview_job(monkeypatch):
    import audiobook_app
    from epub_to_tts import BookInfo, Chapter

    audiobook_app.app.config["TESTING"] = True
    job_id = "edge-preview-retry-1"
    ch = Chapter(index=0, title="Cap0", text=TESTO)
    info = BookInfo(title="T", author="A", language="it", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    monkeypatch.setitem(audiobook_app.jobs, job_id,
                        {"info": info, "status": "analyzed", "preview_text": TESTO})
    shutil.rmtree(audiobook_app.UPLOAD_DIR / job_id, ignore_errors=True)
    yield audiobook_app, job_id
    shutil.rmtree(audiobook_app.UPLOAD_DIR / job_id, ignore_errors=True)


def _get(app_mod, job_id):
    return app_mod.app.test_client().get(
        f"/api/preview_audio/{job_id}",
        query_string={"voice": "it-IT-IsabellaNeural", "rate": "+0%"})


def test_route_recupera_il_noaudio_del_primo_tentativo(fake_edge, preview_job):
    app_mod, job_id = preview_job
    fake_edge["steps"] = [NoAudioReceived("No audio was received.")]
    r = _get(app_mod, job_id)
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.mimetype == "audio/mpeg"
    r.close()
    assert fake_edge["urls"] == [LEGACY, MSEDGE]


def test_route_502_senza_audio_e_nessuna_cache(fake_edge, preview_job):
    app_mod, job_id = preview_job
    fake_edge["steps"] = [NoAudioReceived("No audio was received.")] * 20
    r = _get(app_mod, job_id)
    assert r.status_code == 502
    assert r.get_json()["code"] == "tts_failed"
    work = app_mod.UPLOAD_DIR / job_id
    assert not list(work.glob("preview_*")), list(work.iterdir())
    # al nuovo clic si rigenera invece di servire un file vuoto o di silenzio
    fake_edge["steps"] = []
    r = _get(app_mod, job_id)
    assert r.status_code == 200
    r.close()
