"""Stato persistito del backend TTS: circuit breaker a senso unico.

Modulo foglia. Nessun import di `audiobook_app` o `gemini_tts`: lo stato e'
un dato, non una decisione. Chi decide di far scattare il breaker e' il
chiamante, che confronta `record_failure` con ABM_CF_TRIP_FAILURES.

Il rientro su Cloudflare avviene solo per azione manuale dell'admin
(`reset`), mai automaticamente: un backend che e' andato giu' per credito
esaurito tornerebbe a cadere subito, e ogni caduta costa un job.

Fail-safe di lettura: un file ASSENTE e' un'installazione pulita (nessun
trip e' mai avvenuto, {} e' corretto). Un file PRESENTE ma illeggibile (I/O,
JSON invalido, radice non-dict, o una singola voce per-modello di forma
sbagliata) e' un'altra cosa: lo stato precedente esiste e non sappiamo
leggerlo. In quel caso NON si riparte puliti: si considera scattato ogni
modello finche' un reset esplicito dall'admin non riscrive un valore
concreto. Il motivo per cui questo stato e' persistito e' precisamente che
un riavvio non possa rimettere in produzione un backend guasto senza che
nessuno lo sappia; rispondere "pulito" a uno stato che non si riesce a
leggere sarebbe il riarmo silenzioso che l'interruttore deve impedire.

Igiene dei dati: `detail` (passato a `trip()`) viene persistito su disco e
stampato su stdout COSI' COM'E', troncato a 300 caratteri ma non altrimenti
filtrato o redatto. Questo modulo non applica alcuna redazione: e' cura
esclusiva del chiamante non passare qui header, token o altre credenziali.

File di stato: <data_dir>/_tts_backend_state.json
"""
import json
import os
import threading
import time
from datetime import datetime, timezone

import community_store

_STATE_PATH = None
_LOCK = threading.RLock()
_CACHE = {}

# True quando il file di stato ESISTEVA ma non e' stato letto correttamente
# (I/O, JSON invalido, radice non-dict). Governa solo il fallback di
# `state()`/`is_tripped()` per i model_key che non hanno (ancora) una voce
# concreta in _CACHE: una volta che un modello riceve un valore esplicito
# (trip o reset), quel valore concreto prevale sempre su questo flag.
_FAIL_SAFE = False

_FILENAME = "_tts_backend_state.json"


def init(data_dir):
    """Fissa la directory dello stato e ricarica dal disco."""
    global _STATE_PATH, _CACHE
    with _LOCK:
        _STATE_PATH = os.path.join(data_dir, _FILENAME)
        _CACHE = _load()


def _load():
    """Carica lo stato da disco distinguendo i due casi che contano:

    - File ASSENTE: installazione nuova, o nessun modello e' mai scattato.
      {} e' la risposta corretta - non c'e' nulla da riarmare, e trattare
      questo caso come "tutto scattato" spegnerebbe Cloudflare dal
      primissimo avvio.
    - File PRESENTE ma illeggibile: lo stato precedente ESISTE e non sappiamo
      leggerlo. Attiva il fail-safe globale (`_FAIL_SAFE`): ogni modello
      senza un valore concreto viene considerato scattato finche' un reset
      esplicito dall'admin non lo smentisce singolarmente. Una singola voce
      per-modello di forma sbagliata (JSON top-level valido, ma
      `raw[model_key]` non e' un dict) riceve lo stesso trattamento, limitato
      pero' a quel modello soltanto: viene materializzata in _CACHE come
      trip concreto con motivo `state_entry_corrupt`, cosi' che il resto del
      modulo veda sempre e solo dict ben formati e non possa mai sollevare
      un'eccezione sul percorso caldo della sintesi.
    """
    global _FAIL_SAFE
    _FAIL_SAFE = False
    if not _STATE_PATH or not os.path.isfile(_STATE_PATH):
        return {}
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            raise ValueError(f"radice e' {type(raw).__name__}, non un dict")
    except (OSError, ValueError) as e:
        _FAIL_SAFE = True
        print(f"[tts-backend-state] BOOT: stato PRESENTE ma ILLEGGIBILE "
              f"({e}) - fail-safe attivo: TUTTI i modelli sono considerati "
              f"scattati (Cloudflare disabilitato) finche' un reset "
              f"esplicito dall'admin non li riarma singolarmente. "
              f"path={_STATE_PATH}", flush=True)
        return {}

    data = {}
    tripped_models = []
    for model_key, entry in raw.items():
        if isinstance(entry, dict):
            data[model_key] = entry
            if entry.get("tripped_at"):
                tripped_models.append(model_key)
        else:
            # Voce per-modello non riconoscibile (schema diverso da quello
            # atteso): stesso criterio del file illeggibile, applicato al
            # singolo modello. Non e' leggibile, quindi vale "scattato", mai
            # "pulito" - e mai un'eccezione propagata al chiamante.
            print(f"[tts-backend-state] BOOT: voce di stato per "
                  f"{model_key!r} non e' un dict ({type(entry).__name__}) - "
                  f"trattata come scattata finche' un reset esplicito non la "
                  f"riscrive.", flush=True)
            data[model_key] = _failsafe_placeholder(
                "state_entry_corrupt",
                f"voce di stato non e' un dict ({type(entry).__name__})",
            )
            tripped_models.append(model_key)

    if tripped_models:
        print(f"[tts-backend-state] BOOT: stato ricaricato con backend gia' "
              f"scattato per: {', '.join(sorted(tripped_models))}. "
              f"Cloudflare resta disabilitato per questi modelli finche' un "
              f"reset esplicito dall'admin.", flush=True)
    return data


