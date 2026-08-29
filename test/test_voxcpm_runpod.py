"""Il ponte HTTP verso l'endpoint RunPod, con un doppio al posto della rete.

Il doppio e' una sessione finta che risponde da un copione: `post` e `get`
tirano fuori la prossima risposta preparata e annotano com'erano state
chiamate. Niente monkeypatch di `requests`, cosi' il test verifica il
contratto (che URL, che header, che corpo) e non l'implementazione.
"""
import json

import pytest

import voxcpm_tts


class FintaRisposta:
    def __init__(self, status_code=200, body=None, text=""):
        self.status_code = status_code
        self._body = body if body is not None else {}
        self.text = text or json.dumps(self._body)

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise voxcpm_tts.requests.RequestException(f"HTTP {self.status_code}")


class FintaSessione:
    """Risponde dal copione e tiene il registro delle chiamate."""

    def __init__(self, post=None, get=None):
        self.copione_post = list(post or [])
        self.copione_get = list(get or [])
        self.post_fatte = []
        self.get_fatte = []

    def post(self, url, headers=None, json=None, timeout=None):
        self.post_fatte.append({"url": url, "headers": headers, "json": json})
        if not self.copione_post:
            raise AssertionError(f"POST non previsto: {url}")
        r = self.copione_post.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def get(self, url, headers=None, timeout=None):
        self.get_fatte.append({"url": url, "headers": headers})
        if not self.copione_get:
            raise AssertionError(f"GET non previsto: {url}")
        r = self.copione_get.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture(autouse=True)
def endpoint_configurato(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "ep-di-prova")
    monkeypatch.setenv("ABM_VOXCPM_API_KEY", "chiave-di-prova")


def dormi_finto(_secondi):
    """Sostituisce time.sleep: i test del backoff non devono durare come lui."""
    return None


def test_run_job_sottomette_e_raccoglie():
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "IN_QUEUE"}),
             FintaRisposta(body={"status": "IN_PROGRESS"}),
             FintaRisposta(body={"status": "COMPLETED",
                                 "output": {"audio_seconds": 12.0}})],
    )
    out = voxcpm_tts.run_job({"input": {"action": "generate"}},
                             session=ses, sleep=dormi_finto, poll=0)
    assert out == {"audio_seconds": 12.0}
    assert ses.post_fatte[0]["url"] == "https://api.runpod.ai/v2/ep-di-prova/run"
    assert ses.get_fatte[0]["url"] == "https://api.runpod.ai/v2/ep-di-prova/status/job-1"


def test_non_usa_mai_runsync():
    # /runsync risponde 200 senza output quando il job supera la finestra
    # della richiesta, e il job continua a essere fatturato senza che nessuno
    # ne raccolga il risultato. Il primo job di una sessione la supera sempre.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "COMPLETED", "output": {}})],
    )
    voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert all("runsync" not in c["url"] for c in ses.post_fatte)


def test_la_chiave_viaggia_nell_header_e_non_nel_corpo():
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-1"})],
        get=[FintaRisposta(body={"status": "COMPLETED", "output": {}})],
    )
    voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    head = ses.post_fatte[0]["headers"]
    assert head["Authorization"] == "Bearer chiave-di-prova"
    assert "chiave-di-prova" not in json.dumps(ses.post_fatte[0]["json"])


def test_submit_ritenta_sui_transitori():
    ses = FintaSessione(
        post=[FintaRisposta(status_code=503, text="scaling"),
              FintaRisposta(body={"id": "job-2"})],
        get=[FintaRisposta(body={"status": "COMPLETED", "output": {"ok": 1}})],
    )
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert out == {"ok": 1}
    assert len(ses.post_fatte) == 2


def test_submit_non_ritenta_sugli_errori_definitivi():
    # 401 non migliora riprovando: la chiave sbagliata resta sbagliata.
    ses = FintaSessione(post=[FintaRisposta(status_code=401, text="unauthorized")])
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert "401" in str(e.value)
    assert len(ses.post_fatte) == 1


