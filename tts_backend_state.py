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

Forma su disco: `{"version": 2, "_credit": {...ledger...}, "models":
{model_key: {...}}}`. Il ledger della spesa Cloudflare vive SEMPRE sotto la
chiave riservata top-level `_credit`, mai dentro lo spazio dei `model_key`
(`_CACHE` in memoria contiene solo voci di modello: il ledger e' un dict
separato, `_CREDIT`). Questo rende impossibile, per costruzione, la
collisione fra un `model_key` chiamato letteralmente `_credit` e il ledger:
il primo vivrebbe sotto `models["_credit"]`, il secondo resta al top level -
percorsi diversi, mai fusi.

Riconoscimento del formato: SOLO dal marcatore esplicito `version`, mai
dalla forma dei dati. Un file scritto dalle versioni precedenti (prima di
questo modulo, e prima di questo stesso giro di fix) non contiene mai la
chiave `version`: nessun codice precedente l'ha mai scritta. Percio':

- `version` ASSENTE dal file -> formato vecchio piatto: ogni chiave
  top-level diversa da `_credit` e' una voce di modello, `models` e
  `version` comprese se mai comparissero con quel nome (un `model_key`
  chiamato letteralmente cosi' e' un dato legittimo del formato vecchio, non
  un segnale). Migrato in memoria e riscritto nel formato nuovo alla
  prossima `_save()`.
- `version` presente e uguale esattamente all'intero 2 -> formato nuovo: le
  voci di modello vivono SOLO sotto `models`; qualunque altra chiave
  top-level (incluse `_credit` e `version` stesse) non e' mai una voce di
  modello.
- `version` presente ma diverso (tipo sbagliato, o valore intero
  sconosciuto/futuro) -> dato illeggibile: stessa gravita' di un JSON
  invalido, fail-safe sull'intero file. Non viene MAI interpretato come
  formato vecchio: un formato futuro letto come piatto perderebbe di nuovo
  dei trip in silenzio, esattamente il difetto che questo marcatore esiste
  per escludere (in precedenza il segnale era la sola presenza/forma della
  chiave `models`, ingannabile da un `model_key` vecchio chiamato
  letteralmente `models`: l'intero file, non solo la voce collidente,
  andava perso in silenzio).

Una precedente versione di questo modulo usava la presenza/forma della
chiave `models` come euristica di formato: si e' rivelata ambigua (un
model_key del formato vecchio chiamato `models` viene scambiato per il
contenitore) e sostituita da questo marcatore esplicito.

