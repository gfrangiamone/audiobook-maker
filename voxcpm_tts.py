"""Motore TTS VoxCPM2 servito dal worker RunPod serverless.

Porting del cuore di `voxcpm_book.py` (repo `abm-voxcpm-worker`), non una
riscrittura: pianificazione dei chunk, sottomissione `/run`, polling
`/status`, tassonomia degli errori.

Il modulo non legge file di catalogo: le voci le risolve `voxcpm_catalog`.
Qui c'e' il dialogo con RunPod e il listino.

Economia del motore, che spiega scelte che altrove sembrerebbero strane
(§2 e §9.2 della spec): il costo sta nell'accensione del worker (~180 s a
freddo), non nei caratteri. Un job da 1 chunk e uno da 8 costano uguale.
Da qui l'unita' di lavoro per capitolo e il retry a caldo dentro lo stesso
job invece del rilancio a freddo.
"""
import base64
import collections
import json
import logging
import os
import threading
import time

import requests

import voxcpm_catalog

_LOG = logging.getLogger(__name__)

MODEL_ID = voxcpm_catalog.MODEL_ID
MODEL_LABEL = voxcpm_catalog.MODEL_LABEL

# Costo GPU misurato il 2026-08-04 su RTX 4090 a $1,10/h: 28,5x realtime su
# 11.919 caratteri e 51 chunk a concorrenza 16 (§8.3). Alimenta SOLO l'audit
# del margine reale: il prezzo all'utente e' la tariffa, non questo numero.
_COST_USD_PER_MCHAR = 0.91


def _f(env, default):
    try:
        return float(str(os.environ.get(env, default)).replace(",", "."))
    except (ValueError, TypeError):
        return float(default)


def _i(env, default):
    try:
        return int(os.environ.get(env, str(default)))
    except (ValueError, TypeError):
        return int(default)


def endpoint_id():
    return os.environ.get("ABM_VOXCPM_ENDPOINT_ID", "").strip()


def api_key():
    return os.environ.get("ABM_VOXCPM_API_KEY", "").strip()


def rate_eur_per_mchar():
    """Tariffa di listino all'utente. 0 = non configurata (motore nascosto)."""
    return _f("ABM_VOXCPM_RATE_EUR_PER_MCHAR", 0.0)


def cost_usd_per_mchar():
    return _f("ABM_VOXCPM_COST_USD_PER_MCHAR", _COST_USD_PER_MCHAR)


def free_threshold_eur():
    return _f("ABM_VOXCPM_FREE_THRESHOLD_EUR", 0.50)


def concurrency():
    """Chunk in volo dentro un singolo job del worker. Floor a 1."""
    return max(1, _i("ABM_VOXCPM_CONCURRENCY", 32))


def is_available():
    """True sse il motore e' completamente configurato.

    Servono tutte e quattro le condizioni: endpoint, chiave, un catalogo con
    almeno una voce valida e una tariffa di listino. Se manca qualcosa VoxCPM
    non compare fra i modelli (§9.4), come gia' fa Gemini senza API key.

    La tariffa e' parte del requisito e non un dettaglio: §15.3 la lascia da
    fissare prima del deploy, e generare libri a prezzo non deciso e' peggio
    che non offrire il motore.
    """
    if not endpoint_id() or not api_key():
        return False
    if rate_eur_per_mchar() <= 0:
        return False
    return bool(voxcpm_catalog.voices())


def compute_user_price_eur(chars):
    """Prezzo di listino per `chars` caratteri.

    Tariffa diretta EUR/Mchar (D4), non la catena costo-USD + margine +
    fee PayPal di Gemini e Speechify: li' il costo provider e' una fattura,
    qui e' tempo di GPU, e il listino e' una decisione commerciale a se'.
    Le fee sono percio' gia' dentro la tariffa.

    Chiavi di ritorno allineate a `speechify_tts.compute_user_price_eur`,
    cosi' i chiamanti a valle non distinguono i due motori.
    """
    try:
        chars = int(chars or 0)
    except (TypeError, ValueError):
        chars = 0
    if chars < 0:
        chars = 0
    list_price = round(chars / 1_000_000.0 * rate_eur_per_mchar(), 2)
    threshold = free_threshold_eur()
    is_free = list_price < threshold
    return {
        "chars": chars,
        "cost_usd": round(chars / 1_000_000.0 * cost_usd_per_mchar(), 6),
        "list_price_eur": list_price,
        "user_price_eur": 0.0 if is_free else list_price,
        "is_free": is_free,
        "free_threshold_eur": threshold,
    }


