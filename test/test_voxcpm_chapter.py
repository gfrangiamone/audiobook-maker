"""Un capitolo intero: payload, trasporto dell'audio, politica di ritentativo.

`run_job` e' sostituito da un doppio che segue un copione di esiti. Cosi' il
test verifica LA POLITICA — quante volte si rifa', con che concorrenza, quando
si arrende — senza rifare le prove del ponte HTTP, che sono nel Task 6.
"""
import base64
import os

import pytest
import requests

import tts_split
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


@pytest.mark.parametrize("testo, atteso", [
    # Il caso del collaudo del 9/9/2026: VoxCPM leggeva «umano punto il».
    ("bisogno per un affare umano\u2026 il paragone e', il piu' delle volte",
     "bisogno per un affare umano, il paragone e', il piu' delle volte"),
    # Tre punti ASCII, anche spaziati, valgono come il carattere unico.
    ("aspetta ... vieni qui", "aspetta, vieni qui"),
    ("aspetta . . . vieni qui", "aspetta, vieni qui"),
    ("aspetta\u2026. vieni qui", "aspetta, vieni qui"),
    # Segue una frase nuova: la pausa resta un punto, non si incolla.
    ("Non lo so\u2026 Forse domani.", "Non lo so. Forse domani."),
    ("Erano in\u2026 3 o 4.", "Erano in. 3 o 4."),
    # Fine del chunk: punto.
    ("Non lo so\u2026", "Non lo so."),
    # Una virgoletta in mezzo non cambia il verdetto: conta la lettera.
    ("disse\u2026 \u00abvieni\u00bb", "disse, \u00abvieni\u00bb"),
    ("disse\u2026 \u00abVieni\u00bb", "disse. \u00abVieni\u00bb"),
    ("\u00abNon so\u2026\u00bb disse lei.", "\u00abNon so,\u00bb disse lei."),
    # In testa, o dopo un altro segno di chiusura, i puntini cadono.
    ("\u2026e poi niente", "e poi niente"),
    ("Ah!\u2026 poi niente", "Ah! poi niente"),
    ("Ecco, \u2026 poi niente", "Ecco, poi niente"),
    # Senza puntini il testo non si tocca, compreso un punto singolo.
    ("Prima frase. Seconda frase.", "Prima frase. Seconda frase."),
    ("", ""),
])
def test_normalizza_puntini(testo, atteso):
    assert voxcpm_tts.normalizza_puntini(testo) == atteso


def test_i_puntini_non_arrivano_al_worker(tmp_path, monkeypatch):
    finto = FintoRunJob(esito_ok())
    monkeypatch.setattr(voxcpm_tts, "run_job", finto)
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    voxcpm_tts.synthesize_chapter(
        ["per un affare umano\u2026 il paragone", "Non lo so\u2026"],
        VOCE, str(tmp_path / "cap.pcm"))
    assert finto.payload[0]["input"]["chunks"] == [
        "per un affare umano, il paragone", "Non lo so."]


# -- I puntini sul confine di chunk --------------------------------------
#
# split_text_into_chunks tratta i puntini come fine frase, quindi il taglio
# cade proprio li'. Se la normalizzazione gira sui chunk gia' spezzati non
# vede il seguito, legge "fine testo" e promuove i puntini a punto: pausa
# lunga in mezzo alla frase. Per questo _plan_chunks la applica prima.

CONFINE = (
    "Ma se paragoniamo la nostra attenzione, la serieta della nostra ricerca, "
    "il nostro desiderio di conoscere all'attenzione, alla serieta, al desiderio "
    "che portiamo nel trovare tale aiuto di cui abbiamo bisogno "
    "per un affare umano ... il paragone e, il piu delle volte, "
    "a favore dell'affare umano."
)


class FintoCapitolo:
    def __init__(self, testo):
        self.index = 0
        self.title = ""
        self.text = testo


class FintoLibro:
    def __init__(self, testo):
        self.chapters = [FintoCapitolo(testo)]