def test_rimbalzo_riconosciuto_dal_job_fallito():
    # Il worker che respinge risponde con `error`, quindi RunPod marca FAILED:
    # il rimbalzo va riconosciuto QUI, non dove si legge un output riuscito.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-3"})],
        get=[FintaRisposta(body={
            "status": "FAILED",
            "output": {"error": "worker in spegnimento, rilanciare il job",
                       "engine_dead": True, "bounced": True}})],
    )
    with pytest.raises(voxcpm_tts.VoxcpmRimbalzato) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert e.value.ritentabile is True
    assert e.value.job_id == "job-3"


def test_rimbalzo_riconosciuto_anche_senza_il_campo_bounced():
    # `bounced` esiste solo dalle immagini nuove: il testo resta il criterio
    # di riserva, se no un endpoint vecchio scambia i rimbalzi per guasti.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-4"})],
        get=[FintaRisposta(body={
            "status": "FAILED",
            "output": {"error": "worker in spegnimento", "engine_dead": True}})],
    )
    with pytest.raises(voxcpm_tts.VoxcpmRimbalzato):
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)


def test_motore_compromesso_non_e_un_rimbalzo():
    # Il guasto vero: si ritenta, ma stringendo il batch. Confonderlo col
    # rimbalzo e' l'errore che costo' dieci job su tredici (§9.3).
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-5"})],
        get=[FintaRisposta(body={
            "status": "FAILED",
            "output": {"error": "motore compromesso: il worker si spegne",
                       "engine_dead": True, "failed_indices": [2, 3]}})],
    )
    with pytest.raises(voxcpm_tts.VoxcpmMotoreCompromesso) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert not isinstance(e.value, voxcpm_tts.VoxcpmRimbalzato)
    assert e.value.ritentabile is True


def test_errore_nell_output_di_un_job_completato():
    # Il worker puo' consegnare COMPLETED con `error` dentro: e' il caso
    # dell'upload fallito. Non e' audio, quindi non e' un successo.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-6"})],
        get=[FintaRisposta(body={"status": "COMPLETED",
                                 "output": {"error": "upload su presigned PUT fallito"}})],
    )
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert "upload" in str(e.value)


def test_coda_satura_non_e_ritentabile():
    # Mai passato per IN_PROGRESS entro il tetto di coda: l'endpoint e' saturo,
    # non lento. Rimettersi in fila non aiuta nessuno.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-7"})],
        get=[FintaRisposta(body={"status": "IN_QUEUE"}) for _ in range(50)],
        # il cancel a fine attesa
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))
    orologio = iter([0.0] + [float(i) for i in range(1, 200)])
    with pytest.raises(voxcpm_tts.VoxcpmCodaSatura) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                           poll=0, queue_timeout=10, clock=lambda: next(orologio))
    assert e.value.ritentabile is False


def test_job_partito_e_mai_finito_si_cancella():
    # Un job che avanza ma non chiude entro il tetto: si cancella (RunPod
    # fattura a secondi finche' gira) e si segnala come ritentabile.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-8"})],
        get=[FintaRisposta(body={"status": "IN_PROGRESS"}) for _ in range(50)],
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))
    orologio = iter([0.0] + [float(i) for i in range(1, 200)])
    with pytest.raises(voxcpm_tts.VoxcpmBloccato) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                           poll=0, timeout=10, clock=lambda: next(orologio))
    assert e.value.ritentabile is True
    assert ses.post_fatte[-1]["url"].endswith("/cancel/job-8")


def test_un_transitorio_di_rete_sul_polling_non_uccide_il_job():
    # Il job sull'endpoint vive per conto suo: una GET che non passa e' un
    # problema nostro, e abbandonarlo lascerebbe una GPU accesa e pagata.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-9"})],
        get=[voxcpm_tts.requests.RequestException("connessione persa"),
             FintaRisposta(body={"status": "COMPLETED", "output": {"ok": 2}})],
    )
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert out == {"ok": 2}