def estimate_book_cost(chapters, language="it"):
    """Stima end-to-end sui caratteri di input, capitolo per capitolo.

    Args:
        chapters: lista di oggetti con attributo `.text`.
        language: ISO 639-1 della voce scelta (informativo).
    """
    chars_per_chapter = []
    chars_total = 0
    for ch in chapters:
        n = len(getattr(ch, "text", "") or "")
        chars_per_chapter.append(n)
        chars_total += n
    price = compute_user_price_eur(chars_total)
    return {
        "chars_total": chars_total,
        "chars_per_chapter": chars_per_chapter,
        "cost_usd": price["cost_usd"],
        "list_price_eur": price["list_price_eur"],
        "user_price_eur": price["user_price_eur"],
        "is_free": price["is_free"],
        "language": language,
        "model_key": MODEL_ID,
        "model_label": MODEL_LABEL,
    }


# --------------------------------------------------------------------------
# Errori
# --------------------------------------------------------------------------
class VoxcpmJobError(RuntimeError):
    """Un job VoxCPM non ha consegnato l'audio.

    `ritentabile` dice se rifare il job ha una speranza. E' la tabella §9.4
    della spec messa nel tipo: chi orchestra decide la politica, ma non deve
    ridedurre da un messaggio se quel fallimento si rifa' o no.
    """

    ritentabile = False

    def __init__(self, messaggio, job_id=""):
        super().__init__(messaggio)
        self.job_id = job_id


class VoxcpmRimbalzato(VoxcpmJobError):
    """Respinto da un worker gia' in spegnimento: non e' un guasto nostro.

    Il controllo all'ingresso di `handler.py` rifiuta i job che arrivano su un
    worker dichiarato morto, e lo fa PRIMA di toccare la GPU. Si rifa'
    identico: stessa concorrenza, e senza spendere i tentativi riservati alla
    GPU che non regge.
    """

    ritentabile = True


class VoxcpmMotoreCompromesso(VoxcpmJobError):
    """Il processo nanovllm e' caduto (tipicamente un OOM) e il worker si spegne.

    Ritentabile, ma stringendo il batch: la causa comune e' la VRAM al limite.
    Distinto dal rimbalzo apposta — vedi §9.3.
    """

    ritentabile = True


class VoxcpmBloccato(VoxcpmJobError):
    """Partito e mai arrivato: cancellato per non pagarlo a vuoto.

    E' il caso in cui ritentare conviene di piu', perche' il tentativo nuovo
    quasi sempre finisce su un altro worker.
    """

    ritentabile = True


class VoxcpmCodaSatura(VoxcpmJobError):
    """Mai partito: l'endpoint e' saturo, non lento.

    L'unica riga non ritentabile della tabella §9.4: rimettersi in fila
    dietro se stessi non libera nessun worker.
    """

    ritentabile = False


class VoxcpmAnnullato(VoxcpmJobError):
    """Annullamento dell'utente osservato durante l'attesa del job.

    Distinta da `VoxcpmBloccato`/`VoxcpmCodaSatura`: non e' un guasto o una
    saturazione dell'endpoint, e' `cancelled()` diventato vero mentre
    `_attendi_esito` dormiva fra un poll e l'altro (Review finale, Important
    F3). Non ritentabile per definizione: l'utente ha chiesto di fermarsi.
    """

    ritentabile = False


# Quante volte si rifa' un job i cui chunk sono usciti a silenzio, e quante
# se n'e' rimbalzato uno. Budget separati perche' misurano cose diverse: il
# primo il carico sulla GPU, il secondo la sfortuna nell'instradamento.
SILENCE_RETRIES = 2
BOUNCE_RETRIES = 6

# Sottostringhe che, nel messaggio d'errore, dicono "la GPU non ce l'ha
# fatta". Sono i casi in cui rifare piu' stretti ha senso: una firma scaduta
# o un testo malformato non migliorano certo a concorrenza 4.
_GPU_PRESSURE = ("out of memory", "cuda", "nvml", "cublas", "device-side",
                 "motore compromesso")

_RUNPOD_BASE = "https://api.runpod.ai/v2"
_SUBMIT_RETRIES = 4
_HTTP_TRANSIENT = (429, 500, 502, 503, 504)