File di stato: <data_dir>/_tts_backend_state.json
"""
import json
import math
import os
import threading
import time
from datetime import datetime, timezone

import community_store

_STATE_PATH = None
_LOCK = threading.RLock()

# Voci per-modello del circuit breaker (model_key -> entry). Non contiene MAI
# la chiave riservata del ledger credito (vedi _CREDIT_KEY / _CREDIT sotto):
# i due spazi sono tenuti separati per costruzione, non per convenzione.
_CACHE = {}

# Chiave riservata top-level su disco per il ledger della spesa Cloudflare, e
# chiave (sempre top-level) sotto cui vivono le voci di modello nel formato
# nuovo. Nessuna delle due puo' mai comparire come model_key reale in
# _CACHE: un model_key letteralmente uguale a una di queste due stringhe
# finisce comunque annidato dentro `models[...]`, quindi non collide mai col
# ledger ne' con il contenitore stesso.
_CREDIT_KEY = "_credit"
_MODELS_KEY = "models"
_VERSION_KEY = "version"

# Numero di formato scritto da questo modulo. L'UNICO segnale usato per
# distinguere il formato nuovo (voci di modello sotto `_MODELS_KEY`) dal
# formato vecchio piatto (voci di modello mescolate al top level): mai la
# forma dei dati, vedi il docstring di modulo. Sentinella distinta da None
# per poter distinguere "chiave assente" (formato vecchio) da "chiave
# presente con valore null/di tipo sbagliato" (dato illeggibile).
_STATE_VERSION = 2
_VERSION_ABSENT = object()

# Ledger della spesa Cloudflare: dict indipendente da _CACHE, mai annidato al
# suo interno. Vedi _default_credit_ledger() per la forma.
_CREDIT = {}

# True quando il file di stato ESISTEVA ma non e' stato letto correttamente
# (I/O, JSON invalido, radice non-dict). Governa solo il fallback di
# `state()`/`is_tripped()` per i model_key che non hanno (ancora) una voce
# concreta in _CACHE: una volta che un modello riceve un valore esplicito
# (trip o reset), quel valore concreto prevale sempre su questo flag.
_FAIL_SAFE = False

_FILENAME = "_tts_backend_state.json"

# Soglia di pre-allarme sul credito, in USD (la valuta in cui Cloudflare
# denomina il credito AI Gateway). Il default valeva 5 EUR prima che il
# credito fosse riportato alla valuta del fornitore: 5 USD e' lo stesso
# ordine di grandezza, non lo stesso importo, e resta comunque un valore che
# ogni installazione seria ridichiara secondo il proprio ritmo di consumo.
_DEFAULT_ALERT_USD = 5.0

# Nomi di variabile gia' segnalati come obsoleti: l'avviso di ripiego vale
# una volta per processo, non a ogni lettura (queste funzioni stanno sul
# percorso caldo della sintesi, un print per chunk sarebbe rumore puro).
_LEGACY_ENV_WARNED = set()


def init(data_dir):
    """Fissa la directory dello stato e ricarica dal disco."""
    global _STATE_PATH, _CACHE
    with _LOCK:
        _STATE_PATH = os.path.join(data_dir, _FILENAME)
        _CACHE = _load()


def _default_credit_ledger():
    return {"spent_usd": 0.0, "alerted": False}


def _parse_credit_ledger(raw_credit):
    """Sanifica la voce del ledger letta da disco (chiave riservata
    `_CREDIT_KEY`, mai un model_key). Non solleva mai: una voce assente, non
    un dict, o con `spent_usd` di forma inattesa (stringa non numerica,
    None, NaN/Infinity - vedi `_safe_float`) degrada al ledger vuoto (0 speso,
    non ancora segnalato). E' la scelta piu' conservativa: nel caso peggiore
    genera un allarme di troppo dopo una ricarica, mai zero quando servirebbe
    (a differenza di un residuo rimasto +Infinity per un valore non finito
    mai sanificato).

    MIGRAZIONE valuta: il credito Cloudflare e' denominato in USD, ed e' in
    USD che il ledger tiene i conti. Un file scritto prima di questo giro
    porta `spent_eur`: viene riconvertito in USD col cambio dichiarato
    (`ABM_GEMINI_USD_EUR_RATE`, la stessa variabile usata da Gemini,
    Speechify e dal calcolo prezzo) invece di essere buttato. Buttarlo
    significherebbe ripartire da 0 speso su un credito gia' consumato: il
    residuo stimato salirebbe di colpo e il pre-allarme resterebbe muto fino
    a esaurimento vero, cioe' fino al failover. La migrazione NON e' legata
    a `_STATE_VERSION`: quel marcatore governa le voci di MODELLO, e
    cambiarlo qui farebbe leggere l'intero stato come illeggibile,
    spegnendo Cloudflare su tutti i modelli al primo avvio dopo il deploy.
    """
    if not isinstance(raw_credit, dict):
        if raw_credit is not None:
            print(f"[tts-backend-state] BOOT: ledger credito "
                  f"({_CREDIT_KEY!r}) non e' un dict "
                  f"({type(raw_credit).__name__}) - ripartito da 0 speso.",
                  flush=True)
        return _default_credit_ledger()
    if "spent_usd" in raw_credit:
        spent_usd = _safe_float(raw_credit.get("spent_usd"))
    elif "spent_eur" in raw_credit:
        rate = usd_eur_rate()
        spent_usd = _safe_float(raw_credit.get("spent_eur")) / rate
        print(f"[tts-backend-state] BOOT: ledger credito in EUR (formato "
              f"precedente) convertito in USD al cambio {rate}: "
              f"{spent_usd:.4f} USD speso.", flush=True)
    else:
        spent_usd = 0.0
    return {
        "spent_usd": spent_usd,
        "alerted": bool(raw_credit.get("alerted")),
    }


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

    Il ledger credito (chiave riservata `_CREDIT_KEY`) e' sempre estratto
    PRIMA di interpretare le voci di modello, ed e' l'unica lettura che lo
    tocca: qualunque sia la sua forma (assente, corrotta, non-dict), non
    viene mai scambiato per un modello scattato, e non appare mai in
    `_CACHE`.

    Formato riconosciuto SOLO dal marcatore esplicito `_VERSION_KEY`, mai
    dalla forma dei dati (vedi il docstring di modulo per il perche'):
    `version` assente -> formato vecchio piatto, ogni chiave diversa da
    `_credit` e' una voce di modello; `version == _STATE_VERSION` (int,
    valore esatto) -> formato nuovo, voci di modello SOLO sotto
    `_MODELS_KEY`; qualunque altro valore di `version` (tipo sbagliato o
    intero sconosciuto) -> dato illeggibile, stesso trattamento fail-safe di
    un JSON invalido, MAI riletto come formato vecchio.
    """
    global _FAIL_SAFE, _CREDIT
    _FAIL_SAFE = False
    _CREDIT = _default_credit_ledger()
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

    version = raw.get(_VERSION_KEY, _VERSION_ABSENT)

    if version is _VERSION_ABSENT:
        # Formato vecchio piatto: nessuna chiave riservata per le voci di
        # modello, che vivono mescolate al top level. Solo `_credit' e'
        # riservata; QUALUNQUE altra chiave, "models" o "version" comprese
        # se un domani comparissero con quel nome in un file di questo
        # formato, e' una voce di modello vera - mai un segnale di formato
        # (era esattamente questo, basato sulla forma di `models`, il difetto
        # del giro precedente: un `model_key` reale chiamato `models`
        # veniva scambiato per il contenitore nuovo, perdendo in silenzio
        # ogni altro modello dello stesso file).
        _CREDIT = _parse_credit_ledger(raw.get(_CREDIT_KEY))
        model_items = [(k, v) for k, v in raw.items() if k != _CREDIT_KEY]
    elif (isinstance(version, int) and not isinstance(version, bool)
          and version == _STATE_VERSION):
        # Formato nuovo, marcatore riconosciuto: le voci di modello vivono
        # SOLO sotto `_MODELS_KEY`. Qualunque altra chiave top-level
        # (`_credit` e `version` comprese) non e' mai una voce di modello.
        models_raw = raw.get(_MODELS_KEY)
        if not isinstance(models_raw, dict):
            _FAIL_SAFE = True
            print(f"[tts-backend-state] BOOT: stato PRESENTE, formato "
                  f"nuovo ({_VERSION_KEY}={_STATE_VERSION}) ma "
                  f"{_MODELS_KEY!r} non e' un dict "
                  f"({type(models_raw).__name__}) - fail-safe attivo: "
                  f"TUTTI i modelli sono considerati scattati (Cloudflare "
                  f"disabilitato) finche' un reset esplicito dall'admin "
                  f"non li riarma singolarmente. path={_STATE_PATH}",
                  flush=True)
            return {}
        _CREDIT = _parse_credit_ledger(raw.get(_CREDIT_KEY))
        model_items = list(models_raw.items())
    else:
        # Marcatore `version` presente ma non riconosciuto (tipo sbagliato,
        # o intero futuro/sconosciuto): NON viene mai interpretato come
        # formato vecchio, altrimenti un formato futuro letto come piatto
        # perderebbe di nuovo dei trip in silenzio. Stessa gravita' di un
        # JSON invalido: fail-safe sull'intero file, ledger compreso (resta
        # al default gia' assegnato sopra - non ci fidiamo nemmeno della sua
        # posizione in un formato che non riconosciamo).
        _FAIL_SAFE = True
        print(f"[tts-backend-state] BOOT: stato PRESENTE con marcatore "
              f"{_VERSION_KEY!r} non riconosciuto ({version!r}) - fail-safe "
              f"attivo: TUTTI i modelli sono considerati scattati "
              f"(Cloudflare disabilitato) finche' un reset esplicito "
              f"dall'admin non li riarma singolarmente. "
              f"path={_STATE_PATH}", flush=True)
        return {}

    data = {}
    tripped_models = []
    for model_key, entry in model_items:
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
    """Persiste _CACHE (voci di modello) e _CREDIT (ledger) su disco nella
    forma nuova `{"version": 2, "_credit": {...}, "models": {...}}`, tmp +
    fsync + os.replace, riusando il primitivo condiviso
    `community_store.atomic_write_json` (stesso usato da
    token/pagamenti/voucher/usage) invece di una seconda implementazione
    inline. Verifica rileggendo, con retry+backoff (3 tentativi) come
    `gemini_tts.set_admin_disabled`: un trip() riuscito solo in memoria e mai
    arrivato su disco e' il caso peggiore per un interruttore a senso unico,
    perche' un riavvio del processo lo dimentica e rimette in produzione un
    backend guasto senza che nessuno lo sappia. Il fallimento e' quindi
    loggato in modo evidente, non un semplice print silenzioso.

    Va sempre chiamata sotto `_LOCK` (dal chiamante): `_CACHE`/`_CREDIT` non
    cambiano durante il retry. Ritorna True se persistito e verificato, False
    altrimenti.

    `_CREDIT` e' gia' sanificato (solo float finiti, vedi `_safe_float`) da
    ogni punto che lo scrive (`add_spend`, `reset_spend`,
    `claim_credit_alert`, `mark_credit_alerted`) e da `_parse_credit_ledger`
    al caricamento: uno snapshot con un NaN/Infinity al suo interno
    romperebbe il confronto `check == snapshot` qui sotto (il JSON round-trip
    di NaN produce un oggetto float diverso, non uguale a se stesso) per
    QUALUNQUE chiamata a `_save()` nell'intero modulo, non solo per il
    ledger - da cui l'obbligo di non lasciarlo mai entrare non sanificato.
    """
    if not _STATE_PATH:
        return False
    snapshot = {
        _VERSION_KEY: _STATE_VERSION,
        _CREDIT_KEY: dict(_CREDIT),
        _MODELS_KEY: dict(_CACHE),
    }
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
    decisa dal chiamante confrontando con ABM_CF_TRIP_FAILURES).

    `OverflowError` e' catturata accanto a `TypeError`/`ValueError`: e' il
    difetto gemello di `_safe_float` con i non finiti. `int(value)` su un
    valore gia' `float` non passa da nessuna conversione stringa, quindi
    `int(float('nan'))` solleva `ValueError` (catturato), ma
    `int(float('inf'))` solleva `OverflowError` - non catturata sarebbe
    esattamente la stessa classe di crash silenzioso sul percorso caldo che
    questa funzione esiste per evitare."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
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