def test_endpoint_non_configurato(monkeypatch):
    monkeypatch.setenv("ABM_VOXCPM_ENDPOINT_ID", "")
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        voxcpm_tts.run_job({"input": {}}, session=FintaSessione(),
                           sleep=dormi_finto, poll=0)


def test_cancel_job_non_esplode_se_la_rete_cade():
    # Si cancella nel `finally` di percorsi che stanno gia' fallendo: farlo
    # esplodere sostituirebbe l'errore vero con uno di rete.
    ses = FintaSessione(post=[voxcpm_tts.requests.RequestException("giu'")])
    voxcpm_tts.cancel_job("job-x", session=ses)   # non solleva


def test_timed_out_e_bloccato_non_un_generico_non_ritentabile():
    # TIMED_OUT lo chiude RunPod, non il worker: e' "partito e mai arrivato",
    # cioe' VoxcpmBloccato — non un VoxcpmJobError semplice che verrebbe letto
    # come non ritentabile mentre l'unica riga non ritentabile di §9.4 e'
    # VoxcpmCodaSatura.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-10"})],
        get=[FintaRisposta(body={"status": "TIMED_OUT", "output": {}})],
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))
    with pytest.raises(voxcpm_tts.VoxcpmBloccato) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert e.value.ritentabile is True


def test_cancelled_dal_lato_runpod_e_bloccato():
    # Stesso discorso di TIMED_OUT: un CANCELLED letto da /status arriva da
    # fuori (dashboard, un altro processo), non dal nostro `cancel_job`.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-11"})],
        get=[FintaRisposta(body={"status": "CANCELLED", "output": {}})],
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))
    with pytest.raises(voxcpm_tts.VoxcpmBloccato) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert e.value.ritentabile is True


def test_status_401_non_ritenta_e_non_e_ritentabile():
    # Come per la sottomissione: una chiave revocata resta revocata, e
    # rimettersi ad aspettare fino al tetto di coda o di esecuzione la
    # travestirebbe da "job bloccato" ritentabile mentre non lo e'.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-12"})],
        get=[FintaRisposta(status_code=401, text="unauthorized")],
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))
    with pytest.raises(voxcpm_tts.VoxcpmJobError) as e:
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert "401" in str(e.value)
    assert e.value.ritentabile is False
    assert len(ses.get_fatte) == 1


def test_status_503_sul_polling_continua_a_sondare():
    # Stesso criterio di `_submit`: un 503 sul polling e' del server che
    # scala, non del job. Non deve ne' uccidere il job ne' consumare il
    # tetto di esecuzione come farebbe un errore definitivo.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-13"})],
        get=[FintaRisposta(status_code=503, text="scaling"),
             FintaRisposta(body={"status": "COMPLETED", "output": {"ok": 3}})],
    )
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert out == {"ok": 3}


def test_on_queue_che_esplode_cancella_il_job_e_rilancia_l_originale():
    # Qualunque eccezione che non sia il successo lascia un job in volo, e va
    # cancellato prima di rilanciare: farlo dopo (o non farlo) lascerebbe una
    # GPU accesa e pagata anche se l'eccezione non c'entra con la rete.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-14"})],
        get=[FintaRisposta(body={"status": "IN_QUEUE"})],
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))

    def esplodi(_secondi_in_coda):
        raise RuntimeError("callback della UI in errore")

    with pytest.raises(RuntimeError, match="callback della UI in errore"):
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                           poll=0, on_queue=esplodi)
    assert ses.post_fatte[-1]["url"].endswith("/cancel/job-14")


def test_submit_risposta_senza_id_non_esplode_con_keyerror():
    # Un 2xx senza un `id` valido non e' un KeyError da lasciar risalire: e'
    # un job mai sottomesso, e Task 7 lo deve poter riconoscere come tale.
    ses = FintaSessione(post=[FintaRisposta(body={"non": "ha un id"})])
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)