def _base():
    ep = endpoint_id()
    if not ep or not api_key():
        raise VoxcpmJobError(
            "endpoint VoxCPM non configurato: servono ABM_VOXCPM_ENDPOINT_ID "
            "e ABM_VOXCPM_API_KEY")
    return f"{_RUNPOD_BASE}/{ep}"


def _headers():
    return {"Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json"}


def queue_timeout_s():
    return _f("ABM_VOXCPM_QUEUE_TIMEOUT_S", 900.0)


def job_timeout_s():
    return _f("ABM_VOXCPM_JOB_TIMEOUT_S", 1800.0)


def poll_seconds():
    return _f("ABM_VOXCPM_POLL_S", 2.0)


def _rimbalzo(out, testo):
    """Il rimbalzo si riconosce dal campo o, sulle immagini vecchie, dal testo."""
    return bool(out.get("bounced")) or "in spegnimento" in testo


def _errore_del_job(out, testo, job_id):
    """Da una risposta fallita all'eccezione giusta."""
    if _rimbalzo(out, testo):
        return VoxcpmRimbalzato(testo, job_id)
    basso = testo.lower()
    if out.get("engine_dead") or any(k in basso for k in _GPU_PRESSURE):
        return VoxcpmMotoreCompromesso(testo, job_id)
    return VoxcpmJobError(testo, job_id)


def _submit(payload, session, sleep):
    ultimo = ""
    for tentativo in range(_SUBMIT_RETRIES):
        try:
            r = session.post(f"{_base()}/run", headers=_headers(),
                             json=payload, timeout=60)
        except requests.RequestException as e:
            ultimo = str(e)
        else:
            if r.status_code < 400:
                try:
                    return r.json()["id"]
                except (ValueError, KeyError, TypeError) as e:
                    # Un 2xx senza un id valido non e' un transitorio da
                    # ritentare: e' una risposta che il worker non sa dare.
                    raise VoxcpmJobError(
                        f"risposta di /run senza un id valido: {e}")
            if r.status_code not in _HTTP_TRANSIENT:
                raise VoxcpmJobError(f"HTTP {r.status_code}: {r.text[:200]}")
            ultimo = f"HTTP {r.status_code}"
        if tentativo < _SUBMIT_RETRIES - 1:
            sleep(min(30, 2 ** tentativo))
    raise VoxcpmJobError(f"esauriti i tentativi di sottomissione ({ultimo})")


def cancel_job(job_id, *, session=None):
    """Cancella un job in volo. Non solleva mai.

    Si chiama nei percorsi che stanno gia' fallendo: farla esplodere
    sostituirebbe l'errore vero con uno di rete. Un job abbandonato pero' va
    cancellato davvero, perche' continua a occupare la GPU e si paga a secondi.
    """
    ses = session or requests
    try:
        r = ses.post(f"{_base()}/cancel/{job_id}", headers=_headers(),
                     json=None, timeout=30)
        codice = getattr(r, "status_code", None)
        if codice is not None and not (200 <= codice < 300):
            _LOG.warning("cancel del job %s non confermata: HTTP %s",
                         job_id, codice)
    except Exception:      # noqa: BLE001 - best effort, per definizione
        pass


# Tick massimo della sonnellino a rate limitato in `_attendi_esito`: `cancelled`
# va controllato spesso durante l'attesa fra un poll e l'altro, non solo fra un
# poll e il successivo, altrimenti un `poll_s` di qualche decina di secondi (o
# un `job_timeout_s` di 1800s da attraversare intero) terrebbe un cancel
# dell'utente in sospeso per minuti (Review finale, Important F3).
_TICK_ANNULLAMENTO_S = 1.0