# --- Ledger della spesa Cloudflare -----------------------------------------
# Il credito AI Gateway e' unico per l'account: la spesa di ogni modello lo
# intacca, quindi il ledger e' globale e vive nel dict `_CREDIT`, isolato da
# `_CACHE` (vedi `_CREDIT_KEY` / `_MODELS_KEY` e il docstring di modulo per
# la forma su disco e perche' i due spazi non si mescolano mai).


def _f_env(name, default):
    try:
        return float((os.environ.get(name, "") or "").replace(",", ".") or default)
    except (TypeError, ValueError):
        return float(default)


def _warn_legacy_env(old_name, new_name, converted_usd):
    """Avvisa UNA volta per processo che si sta usando un nome obsoleto.

    Non solleva e non blocca: il valore convertito viene usato comunque. Chi
    legge questo avviso ha una configurazione che funziona ma denomina il
    credito in una valuta che Cloudflare non usa, e va allineata alla prima
    occasione utile.
    """
    if old_name in _LEGACY_ENV_WARNED:
        return
    _LEGACY_ENV_WARNED.add(old_name)
    print(f"[tts-backend-state] {old_name} e' obsoleta: il credito "
          f"Cloudflare e' denominato in USD. Valore convertito al cambio "
          f"({converted_usd:.2f} USD) e usato lo stesso. Impostare "
          f"{new_name} nell'unit systemd e rimuovere la vecchia.",
          flush=True)