def _save():
    """Persiste _CACHE su disco: tmp + fsync + os.replace, riusando il
    primitivo condiviso `community_store.atomic_write_json` (stesso usato da
    token/pagamenti/voucher/usage) invece di una seconda implementazione
    inline. Verifica rileggendo, con retry+backoff (3 tentativi) come
    `gemini_tts.set_admin_disabled`: un trip() riuscito solo in memoria e mai
    arrivato su disco e' il caso peggiore per un interruttore a senso unico,
    perche' un riavvio del processo lo dimentica e rimette in produzione un
    backend guasto senza che nessuno lo sappia. Il fallimento e' quindi
    loggato in modo evidente, non un semplice print silenzioso.

    Va sempre chiamata sotto `_LOCK` (dal chiamante): `_CACHE` non cambia
    durante il retry. Ritorna True se persistito e verificato, False
    altrimenti.
    """
    if not _STATE_PATH:
        return False
    snapshot = dict(_CACHE)
    last_err = None
    for attempt in range(3):
        try:
            community_store.atomic_write_json(_STATE_PATH, snapshot,
                                               fsync=True, indent=2)
            with open(_STATE_PATH, "r", encoding="utf-8") as f:
                check = json.load(f)
            if check == snapshot:
                return True
            last_err = ValueError("rilettura post-scrittura non combacia")
        except (OSError, ValueError) as e:
            last_err = e
        if attempt < 2:
            time.sleep(0.2 * (attempt + 1))
    print(f"[tts-backend-state] ERROR: stato NON persistito su disco dopo 3 "
          f"tentativi ({last_err}) - lo stato in memoria e' aggiornato ma un "
          f"riavvio del processo ripristinerebbe quello precedente da disco: "
          f"se questo era un trip, Cloudflare potrebbe tornare attivo senza "
          f"che nessuno lo sappia. Verificare spazio disco / permessi su "
          f"{_STATE_PATH}.", flush=True)
    return False


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _failsafe_placeholder(trip_reason, trip_detail):
    """Voce sintetica "gia' scattata" per un modello privo di un valore
    concreto quando il fail-safe (globale o per-voce) e' attivo. Fattorizzata
    per non far divergere le due forme (`state()` e `_load()` per lo schema
    per-voce corrotto) e per essere l'unica sorgente usata anche da
    `_entry_for_mutation()`."""
    return {
        "active": "vertex",
        "tripped_at": _now(),
        "trip_reason": trip_reason,
        "trip_detail": trip_detail,
        "trip_job_id": None,
        "consecutive_failures": 0,
        "notified": False,
    }


def state(model_key):
    """Stato corrente del modello. Non solleva mai eccezioni: `_CACHE`
    contiene solo dict ben formati (sanificati in `_load()`), e per i
    model_key assenti applica il fallback fail-safe (vedi `_FAIL_SAFE`).
    Lettura pura: a differenza di `_entry_for_mutation()`, non scrive mai in
    `_CACHE`."""
    with _LOCK:
        entry = _CACHE.get(model_key)
        if entry is not None:
            return dict(entry)
        if _FAIL_SAFE:
            # Fail-safe globale attivo (file di stato illeggibile al boot) e
            # questo modello non ha ancora un valore concreto (nessun reset
            # esplicito ricevuto da allora): consideralo scattato, mai
            # pulito.
            return _failsafe_placeholder(
                "state_file_unreadable",
                "stato precedente non ricostruibile dal disco al boot",
            )
        return {}


def is_tripped(model_key):
    return bool(state(model_key).get("tripped_at"))