def run_job(payload, *, session=None, sleep=time.sleep, poll=None, timeout=None,
            queue_timeout=None, clock=time.time, on_queue=None, cancelled=None):
    """Sottomette il job e ne aspetta l'esito. Ritorna l'`output`.

    `/run` piu' polling su `/status`, mai `/runsync`: quello risponde 200 e
    senza `output` quando il job supera la finestra della richiesta, e il job
    continua a girare — e a essere pagato — senza che nessuno ne raccolga il
    risultato. Il primo job di una sessione quella finestra la supera sempre,
    per via del cold start di ~180 s (§9.1).

    Args:
        payload: il corpo completo, `{"input": {...}}`.
        session: oggetto con `post`/`get` alla `requests`. Il default e'
            `requests` stesso; nei test e' il doppio.
        sleep: funzione d'attesa. Iniettabile perche' un test del backoff non
            deve durare quanto il backoff.
        poll: secondi fra due sonde. `None` = da ambiente.
        timeout: tetto sull'esecuzione, in secondi. `None` = da ambiente.
        queue_timeout: tetto sull'attesa in coda. `None` = da ambiente.
        clock: sorgente del tempo, iniettabile come `sleep`.
        on_queue: callback opzionale `(secondi_in_coda)` chiamata mentre il
            job e' ancora in fila. Serve alla UI per dichiarare l'attesa
            invece di fingere un progresso che non c'e' (§9.1).
        cancelled: predicato opzionale senza argomenti.
            `None` (default) mantiene il comportamento precedente: nessun
            controllo durante l'attesa. Se passato, viene controllato a tick
            di al piu' `_TICK_ANNULLAMENTO_S` secondi durante il sonno fra un
            poll e l'altro: appena torna vero, il job viene cancellato e
            l'attesa si interrompe subito, senza aspettare il resto del tick
            di polling.

    Raises:
        VoxcpmRimbalzato, VoxcpmMotoreCompromesso, VoxcpmBloccato,
        VoxcpmCodaSatura, VoxcpmAnnullato, VoxcpmJobError: vedi la tabella §9.4.
    """
    ses = session or requests
    attesa = poll_seconds() if poll is None else float(poll)
    tetto_exec = job_timeout_s() if timeout is None else float(timeout)
    tetto_coda = queue_timeout_s() if queue_timeout is None else float(queue_timeout)

    job_id = _submit(payload, ses, sleep)
    try:
        return _attendi_esito(job_id, ses, sleep, attesa, tetto_exec,
                              tetto_coda, clock, on_queue, cancelled=cancelled)
    except BaseException:
        # Qualunque uscita che non sia il `return` di successo lascia un job
        # in volo, e RunPod lo fattura finche' gira: si cancella prima di
        # rilanciare, senza mai sostituire l'errore vero con uno di rete
        # (`cancel_job` non solleva mai). Se l'uscita e' gia' un
        # `VoxcpmAnnullato`, il job e' gia' stato cancellato da
        # `_attendi_esito`: `cancel_job` e' idempotente e non ripete l'HTTP
        # dell'annullamento a vuoto (l'endpoint risponde 2xx a un cancel su un
        # job gia' cancellato).
        cancel_job(job_id, session=ses)
        raise


def _dormi_annullabile(sleep, attesa, cancelled, job_id, ses):
    """Dorme `attesa` secondi in tick di al piu' `_TICK_ANNULLAMENTO_S`,
    controllando `cancelled` dopo ogni tick (e prima, se `attesa` e' 0).

    Se l'annullamento arriva a meta' dell'attesa, non si sta ad aspettare il
    resto: si cancella subito il job (RunPod lo fattura a secondi finche'
    gira) e si solleva `VoxcpmAnnullato`, invece di lasciare il chiamante in
    sonno fino al prossimo poll.
    """
    if cancelled is None:
        sleep(attesa)
        return
    rimanente = attesa
    while True:
        if cancelled():
            cancel_job(job_id, session=ses)
            raise VoxcpmAnnullato(
                f"job {job_id} annullato durante l'attesa", job_id)
        if rimanente <= 0:
            return
        tick = min(_TICK_ANNULLAMENTO_S, rimanente)
        sleep(tick)
        rimanente -= tick