def _safe_float(value, default=0.0):
    """Converte in float senza mai sollevare. Stesso ruolo di `_safe_int`
    (righe sopra) ma per i campi del ledger credito: un `spent_usd` di forma
    inattesa letto da disco (stringa non numerica, `None`, lista, dict - file
    modificato a mano, corruzione parziale, futura evoluzione di schema) vale
    `default`, non un'eccezione. `add_spend` in particolare e' pensata per
    essere chiamata a ogni chunk sintetizzato su Cloudflare: una singola voce
    corrotta non deve poter uccidere ogni chiamata successiva sul percorso
    caldo della sintesi.

    Un valore convertibile ma NON finito (`NaN`, `Infinity`, `-Infinity` -
    tutti float validi per Python/JSON) e' trattato come malformato quanto
    una stringa non numerica: degrada a `default`, non passa. Senza questo
    controllo, due guasti silenziosi riprodotti in review: (1) `spent_usd =
    -Infinity` rende `credit_left_usd()` = `+Infinity`, spegnendo il
    pre-allarme per sempre senza errori; (2) `spent_usd = NaN` sopravvive a
    un'operazione aritmetica reale (resta NaN), e un NaN scritto su disco
    rompe il confronto `check == snapshot` di OGNI `_save()` successivo
    nell'intero modulo (round-trip JSON di NaN produce un nuovo oggetto float
    che non e' mai `==` a se stesso), non solo per il ledger - da cui il
    falso log critico "stato NON persistito" su trip/reset/record_failure di
    qualunque modello."""
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(result):
        return default
    return result