def _entry_for_mutation(model_key):
    """Restituisce `(entry, existed)` per `model_key`, l'UNICO punto in cui
    un mutatore ottiene la voce da modificare. Chiamare sempre sotto `_LOCK`.

    Se la voce esiste gia' in `_CACHE`, la ritorna cosi' com'e' (`existed`
    True). Altrimenti la crea e la inserisce: se il fail-safe globale e'
    attivo, la voce creata e' GIA' scattata (stessa causa del fallback di
    `state()`), non un dict vuoto - senza questo, un mutatore che tocca un
    solo campo (`record_failure`, `record_success`, `mark_notified`)
    scriverebbe una voce "pulita per omissione" priva di `tripped_at`, che da
    quel momento scavalcherebbe il fallback fail-safe in `state()` senza che
    nessuno abbia mai chiamato `reset()`: esattamente il riarmo silenzioso
    che questo modulo esiste per impedire. Difetto corretto in questo giro:
    prima le tre funzioni costruivano ciascuna la propria voce vuota via
    `_CACHE.setdefault(model_key, {})`, ignorando `_FAIL_SAFE`.

    `existed=False` segnala che la voce e' stata appena creata da QUESTA
    chiamata: serve a `trip()` per continuare a distinguere "gia' scattato
    per un trip reale precedente" da "appena materializzato ora dal
    fail-safe", perche' la prima `trip()` reale su un modello scattato solo
    virtualmente deve comunque ritornare True e registrare la causa vera, non
    essere scavalcata dalla propria materializzazione fail-safe.
    """
    entry = _CACHE.get(model_key)
    if entry is not None:
        return entry, True
    entry = _failsafe_placeholder(
        "state_file_unreadable",
        "stato precedente non ricostruibile dal disco al boot",
    ) if _FAIL_SAFE else {}
    _CACHE[model_key] = entry
    return entry, False


def _safe_int(value, default=0):
    """Converte in int senza mai sollevare. Un `consecutive_failures` non
    numerico letto da disco (schema diverso di una versione precedente, o
    corruzione parziale della singola voce) vale `default`, non un'eccezione
    che ucciderebbe un job sul percorso caldo della sintesi: un contatore
    illeggibile non e' evidenza di N fallimenti reali, e ripartire da 0 e' la
    scelta piu' conservativa (non fa scattare nulla da solo - la soglia resta
    decisa dal chiamante confrontando con ABM_CF_TRIP_FAILURES)."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def trip(model_key, *, reason, detail, job_id):
    """Fa scattare il breaker. True solo al PRIMO chiamante.

    Con piu' job in corso, N thread scoprono l'avaria nello stesso istante:
    il ritorno booleano sotto lock e' cio' che permette di mandare una sola
    email all'admin senza un secondo meccanismo di deduplica.

    Se il modello era gia' scattato solo "virtualmente" per fail-safe (nessun
    valore concreto in _CACHE), `_entry_for_mutation` la materializza qui
    sotto con `existed=False`: il controllo idempotente ignora percio' il
    `tripped_at` che il fail-safe vi ha appena scritto e procede a
    sovrascriverlo con i dati reali. Non e' un secondo trip - prima d'ora non
    esisteva alcun record concreto per questo modello.
    """
    with _LOCK:
        entry, existed = _entry_for_mutation(model_key)
        if existed and entry.get("tripped_at"):
            return False
        entry.update({
            "active": "vertex",
            "tripped_at": _now(),
            "trip_reason": reason,
            "trip_detail": str(detail)[:300],
            "trip_job_id": job_id,
            "notified": False,
        })
        _save()
        print(f"[tts-backend-state] TRIP {model_key}: {reason} ({detail})")
        return True


def mark_notified(model_key):
    with _LOCK:
        entry, _existed = _entry_for_mutation(model_key)
        entry["notified"] = True
        _save()


def reset(model_key):
    """Rientro manuale su Cloudflare. True se c'era davvero un trip da
    azzerare - incluso il caso in cui il trip fosse solo virtuale (fail-safe,
    nessun record concreto ancora presente)."""
    with _LOCK:
        had_trip = is_tripped(model_key)
        entry, _existed = _entry_for_mutation(model_key)
        entry.update({
            "active": "cloudflare",
            "tripped_at": None,
            "trip_reason": None,
            "trip_detail": None,
            "trip_job_id": None,
            "consecutive_failures": 0,
            "notified": False,
        })
        _save()
        print(f"[tts-backend-state] RESET {model_key} (aveva trip: {had_trip})")
        return had_trip


def record_failure(model_key):
    """Incrementa e ritorna i fallimenti consecutivi. Non fa scattare nulla.

    Vedi `_safe_int`: un `consecutive_failures` malformato letto da disco non
    deve mai far sollevare questa funzione, dichiarata dal modulo come
    chiamata per ogni fallimento di sintesi (percorso caldo)."""
    with _LOCK:
        entry, _existed = _entry_for_mutation(model_key)
        entry["consecutive_failures"] = _safe_int(entry.get("consecutive_failures", 0)) + 1
        _save()
        return entry["consecutive_failures"]


def record_success(model_key):
    with _LOCK:
        entry, _existed = _entry_for_mutation(model_key)
        if entry.get("consecutive_failures"):
            entry["consecutive_failures"] = 0
            _save()