def pianifica(pre_split):
    """I chunk del capitolo CONFINE con un max_chars che taglia sui puntini."""
    plan = tts_split._plan_chunks(FintoLibro(CONFINE), max_chars=250,
                                  pre_split=pre_split)
    return [voce["text"] for voce in plan]


def test_senza_normalizzazione_a_monte_i_puntini_finiscono_a_fine_chunk():
    # Il difetto, riprodotto: il taglio cade sui puntini (che prepare_tts_text
    # ha gia' accostato alla parola precedente)...
    chunks = pianifica(None)
    assert chunks[0].endswith("per un affare umano...")
    assert chunks[1].startswith("il paragone e,")
    # ...e normalizzando chunk per chunk diventano un punto fermo.
    assert voxcpm_tts.normalizza_puntini(chunks[0]).endswith("affare umano.")


def test_i_puntini_sul_confine_di_chunk_restano_una_virgola():
    chunks = pianifica(tts_split._pick_pre_split(VOCE))
    assert "affare umano, il paragone" in " ".join(chunks)
    # Nessun chunk finisce coi puntini, e nessun chunk che non sia l'ultimo
    # chiude la frase spezzata a meta'.
    assert not any(c.rstrip().endswith("...") for c in chunks)
    assert not any(c.rstrip().endswith("affare umano.") for c in chunks[:-1])


def test_la_normalizzazione_a_monte_e_solo_di_voxcpm():
    assert tts_split._pick_pre_split(VOCE) is voxcpm_tts.normalizza_puntini
    assert tts_split._pick_pre_split("it-IT-ElsaNeural") is None
    assert tts_split._pick_pre_split("") is None


def test_prompt_text_e_la_trascrizione_esatta(tmp_path, monkeypatch):
    finto = FintoRunJob(esito_ok())
    sintetizza(finto, tmp_path, monkeypatch)
    atteso = voxcpm_catalog.parse_voice_id(VOCE)["transcript"]
    assert finto.payload[0]["input"]["prompt_text"] == atteso
    assert atteso    # senza, il canale che porta l'identita' resterebbe vuoto


def test_il_payload_dice_al_worker_che_lingua_legge(tmp_path, monkeypatch):
    # La verifica delle code gira sul worker, sulla sua CPU. Senza questo
    # campo l'ASR indovina la lingua da quattro secondi d'audio e sbaglia
    # piu' spesso, e i falsi sospetti si pagano in GPU rigenerata.
    finto = FintoRunJob(esito_ok())
    sintetizza(finto, tmp_path, monkeypatch)
    assert finto.payload[0]["input"]["language"] == "it"


def test_code_tagliate_dal_worker_nelle_misure(tmp_path, monkeypatch):
    # Il worker le ha gia' ritentate e ha consegnato lo stesso: il capitolo
    # c'e', ma con delle frasi finite a meta'. Questo numero e' l'unica
    # traccia che ne resta.
    finto = FintoRunJob(esito_ok(chunks_difettosi=[0, 2]))
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert stats["code_tagliate"] == 2


def test_senza_verifica_le_code_tagliate_sono_zero(tmp_path, monkeypatch):
    # Un endpoint con la verifica spenta non manda il campo: e' zero, non un
    # errore.
    finto = FintoRunJob(esito_ok())
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert stats["code_tagliate"] == 0


def test_code_tagliate_solo_del_tentativo_consegnato(tmp_path, monkeypatch):
    # Il primo tentativo si butta per i chunk a silenzio: le sue code non
    # stanno nell'audio consegnato, e sommarle direbbe che il capitolo e'
    # messo peggio di com'e'.
    finto = FintoRunJob(
        esito_ok(failed_indices=[1], chunks_difettosi=[0, 1, 2]),
        esito_ok(chunks_difettosi=[2]))
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert stats["code_tagliate"] == 1


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
    # Il budget e' BOUNCE_RETRIES ritentativi oltre al primo tentativo vero.
    assert len(finto.payload) == voxcpm_tts.BOUNCE_RETRIES + 1


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
    # Il budget e' SILENCE_RETRIES ritentativi oltre al primo tentativo vero.
    assert len(finto.payload) == voxcpm_tts.SILENCE_RETRIES + 1


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
    # failed_indices presente e vuoto: il worker rispetta il protocollo, ha
    # solo caricato zero byte su R2.
    finto = FintoRunJob({"s3": {"bytes": 0}, "sample_rate": 48000,
                        "failed_indices": []},
                        {"s3": {"bytes": 0}, "sample_rate": 48000,
                        "failed_indices": []},
                        {"s3": {"bytes": 0}, "sample_rate": 48000,
                        "failed_indices": []})
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