def add_spend(model_key, usd):
    """Accumula la spesa stimata di una chiamata sul ledger locale, in USD.

    USD e non EUR perche' e' la valuta in cui Cloudflare denomina il credito
    e fattura le tariffe Workers AI: il ledger deve poter essere confrontato
    a occhio col saldo che l'admin legge sulla dashboard del fornitore, senza
    un cambio di mezzo che ne sposta le cifre.

    `model_key` non e' usato per ripartire la spesa (il credito e' unico per
    l'account, vedi sopra): resta nella firma per simmetria con le altre
    funzioni di questo modulo chiamate dal percorso di sintesi, e per una
    futura rottura di spesa per modello se mai servisse."""
    with _LOCK:
        _CREDIT["spent_usd"] = _safe_float(_CREDIT.get("spent_usd")) + _safe_float(usd)
        _save()


def reset_spend():
    """Azzera il ledger: da chiamare quando l'admin ricarica il credito.

    E' l'UNICA cosa che riarma il pre-allarme (`alerted` torna False insieme a
    `spent_usd`), quindi la via che la raggiunge deve restare percorribile
    anche quando NON e' avvenuto alcun failover: il ciclo normale del credito
    e' "residuo sotto soglia -> email di pre-allarme -> ricarica -> topup",
    tutto con Cloudflare ancora sano. Legarla al rientro dal breaker (come
    faceva il solo ramo `topup` della POST `action="reset"`, raggiungibile
    unicamente col pulsante di rientro abilitato, cioe' solo dopo un trip)
    la rendeva irraggiungibile proprio in quello scenario: l'allarme sarebbe
    partito una volta sola nella vita dell'installazione. Vedi
    l'azione `POST /admin/api/tts_backend {"action": "topup"}`.
    """
    global _CREDIT
    with _LOCK:
        _CREDIT = _default_credit_ledger()
        _save()


def usd_eur_rate():
    """Cambio USD->EUR dichiarato (`ABM_GEMINI_USD_EUR_RATE`, default 0.86).

    E' la STESSA variabile gia' usata da Gemini, Speechify e dal calcolo del
    prezzo al cliente: il credito Cloudflare non introduce un secondo cambio
    per conto proprio, altrimenti due parti dell'app convertirebbero lo
    stesso dollaro a due tassi diversi. Serve qui per due sole cose: migrare
    un ledger vecchio scritto in EUR, e affiancare l'equivalente in euro
    all'importo in dollari. MAI per decidere un allarme: soglia, saldo e
    spesa si confrontano fra loro sempre in USD, cosi' un ritocco del cambio
    non puo' far scattare (o tacere) il pre-allarme.

    Un valore <= 0 o non numerico e' inutilizzabile (dividerebbe per zero
    nella migrazione): degrada al default invece di sollevare.
    """
    rate = _f_env("ABM_GEMINI_USD_EUR_RATE", 0.86)
    if not rate or rate <= 0:
        return 0.86
    return rate


