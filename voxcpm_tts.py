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
import json
import logging
import os
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


def run_job(payload, *, session=None, sleep=time.sleep, poll=None, timeout=None,
            queue_timeout=None, clock=time.time, on_queue=None):
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

    Raises:
        VoxcpmRimbalzato, VoxcpmMotoreCompromesso, VoxcpmBloccato,
        VoxcpmCodaSatura, VoxcpmJobError: vedi la tabella §9.4.
    """
    ses = session or requests
    attesa = poll_seconds() if poll is None else float(poll)
    tetto_exec = job_timeout_s() if timeout is None else float(timeout)
    tetto_coda = queue_timeout_s() if queue_timeout is None else float(queue_timeout)

    job_id = _submit(payload, ses, sleep)
    try:
        return _attendi_esito(job_id, ses, sleep, attesa, tetto_exec,
                              tetto_coda, clock, on_queue)
    except BaseException:
        # Qualunque uscita che non sia il `return` di successo lascia un job
        # in volo, e RunPod lo fattura finche' gira: si cancella prima di
        # rilanciare, senza mai sostituire l'errore vero con uno di rete
        # (`cancel_job` non solleva mai).
        cancel_job(job_id, session=ses)
        raise


def _attendi_esito(job_id, ses, sleep, attesa, tetto_exec, tetto_coda, clock,
                    on_queue):
    """Il polling vero e proprio: isolato per poterlo avvolgere in un solo
    `try/except` che cancella il job su qualunque uscita non riuscita."""
    t0 = clock()
    t_run = None
    while True:
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
            sleep(attesa)
            continue

        if r.status_code >= 400:
            if r.status_code in _HTTP_TRANSIENT:
                # Stesso criterio di `_submit`: un 429/5xx e' del server che
                # respira, non del job. Si riprova a sondare.
                sleep(attesa)
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
        sleep(attesa)
