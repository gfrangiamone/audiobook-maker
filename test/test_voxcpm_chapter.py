"""Un capitolo intero: payload, trasporto dell'audio, politica di ritentativo.

`run_job` e' sostituito da un doppio che segue un copione di esiti. Cosi' il
test verifica LA POLITICA — quante volte si rifa', con che concorrenza, quando
si arrende — senza rifare le prove del ponte HTTP, che sono nel Task 6.
"""
import base64
import os

import pytest

import voxcpm_catalog
import voxcpm_tts

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "voxcpm_catalog")
VOCE = "voxcpm:v2:it-IT/Stefano"
CHUNKS = ["Prima frase.", "Seconda frase.", "Terza frase."]


@pytest.fixture(autouse=True)
def catalogo_e_endpoint(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "32")
    # R2 spento: il percorso inline e' quello collaudabile senza credenziali.
    monkeypatch.delenv("ABM_S3_BUCKET", raising=False)
    voxcpm_catalog.invalidate_cache()
    voxcpm_tts.invalidate_clone_cache()


def esito_ok(pcm=b"\x01\x02" * 100, **extra):
    d = {"audio_b64": base64.b64encode(pcm).decode("ascii"),
         "sample_rate": 48000, "chars": 42, "audio_seconds": 3.0,
         "tts_seconds": 1.0, "failed_indices": []}
    d.update(extra)
    return d


class FintoRunJob:
    """Segue un copione di esiti; annota i payload che ha ricevuto."""

    def __init__(self, *esiti):
        self.esiti = list(esiti)
        self.payload = []
        self.attese = []

    def __call__(self, payload, **kw):
        self.payload.append(payload)
        if not self.esiti:
            raise AssertionError("job non previsto dal copione")
        e = self.esiti.pop(0)
        if isinstance(e, Exception):
            raise e
        return e


def sintetizza(finto, tmp_path, monkeypatch, **kw):
    monkeypatch.setattr(voxcpm_tts, "run_job", finto)
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    dest = str(tmp_path / "cap.pcm")
    return voxcpm_tts.synthesize_chapter(CHUNKS, VOCE, dest, **kw), dest


def test_il_payload_e_in_hifi_con_prefisso_e_trascrizione(tmp_path, monkeypatch):
    finto = FintoRunJob(esito_ok())
    sintetizza(finto, tmp_path, monkeypatch)
    inp = finto.payload[0]["input"]
    assert inp["action"] == "generate"
    assert inp["chunks"] == CHUNKS
    assert inp["output_format"] == "pcm"
    assert inp["concurrency"] == 32
    assert inp["cfg"] == voxcpm_tts.CFG_READ
    # hifi: il prefisso porta l'identita', il riferimento l'accompagna.
    assert inp["prompt_format"] == "wav"
    assert inp["reference_format"] == "wav"
    assert base64.b64decode(inp["prompt_wav_b64"])[:4] == b"RIFF"
    assert base64.b64decode(inp["reference_wav_b64"])[:4] == b"RIFF"


def test_prompt_text_e_la_trascrizione_esatta(tmp_path, monkeypatch):
    finto = FintoRunJob(esito_ok())
    sintetizza(finto, tmp_path, monkeypatch)
    atteso = voxcpm_catalog.parse_voice_id(VOCE)["transcript"]
    assert finto.payload[0]["input"]["prompt_text"] == atteso
    assert atteso    # senza, il canale che porta l'identita' resterebbe vuoto


def test_l_audio_finisce_nel_file(tmp_path, monkeypatch):
    finto = FintoRunJob(esito_ok(pcm=b"\xaa\xbb" * 50))
    stats, dest = sintetizza(finto, tmp_path, monkeypatch)
    with open(dest, "rb") as f:
        assert f.read() == b"\xaa\xbb" * 50
    assert stats["sample_rate"] == 48000
    assert stats["jobs"] == 1
    assert stats["redone"] == 0


def test_il_wav_della_voce_si_codifica_una_volta_sola(tmp_path, monkeypatch):
    # Rileggere e ricodificare in base64 lo stesso file a ogni capitolo e'
    # lavoro ripetuto su un dato che non cambia: su un libro da 40 capitoli
    # sono 40 letture identiche.
    finto = FintoRunJob(esito_ok(), esito_ok())
    monkeypatch.setattr(voxcpm_tts, "run_job", finto)
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    letture = {"n": 0}
    vero = voxcpm_catalog.sample_path

    def conta(vid):
        letture["n"] += 1
        return vero(vid)

    monkeypatch.setattr(voxcpm_catalog, "sample_path", conta)
    voxcpm_tts.synthesize_chapter(CHUNKS, VOCE, str(tmp_path / "a.pcm"))
    voxcpm_tts.synthesize_chapter(CHUNKS, VOCE, str(tmp_path / "b.pcm"))
    assert letture["n"] == 1


def test_rimbalzo_si_rifa_uguale(tmp_path, monkeypatch):
    # Il worker non ha nemmeno acceso la GPU: stringere il batch curerebbe una
    # malattia che non c'e'. Stessa concorrenza, e i tentativi veri non si
    # consumano.
    finto = FintoRunJob(
        voxcpm_tts.VoxcpmRimbalzato("worker in spegnimento", "j1"),
        esito_ok())
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert [p["input"]["concurrency"] for p in finto.payload] == [32, 32]
    assert stats["bounced"] == 1
    assert stats["redone"] == 0