def to_eur(usd):
    """Equivalente in EUR di un importo in USD, per il solo DISPLAY.

    Gli importi autorevoli del credito Cloudflare sono in USD: questa
    funzione esiste perche' pannello ed email possano affiancare la cifra in
    euro a chi ragiona in euro, non per riportare la contabilita' in EUR.
    """
    return _safe_float(usd) * usd_eur_rate()


def _declared_balance_usd():
    """Saldo dichiarato dall'admin, in USD, con ripiego sul nome vecchio.

    `ABM_CF_CREDIT_BALANCE_USD` e' il nome corrente. Se non e' dichiarato ma
    lo e' `ABM_CF_CREDIT_BALANCE_EUR` (il nome che questa variabile aveva
    prima che il credito tornasse alla valuta in cui Cloudflare lo denomina),
    il valore viene convertito al cambio e usato lo stesso, con un avviso a
    stdout. Il ripiego non e' cortesia: senza, un deploy che arriva prima
    dell'aggiornamento dell'unit systemd leggerebbe 0, e un saldo 0 SPEGNE
    il pre-allarme in silenzio - l'admin scoprirebbe il credito finito dal
    failover, cioe' proprio cio' che il pre-allarme esiste per evitare.
    """
    if (os.environ.get("ABM_CF_CREDIT_BALANCE_USD", "") or "").strip():
        return _f_env("ABM_CF_CREDIT_BALANCE_USD", 0.0)
    if (os.environ.get("ABM_CF_CREDIT_BALANCE_EUR", "") or "").strip():
        usd = _f_env("ABM_CF_CREDIT_BALANCE_EUR", 0.0) / usd_eur_rate()
        _warn_legacy_env("ABM_CF_CREDIT_BALANCE_EUR",
                         "ABM_CF_CREDIT_BALANCE_USD", usd)
        return usd
    return 0.0


def _alert_threshold_usd():
    """Soglia di pre-allarme in USD, con lo stesso ripiego sul nome vecchio.

    Qui il ripiego pesa meno che sul saldo (un default esiste), ma lasciare i
    due nomi disallineati darebbe la combinazione peggiore: saldo convertito
    dal nome vecchio e soglia presa dal default, cioe' una soglia diversa da
    quella che l'admin crede di aver impostato.
    """
    if (os.environ.get("ABM_CF_CREDIT_ALERT_USD", "") or "").strip():
        return _f_env("ABM_CF_CREDIT_ALERT_USD", _DEFAULT_ALERT_USD)
    if (os.environ.get("ABM_CF_CREDIT_ALERT_EUR", "") or "").strip():
        usd = _f_env("ABM_CF_CREDIT_ALERT_EUR", 0.0) / usd_eur_rate()
        _warn_legacy_env("ABM_CF_CREDIT_ALERT_EUR",
                         "ABM_CF_CREDIT_ALERT_USD", usd)
        return usd
    return _DEFAULT_ALERT_USD