def _attendi_esito(job_id, ses, sleep, attesa, tetto_exec, tetto_coda, clock,
                    on_queue, cancelled=None):
    """Il polling vero e proprio: isolato per poterlo avvolgere in un solo
    `try/except` che cancella il job su qualunque uscita non riuscita."""
    t0 = clock()
    t_run = None
    while True:
        if cancelled is not None and cancelled():
            cancel_job(job_id, session=ses)
            raise VoxcpmAnnullato(
                f"job {job_id} annullato durante l'attesa", job_id)
        trascorso = clock() - t0
        if t_run is None:
            if trascorso > tetto_coda:
                raise VoxcpmCodaSatura(
                    f"job {job_id} mai partito: {trascorso / 60:.0f} min in "
                    f"coda, oltre i {tetto_coda / 60:.0f} concessi. "
                    f"L'endpoint e' saturo, non lento", job_id)
        elif clock() - t_run > tetto_exec:
            raise VoxcpmBloccato(
                f"job {job_id} oltre {tetto_exec:.0f}s di esecuzione: il "
                f"worker non sta avanzando, si cancella e si rifa", job_id)

        try:
            r = ses.get(f"{_base()}/status/{job_id}", headers=_headers(),
                        timeout=60)
        except requests.RequestException:
            # Il job sull'endpoint vive per conto suo: una sonda che non passa
            # e' un problema nostro, e abbandonarlo qui lascerebbe una GPU
            # accesa e pagata.
            _dormi_annullabile(sleep, attesa, cancelled, job_id, ses)
            continue

        if r.status_code >= 400:
            if r.status_code in _HTTP_TRANSIENT:
                # Stesso criterio di `_submit`: un 429/5xx e' del server che
                # respira, non del job. Si riprova a sondare.
                _dormi_annullabile(sleep, attesa, cancelled, job_id, ses)
                continue
            # Un 401/403/404 non migliora aspettando: la chiave revocata resta
            # revocata. Non e' ritentabile, e Task 7 non deve riscoprirlo
            # dopo aver aspettato fino al tetto di coda o di esecuzione.
            raise VoxcpmJobError(
                f"job {job_id}: HTTP {r.status_code} su /status: "
                f"{r.text[:200]}", job_id)
        st = r.json()

        stato = st.get("status")
        if t_run is None and stato == "IN_PROGRESS":
            t_run = clock()
        if stato in ("COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"):
            out = st.get("output")
            out = out if isinstance(out, dict) else {}
            if stato == "COMPLETED" and not out.get("error"):
                return out
            # L'`output` per primo, quando c'e': il worker che rifiuta o che
            # muore risponde con un dizionario — `engine_dead`, `bounced`, la
            # scheda, la VRAM libera — mentre `error` di RunPod e' la sola
            # stringa. Leggere prima quella butterebbe via proprio i campi
            # messi li' per diagnosticare il guasto.
            dettaglio = json.dumps(out) if out else json.dumps(
                st.get("error") or st)
            testo = f"job {job_id} {stato}: {dettaglio[:400]}"
            if stato in ("TIMED_OUT", "CANCELLED"):
                # RunPod l'ha chiuso lei, non il worker: e' "partito e mai
                # arrivato", cioe' esattamente VoxcpmBloccato (§9.4) — non un
                # generico VoxcpmJobError non ritentabile.
                raise VoxcpmBloccato(testo, job_id)
            raise _errore_del_job(out, testo, job_id)

        if t_run is None and on_queue is not None:
            on_queue(trascorso)
        _dormi_annullabile(sleep, attesa, cancelled, job_id, ses)


# --------------------------------------------------------------------------
# Un capitolo, un job (§7.3)
# --------------------------------------------------------------------------

# Aderenza al testo e al riferimento. E' il default di lettura del client
# (`voxcpm_book.py`, CFG_READ): alzarlo irrigidisce la dizione, abbassarlo
# fa divagare la voce dal campione.
CFG_READ = 2.0

# Concorrenza minima: sotto i 4 chunk in volo il worker paga piu' overhead di
# quanto guadagni in stabilita', e il capitolo che non passa a 4 non passa.
_CONCURRENCY_FLOOR = 4

# FIFO, non LRU: le voci di un libro sono poche (una manciata di personaggi),
# il tetto serve solo contro un chiamante che passasse voice_id a raffica
# (es. un audit su tutto il catalogo) senza mai liberare la cache.
_CLONE_CACHE_MAX = 16
_clone_cache = collections.OrderedDict()
_clone_lock = threading.Lock()

# Indirezione sul sonno, cosi' i test della politica di ritentativo non
# durano quanto le pause che verificano.
_dormi = time.sleep


def invalidate_clone_cache():
    """Svuota la cache dei campioni codificati. La chiamano i test."""
    with _clone_lock:
        _clone_cache.clear()


def clone_block(voice_id):
    """I campi del payload che determinano la voce, in modalita' `hifi`.

    `hifi` per tutte le voci (§7.4): prefisso piu' riferimento. Il canale che
    porta l'identita' e' `prompt_wav_b64`, misurato il 2026-08-28 incrociando
    i due canali — il risultato segue il prefisso e ignora il riferimento.
    Per questo `prompt_text` e' un requisito duro: senza la trascrizione
    esatta il prefisso non entra nel canale che conta e la resa crolla a
    quella di `reference`, gia' giudicata inaccettabile.

    Il risultato e' memorizzato per `voice_id`: il wav non cambia, e su un
    libro da quaranta capitoli sarebbero quaranta letture identiche.
    """
    with _clone_lock:
        pronto = _clone_cache.get(voice_id)
    if pronto is not None:
        return dict(pronto)

    rec = voxcpm_catalog.parse_voice_id(voice_id)
    with open(voxcpm_catalog.sample_path(voice_id), "rb") as f:
        wav = base64.b64encode(f.read()).decode("ascii")
    blocco = {
        "prompt_wav_b64": wav,
        "prompt_format": "wav",
        "prompt_text": rec["transcript"],
        "reference_wav_b64": wav,
        "reference_format": "wav",
    }
    with _clone_lock:
        _clone_cache[voice_id] = blocco
        if len(_clone_cache) > _CLONE_CACHE_MAX:
            _clone_cache.popitem(last=False)
    return dict(blocco)


