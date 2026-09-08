"""La normalizzazione del testo deve valere ovunque l'utente la possa vedere.

`_plan_chunks` normalizza (maiuscolo -> sentence case, punto dopo l'heading), ma
due percorsi che l'utente usa per giudicare il risultato non ne beneficiavano:

1. ANTEPRIMA VOCE. L'endpoint applicava la catena a un testo gia` appiattito su
   una riga sola (`re.sub(r'\\s+', ' ')` a monte, sia nell'estratto per capitoli
   selezionati sia nel `preview_text` salvato all'analisi). Le normalizzazioni
   ragionano per riga: su una riga sola `_ensure_heading_pause` non riconosce
   piu` l'heading e il titolo resta incollato al primo paragrafo. Il maiuscolo
   veniva comunque abbassato dalla regola inline, quindi il difetto si sentiva
   solo come pausa mancante — ed e` il difetto che l'utente ha segnalato.

   Il test che gia` esisteva non lo intercettava perche' iniettava a mano un
   `preview_text` CON gli a-capo: uno stato che nel flusso reale non esiste.

2. SNAPSHOT .abm. Lo snapshot scaricabile mostrava il testo pre-normalizzazione:
   l'utente lo legge come prova di cosa verra` letto, e ci trovava il MAIUSCOLO
   e il titolo senza punto. Ora il .abm porta il testo preparato per il TTS —
   ottimizzazione AI inclusa, come sempre — cosi` quello che si legge e` quello
   che si sente.
"""
import importlib
import io
import json
import shutil
import zipfile

import pytest


TESTO = ("L'AMORE E LA SUA DISINTEGRAZIONE NELLA SOCIETA OCCIDENTALE\n\n"
         "Se l'amore e` una capacita` del carattere maturo e produttivo, ne "
         "segue che la capacita` d'amare in una vita individuale dipende "
         "dall'influenza che questa civilta` ha sul carattere della persona "
         "media. La risposta e` negativa, e nessun osservatore obiettivo "
         "della nostra vita occidentale puo` dubitarne davvero.")

ATTESO = "L'amore e la sua disintegrazione nella societa occidentale."


@pytest.fixture
def app_env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import audiobook_app
    importlib.reload(audiobook_app)
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app, tmp_path


# ── 1. anteprima voce ──

def _fake_speechify(seen):
    def _synth(text, voice_id, output_path, emotion=None, rate="+0%", **kw):
        seen["text"] = text
        with open(output_path, "wb") as fp:
            fp.write(b"\x00\x00" * 4800)  # 0.1s @ 48kHz mono 16-bit
        return {"success": True, "bytes_written": 9600, "sample_rate": 48000,
                "channels": 1, "billable_chars": len(text),
                "voice_name": "harper_32"}
    return _synth


def _preview(app_mod, monkeypatch, job_id, query):
    import speechify_tts
    seen = {}
    monkeypatch.setattr(speechify_tts, "synthesize", _fake_speechify(seen))
    shutil.rmtree(app_mod.UPLOAD_DIR / job_id, ignore_errors=True)
    try:
        client = app_mod.app.test_client()
        r = client.get(f"/api/preview_audio/{job_id}", query_string=query)
        assert r.status_code == 200, r.get_data(as_text=True)
    finally:
        shutil.rmtree(app_mod.UPLOAD_DIR / job_id, ignore_errors=True)
    return seen["text"]


