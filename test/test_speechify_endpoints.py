import shutil

import pytest

from epub_to_tts import BookInfo, Chapter


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    import audiobook_app
    audiobook_app._invalidate_voices_cache()
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


@pytest.fixture
def spx_job(client):
    """Job analizzato con un capitolo da 200000 caratteri, per la stima combinata.

    Riferisce dinamicamente `audiobook_app.jobs`/`_jobs_lock` (invece di un
    import statico a livello modulo) perche' `test_voices_exclude_speechify_without_key`
    ricarica `audiobook_app` con `importlib.reload`, sostituendo l'oggetto
    modulo: un import catturato all'import-time del file punterebbe al dict
    `jobs` stantio del modulo pre-reload.
    """
    import audiobook_app
    ch = Chapter(index=0, title="Cap0", text="A" * 200000)
    info = BookInfo(
        title="T",
        author="A",
        language="en",
        chapters=[ch],
        total_words=ch.word_count,
        total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs["spx_est_1"] = {"info": info, "status": "analyzed"}
    yield "spx_est_1"
    with audiobook_app._jobs_lock:
        audiobook_app.jobs.pop("spx_est_1", None)


def test_voices_include_speechify_when_available(client):
    r = client.get("/api/voices")
    assert r.status_code == 200
    data = r.get_json()
    en_voices = data["en"]["voices"]
    ids = [v["id"] for v in en_voices]
    assert any(i.startswith("speechify:simba-3.2:") for i in ids)


def test_voices_exclude_speechify_without_key(monkeypatch):
    monkeypatch.delenv("ABM_SPEECHIFY_API_KEY", raising=False)
    import importlib
    import audiobook_app
    importlib.reload(audiobook_app)
    audiobook_app._invalidate_voices_cache()
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    r = c.get("/api/voices")
    assert r.status_code == 200
    data = r.get_json()
    en_voices = data["en"]["voices"]
    ids = [v["id"] for v in en_voices]
    assert not any(i.startswith("speechify:") for i in ids)


def test_combined_estimate_speechify(client, spx_job):
    """La stima combinata per una voce speechify usa il pricing Speechify e
    ritorna la forma completa della risposta (paypal_* inclusi, no early-return).
    """
    import speechify_tts

    r = client.post("/api/combined_estimate", json={
        "job_id": spx_job,
        "voice_id": "speechify:simba-3.2:harper_32",
        "selected_chapters": [0],
    })
    assert r.status_code == 200, r.get_data(as_text=True)
    data = r.get_json()
    bd = data.get("speechify_breakdown") or {}
    expected = speechify_tts.compute_user_price_eur(200_000)["user_price_eur"]
    assert bd.get("user_price_eur") == expected
    assert data["speechify_eur"] == expected
    assert "paypal_available" in data  # shape completa, non early-return


def test_generate_passes_speechify_emotion(client, monkeypatch):
    """/api/generate salva l'emozione validata sul job e la inoltra a
    run_generation via kwargs (percorso free: 1000 char < soglia gratuita
    Speechify, nessun payment_token necessario).
    """
    import audiobook_app
    from epub_to_tts import BookInfo, Chapter

    captured = {}

    def _fake_run(job_id, info, voice, rate, single_file, **kw):
        captured["voice"] = voice
        captured["speechify_emotion"] = kw.get("speechify_emotion")

    monkeypatch.setattr(audiobook_app, "run_generation", _fake_run)
    # Evita l'invio di una email admin reale (SMTP configurato nell'ambiente
    # dev) quando il test colpisce l'endpoint /api/generate vero.
    monkeypatch.setattr(audiobook_app, "_admin_notify_generation", lambda *a, **k: None)

    # Rende sincrono lo spawn del thread di generazione: senza questo, il
    # dict `captured` viene mutato da un thread daemon reale senza join,
    # rendendo le asserzioni sotto teoricamente in race con il return
    # dell'endpoint.
    class _SyncThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None):
            self._t, self._a, self._k = target, args, kwargs or {}

        def start(self):
            self._t(*self._a, **self._k)
    monkeypatch.setattr(audiobook_app.threading, "Thread", _SyncThread)

    job_id = "spx-gen-1"
    ch = Chapter(index=0, title="Cap0", text="A" * 1000)
    info = BookInfo(
        title="T", author="A", language="en", chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": "analyzed"}
    try:
        r = client.post("/api/generate", json={
            "job_id": job_id,
            "voice": "speechify:simba-3.2:harper_32",
            "rate": "+0%",
            "output_format": "mp3",
            "speechify_emotion": "cheerful",
            "lang": "en",
        })
        assert r.status_code in (200, 202), r.get_data(as_text=True)
        assert audiobook_app.jobs[job_id].get("speechify_emotion") == "cheerful"
        assert captured.get("speechify_emotion") == "cheerful"
        assert captured.get("voice") == "speechify:simba-3.2:harper_32"
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(job_id, None)


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not in PATH")
def test_preview_audio_speechify(client, monkeypatch):
    """/api/preview_audio deve sintetizzare via Speechify (PCM->MP3) per una
    voce speechify:, rispettando emotion/rate passati come query string
    (l'endpoint e' GET, legge da request.args).
    """
    import audiobook_app
    import speechify_tts

    def _fake_synth(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00" * 4800)  # 0.1s @ 48kHz mono 16-bit
        return {"success": True, "bytes_written": 9600, "sample_rate": 48000,
                "channels": 1, "billable_chars": len(text), "voice_name": "harper_32"}
    monkeypatch.setattr(speechify_tts, "synthesize", _fake_synth)

    job_id = "spx-preview-1"
    ch = Chapter(index=0, title="Cap0", text="Hello world. " * 40)
    info = BookInfo(title="T", author="A", language="en", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": "analyzed",
                                      "preview_text": "Hello world. " * 40}
    try:
        r = client.get(f"/api/preview_audio/{job_id}",
                       query_string={"voice": "speechify:simba-3.2:harper_32",
                                     "rate": "+0%", "speechify_emotion": "calm"})
        assert r.status_code == 200, r.get_data(as_text=True)
        assert r.mimetype in ("audio/mpeg", "audio/mp3")
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(job_id, None)


def test_generate_speechify_unconfigured_returns_400(client, monkeypatch):
    """/api/generate deve rifiutare una voce Speechify PRIMA di consumare
    token/spawnare il thread quando ABM_SPEECHIFY_API_KEY non e' configurata
    (parita' con il guard analogo per le voci Gemini).
    """
    import audiobook_app

    monkeypatch.delenv("ABM_SPEECHIFY_API_KEY", raising=False)

    job_id = "spx-gen-unconfigured"
    ch = Chapter(index=0, title="Cap0", text="A" * 1000)
    info = BookInfo(
        title="T", author="A", language="en", chapters=[ch],
        total_words=ch.word_count, total_chars=ch.char_count,
        estimated_duration_minutes=1.0,
    )
    with audiobook_app._jobs_lock:
        audiobook_app.jobs[job_id] = {"info": info, "status": "analyzed"}
    try:
        r = client.post("/api/generate", json={
            "job_id": job_id,
            "voice": "speechify:simba-3.2:harper_32",
            "rate": "+0%",
            "output_format": "mp3",
            "lang": "en",
        })
        assert r.status_code == 400, r.get_data(as_text=True)
        assert r.get_json().get("error") == "speechify_not_configured"
    finally:
        with audiobook_app._jobs_lock:
            audiobook_app.jobs.pop(job_id, None)