def test_capitolo_senza_chunk_e_un_errore(tmp_path, monkeypatch):
    finto = FintoRunJob()
    monkeypatch.setattr(voxcpm_tts, "run_job", finto)
    with pytest.raises(ValueError):
        voxcpm_tts.synthesize_chapter([], VOCE, str(tmp_path / "x.pcm"))
    assert finto.payload == []


def test_risposta_senza_failed_indices_e_un_errore_di_protocollo(tmp_path, monkeypatch):
    # Assente e zero non sono la stessa cosa: un worker che non dichiara
    # affatto i chunk caduti non ha rispettato il protocollo, e il capitolo
    # non si consegna sulla fiducia.
    finto = FintoRunJob({"audio_b64": base64.b64encode(b"\x00" * 4).decode(),
                         "sample_rate": 48000})
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        sintetizza(finto, tmp_path, monkeypatch)
    assert "failed_indices" in str(e.value)


def test_le_statistiche_vengono_dal_tentativo_consegnato(tmp_path, monkeypatch):
    # Un chunk a silenzio nel primo tentativo non deve sommarsi al secondo:
    # i caratteri e i secondi d'audio del capitolo sono quelli del tentativo
    # consegnato, non la somma coi tentativi scartati. I secondi di GPU
    # invece si pagano anche sul tentativo buttato via, e quelli si sommano.
    scartato = esito_ok(chars=100, audio_seconds=5.0, tts_seconds=2.0,
                        failed_indices=[1])
    consegnato = esito_ok(chars=42, audio_seconds=3.0, tts_seconds=1.0)
    finto = FintoRunJob(scartato, consegnato)
    stats, _ = sintetizza(finto, tmp_path, monkeypatch)
    assert stats["chars"] == 42
    assert stats["audio_seconds"] == 3.0
    assert stats["tts_seconds"] == 3.0


def test_scarica_traduce_un_fallimento_di_rete_in_errore_di_dominio(tmp_path, monkeypatch):
    # `_scarica` e' il trasporto: chi la chiama (`_consegna`) e chi chiama
    # lui (`synthesize_chapter`) devono vedere solo VoxcpmJobError, mai
    # requests.HTTPError.
    class RispostaRotta:
        def raise_for_status(self):
            raise requests.HTTPError("500 Server Error")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def iter_content(self, chunk_size):
            return iter(())

    monkeypatch.setattr(voxcpm_tts.requests, "get",
                        lambda *a, **kw: RispostaRotta())
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    dest = str(tmp_path / "cap.pcm")
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        voxcpm_tts._scarica("https://r2.esempio/x?firma", dest)
    # Il .part parziale non deve restare in giro dopo un fallimento.
    assert not os.path.exists(dest + ".part")


class _RispostaGet:
    """Una GET finta: o consegna `corpo`, o fallisce come `errore` dice."""

    def __init__(self, corpo=b"", errore=None):
        self.corpo = corpo
        self.errore = errore

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def raise_for_status(self):
        if isinstance(self.errore, requests.HTTPError):
            raise self.errore

    def iter_content(self, chunk_size):
        yield self.corpo[:2]
        if self.errore is not None:
            # La connessione cade a meta' corpo: e' esattamente il caso
            # del 2026-09-08 (ChunkedEncodingError al capitolo 247/250).
            raise self.errore
        yield self.corpo[2:]


def _get_a_sequenza(monkeypatch, risposte):
    """`requests.get` che consegna `risposte` una per chiamata e le conta."""
    chiamate = []
    coda = list(risposte)

    def get(url, **kw):
        chiamate.append(url)
        return coda.pop(0)

    monkeypatch.setattr(voxcpm_tts.requests, "get", get)
    return chiamate