def test_submit_non_dorme_dopo_l_ultimo_tentativo():
    # L'ultimo tentativo fallito non deve aspettare per niente: non c'e' un
    # tentativo successivo a giustificare il backoff.
    chiamate_sleep = []

    def conta_sleep(secondi):
        chiamate_sleep.append(secondi)

    ses = FintaSessione(
        post=[FintaRisposta(status_code=503, text="scaling")
              for _ in range(voxcpm_tts._SUBMIT_RETRIES)],
    )
    with pytest.raises(voxcpm_tts.VoxcpmJobError):
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=conta_sleep, poll=0)
    assert len(chiamate_sleep) == voxcpm_tts._SUBMIT_RETRIES - 1


def test_annullamento_e_osservato_a_tick_brevi_non_dopo_poll_s():
    # Review finale, Important F3: prima `cancelled()` era controllato solo
    # fra un poll e l'altro (mai DENTRO il sonno di `poll_s`), quindi un
    # `poll_s` lungo (o un `job_timeout_s` di minuti) teneva un cancel
    # dell'utente in sospeso fino al prossimo giro. Con `poll=30` un fix che
    # dormisse i 30s tutti d'un fiato farebbe scadere lo script GET (uno solo
    # previsto) o comunque non si accorgerebbe dell'annullamento se non dopo
    # l'intera attesa: qui deve bastare qualche tick da 1s.
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-15"})],
        get=[FintaRisposta(body={"status": "IN_QUEUE"})],
    )
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))

    tick_sleeps = []

    def sleep_che_conta(secondi):
        tick_sleeps.append(secondi)

    def cancellato():
        # Falso al primo controllo (subito dopo il poll IN_QUEUE): il cancel
        # arriva mentre si dorme, non prima.
        return len(tick_sleeps) >= 2

    with pytest.raises(voxcpm_tts.VoxcpmAnnullato):
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=sleep_che_conta,
                           poll=30, cancelled=cancellato)
    # Ogni tick e' al piu' 1s: non si e' dormito 30s tutti insieme prima di
    # accorgersi dell'annullamento.
    assert all(s <= 1.0 for s in tick_sleeps)
    # Pochi tick (2), non l'intero poll_s (che ne richiederebbe 30 da 1s).
    assert len(tick_sleeps) < 5
    assert ses.post_fatte[-1]["url"].endswith("/cancel/job-15")


def test_annullamento_gia_vero_non_fa_nemmeno_un_poll():
    # Se cancelled() e' gia' vero all'ingresso (fra una sottomissione e la
    # successiva, con la GET ancora da fare), non ha senso spendere quel poll:
    # si cancella e si esce subito.
    ses = FintaSessione(post=[FintaRisposta(body={"id": "job-16"})])
    ses.copione_post.append(FintaRisposta(body={"status": "CANCELLED"}))
    with pytest.raises(voxcpm_tts.VoxcpmAnnullato):
        voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto,
                           poll=0, cancelled=lambda: True)
    assert ses.get_fatte == []
    assert ses.post_fatte[-1]["url"].endswith("/cancel/job-16")


def test_senza_cancelled_il_comportamento_non_cambia():
    # Compatibilita': tutte le chiamate esistenti non passano `cancelled`, e
    # devono continuare a funzionare esattamente come prima (nessun controllo,
    # nessun tick).
    ses = FintaSessione(
        post=[FintaRisposta(body={"id": "job-17"})],
        get=[FintaRisposta(body={"status": "COMPLETED", "output": {"ok": 9}})],
    )
    out = voxcpm_tts.run_job({"input": {}}, session=ses, sleep=dormi_finto, poll=0)
    assert out == {"ok": 9}


def test_cancel_job_logga_se_la_cancellazione_non_e_confermata(caplog):
    # Non deve sollevare (e' best-effort), ma deve lasciare traccia: un
    # cancel non confermato e' un job che magari continua a girare e pagare.
    ses = FintaSessione(post=[FintaRisposta(status_code=404, text="not found")])
    with caplog.at_level("WARNING"):
        voxcpm_tts.cancel_job("job-y", session=ses)   # non solleva
    assert "404" in caplog.text
    assert "chiave-di-prova" not in caplog.text
