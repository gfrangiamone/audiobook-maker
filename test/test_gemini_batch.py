"""Trasporto batch di Gemini TTS sull'API Gemini (solo catalogo gratuito)."""
import base64
import io
import json
import wave

import pytest

import env_utils
import gemini_batch
import gemini_tts
import generation_engine


def _wav(secondi=1.0, ampiezza=5000):
    campioni = int(gemini_tts.AUDIO_SAMPLE_RATE * secondi)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(gemini_tts.AUDIO_SAMPLE_RATE)
        w.writeframes(ampiezza.to_bytes(2, "little", signed=True) * campioni)
    return buf.getvalue()


def risposta_audio(wav=None):
    return {"response": {
        "candidates": [{"content": {"role": "model", "parts": [{"inlineData": {
            "mimeType": "audio/wav",
            "data": base64.b64encode(wav or _wav()).decode()}}]},
            "finishReason": "STOP"}],
        # serviceTier: campo arrivato dopo la versione dell'SDK (05/11/2026),
        # le risposte vere lo portano e non deve far scartare il chunk
        "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 100,
                          "serviceTier": "SERVICE_TIER_STANDARD"}}}


RIFIUTO = {"response": {"candidates": [{"finishReason": "OTHER"}]}}


class Errore(Exception):
    def __init__(self, code):
        super().__init__(f"HTTP {code}")
        self.code = code


class _Stato:
    def __init__(self, name):
        self.name = name


class _Job:
    def __init__(self, name, stato, file_name=None):
        self.name = name
        self.state = _Stato(stato)
        self.dest = type("D", (), {"file_name": file_name})() if file_name else None
        self.error = None

    @property
    def done(self):
        return self.state.name not in ("JOB_STATE_PENDING", "JOB_STATE_RUNNING")


class Client:
    """Doppio dell'SDK: un batch e' pronto dopo `giri` letture dello stato."""

    def __init__(self, risponde=None, giri=1, stato_finale="JOB_STATE_SUCCEEDED",
                 errori_create=()):
        self.risponde = risponde or (lambda key: risposta_audio())
        self.giri = giri
        self.stato_finale = stato_finale
        self.errori_create = list(errori_create)
        self.caricati = {}      # nome file -> righe JSONL
        self.batch = {}         # nome batch -> {"src", "letture"}
        self.cancellati, self.file_cancellati = [], []
        self.files = self
        self.batches = _Batches(self)

    # files
    def upload(self, file, config):
        nome = f"files/in{len(self.caricati)}"
        with open(file, encoding="utf-8") as f:
            self.caricati[nome] = [json.loads(r) for r in f if r.strip()]
        return type("F", (), {"name": nome})()

    def download(self, file):
        src = file.replace("files/out-", "")
        righe = [dict(self.risponde(r["key"]), key=r["key"]) for r in self.caricati[src]]
        return "\n".join(json.dumps(r) for r in righe).encode()

    def delete(self, name):
        self.file_cancellati.append(name)


class _Batches:
    def __init__(self, c):
        self.c = c

    def create(self, model, src, config):
        if self.c.errori_create:
            e = self.c.errori_create.pop(0)
            if e is not None:
                raise e
        nome = f"batches/b{len(self.c.batch)}"
        self.c.batch[nome] = {"src": src, "letture": 0, "model": model}
        return _Job(nome, "JOB_STATE_PENDING")

    def get(self, name):
        b = self.c.batch[name]
        b["letture"] += 1
        if b["letture"] < self.c.giri:
            return _Job(name, "JOB_STATE_RUNNING")
        return _Job(name, self.c.stato_finale, f"files/out-{b['src']}")

    def cancel(self, name):
        self.c.cancellati.append(name)


@pytest.fixture
def ambiente(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BATCH_POLL_S", "5")
    monkeypatch.setenv("ABM_GEMINI_BATCH_IN_FLIGHT", "4")
    monkeypatch.setenv("ABM_GEMINI_BATCH_CHUNKS", "50")


def items(tmp_path, *chiavi):
    return [{"key": k, "text": f"Frase numero {k}.", "dest": str(tmp_path / f"c{k}.pcm"),
             "prompt_path": str(tmp_path / f"prompt{k + 1}.txt")} for k in chiavi]


def sintetizza(tmp_path, its, client, **kw):
    kw.setdefault("sleep", lambda s: None)
    return gemini_batch.synthesize_batch(its, "gemini:flash38:Kore", work_dir=str(tmp_path),
                                         client=client, **kw)


# --- richiesta, tariffa, accensione -----------------------------------------

def test_la_riga_del_batch_e_la_richiesta_sincrona_in_forma_rest():
    finale = gemini_tts.build_final_text("Ciao.", "calmo", "+0%", None)
    r38 = gemini_tts.speech_request_json(finale, "Kore", "flash38", 0.7)
    assert r38["contents"] == [{"role": "user", "parts": [
        {"text": "Ciao.", "speechMetadata": {"style": "calmo"}}]}]
    assert r38["generationConfig"] == {
        "responseModalities": ["AUDIO"], "temperature": 0.7,
        "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": "Kore"}}}}
    # flash31 non legge speechMetadata: lo stile resta nel testo, come in sincrono
    r31 = gemini_tts.speech_request_json(finale, "Kore", "flash31", None)
    assert r31["contents"] == [{"role": "user", "parts": [{"text": finale}]}]
    assert "temperature" not in r31["generationConfig"]