def _http_error(codice):
    r = requests.Response()
    r.status_code = codice
    return requests.HTTPError(f"{codice}", response=r)


def test_scarica_ritenta_una_connessione_caduta_a_meta(tmp_path, monkeypatch):
    # Due cadute a meta' corpo e poi la consegna: il file arriva intero, con
    # una pausa che raddoppia fra un tentativo e l'altro, e nessun .part
    # sopravvive ai tentativi falliti.
    pause = []
    monkeypatch.setattr(voxcpm_tts, "_dormi", pause.append)
    chiamate = _get_a_sequenza(monkeypatch, [
        _RispostaGet(b"abcd", requests.exceptions.ChunkedEncodingError("x")),
        _RispostaGet(b"abcd", requests.exceptions.ConnectionError("y")),
        _RispostaGet(b"abcd"),
    ])
    dest = str(tmp_path / "cap.pcm")
    voxcpm_tts._scarica("https://r2.esempio/x?firma", dest)
    assert open(dest, "rb").read() == b"abcd"
    assert len(chiamate) == 3
    assert pause == [2.0, 4.0]
    assert not os.path.exists(dest + ".part")


def test_scarica_insiste_fino_a_dieci_volte_con_pausa_a_tetto(tmp_path, monkeypatch):
    # Un guasto lungo (R2 o la rete giu' per qualche minuto): nove cadute e
    # poi la consegna. La pausa raddoppia fino a 60 s e li' si ferma, per un
    # totale di circa cinque minuti: ben sotto la validita' della GET firmata.
    pause = []
    monkeypatch.setattr(voxcpm_tts, "_dormi", pause.append)
    chiamate = _get_a_sequenza(monkeypatch, [
        _RispostaGet(b"abcd", requests.exceptions.ConnectionError("giu'"))
        for _ in range(9)
    ] + [_RispostaGet(b"abcd")])
    dest = str(tmp_path / "cap.pcm")
    voxcpm_tts._scarica("https://r2.esempio/x?firma", dest)
    assert open(dest, "rb").read() == b"abcd"
    assert len(chiamate) == 10 == voxcpm_tts._SCARICA_TENTATIVI
    assert pause == [2.0, 4.0, 8.0, 16.0, 32.0, 60.0, 60.0, 60.0, 60.0]
    assert sum(pause) < 6 * 60


def test_scarica_si_arrende_dopo_i_tentativi(tmp_path, monkeypatch):
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    chiamate = _get_a_sequenza(monkeypatch, [
        _RispostaGet(b"abcd", requests.exceptions.ChunkedEncodingError("x"))
        for _ in range(voxcpm_tts._SCARICA_TENTATIVI)
    ])
    dest = str(tmp_path / "cap.pcm")
    with pytest.raises(voxcpm_tts.VoxcpmConsegnaFallita) as e:
        voxcpm_tts._scarica("https://r2.esempio/x?firma", dest)
    assert "ChunkedEncodingError" in str(e.value)
    assert e.value.ritentabile
    assert len(chiamate) == voxcpm_tts._SCARICA_TENTATIVI
    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")


def test_scarica_non_ritenta_un_4xx(tmp_path, monkeypatch):
    # Una firma scaduta o una chiave assente non passano da sole: un solo
    # tentativo e il verdetto subito, senza pause.
    pause = []
    monkeypatch.setattr(voxcpm_tts, "_dormi", pause.append)
    chiamate = _get_a_sequenza(monkeypatch, [
        _RispostaGet(b"", _http_error(403)), _RispostaGet(b"abcd")])
    dest = str(tmp_path / "cap.pcm")
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        voxcpm_tts._scarica("https://r2.esempio/x?firma", dest)
    assert "HTTP 403" in str(e.value)
    assert len(chiamate) == 1
    assert pause == []