def credit_check_enabled():
    """`False` se l'admin ha spento il controllo del credito Cloudflare
    (`ABM_CF_CREDIT_CHECK=0`), `True` per default.

    Esiste perche' il pre-allarme e' utile soltanto su un credito prepagato
    che si esaurisce senza preavviso. Con la ricarica automatica a soglia
    attiva sul pannello Cloudflare, il credito si ricarica da solo: il
    residuo stimato da questo modulo non descrive piu' nulla di azionabile e
    l'email di pre-allarme diventerebbe rumore periodico su una condizione
    che il fornitore ha gia' risolto da solo.

    Spegne SOLO l'allarme e il residuo, MAI la contabilita': `add_spend()`
    continua ad accumulare `spent_usd` a ogni chiamata. La spesa cumulata
    serve comunque - e' il solo modo per sapere quanto costa davvero
    Cloudflare - e resta visibile nel pannello admin; e' il "quanto ne
    resta" a perdere significato, non il "quanto ne ho speso".

    Nota su cosa NON e' equivalente: lasciare `ABM_CF_CREDIT_BALANCE_USD` a 0
    ottiene il silenzio per un'altra strada (nessun saldo dichiarato =>
    nessun allarme possibile), ma dice "non so quanto credito ho", mentre
    questa variabile dice "non voglio che il credito venga sorvegliato". La
    differenza conta al primo incidente: davanti a un pannello muto, la
    prima serve a distinguere una configurazione dimenticata da una scelta.
    """
    raw = (os.environ.get("ABM_CF_CREDIT_CHECK", "") or "").strip().lower()
    if not raw:
        return True
    return raw in ("true", "1", "yes", "on")


def credit_balance_usd():
    """Saldo dichiarato dall'admin (`ABM_CF_CREDIT_BALANCE_USD`), 0 se non
    dichiarato. PURA: nessuna mutazione, nessun consumo dell'allarme.

    Esposta per la stessa ragione di `credit_alert_threshold_usd()`: chi deve
    decidere se il residuo e' un numero conoscibile (0 = nessun saldo
    dichiarato, quindi `credit_left_usd()` non significa nulla) non deve
    rileggersi l'ambiente per conto proprio con una convenzione di parsing
    diversa da questa.
    """
    return _declared_balance_usd()


def credit_left_usd():
    """Residuo stimato in USD: saldo dichiarato meno speso cumulato.

    E' una STIMA: l'API Cloudflare non restituisce i token, quindi la spesa e'
    calcolata dal chiamante sui secondi di audio prodotti. Vedi §10.2 della
    spec per l'esito della ricognizione sull'API del saldo.
    """
    with _LOCK:
        spent = _safe_float(_CREDIT.get("spent_usd"))
    return _declared_balance_usd() - spent


def credit_spent_usd():
    """Spesa Cloudflare cumulata sul ledger locale, in USD. PURA.

    E' l'unica meta' del conto che resta significativa quando il controllo
    del credito e' spento (`ABM_CF_CREDIT_CHECK=0`): senza un saldo da
    sorvegliare il "quanto ne resta" non descrive nulla, ma il "quanto ne ho
    speso" continua a misurare cosa costa Cloudflare. Il pannello admin la
    mostra al posto del residuo in quel caso.
    """
    with _LOCK:
        return _safe_float(_CREDIT.get("spent_usd"))


def declared_balance_usd():
    """Saldo Cloudflare DICHIARATO dall'admin (`ABM_CF_CREDIT_BALANCE_USD`),
    non il residuo. PURA: nessuna mutazione, nessun consumo dell'allarme.

    Esiste perche' `credit_left_usd()` ritorna un numero anche quando nessun
    saldo e' stato dichiarato - in quel caso e' la spesa cambiata di segno,
    non una misura: `credit_alert_pending()`/`claim_credit_alert()` lo sanno
    e con saldo <= 0 non allarmano mai. Chi deve MOSTRARE il residuo (log,
    pannello, email) usa questa funzione per distinguere "residuo basso" da
    "nessun saldo dichiarato" invece di stampare un negativo senza senso."""
    return _declared_balance_usd()


def credit_alert_threshold_usd():
    """Soglia di pre-allarme (`ABM_CF_CREDIT_ALERT_USD`), la stessa letta da
    `credit_alert_pending()`/`claim_credit_alert()`. Esposta perche' chi
    manda l'email possa dichiarare il numero all'admin senza rileggere
    l'ambiente per conto proprio (due letture divergono nel tempo). PURA:
    nessuna mutazione, nessun consumo dell'allarme."""
    return _alert_threshold_usd()


