"""Trasporto batch di VoxCPM: le route `/batch` di RunPod e il ripiego su `/run`.

La rete e' una sessione finta che risponde per percorso (`POST /batch`,
`GET /batch/<id>`, ...) e annota le chiamate; R2 e' sostituito da funzioni
finte, come il download. In fondo, la pre-sintesi del libro con
`synthesize_batch` sostituito da un doppio.
"""
import json
import os

import pytest

import generation_engine
import storage_backend
import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
VOCE = "voxcpm:v2:it-IT/Stefano"


class Risposta:
    def __init__(self, body=None, status_code=200):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body)

    def json(self):
        return self._body


class Sessione:
    """Risponde per (metodo, percorso dopo l'endpoint); l'ultima risposta di
    un percorso si ripete. Annota ogni chiamata in ordine."""

    def __init__(self, copione):
        self.copione = {k: list(v) for k, v in copione.items()}
        self.chiamate = []

    def _rispondi(self, metodo, url, corpo):
        percorso = url.split("/ep-di-prova", 1)[1]
        self.chiamate.append((metodo, percorso, corpo))
        coda = self.copione.get((metodo, percorso))
        if not coda:
            raise AssertionError(f"{metodo} non previsto: {percorso}")
        r = coda[0] if len(coda) == 1 else coda.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def post(self, url, headers=None, json=None, timeout=None):
        return self._rispondi("post", url, json)

    def get(self, url, headers=None, timeout=None):
        return self._rispondi("get", url, None)


@pytest.fixture(autouse=True)
def ambiente(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_BATCH_POLL_S", "5")
    voxcpm_catalog.invalidate_cache()
    voxcpm_tts.invalidate_clone_cache()
    # R2 acceso e finto: gli oggetti caricati dal "worker" stanno in `r2`.
    r2 = {}
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: f"https://r2/put/{key}?ttl={ttl}")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, *a, **k: f"https://r2/get/{key}")
    monkeypatch.setattr(storage_backend, "delete_object", lambda key: r2.pop(key, None))

    def scarica(url, dest):
        with open(dest, "wb") as f:
            f.write(r2[url.rsplit("/get/", 1)[1]])
    monkeypatch.setattr(voxcpm_tts, "_scarica", scarica)
    return r2


def dormi(_s):
    return None