def _register_job(app_mod, job_id, preview_text):
    from epub_to_tts import BookInfo, Chapter
    ch = Chapter(index=1, title="Capitolo primo", text=TESTO)
    info = BookInfo(title="T", author="A", language="it", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    with app_mod._jobs_lock:
        app_mod.jobs[job_id] = {"info": info, "status": "analyzed",
                                "preview_text": preview_text}
    return info


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not in PATH")
def test_preview_from_selected_chapters_keeps_heading_pause(app_env, monkeypatch):
    """Percorso `selected_chapters`: l'estratto nasce dal testo del capitolo e
    veniva appiattito prima della normalizzazione."""
    app_mod, _ = app_env
    app_mod._invalidate_voices_cache()
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    job_id = "prev-sel-1"
    _register_job(app_mod, job_id, "irrilevante: vince la selezione")
    try:
        text = _preview(app_mod, monkeypatch, job_id, {
            "voice": "speechify:simba-3.2:harper_32", "rate": "+0%",
            "selected_chapters": "1"})
    finally:
        with app_mod._jobs_lock:
            app_mod.jobs.pop(job_id, None)
    assert ATTESO in text
    assert "L'AMORE" not in text


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not in PATH")
def test_preview_from_analyze_fallback_keeps_heading_pause(app_env, monkeypatch):
    """Percorso di fallback: il `preview_text` e` quello che /api/analyze ha
    salvato, gia` troncato e appiattito. Deve arrivare gia` normalizzato."""
    app_mod, _ = app_env
    app_mod._invalidate_voices_cache()
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    client = app_mod.app.test_client()
    r = client.post("/api/analyze", data={
        "epub": (io.BytesIO(TESTO.encode("utf-8")), "Prova titoli.txt")},
        content_type="multipart/form-data")
    assert r.status_code == 200, r.get_data(as_text=True)
    job_id = r.get_json()["job_id"]
    try:
        preview_text = app_mod.jobs[job_id].get("preview_text", "")
        assert ATTESO in preview_text, repr(preview_text)
        text = _preview(app_mod, monkeypatch, job_id, {
            "voice": "speechify:simba-3.2:harper_32", "rate": "+0%"})
        assert ATTESO in text
        assert "L'AMORE" not in text
    finally:
        with app_mod._jobs_lock:
            app_mod.jobs.pop(job_id, None)


# ── 2. snapshot .abm ──

def _abm_chapters(app_env, job_extra=None):
    app_mod, tmp_path = app_env
    import generation_engine
    from epub_to_tts import BookInfo, Chapter
    job_id = "abm-norm-1"
    (tmp_path / job_id).mkdir(parents=True, exist_ok=True)
    ch = Chapter(index=1, title="Capitolo primo", text=TESTO)
    info = BookInfo(title="Prova", author="A", language="it", chapters=[ch],
                    total_words=ch.word_count, total_chars=ch.char_count,
                    estimated_duration_minutes=1.0)
    job = {"info": info, "status": "analyzed", "original_filename": "p.txt"}
    job.update(job_extra or {})
    generation_engine._jobs[job_id] = job
    try:
        path, _name = generation_engine._generate_optimized_abm(job_id)
        assert path, "nessuno snapshot generato"
        with zipfile.ZipFile(path) as zf:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
            texts = {n: zf.read(n).decode("utf-8")
                     for n in zf.namelist() if n.startswith("chapters/")}
        return manifest, texts
    finally:
        generation_engine._jobs.pop(job_id, None)


def test_abm_snapshot_carries_tts_ready_text(app_env):
    """Il testo nello snapshot e` quello che il TTS legge: niente MAIUSCOLO e
    heading col punto."""
    _manifest, texts = _abm_chapters(app_env)
    body = "\n".join(texts.values())
    assert ATTESO in body, repr(body[:200])
    assert "L'AMORE" not in body


def test_abm_snapshot_keeps_paragraph_structure(app_env):
    """La preparazione non appiattisce lo snapshot: il .abm resta un progetto
    leggibile e ri-caricabile, con i suoi paragrafi."""
    _manifest, texts = _abm_chapters(app_env)
    body = "\n".join(texts.values())
    assert "\n\n" in body


def test_abm_snapshot_applies_parenthesis_flags(app_env):
    """Le parentesi seguono la scelta dell'utente, come nella generazione."""
    testo = "Il titolo del capitolo.\n\nUna frase (con inciso) e via."
    from epub_to_tts import Chapter
    import generation_engine

    def _run(job_extra):
        app_mod, tmp_path = app_env
        from epub_to_tts import BookInfo
        job_id = "abm-paren-1"
        (tmp_path / job_id).mkdir(parents=True, exist_ok=True)
        ch = Chapter(index=1, title="Cap", text=testo)
        info = BookInfo(title="P", author="", language="it", chapters=[ch],
                        total_words=ch.word_count, total_chars=ch.char_count,
                        estimated_duration_minutes=1.0)
        job = {"info": info, "status": "analyzed"}
        job.update(job_extra)
        generation_engine._jobs[job_id] = job
        try:
            path, _ = generation_engine._generate_optimized_abm(job_id)
            with zipfile.ZipFile(path) as zf:
                return "\n".join(zf.read(n).decode("utf-8")
                                 for n in zf.namelist()
                                 if n.startswith("chapters/"))
        finally:
            generation_engine._jobs.pop(job_id, None)

    assert "con inciso" not in _run({})
    assert "con inciso" in _run({"read_round_parens": True})


def test_abm_snapshot_declares_the_normalization_in_manifest(app_env):
    """Il manifest dichiara cosa e` stato applicato: lo snapshot e` evidenza,
    e un'evidenza dice anche da dove viene."""
    manifest, _texts = _abm_chapters(app_env)
    prep = manifest.get("tts_text_prepared")
    assert isinstance(prep, dict), manifest
    assert prep.get("shouting_normalized") is True
    assert prep.get("heading_pause") is True
    assert prep.get("round_parens_read") is False
    assert prep.get("square_brackets_read") is False