# Chiavi di un output di job che si possono stampare in un messaggio
# d'errore. Whitelist e non l'intero dict: l'output porta anche URL firmati
# (get/put su R2), che nei log non devono mai finire.
_CHIAVI_DIAGNOSTICA = ("error", "format", "bytes", "chunks")


def _riassunto(out):
    """Estratto sicuro di un output di job, per i messaggi d'errore."""
    ridotto = {k: out.get(k) for k in _CHIAVI_DIAGNOSTICA if k in out}
    return json.dumps(ridotto)[:300]


def _scarica(url, dest):
    """Scrive in `dest` il corpo di `url`, senza tenerlo tutto in memoria.

    Il PCM di un capitolo a 48 kHz sta sulle decine di megabyte: leggerlo in
    una stringa moltiplicherebbe la memoria del server per il numero di
    capitoli in volo.

    Un fallimento di rete esce come `VoxcpmJobError`, non come
    `requests.HTTPError`: e' il contratto dichiarato da `synthesize_chapter`,
    e chi chiama non deve conoscere il trasporto per capire cosa e' successo.
    Il messaggio non riporta `url`: e' una GET firmata, e finirebbe nei log.
    """
    tmp = dest + ".part"
    try:
        with requests.get(url, stream=True, timeout=300) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for pezzo in r.iter_content(chunk_size=1 << 20):
                    if pezzo:
                        f.write(pezzo)
        os.replace(tmp, dest)
    except requests.RequestException as e:
        codice = getattr(getattr(e, "response", None), "status_code", None)
        dettaglio = f"HTTP {codice}" if codice else type(e).__name__
        raise VoxcpmJobError(
            f"scaricamento del capitolo da R2 fallito: {dettaglio}") from e
    finally:
        # Un fallimento a meta' lascia un `.part` orfano: sul prossimo
        # tentativo scriverebbe su un file gia' li', ingannando chi guarda
        # solo la dimensione.
        if os.path.exists(tmp):
            os.remove(tmp)


def _cancella_intermedio(key):
    """Cancella l'intermedio R2. Non solleva mai.

    Si chiama quando il capitolo e' gia' scritto (o gia' scartato): una
    cancellazione fallita lascia solo un oggetto orfano su R2, non deve
    buttare via lavoro gia' fatto.
    """
    import storage_backend
    try:
        storage_backend.delete_object(key)
    except Exception:      # noqa: BLE001 - best effort, per definizione
        _LOG.warning("cancellazione R2 non riuscita per la chiave %s", key)