def riga(chiave, pcm=b"\x01\x02" * 50, *, status="COMPLETED", output=None, exec_ms=60000):
    out = output if output is not None else {
        "failed_indices": [], "sample_rate": 48000, "chars": 10, "audio_seconds": 1.0,
        "tts_seconds": 0.5, "chunk_samples": [len(pcm) // 2],
        "s3": {"key": chiave, "bytes": len(pcm)}, "worker": "w1",
        "gpu": "NVIDIA RTX PRO 6000 Blackwell MIG 1g.24gb"}
    return {"id": f"r-{chiave}", "status": status, "input": {"s3": {"key": chiave}},
            "output": out, "executionTime": exec_ms, "delayTime": 1000}


def items(tmp_path, *chiavi):
    return [{"chunks": [f"Frase {k}."], "dest": str(tmp_path / f"{k}.pcm"), "key": k}
            for k in chiavi]


def test_il_trasporto_si_sceglie_dall_ambiente(monkeypatch):
    monkeypatch.delenv("ABM_VOXCPM_TRANSPORT", raising=False)
    assert voxcpm_tts.transport() == "run"
    monkeypatch.setenv("ABM_VOXCPM_TRANSPORT", " Batch ")
    assert voxcpm_tts.transport() == "batch"
    monkeypatch.setenv("ABM_VOXCPM_TRANSPORT", "altro")
    assert voxcpm_tts.transport() == "run"


def test_il_batch_nasce_vuoto_e_l_id_si_salva_prima_delle_richieste(monkeypatch):
    # Gruppi da ~1 payload: il tetto dei 10 MiB si prova senza 10 MiB.
    monkeypatch.setattr(voxcpm_tts, "_BATCH_BODY_MAX_BYTES", 30)
    ses = Sessione({("post", "/batch"): [Risposta({"id": "b1"})],
                    ("post", "/batch/b1/requests"): [Risposta({})],
                    ("post", "/batch/b1/finalize"): [Risposta({"status": "FINALIZED"})]})
    visti = []
    payloads = [{"input": {"n": i}} for i in range(3)]
    bid = voxcpm_tts.batch_create(
        payloads, session=ses, sleep=dormi,
        on_batch_id=lambda b: visti.append((b, len(ses.chiamate))))
    assert bid == "b1"
    assert visti == [("b1", 1)]                       # subito dopo la creazione
    assert ses.chiamate[0] == ("post", "/batch", [])
    # Il corpo dell'aggiunta e' un array, non `{"requests": [...]}`.
    gruppi = [c[2] for c in ses.chiamate if c[1] == "/batch/b1/requests"]
    assert [len(g) for g in gruppi] == [1, 1, 1]
    assert all(isinstance(g, list) for g in gruppi)
    assert ses.chiamate[-1][1] == "/batch/b1/finalize"


def test_una_bozza_rifiutata_si_cancella_subito():
    ses = Sessione({("post", "/batch"): [Risposta({"id": "b1"})],
                    ("post", "/batch/b1/requests"): [Risposta({"detail": "bad"}, 400)],
                    ("post", "/batch/b1/cancel"): [Risposta({})]})
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        voxcpm_tts.batch_create([{"input": {}}], session=ses, sleep=dormi)
    assert ses.chiamate[-1] == ("post", "/batch/b1/cancel", None)


def test_batch_riuscito_consegna_ogni_lotto(tmp_path, ambiente):
    ambiente["k1"] = b"\x01\x02" * 50
    ambiente["k2"] = b"\x03\x04" * 50
    ses = Sessione({
        ("post", "/batch"): [Risposta({"id": "b1"})],
        ("post", "/batch/b1/requests"): [Risposta({})],
        ("post", "/batch/b1/finalize"): [Risposta({})],
        ("get", "/batch/b1"): [Risposta({"status": "FINALIZED", "requestTotal": 2}),
                               Risposta({"status": "COMPLETED", "requestTotal": 2,
                                         "requestCompleted": 2})],
        ("get", "/batch/b1/requests?offset=0&limit=50"): [Risposta({
            "requests": [riga("k2", b"\x03\x04" * 50), riga("k1")], "hasMore": False})],
    })
    conti = []
    esiti, scartate = voxcpm_tts.synthesize_batch(
        items(tmp_path, "k1", "k2"), VOCE, speed=0.9, session=ses, sleep=dormi,
        on_counts=lambda f, t: conti.append((f, t)))
    assert scartate == []
    assert [e["bytes"] for e in esiti] == [100, 100]
    assert (tmp_path / "k1.pcm").read_bytes() == b"\x01\x02" * 50
    assert (tmp_path / "k2.pcm").read_bytes() == b"\x03\x04" * 50
    assert esiti[0]["runpod"] == [{"exec_s": 60.0, "queue_s": 1.0, "worker": "w1",
                                   "gpu": "NVIDIA RTX PRO 6000 Blackwell MIG 1g.24gb"}]
    assert conti[-1] == (2, 2)
    assert ambiente == {}                              # intermedi cancellati
    # Il payload e' quello di `/run`, con link di upload da 7 giorni e la policy.
    inviati = [c[2] for c in ses.chiamate if c[1] == "/batch/b1/requests"][0]
    assert inviati[0]["input"]["action"] == "generate"
    assert inviati[0]["input"]["speed"] == 0.9
    assert inviati[0]["input"]["s3"]["put_url"].endswith(f"ttl={7 * 86400}")
    assert inviati[0]["policy"]["executionTimeout"] > 0


def test_cio_che_il_batch_non_consegna_torna_al_chiamante(tmp_path, ambiente):
    ambiente["k1"] = b"\x01\x02" * 50
    fallita = riga("k2", status="FAILED", output={})
    fallita["error"] = "handler crashed"
    silenzio = riga("k3")
    silenzio["output"]["failed_indices"] = [0]
    ses = Sessione({
        ("get", "/batch/b9"): [Risposta({"status": "COMPLETED"})],
        ("get", "/batch/b9/requests?offset=0&limit=50"): [Risposta({
            "requests": [riga("k1"), fallita, silenzio], "hasMore": False})],
    })
    esiti, scartate = voxcpm_tts.synthesize_batch(
        items(tmp_path, "k1", "k2", "k3"), VOCE, batch_id="b9", session=ses, sleep=dormi)
    assert esiti[0] is not None and esiti[1] is None and esiti[2] is None
    # La GPU spesa dai lotti persi resta nel conto.
    assert len(scartate) == 2
    # Ripreso un batch esistente: niente creato da capo.
    assert not [c for c in ses.chiamate if c[0] == "post"]


def test_un_batch_rimasto_in_bozza_si_cancella_e_si_ricrea(tmp_path, ambiente):
    ambiente["k1"] = b"\x01\x02" * 50
    ses = Sessione({
        ("get", "/batch/vecchio"): [Risposta({"status": "DRAFT"})],
        ("post", "/batch/vecchio/cancel"): [Risposta({})],
        ("post", "/batch"): [Risposta({"id": "nuovo"})],
        ("post", "/batch/nuovo/requests"): [Risposta({})],
        ("post", "/batch/nuovo/finalize"): [Risposta({})],
        ("get", "/batch/nuovo"): [Risposta({"status": "COMPLETED"})],
        ("get", "/batch/nuovo/requests?offset=0&limit=50"): [Risposta({
            "requests": [riga("k1")], "hasMore": False})],
    })
    salvati = []
    esiti, _ = voxcpm_tts.synthesize_batch(
        items(tmp_path, "k1"), VOCE, batch_id="vecchio", session=ses, sleep=dormi,
        on_batch_id=salvati.append)
    assert salvati == ["nuovo"]
    assert esiti[0]["bytes"] == 100


def test_l_annullamento_cancella_il_batch(tmp_path):
    ses = Sessione({("get", "/batch/b1"): [Risposta({"status": "FINALIZED"})],
                    ("post", "/batch/b1/cancel"): [Risposta({})]})
    letture = []
    with pytest.raises(voxcpm_tts.VoxcpmAnnullato):
        voxcpm_tts.synthesize_batch(
            items(tmp_path, "k1"), VOCE, batch_id="b1", session=ses, sleep=dormi,
            cancelled=lambda: len(letture) > 0,
            on_counts=lambda f, t: letture.append(f))
    assert ("post", "/batch/b1/cancel", None) in ses.chiamate


def test_oltre_il_tetto_si_cancella_e_si_raccoglie_quel_che_c_e(tmp_path, ambiente,
                                                                monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_BATCH_TIMEOUT_S", "60")
    ambiente["k1"] = b"\x01\x02" * 50
    orologio = iter([0.0, 30.0, 120.0, 130.0])
    ses = Sessione({
        ("get", "/batch/b1"): [Risposta({"status": "FINALIZED"})],
        ("post", "/batch/b1/cancel"): [Risposta({})],
        ("get", "/batch/b1/requests?offset=0&limit=50"): [Risposta({
            "requests": [riga("k1"), {"id": "r2", "status": "IN_QUEUE",
                                      "input": {"s3": {"key": "k2"}}}],
            "hasMore": False})],
    })
    esiti, _ = voxcpm_tts.synthesize_batch(
        items(tmp_path, "k1", "k2"), VOCE, batch_id="b1", session=ses, sleep=dormi,
        clock=lambda: next(orologio))
    assert esiti[0] is not None and esiti[1] is None
    assert ("post", "/batch/b1/cancel", None) in ses.chiamate


def test_le_pagine_dei_risultati_si_leggono_tutte():
    ses = Sessione({
        ("get", "/batch/b1/requests?offset=0&limit=50"): [Risposta({
            "requests": [{"id": i} for i in range(50)], "hasMore": True})],
        ("get", "/batch/b1/requests?offset=50&limit=50"): [Risposta({
            "requests": [{"id": 50}], "hasMore": False})],
    })
    assert len(list(voxcpm_tts.batch_requests("b1", session=ses, sleep=dormi))) == 51


def test_senza_r2_il_batch_non_parte(tmp_path, monkeypatch):
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    with pytest.raises(voxcpm_tts.VoxcpmUnavailable):
        voxcpm_tts.synthesize_batch(items(tmp_path, "k1"), VOCE, session=Sessione({}))


# --- dentro la pre-sintesi del libro -------------------------------------------

def blocco(testo, capitolo):
    return {"text": testo, "chapter_index": capitolo}


PIANO = [blocco("a", 0), blocco("b", 0), blocco("c", 1), blocco("d", 2)]


class FintoBatch:
    """Al posto di `synthesize_batch`: consegna i lotti tranne quelli in `persi`."""

    def __init__(self, persi=()):
        self.persi = set(persi)
        self.items = []
        self.kw = {}

    def __call__(self, items, voice_id, **kw):
        self.items, self.kw = items, kw
        kw["on_batch_id"]("b-42")
        esiti = []
        for it in items:
            if it["key"] in self.persi:
                esiti.append(None)
                continue
            pcm = b"".join(bytes([len(c)]) * 4 for c in it["chunks"])
            with open(it["dest"], "wb") as f:
                f.write(pcm)
            st = voxcpm_tts._stats_vuote()
            st.update(jobs=1, sample_rate=48000, bytes=len(pcm),
                      chunk_samples=[2] * len(it["chunks"]),
                      runpod=[{"exec_s": 50.0, "queue_s": 1.0, "worker": "wb", "gpu": ""}])
            esiti.append(st)
        return esiti, [{"exec_s": 7.0, "queue_s": 0.0, "worker": "wb", "gpu": ""}]


class FintaSintesi:
    def __init__(self):
        self.chiamate = []

    def __call__(self, chunks, voice_id, dest_path, **kw):
        self.chiamate.append(kw.get("key"))
        with open(dest_path, "wb") as f:
            f.write(b"\x09\x09" * len(chunks))
        st = voxcpm_tts._stats_vuote()
        st.update(jobs=1, sample_rate=48000, bytes=2 * len(chunks),
                  runpod=[{"exec_s": 30.0, "queue_s": 1.0, "worker": "wr", "gpu": ""}])
        return st


def test_la_pre_sintesi_in_batch_ripiega_su_run_per_i_lotti_persi(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_TRANSPORT", "batch")
    monkeypatch.setenv("ABM_VOXCPM_BATCH_CHARS", "2")      # lotti: [cap 0], [cap 1, cap 2]
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")
    monkeypatch.setattr(generation_engine.pending_jobs, "patch", lambda *a, **k: None)
    batch = FintoBatch(persi={"voxcpm/job-1/ch000000.pcm"})
    run = FintaSintesi()
    monkeypatch.setattr(voxcpm_tts, "synthesize_batch", batch)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", run)
    job = {}
    esiti = generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1",
                                               set(), job=job)
    assert [it["key"] for it in batch.items] == ["voxcpm/job-1/ch000000.pcm",
                                                "voxcpm/job-1/ch000001.pcm"]
    assert run.chiamate == ["voxcpm/job-1/ch000000.pcm"]   # solo il lotto perso
    assert job["voxcpm_batch_id"] == "b-42"
    # Il lotto perso rifatto via /run; quello di due capitoli ritagliato.
    leggi = lambda i: (tmp_path / f"chunk_{i:06d}.pcm").read_bytes()
    assert leggi(0) == b"		" * 2 and leggi(1) == b""
    assert leggi(2) == b"" * 4 and leggi(3) == b"" * 4
    assert not list(tmp_path.glob("lotto_*"))
    assert set(esiti) == {0, 1, 2, 3}
    # Nel conto: il lotto del batch, il lotto rifatto e la GPU dei persi.
    assert sorted(r["exec_s"] for r in job["voxcpm_actual"]["runpod"]) == [7.0, 30.0, 50.0]


def test_se_il_batch_non_parte_tutto_va_via_run(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_TRANSPORT", "batch")
    monkeypatch.setenv("ABM_VOXCPM_BATCH_CHARS", "0")
    monkeypatch.setenv("ABM_VOXCPM_JOBS", "1")

    def guasto(*a, **k):
        raise voxcpm_tts.VoxcpmUnavailable("R2 spento")
    run = FintaSintesi()
    monkeypatch.setattr(voxcpm_tts, "synthesize_batch", guasto)
    monkeypatch.setattr(voxcpm_tts, "synthesize_chapter", run)
    generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1", set(), job={})
    assert len(run.chiamate) == 3


def test_annullare_durante_il_batch_e_un_annullamento_del_job(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_TRANSPORT", "batch")

    def annullato(*a, **k):
        raise voxcpm_tts.VoxcpmAnnullato("batch annullato", "b1")
    monkeypatch.setattr(voxcpm_tts, "synthesize_batch", annullato)
    with pytest.raises(generation_engine._CancelledError):
        generation_engine._voxcpm_pre_pass(PIANO, VOCE, "+0%", tmp_path, "job-1", set(),
                                           job={})