def credit_alert_pending():
    """PURA: nessuna mutazione, nessuna scrittura su `_CREDIT`, nessuna
    materializzazione di entry, nessun tocco al disco. Ritorna `True` se il
    residuo stimato e' sotto soglia e l'allarme non e' ancora stato
    consumato da `claim_credit_alert()`. Chiamabile un numero arbitrario di
    volte (es. da una pagina di stato admin che vuole solo MOSTRARE
    "allarme credito: si/no") con lo stesso esito, senza alcun effetto
    collaterale: a differenza della vecchia `should_alert_credit()` (rimossa
    in questo giro), questa funzione non decide mai da sola se l'email va
    mandata e non puo' mai "consumare" l'unico allarme disponibile.

    Con saldo dichiarato a 0 (default) ritorna sempre `False`: sarebbe
    rumore costante su un'installazione che non usa Cloudflare.

    Con il controllo disattivato (`ABM_CF_CREDIT_CHECK=0`, tipicamente
    perche' la ricarica automatica Cloudflare copre gia' l'esaurimento)
    ritorna sempre `False`, prima ancora di leggere saldo e ledger.

    Per il percorso da cui parte davvero l'invio dell'email usare
    `claim_credit_alert()`, MAI questa funzione.
    """
    if not credit_check_enabled():
        return False
    balance = _declared_balance_usd()
    if balance <= 0:
        return False
    with _LOCK:
        if _CREDIT.get("alerted"):
            return False
        spent = _safe_float(_CREDIT.get("spent_usd"))
    return (balance - spent) < _alert_threshold_usd()


def claim_credit_alert():
    """Check-and-set ATOMICO sotto `_LOCK`: ritorna `True` a ESATTAMENTE un
    chiamante quando il residuo stimato scende sotto soglia, poi marca
    l'allarme come dato e lo persiste. Nessun'altra chiamata (anche
    concorrente, anche successiva) puo' piu' ricevere `True` finche' un
    topup (`reset_spend()` con saldo dichiarato rialzato) non riarma
    l'allarme.

    QUESTA E', E DEVE RESTARE, L'UNICA FUNZIONE DA CUI PARTE L'INVIO
    DELL'EMAIL DI ALLARME CREDITO. Chiamarla per qualunque altro scopo (es.
    per popolare una pagina di stato, un log, un contatore) BRUCIA
    silenziosamente l'unica occasione di allarme senza che nessuna email
    parta mai: per una lettura che non deve consumare nulla usare
    `credit_alert_pending()`.

    Verificata sotto concorrenza reale (thread + barrier + sleep fra check e
    uso): N chiamate parallele che vedrebbero tutte le condizioni per
    allarmare, se non fosse per l'atomicita', producono esattamente un
    `True`. Un check-poi-act con `mark_credit_alerted()` chiamata
    separatamente dal chiamante, come in una versione precedente, non
    garantiva questa proprieta': un I/O reale (invio email) fra le due
    chiamate lascia una finestra in cui tutti i chiamanti concorrenti
    leggono ancora `alerted=False`.

    Con `ABM_CF_CREDIT_CHECK=0` ritorna sempre `False` senza toccare il
    ledger: l'allarme non viene ne' dato ne' CONSUMATO, cosi' riaccendere il
    controllo lo ritrova ancora armato invece di averlo perso in silenzio
    mentre era spento.
    """
    if not credit_check_enabled():
        return False
    balance = _declared_balance_usd()
    if balance <= 0:
        return False
    threshold = _alert_threshold_usd()
    with _LOCK:
        if _CREDIT.get("alerted"):
            return False
        spent = _safe_float(_CREDIT.get("spent_usd"))
        if (balance - spent) >= threshold:
            return False
        _CREDIT["alerted"] = True
        _save()
        return True


def mark_credit_alerted():
    """Marca l'allarme come gia' dato, SENZA passare dal controllo soglia di
    `claim_credit_alert()`. Il percorso normale da cui parte l'email resta
    SEMPRE `claim_credit_alert()`: questa funzione esiste solo per chi debba
    marcare l'allarme a prescindere dal residuo attuale (es. nei test che
    simulano "allarme gia' dato" senza attraversare la soglia reale).
    Idempotente: chiamarla piu' volte non ha alcun effetto aggiuntivo, e non
    fa mai scattare una seconda email da sola perche' non e' lei a decidere
    se allarmare."""
    with _LOCK:
        _CREDIT["alerted"] = True
        _save()