def test_rimbalzi_a_oltranza_si_arrendono(tmp_path, monkeypatch):
    troppi = [voxcpm_tts.VoxcpmRimbalzato("in spegnimento", "j")
              for _ in range(voxcpm_tts.BOUNCE_RETRIES + 2)]
    finto = FintoRunJob(*troppi)
    with pytest.raises(voxcpm_tts.VoxcpmRimbalzato):
        sintetizza(finto, tmp_path, monkeypatch)


def test_motore_compromesso_si_rifa_a_batch_stretto(tmp_path, monkeypatch):
    finto = FintoRunJob(
        voxcpm_tts.VoxcpmMotoreCompromesso("motore compromesso", "j2"),
        esito_ok())
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert [p["input"]["concurrency"] for p in finto.payload] == [32, 8]
    assert stats["redone"] == 1


def test_chunk_a_silenzio_buttano_il_capitolo(tmp_path, monkeypatch):
    # Il worker consegna audio "buono": e' proprio il caso pericoloso, perche'
    # a valle passerebbe ogni verifica. Il silenzio va riconosciuto qui.
    finto = FintoRunJob(esito_ok(failed_indices=[1]), esito_ok())
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert [p["input"]["concurrency"] for p in finto.payload] == [32, 8]
    assert stats["redone"] == 1
    assert stats["failed_chunks"] == 0


def test_silenzio_ostinato_e_un_fallimento(tmp_path, monkeypatch):
    finto = FintoRunJob(*[esito_ok(failed_indices=[1])
                          for _ in range(voxcpm_tts.SILENCE_RETRIES + 1)])
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        sintetizza(finto, tmp_path, monkeypatch)
    assert "silenzio" in str(e.value)


def test_la_concorrenza_non_scende_sotto_quattro(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_CONCURRENCY", "8")
    finto = FintoRunJob(esito_ok(failed_indices=[0]),
                        esito_ok(failed_indices=[0]),
                        esito_ok())
    sintetizza(finto, tmp_path, monkeypatch)
    assert [p["input"]["concurrency"] for p in finto.payload] == [8, 4, 4]


def test_coda_satura_non_si_ritenta(tmp_path, monkeypatch):
    # L'unica riga non ritentabile della tabella §9.4: un secondo tentativo
    # sarebbe un'altra accensione pagata per rimettersi nella stessa fila.
    finto = FintoRunJob(voxcpm_tts.VoxcpmCodaSatura("endpoint saturo", "j3"))
    with pytest.raises(voxcpm_tts.VoxcpmCodaSatura):
        sintetizza(finto, tmp_path, monkeypatch)
    assert len(finto.payload) == 1


def test_con_r2_acceso_l_audio_passa_dalla_put_firmata(tmp_path, monkeypatch):
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: f"https://r2.esempio/{key}?firma")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, download_name=None, ttl=None: f"https://r2.esempio/{key}?get")
    cancellate = []
    monkeypatch.setattr(storage_backend, "delete_object", cancellate.append)
    monkeypatch.setattr(voxcpm_tts, "_scarica",
                        lambda url, dest: open(dest, "wb").write(b"\x07" * 64) and None)
    finto = FintoRunJob({"s3": {"bytes": 64}, "sample_rate": 48000, "chars": 9,
                         "audio_seconds": 1.0, "tts_seconds": 0.5,
                         "failed_indices": []})
    stats, dest = sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    inp = finto.payload[0]["input"]
    assert inp["s3"]["put_url"].startswith("https://r2.esempio/")
    assert inp["s3"]["key"] == "voxcpm/j/ch1.pcm"
    assert os.path.getsize(dest) == 64
    # L'oggetto su R2 e' un intermedio: tenerlo sarebbe pagare storage per un
    # file che il server ha gia' scaricato.
    assert cancellate == ["voxcpm/j/ch1.pcm"]


def test_r2_acceso_ma_il_worker_non_carica_niente(tmp_path, monkeypatch):
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: "https://r2.esempio/x?firma")
    monkeypatch.setattr(storage_backend, "delete_object", lambda k: None)
    finto = FintoRunJob({"s3": {"bytes": 0}, "sample_rate": 48000},
                        {"s3": {"bytes": 0}, "sample_rate": 48000},
                        {"s3": {"bytes": 0}, "sample_rate": 48000})
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    assert "non ha caricato" in str(e.value)


def test_annullamento_prima_di_accendere(tmp_path, monkeypatch):
    # Un job cancellato dall'utente non deve accendere altra GPU: si controlla
    # PRIMA di sottomettere, che e' il momento in cui la spesa comincia.
    finto = FintoRunJob()
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        sintetizza(finto, tmp_path, monkeypatch, cancelled=lambda: True)
    assert finto.payload == []
    assert "annullato" in str(e.value)


def test_voce_sparita_dal_catalogo(tmp_path, monkeypatch):
    finto = FintoRunJob()
    monkeypatch.setattr(voxcpm_tts, "run_job", finto)
    with pytest.raises(ValueError):
        voxcpm_tts.synthesize_chapter(CHUNKS, "voxcpm:v2:it-IT/Fantasma",
                                      str(tmp_path / "x.pcm"))
    assert finto.payload == []