def test_scarica_ritenta_un_5xx(tmp_path, monkeypatch):
    monkeypatch.setattr(voxcpm_tts, "_dormi", lambda _s: None)
    chiamate = _get_a_sequenza(monkeypatch, [
        _RispostaGet(b"", _http_error(503)), _RispostaGet(b"abcd")])
    dest = str(tmp_path / "cap.pcm")
    voxcpm_tts._scarica("https://r2.esempio/x?firma", dest)
    assert open(dest, "rb").read() == b"abcd"
    assert len(chiamate) == 2


def test_download_r2_troncato_e_un_errore(tmp_path, monkeypatch):
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: "https://r2.esempio/x?firma")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, download_name=None, ttl=None: "https://r2.esempio/x?get")
    cancellate = []
    monkeypatch.setattr(storage_backend, "delete_object", cancellate.append)
    # Il worker dichiara 64 byte caricati, ma il download ne consegna solo
    # 32: un troncamento silenzioso scriverebbe un capitolo corto senza che
    # nulla a valle se ne accorga.
    monkeypatch.setattr(voxcpm_tts, "_scarica",
                        lambda url, dest: open(dest, "wb").write(b"\x07" * 32) and None)
    esito = {"s3": {"bytes": 64}, "sample_rate": 48000, "chars": 9,
             "audio_seconds": 1.0, "tts_seconds": 0.5, "failed_indices": []}
    finto = FintoRunJob(*[dict(esito)
                          for _ in range(voxcpm_tts.DELIVERY_RETRIES + 1)])
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    assert "troncat" in str(e.value).lower()
    # Un troncamento e' un guasto del trasporto: il capitolo si risottomette
    # prima di arrendersi, e l'intermedio si cancella a ogni giro, perche'
    # il download parziale non lo salva.
    assert len(finto.payload) == voxcpm_tts.DELIVERY_RETRIES + 1
    assert cancellate == ["voxcpm/j/ch1.pcm"] * (voxcpm_tts.DELIVERY_RETRIES + 1)


def test_consegna_fallita_risottomette_il_capitolo(tmp_path, monkeypatch):
    # L'8/9/2026 un download caduto al capitolo 247 di 250 ha ucciso il job:
    # la sintesi era riuscita, era l'audio a non essere arrivato. Ora il
    # capitolo si rifa' a concorrenza invariata (la GPU non c'entra) e il
    # libro non si perde.
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: "https://r2.esempio/x?firma")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, download_name=None, ttl=None: "https://r2.esempio/x?get")
    cancellate = []
    monkeypatch.setattr(storage_backend, "delete_object", cancellate.append)
    giri = []

    def scarica(url, dest):
        giri.append(url)
        if len(giri) == 1:
            raise voxcpm_tts.VoxcpmConsegnaFallita(
                "scaricamento del capitolo da R2 fallito: ChunkedEncodingError")
        with open(dest, "wb") as f:
            f.write(b"\x07" * 64)

    monkeypatch.setattr(voxcpm_tts, "_scarica", scarica)
    esito = {"s3": {"bytes": 64}, "sample_rate": 48000, "chars": 9,
             "audio_seconds": 1.0, "tts_seconds": 0.5, "failed_indices": []}
    finto = FintoRunJob(dict(esito), dict(esito))
    stats, dest = sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    assert os.path.getsize(dest) == 64
    assert len(finto.payload) == 2
    assert [p["input"]["concurrency"] for p in finto.payload] == [32, 32]
    assert stats["redone"] == 1
    assert stats["jobs"] == 2
    # La GPU si e' pagata due volte: entrambi i giri stanno nel conto.
    assert stats["tts_seconds"] == 1.0
    assert cancellate == ["voxcpm/j/ch1.pcm"] * 2