def test_il_batch_costa_meta_listino_con_l_iva_dell_api_key():
    pieno = gemini_tts.actual_rates("flash38", "apikey")
    batch = gemini_tts.actual_rates("flash38", gemini_tts.BATCH_BACKEND)
    assert batch == pytest.approx((pieno[0] / 2, pieno[1] / 2))


def test_si_accende_solo_fuori_produzione_e_con_la_chiave(monkeypatch):
    monkeypatch.setenv("ABM_BASE_URL", "http://localhost:5621")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "chiave-di-prova")
    monkeypatch.delenv("ABM_GEMINI_TRANSPORT", raising=False)
    assert not gemini_batch.enabled("gemini:flash38:Kore")
    monkeypatch.setenv("ABM_GEMINI_TRANSPORT", "batch")
    assert gemini_batch.enabled("gemini:flash38:Kore")
    assert not gemini_batch.enabled("voxcpm:v2:it-IT/Bruno")
    monkeypatch.setenv("ABM_BASE_URL", "https://audiobook-maker.com")
    assert not gemini_batch.enabled("gemini:flash38:Kore")
    monkeypatch.setenv("ABM_BASE_URL", "http://localhost:5621")
    monkeypatch.delenv("ABM_GEMINI_API_KEY")
    assert not gemini_batch.enabled("gemini:flash38:Kore")


def test_batch_transport_e_unico_per_i_motori(monkeypatch):
    monkeypatch.setenv("ABM_BASE_URL", "https://audiobook-maker.com")
    monkeypatch.setenv("ABM_X_TRANSPORT", "batch")
    assert env_utils.batch_transport("ABM_X_TRANSPORT") is False
    monkeypatch.setenv("ABM_BASE_URL", "http://localhost:5601")
    assert env_utils.batch_transport("ABM_X_TRANSPORT") is True


# --- synthesize_batch --------------------------------------------------------