def synthesize_chapter(chunks, voice_id, dest_path, *, key="", session=None,
                       sleep=None, on_queue=None, cancelled=None):
    """Sintetizza un capitolo intero come un solo job. Scrive il PCM grezzo.

    Un job per capitolo (§7.3): il costo sta nell'accensione del worker, non
    nei caratteri, quindi un job da un chunk e uno da otto costano uguale, e
    l'accensione si ammortizza sui capitoli successivi finche' il worker resta
    caldo.

    Il ritentativo sta qui e non piu' in alto per la stessa ragione (§9.2):
    rifare il capitolo mentre il worker e' caldo costa secondi di GPU, rifarlo
    a freddo costa un'accensione intera.

    Args:
        chunks: i testi del capitolo, gia' spezzati da `tts_split`.
        voice_id: `voxcpm:v2:<locale>/<Nome>`.
        dest_path: dove scrivere il PCM 16 bit mono.
        key: chiave R2 dell'intermedio. Vuota o R2 spento = audio inline.
        session, sleep, on_queue: inoltrati a `run_job`.
        cancelled: predicato senza argomenti. Se vero prima di sottomettere,
            il job non parte: e' il momento in cui la spesa comincia.

    Returns:
        dict con `sample_rate`, `chars`, `audio_seconds`, `tts_seconds`,
        `jobs`, `redone`, `bounced`, `failed_chunks`, `bytes`.

    Raises:
        ValueError: la voce non e' nel catalogo, o `chunks` e' vuoto
            (§9.4, casi normali).
        VoxcpmJobError e sottoclassi: vedi la tabella §9.4.
    """
    import storage_backend

    if not chunks:
        raise ValueError("synthesize_chapter: nessun chunk da sintetizzare")

    clone = clone_block(voice_id)      # prima di tutto: se la voce non c'e',
                                       # si scopre senza aver acceso nulla
    riposa = sleep or _dormi
    su_r2 = bool(key) and storage_backend.is_enabled()
    stats = {"sample_rate": 0, "chars": 0, "audio_seconds": 0.0,
             "tts_seconds": 0.0, "jobs": 0, "redone": 0, "bounced": 0,
             # Strutturalmente sempre 0: un tentativo con chunk a silenzio
             # non arriva mai al `return` sotto (si rifa' o solleva), quindi
             # la consegna che esce da questo ciclo non ne ha mai.
             "failed_chunks": 0, "bytes": 0}

    conc = concurrency()
    tentativo, rimbalzi = 0, 0
    while True:
        if cancelled is not None and cancelled():
            raise VoxcpmJobError("job annullato: nessun altro worker acceso")
        ultimo = tentativo >= SILENCE_RETRIES

        payload = {"input": {
            "action": "generate",
            "chunks": list(chunks),
            **clone,
            "cfg": CFG_READ,
            "concurrency": conc,
            # PCM grezzo, non WAV: i capitoli vengono concatenati byte a byte
            # da `pcm_concat`, e un header WAV in mezzo finirebbe dentro
            # l'audio come rumore.
            "output_format": "pcm",
        }}
        if su_r2:
            payload["input"]["s3"] = {
                "put_url": storage_backend.presigned_put_url(key),
                "key": key,
            }

        try:
            out = run_job(payload, session=session, sleep=riposa,
                          on_queue=on_queue, cancelled=cancelled)
        except VoxcpmRimbalzato:
            # Respinto senza essere partito: si rifa' uguale. La concorrenza
            # resta quella e il contatore dei tentativi veri non si muove,
            # perche' questo non e' un sintomo di carico ma di instradamento.
            rimbalzi += 1
            stats["bounced"] += 1
            if rimbalzi > BOUNCE_RETRIES:
                raise
            # Una pausa che cresce, non un ritentativo immediato: il worker
            # guasto impiega ancora una decina di secondi a uscire, e finche'
            # e' li' respinge tutto.
            riposa(min(30, 10 * rimbalzi))
            continue
        except (VoxcpmBloccato, VoxcpmMotoreCompromesso):
            # Stesso rimedio, due sintomi: il worker che si e' fermato e la
            # GPU che non ha retto vogliono entrambi un batch piu' stretto.
            if ultimo:
                raise
        else:
            if "failed_indices" not in out:
                # Assente e' un worker che non rispetta il protocollo, non un
                # worker senza chunk caduti: zero e assente non sono la
                # stessa cosa, e confonderli terrebbe un capitolo che nessuno
                # ha verificato.
                raise VoxcpmJobError(
                    "risposta senza failed_indices: protocollo del worker "
                    "non rispettato: " + _riassunto(out))

            stats["jobs"] += 1
            stats["sample_rate"] = stats["sample_rate"] or int(
                out.get("sample_rate") or 48000)
            # Non `+=`: i caratteri e i secondi d'audio del capitolo sono
            # quelli del tentativo che finisce per essere consegnato, non la
            # somma coi tentativi scartati per silenzio. `tts_seconds` invece
            # e' GPU pagata anche sul tentativo buttato via, e quella si
            # somma davvero.
            stats["chars"] = int(out.get("chars") or 0)
            stats["audio_seconds"] = float(out.get("audio_seconds") or 0.0)
            stats["tts_seconds"] += float(out.get("tts_seconds") or 0.0)

            bad = out["failed_indices"] or []
            if bad:
                # Il worker mette un secondo di silenzio al posto della frase
                # caduta e tira dritto, cosi' il capitolo resta allineato. Per
                # un audiolibro pero' quel silenzio e' una frase persa, e a
                # valle passerebbe ogni verifica: l'M4B corrisponderebbe
                # esattamente ai frammenti, silenzi compresi.
                if su_r2:
                    _cancella_intermedio(key)
                if ultimo:
                    raise VoxcpmJobError(
                        f"{len(bad)} chunk su {len(chunks)} a silenzio anche a "
                        f"concorrenza {conc}: il capitolo sarebbe bucato, non "
                        f"lo si tiene")
            else:
                scritti = _consegna(out, dest_path, key, su_r2, conc, len(chunks))
                stats["bytes"] = scritti
                return stats

        conc = max(_CONCURRENCY_FLOOR, conc // 4)
        tentativo += 1
        stats["redone"] += 1


def _consegna(out, dest_path, key, su_r2, conc, n_chunk):
    """Porta l'audio del job in `dest_path`. Ritorna i byte scritti."""
    import storage_backend

    if su_r2:
        caricati = int((out.get("s3") or {}).get("bytes") or 0)
        if not caricati:
            raise VoxcpmJobError(
                "il job non ha caricato niente su R2: " + _riassunto(out))
        try:
            _scarica(storage_backend.presigned_get_url(key), dest_path)
            scaricati = os.path.getsize(dest_path)
            if scaricati != caricati:
                # Un troncamento silenzioso scriverebbe un capitolo corto
                # senza che nulla a valle se ne accorga: l'M4B risulterebbe
                # comunque valido, solo piu' breve del dovuto.
                raise VoxcpmJobError(
                    f"scaricamento troncato da R2: il worker ne ha caricati "
                    f"{caricati}, ne sono arrivati {scaricati}")
        finally:
            # L'oggetto su R2 e' un intermedio: il server ha gia' i byte,
            # tenerlo sarebbe pagare storage per una copia che nessuno
            # rilegge. Gira sempre, successo o no: un fallimento a meta'
            # lascia comunque un oggetto da non tenere.
            _cancella_intermedio(key)
        return scaricati

    audio = out.get("audio_b64")
    if not audio:
        raise VoxcpmJobError(
            f"risposta senza audio per {n_chunk} chunk a concorrenza {conc}: "
            + _riassunto(out))
    dati = base64.b64decode(audio)
    tmp = dest_path + ".part"
    with open(tmp, "wb") as f:
        f.write(dati)
    os.replace(tmp, dest_path)
    return len(dati)


def jobs_in_flight():
    """Capitoli sottomessi insieme. Floor a 1.

    Il default e' 2 e non 24 come la concorrenza dei chunk: quella misura il
    batch dentro un worker, questa quanti worker si accendono. Ogni job in
    piu' e' un'accensione in piu' se l'endpoint deve scalare, e l'accensione
    e' il costo dominante (§9.2).
    """
    return max(1, _i("ABM_VOXCPM_JOBS", 2))


def apply_rate(pcm_path, rate, sample_rate):
    """Applica la velocita' di lettura al PCM, sul posto. Ritorna True se fatto.

    L'azione `generate` del worker non ha un parametro di velocita': ce l'ha
    `assemble`, che D9 lascia fuori dal perimetro. La velocita' la mette
    quindi l'app, con un `atempo` di ffmpeg sul PCM grezzo. L'intervallo del
    pannello e' -30%..+30% (§5.2), comodamente dentro il dominio 0,5-2,0 di
    `atempo`: un solo filtro basta, nessuna catena.
    """
    try:
        pct = float(str(rate or "0").replace("%", "").replace("+", "").strip())
    except (TypeError, ValueError):
        return False
    tempo = 1.0 + pct / 100.0
    if abs(tempo - 1.0) < 0.005:
        return False
    tempo = max(0.5, min(2.0, tempo))

    import subprocess
    sr = int(sample_rate or 48000)
    tmp = pcm_path + ".rate"
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "s16le", "-ar", str(sr), "-ac", "1", "-i", pcm_path,
           "-filter:a", f"atempo={tempo:.4f}",
           "-f", "s16le", "-ar", str(sr), "-ac", "1", tmp]
    try:
        subprocess.run(cmd, check=True)
        os.replace(tmp, pcm_path)
        return True
    except Exception:
        # ffmpeg mancante o fallito non deve buttare via l'audio gia' pagato
        # al worker: il PCM originale resta com'era, si consegna a velocita'
        # normale invece di perdere il capitolo. Niente path ne' credenziali
        # nel log, solo il fatto.
        _LOG.warning("apply_rate: ffmpeg non disponibile o fallito, "
                     "velocita' non applicata")
        return False
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