def test_consegna_fallita_a_oltranza_perde_il_capitolo(tmp_path, monkeypatch):
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: "https://r2.esempio/x?firma")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, download_name=None, ttl=None: "https://r2.esempio/x?get")
    monkeypatch.setattr(storage_backend, "delete_object", lambda k: None)

    def scarica_rotto(url, dest):
        raise voxcpm_tts.VoxcpmConsegnaFallita(
            "scaricamento del capitolo da R2 fallito: ConnectionError")

    monkeypatch.setattr(voxcpm_tts, "_scarica", scarica_rotto)
    esito = {"s3": {"bytes": 64}, "sample_rate": 48000, "chars": 9,
             "audio_seconds": 1.0, "tts_seconds": 0.5, "failed_indices": []}
    finto = FintoRunJob(*[dict(esito)
                          for _ in range(voxcpm_tts.DELIVERY_RETRIES + 1)])
    with pytest.raises(voxcpm_tts.VoxcpmConsegnaFallita) as e:
        sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    assert "ConnectionError" in str(e.value)
    assert len(finto.payload) == voxcpm_tts.DELIVERY_RETRIES + 1
    assert not os.path.exists(str(tmp_path / "cap.pcm"))


def test_download_r2_fallito_cancella_comunque_l_intermedio(tmp_path, monkeypatch):
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: "https://r2.esempio/x?firma")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, download_name=None, ttl=None: "https://r2.esempio/x?get")
    cancellate = []
    monkeypatch.setattr(storage_backend, "delete_object", cancellate.append)

    def scarica_rotto(url, dest):
        raise voxcpm_tts.VoxcpmJobError("scaricamento del capitolo da R2 fallito")

    monkeypatch.setattr(voxcpm_tts, "_scarica", scarica_rotto)
    finto = FintoRunJob({"s3": {"bytes": 64}, "sample_rate": 48000, "chars": 9,
                         "audio_seconds": 1.0, "tts_seconds": 0.5,
                         "failed_indices": []})
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    # L'intermedio e' gia' su R2 anche se il download e' fallito: lasciarlo
    # li' sarebbe pagare storage per un file che nessuno riprova a scaricare
    # con questa stessa chiave.
    assert cancellate == ["voxcpm/j/ch1.pcm"]


def test_cancellazione_r2_fallita_non_perde_il_capitolo(tmp_path, monkeypatch):
    # Il capitolo e' gia' scritto su disco quando la cancellazione fallisce:
    # buttare via il risultato per un bucket irraggiungibile sarebbe perdere
    # lavoro buono per un problema di pulizia.
    import storage_backend
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "presigned_put_url",
                        lambda key, ttl=None: "https://r2.esempio/x?firma")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda key, download_name=None, ttl=None: "https://r2.esempio/x?get")

    def rotta(k):
        raise RuntimeError("bucket irraggiungibile")

    monkeypatch.setattr(storage_backend, "delete_object", rotta)
    monkeypatch.setattr(voxcpm_tts, "_scarica",
                        lambda url, dest: open(dest, "wb").write(b"\x07" * 64) and None)
    finto = FintoRunJob({"s3": {"bytes": 64}, "sample_rate": 48000, "chars": 9,
                         "audio_seconds": 1.0, "tts_seconds": 0.5,
                         "failed_indices": []})
    stats, dest = sintetizza(finto, tmp_path, monkeypatch, key="voxcpm/j/ch1.pcm")
    assert os.path.getsize(dest) == 64
    assert stats["bytes"] == 64


def test_invalidare_il_catalogo_svuota_la_cache_dei_campioni(tmp_path, monkeypatch):
    # La cache dei campioni vive in voxcpm_tts, ma la sorgente di verita' e'
    # il catalogo: se qualcuno rigenera le voci e invalida il catalogo (o
    # sposta ABM_VOXCPM_CATALOG_DIR su una cartella nuova), la cache deve
    # seguirlo, non restare con il wav della cartella precedente.
    letture = {"n": 0}
    vero = voxcpm_catalog.sample_path

    def conta(vid):
        letture["n"] += 1
        return vero(vid)

    monkeypatch.setattr(voxcpm_catalog, "sample_path", conta)
    voxcpm_tts.clone_block(VOCE)
    assert letture["n"] == 1
    assert voxcpm_tts._clone_cache

    monkeypatch.setenv("ABM_VOXCPM_CATALOG_DIR", FIXTURE)
    voxcpm_catalog.invalidate_cache()
    assert not voxcpm_tts._clone_cache

    voxcpm_tts.clone_block(VOCE)
    assert letture["n"] == 2