def test_lotti_consegnati_come_la_sintesi_sincrona(tmp_path, ambiente, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BATCH_CHUNKS", "2")
    monkeypatch.setenv("ABM_GEMINI_BATCH_IN_FLIGHT", "2")
    c = Client(giri=2)
    pubblicati = []
    esiti = sintetizza(tmp_path, items(tmp_path, 0, 1, 2, 3, 4), c,
                       style_instruction="calmo", on_in_corso=pubblicati.append)

    assert sorted(esiti) == [0, 1, 2, 3, 4]
    e = esiti[3]
    assert e["backend"] == gemini_tts.BATCH_BACKEND
    assert (e["input_tokens"], e["output_tokens"], e["tokens_measured"]) == (20, 100, True)
    assert e["bytes_written"] == gemini_tts.AUDIO_SAMPLE_RATE * 2
    assert (tmp_path / "c3.pcm").stat().st_size == e["bytes_written"]
    assert (tmp_path / "prompt4.txt").read_text(encoding="utf-8").startswith("[style: calmo")
    # tre lotti (2+2+1), mai piu' di due in volo, modello dell'API key
    assert [len(r) for r in c.caricati.values()] == [2, 2, 1]
    assert {b["model"] for b in c.batch.values()} == {"gemini-3.8-flash-tts"}
    assert max(len(p) for p in pubblicati) == 2 and pubblicati[-1] == []
    assert [r["key"] for r in c.caricati["files/in0"]] == ["0", "1"]
    # file caricati e risposte cancellati da Google a lavoro finito
    assert set(c.file_cancellati) >= set(c.caricati)
    assert not list(tmp_path.glob("gemini_batch_*.jsonl"))


def test_rifiuti_e_audio_muto_restano_al_giro_sincrono(tmp_path, ambiente, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_SILENCE_MAX_GAP_SEC", "8")
    monkeypatch.setenv("ABM_GEMINI_SILENCE_MIN_VOICED", "0.25")

    def risponde(key):
        return {"1": RIFIUTO, "2": risposta_audio(_wav(4.0, 0))}.get(key) or risposta_audio()
    esiti = sintetizza(tmp_path, items(tmp_path, 0, 1, 2), Client(risponde))
    assert sorted(esiti) == [0]
    assert not (tmp_path / "c1.pcm").exists() and not (tmp_path / "c2.pcm").exists()


def test_coda_piena_il_lotto_riparte_al_giro_dopo(tmp_path, ambiente, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BATCH_CHUNKS", "1")
    c = Client(giri=2, errori_create=[None, Errore(429)])
    esiti = sintetizza(tmp_path, items(tmp_path, 0, 1), c)
    assert sorted(esiti) == [0, 1]
    assert len(c.batch) == 2


def test_429_senza_batch_in_volo_lascia_tutto_al_sincrono(tmp_path, ambiente):
    c = Client(errori_create=[Errore(429)])
    assert sintetizza(tmp_path, items(tmp_path, 0, 1), c) == {}
    assert c.file_cancellati == ["files/in0"]


def test_i_batch_persistiti_si_riprendono_senza_ripagarli(tmp_path, ambiente):
    c = Client()
    # batch creato da un run precedente: il doppio lo conosce gia'
    c.caricati["files/in9"] = [{"key": "0"}, {"key": "1"}]
    c.batch["batches/vecchio"] = {"src": "files/in9", "letture": 0, "model": "x"}
    esiti = sintetizza(tmp_path, items(tmp_path, 0, 1, 2), c,
                       in_corso=[{"name": "batches/vecchio", "file": "files/in9",
                                  "keys": [0, 1, 7]}])
    assert sorted(esiti) == [0, 1, 2]
    # nuovo batch solo per il chunk non coperto
    assert [r["key"] for r in c.caricati["files/in1"]] == ["2"]


def test_l_annullamento_cancella_i_batch_in_volo(tmp_path, ambiente):
    c = Client(giri=99)
    letture = []
    with pytest.raises(gemini_batch.GeminiBatchAnnullato):
        sintetizza(tmp_path, items(tmp_path, 0), c,
                   cancelled=lambda: letture.append(1) or len(letture) > 2)
    assert c.cancellati == ["batches/b0"]


def test_oltre_il_tetto_si_cancella_e_il_resto_va_in_sincrono(tmp_path, ambiente, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BATCH_TIMEOUT_S", "60")
    ora = iter(range(0, 10_000, 100))
    c = Client(giri=99)
    assert sintetizza(tmp_path, items(tmp_path, 0), c, clock=lambda: next(ora)) == {}
    assert c.cancellati == ["batches/b0"]


def test_un_batch_fallito_non_consegna_nulla(tmp_path, ambiente):
    c = Client(stato_finale="JOB_STATE_FAILED")
    assert sintetizza(tmp_path, items(tmp_path, 0), c) == {}
    assert "files/in0" in c.file_cancellati


# --- motore ------------------------------------------------------------------

def test_pre_pass_persiste_i_batch_e_mappa_l_annullamento(tmp_path, monkeypatch):
    plan = [{"text": "Uno."}, {"text": "Due."}, {"text": ""}]
    visti = {}

    def finto(its, voice, **kw):
        visti["keys"] = [it["key"] for it in its]
        kw["on_in_corso"]([{"name": "batches/b0", "file": "files/in0", "keys": [1]}])
        return {1: {"ok": True}}
    patch = []
    monkeypatch.setattr(generation_engine.gemini_batch, "synthesize_batch", finto)
    monkeypatch.setattr(generation_engine.pending_jobs, "patch",
                        lambda jid, d: patch.append((jid, d)))
    job = {}
    esiti = generation_engine._gemini_batch_pre_pass(
        plan, "gemini:flash38:Kore", "+0%", None, None, tmp_path, "j1", {0}, job=job)
    assert esiti == {1: {"ok": True}}
    assert visti["keys"] == [1]          # 0 riusato, 2 vuoto: fuori dal batch
    assert job["gemini_batches"][0]["name"] == "batches/b0"
    assert patch == [("j1", {"gemini_batches": job["gemini_batches"]})]

    def annullato(*a, **k):
        raise gemini_batch.GeminiBatchAnnullato("x")
    monkeypatch.setattr(generation_engine.gemini_batch, "synthesize_batch", annullato)
    with pytest.raises(generation_engine._CancelledError):
        generation_engine._gemini_batch_pre_pass(
            plan, "gemini:flash38:Kore", "+0%", None, None, tmp_path, "j1", set(), job=job)

    def rotto(*a, **k):
        raise RuntimeError("upload rifiutato")
    monkeypatch.setattr(generation_engine.gemini_batch, "synthesize_batch", rotto)
    assert generation_engine._gemini_batch_pre_pass(
        plan, "gemini:flash38:Kore", "+0%", None, None, tmp_path, "j1", set(), job=job) == {}


def test_run_generation_contabilizza_il_batch_e_rifa_il_resto(monkeypatch, tmp_path):
    """6 chunk: il batch ne consegna 3, il giro sincrono fa gli altri 3."""
    sincroni = []

    def fake_chunk_gemini(text, voice_id, output_path, max_retries=3, **kwargs):
        sincroni.append(output_path)
        with open(output_path, "wb") as f:
            f.write(b"\x00" * 1000)
        out = {"success": True, "bytes_written": 1000, "input_tokens": 100,
               "output_tokens": 500, "model_key": "flash38", "voice_name": "Kore",
               "attempts_used": 1, "backend": "openrouter"}
        if len(sincroni) == 1:
            out["resplit_pieces"] = 2       # rifiuto recuperato rispezzando
        return out

    def fake_batch(its, voice, **kw):
        out = {}
        for it in its[:3]:
            with open(it["dest"], "wb") as f:
                f.write(b"\x00" * 2000)
            out[it["key"]] = {"success": True, "bytes_written": 2000, "input_tokens": 10,
                              "output_tokens": 50, "model_key": "flash38",
                              "voice_name": "Kore", "attempts_used": 1,
                              "backend": gemini_tts.BATCH_BACKEND, "tokens_measured": True}
        return out

    monkeypatch.setattr(generation_engine, "generate_chunk_pcm_gemini", fake_chunk_gemini)
    # l'audit dei costi di fine job non deve finire nella cartella corrente
    monkeypatch.setattr(generation_engine.gemini_cost_audit, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(generation_engine.gemini_batch, "enabled", lambda v: True)
    monkeypatch.setattr(generation_engine.gemini_batch, "synthesize_batch", fake_batch)
    monkeypatch.setattr(generation_engine.pending_jobs, "patch", lambda *a, **k: None)
    monkeypatch.setattr(generation_engine.gemini_tts, "actual_cost_breakdown",
                        lambda i, o, mk, b: {"total_eur": 0.0}, raising=False)
    plan = [{"chapter_index": 1, "chapter_title": "Cap 1", "chunk_index": c,
             "chunks_in_chapter": 6, "text": "Hello world", "chars": 11} for c in range(6)]
    monkeypatch.setattr(generation_engine, "_plan_chunks",
                        lambda info, max_chars, max_bytes=None, **kw: plan)
    monkeypatch.setattr(generation_engine, "_pick_chunk_max_chars", lambda v, l: 4096)
    monkeypatch.setattr(generation_engine, "_engine_for_voice", lambda v: "gemini")
    monkeypatch.setattr(generation_engine, "_generate_silence_pcm",
                        lambda p, s=1, sample_rate=None: open(p, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "pcm_to_mp3",
                        lambda parts, out, **kw: open(out, "wb").write(b"\x00"))
    monkeypatch.setattr(generation_engine, "_get_audio_duration_ms", lambda p: 1000)
    monkeypatch.setattr(generation_engine, "pcm_size_to_seconds", lambda b, **kw: 1.0)
    monkeypatch.setattr(generation_engine, "_prepare_m4b_cover_path", lambda *a, **k: None)

    class _Info:
        title = "T"
        author = "A"
        language = "it"
        chapters = [type("C", (), {"title": "Cap 1", "text": "..."})()]
    job = {"gen_epoch": 0, "info": _Info(), "status": "queued",
           "last_poll": 9e18, "email_registered": True}
    monkeypatch.setattr(generation_engine, "_jobs", {"jb": job})
    monkeypatch.setattr(generation_engine, "_upload_dir", tmp_path)
    monkeypatch.setattr(generation_engine, "_jobs_lock", None, raising=False)
    try:
        generation_engine.run_generation("jb", _Info(), "gemini:flash38:Kore", "+0%",
                                         single_file=True, output_format="mp3")
    except Exception:
        pass

    assert len(sincroni) == 3
    assert job["gemini_resplit_chunks"] == 1
    ga = job["gemini_actual"]
    assert ga["backends"] == {gemini_tts.BATCH_BACKEND: 3, "openrouter": 3}
    assert ga["input_tokens"] == 3 * 10 + 3 * 100
    assert ga["output_tokens"] == 3 * 50 + 3 * 500
