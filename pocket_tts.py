"""Pocket TTS (Kyutai) — motore a chunk diretto sul worker abm-pocket-worker.

Il worker gira su un VPS a canone fisso (repo gfrangiamone/abm-pocket-worker):
una chiamata `POST /v1/synthesize` per chunk, risposta PCM 16-bit mono a
24 kHz quando il chunk e' pronto. Il worker normalizza il testo (numeri,
date, sigle) e tiene le voci di riferimento di ABM (`voxcpm2/voci_inventate`)
come stati gia' calcolati per il modello di ogni lingua: la voce
`pocket:v1:de-DE/Franziska` diventa `de-DE/Franziska` sul worker.

Il worker serve un libro alla volta, una lingua alla volta: un libro si
dichiara (`BookTicket`, id = job di ABM) e aspetta il suo turno in coda; i
chunk di un libro che non e' di turno tornano con 423 e la stima di attesa.
Per l'utente e' il modello «lento» a prezzo basso, MODEL_LABEL.

Due usi, decisi dalla tariffa `ABM_POCKET_RATE_EUR_PER_MCHAR`:
- > 0 (default 11 EUR per milione di caratteri): motore a pagamento per tutti,
  mai gratuito, con un minimo per libro (`ABM_POCKET_MIN_PRICE_EUR`);
- 0: solo per il catalogo dei libri gratuiti (istanze locali), prezzo zero.
Il motore si accende con `ABM_POCKET_URL` + `ABM_POCKET_TOKEN`.
Velocita' ed emozione non si applicano: Pocket legge sempre al ritmo della voce.
"""
import threading
import time

import requests

from env_utils import env_float, env_int, env_str
import pocket_catalog
import pricing_common as _pricing
import retry_util as _retry
from slot_gate import SlotGate
from text_reflow import spoken_title_prefix
from voice_utils import POCKET_VOICE_PREFIX, is_pocket_voice

MODEL_ID = pocket_catalog.MODEL_ID
MODEL_LABEL = pocket_catalog.MODEL_LABEL
SAMPLE_RATE = 24000                 # nativo del worker, fisso
CHUNK_MAX_CHARS = 280               # come VoxCPM: frasi brevi, meno parole saltate
_CHUNK_MIN_CHARS = 80
_CHUNK_CEIL_CHARS = 1000            # POCKET_MAX_CHUNK_CHARS del worker
# Modo catalogo (tariffa 0): sotto il centesimo il prezzo zero e' gratuito
# per `free_result`.
FREE_THRESHOLD_EUR = 0.01
# Il worker tiene il chunk in coda finche' non tocca a lui (POCKET_SYNC_TIMEOUT_S,
# 900 s): l'attesa HTTP la supera di poco.
_HTTP_TIMEOUT_S = 960
_QUEUE_HTTP_TIMEOUT_S = 30
# La stima di consegna sta dentro la stima di prezzo: un worker lento non
# deve rallentarla, meglio nessuna data.
_ETA_HTTP_TIMEOUT_S = 5
# Attesa fra due controlli del turno: un quarto dell'attesa stimata, entro
# questi limiti (il worker tiene in coda un libro che si fa vivo entro 600 s).
_TURN_POLL_MIN_S = 15
_TURN_POLL_MAX_S = 120
_CANCEL_CHECK_S = 5

_gate = SlotGate(lambda: max_concurrency())


def base_url():
    return env_str("ABM_POCKET_URL").rstrip("/")


def api_token():
    return env_str("ABM_POCKET_TOKEN")


def is_available():
    """True sse indirizzo e token del worker sono configurati."""
    return bool(base_url() and api_token())


def max_concurrency():
    """Chunk in volo verso il worker su tutto il processo. Floor a 1."""
    return max(1, env_int("ABM_POCKET_MAX_CONCURRENCY", 32))


def per_job_concurrency():
    """Chunk in volo per singolo job: il worker ha un processo per vCPU (16)."""
    return max(1, env_int("ABM_POCKET_PER_JOB_CONCURRENCY", 16))


def attempts():
    """Tentativi per chunk: coprono un riavvio del worker (deploy, ~60 s)."""
    return max(1, env_int("ABM_POCKET_ATTEMPTS", 5))


def free_slots():
    return _gate.free()


def slot(timeout=None):
    return _gate.slot(timeout=timeout, what="Pocket concurrency slot")


def chunk_max_chars():
    """Cap caratteri/chunk (ABM_POCKET_CHUNK_CHARS), entro il limite del worker."""
    val = env_int("ABM_POCKET_CHUNK_CHARS", CHUNK_MAX_CHARS)
    return max(_CHUNK_MIN_CHARS, min(_CHUNK_CEIL_CHARS, val))


def free_threshold_eur():
    """Soglia di gratuita': zero sul motore a pagamento (mai gratis), il
    centesimo nel modo catalogo."""
    return FREE_THRESHOLD_EUR if not is_paid() else 0.0


def rate_eur_per_mchar():
    """Tariffa all'utente in EUR per milione di caratteri; 0 = modo catalogo."""
    return max(0.0, env_float("ABM_POCKET_RATE_EUR_PER_MCHAR", 11.0))


def min_price_eur():
    """Prezzo minimo di un libro sul motore a pagamento."""
    return max(0.0, env_float("ABM_POCKET_MIN_PRICE_EUR", 0.50))


def is_paid():
    """True se il motore e' a pagamento (tariffa > 0), False nel modo catalogo."""
    return rate_eur_per_mchar() > 0


def is_offered():
    """True se il motore va mostrato agli utenti: configurato e a pagamento.
    Nel modo catalogo resta disponibile solo a chi conosce gli id voce."""
    return is_available() and is_paid()


def priority():
    """Priorita' dei libri di questa istanza nella coda del worker: la
    produzione (10) passa davanti al catalogo (0, istanze locali)."""
    return env_int("ABM_POCKET_PRIORITY", 10)


def max_queue_wait_s():
    """Attesa massima del turno in coda prima di dare il libro per perso."""
    return max(60, env_int("ABM_POCKET_MAX_QUEUE_WAIT_S", 48 * 3600))


def parse_voice_id(voice_id):
    """('v1', 'it-IT', 'Chiara') da 'pocket:v1:it-IT/Chiara'; ValueError altrimenti."""
    if not is_pocket_voice(voice_id):
        raise ValueError(f"Invalid Pocket voice ID: {voice_id!r}")
    model_key, _, ref = voice_id[len(POCKET_VOICE_PREFIX):].partition(":")
    locale, _, name = ref.partition("/")
    if model_key != MODEL_ID or len(locale) != 5 or locale[2] != "-" or not name:
        raise ValueError(f"Invalid Pocket voice ID: {voice_id!r} "
                         f"(expected 'pocket:{MODEL_ID}:<ll-CC>/<Nome>')")
    return model_key, locale, name


def voice_language(voice_id):
    """Lingua a due lettere della voce ('de' da 'pocket:v1:de-DE/Franziska')."""
    return parse_voice_id(voice_id)[1][:2].lower()


def compute_user_price_eur(chars, language=None):
    """Prezzo per `chars` caratteri, stessa forma degli altri motori.

    A pagamento: tariffa piatta per carattere in ogni lingua (il VPS ha un
    canone fisso: nessun costo a carattere, `cost_usd` zero). `list_price_eur`
    e' la tariffa nuda, base della trattenuta su un cancel e della quota
    gratuita; `user_price_eur` ha il minimo per libro e non e' mai zero.
    Modo catalogo: prezzo zero."""
    try:
        chars = max(0, int(chars or 0))
    except (TypeError, ValueError):
        chars = 0
    out = {"chars": chars, "cost_usd": 0.0, "margin_percent": 0.0}
    rate = rate_eur_per_mchar()
    if rate <= 0:
        return {**out, "base_price_eur": 0.0, **_pricing.free_result(0.0, FREE_THRESHOLD_EUR)}
    list_price = round(chars / 1_000_000.0 * rate, 2)
    return {**out, "base_price_eur": list_price, "list_price_eur": list_price,
            "user_price_eur": round(max(list_price, min_price_eur()), 2),
            "is_free": False, "free_threshold_eur": 0.0, "min_price_eur": min_price_eur()}


def estimate_book_cost(chapters, language="it", strip_round=True, strip_square=True):
    """Stima sui caratteri letti (corpo + titolo parlato)."""
    chars_per_chapter, chars_total, _ = _pricing.billable_chars(
        chapters, spoken_title_prefix, strip_round=strip_round, strip_square=strip_square)
    price = compute_user_price_eur(chars_total)
    return {
        "chars_total": chars_total,
        "chars_per_chapter": chars_per_chapter,
        "cost_usd": price["cost_usd"],
        "user_price_eur": price["user_price_eur"],
        "list_price_eur": price["list_price_eur"],
        "is_free": price["is_free"],
        "margin_percent": price["margin_percent"],
        "language": language,
        "model_key": MODEL_ID,
        "model_label": MODEL_LABEL,
    }


class PocketUnavailable(RuntimeError):
    """Worker non configurato (ABM_POCKET_URL / ABM_POCKET_TOKEN)."""


class PocketFatalError(RuntimeError):
    """Errore non ritentabile: voce assente sul worker, lingua o testo rifiutati (4xx)."""


class PocketQueueTimeout(PocketUnavailable):
    """Il libro non e' arrivato in testa alla coda entro `max_queue_wait_s()`:
    il job fallisce col rimborso, come a motore spento."""


def _headers():
    return {"Authorization": f"Bearer {api_token()}"}


class BookTicket:
    """Il posto di un libro (job di ABM) nella coda del worker.

    `join()` lo dichiara con i caratteri da leggere e aspetta che tocchi a
    lui, `close()` lascia il VPS al prossimo (best-effort: il worker
    lo toglie comunque dopo 10 minuti senza notizie). `on_state(stato)` riceve
    posizione e stima (`position`, `wait_s`, `eta_s`, `state`) a ogni
    controllo; `check_cancelled()` interrompe l'attesa. Lo stesso id dopo un
    riavvio di ABM ritrova il suo posto. Con piu' chunk in volo un solo
    thread alla volta interroga la coda: gli altri trovano il turno gia'
    arrivato."""

    def __init__(self, book_id, chars, language, check_cancelled=None, on_state=None,
                 session=None, sleep=None, clock=None):
        self.id = str(book_id)
        self.chars = max(0, int(chars or 0))
        self.language = (language or "it")[:2].lower()
        self.priority = priority()
        self._cancelled = check_cancelled or (lambda: False)
        self._on_state = on_state or (lambda _state: None)
        self._session = session or requests.Session()
        self._sleep = sleep or time.sleep
        self._clock = clock or time.monotonic
        self._wait_lock = threading.Lock()
        self.state = None

    def _url(self):
        return f"{base_url()}/v1/books/{self.id}"

    def _note(self, state):
        if isinstance(state, dict):
            self.state = state
            try:
                self._on_state(state)
            except Exception as e:  # noqa: BLE001 — la coda non dipende dalla UI
                print(f"[pocket] on_state fallita: {e}")

    def chunk_fields(self):
        """Campi del libro per POST /v1/synthesize."""
        return {"book": self.id, "book_chars": self.chars, "priority": self.priority}

    def open(self):
        """Dichiara il libro (o lo ridichiara tenendo il posto); ritorna lo stato."""
        resp = self._session.put(self._url(), json={"lang": self.language, "chars": self.chars,
                                                    "priority": self.priority},
                                 headers=_headers(), timeout=_QUEUE_HTTP_TIMEOUT_S)
        if resp.status_code != 200:
            detail = f"Pocket queue HTTP {resp.status_code}: {(getattr(resp, 'text', '') or '')[:200]}"
            if _retry.is_transient_http(resp.status_code, none_is_transient=False):
                raise _PocketRetry(detail)
            raise PocketFatalError(detail)
        self._note(resp.json())
        return self.state

    def join(self):
        """Dichiara il libro e aspetta il turno: True quando tocca a lui, False
        se il job e' annullato prima. Un worker che non risponde (riavvio) non
        e' un errore: il libro si ridichiara al controllo successivo."""
        try:
            self.open()
        except _NET_ERRORS + (_PocketRetry,) as e:
            print(f"[pocket] dichiarazione del libro {self.id} rimandata: {e}")
        return self.wait_turn()

    def refresh(self):
        """Stato aggiornato; se il worker ha perso il libro lo ridichiara."""
        resp = self._session.get(self._url(), headers=_headers(), timeout=_QUEUE_HTTP_TIMEOUT_S)
        if resp.status_code == 404:
            return self.open()
        if resp.status_code != 200:
            raise _PocketRetry(f"Pocket queue HTTP {resp.status_code}")
        self._note(resp.json())
        return self.state

    def note_queued(self, state):
        """Stato ricevuto con un 423 su un chunk."""
        self._note(state)

    def wait_turn(self):
        """Aspetta che il libro sia di turno. True quando lo e', False se il job
        e' annullato; PocketQueueTimeout oltre `max_queue_wait_s()`. Errori di
        rete durante l'attesa: si riprova al giro dopo."""
        with self._wait_lock:
            return self._wait_turn()

    def _wait_turn(self):
        deadline = self._clock() + max_queue_wait_s()
        state = self.state
        while True:
            if self._cancelled():
                return False
            if state and state.get("state") == "active":
                return True
            if self._clock() > deadline:
                raise PocketQueueTimeout(
                    f"book {self.id} not started within {max_queue_wait_s()} s")
            wait_s = (state or {}).get("wait_s") or 0
            pause = min(_TURN_POLL_MAX_S, max(_TURN_POLL_MIN_S, int(wait_s) // 4))
            end = self._clock() + pause
            while self._clock() < end:
                if self._cancelled():
                    return False
                self._sleep(min(_CANCEL_CHECK_S, max(0.0, end - self._clock())))
            try:
                state = self.refresh()
            except _NET_ERRORS + (_PocketRetry,) as e:
                print(f"[pocket] controllo del turno di {self.id} fallito: {e}")
                state = None

    def close(self):
        try:
            self._session.delete(self._url(), headers=_headers(), timeout=_QUEUE_HTTP_TIMEOUT_S)
        except _NET_ERRORS as e:
            print(f"[pocket] chiusura del libro {self.id} fallita: {e}")


def estimate_delivery(chars, language):
    """Attesa e consegna stimate dal worker per un libro accodato adesso
    (`wait_s`, `eta_s`, `position`), None se il worker non risponde."""
    if not is_available():
        return None
    try:
        resp = requests.get(f"{base_url()}/v1/eta", headers=_headers(),
                            params={"lang": (language or "it")[:2].lower(),
                                    "chars": max(0, int(chars or 0)), "priority": priority()},
                            timeout=_ETA_HTTP_TIMEOUT_S)
        return resp.json() if resp.status_code == 200 else None
    except (_NET_ERRORS + (ValueError,)) as e:
        print(f"[pocket] stima di consegna non disponibile: {e}")
        return None


class _PocketRetry(Exception):
    """Tentativo da rifare: 429/5xx (chunk fallito sul worker, riavvio, coda
    lunga) o errore di rete."""


_NET_ERRORS = (requests.RequestException, TimeoutError, ConnectionError)


def synthesize(text, voice_id, output_path, emotion=None, rate="+0%", max_attempts=None,
               session=None, sleep=None, book=None):
    """Sintetizza `text` sul worker e scrive il PCM in `output_path`.

    Ritorna dict success/bytes_written/sample_rate/channels/billable_chars/
    voice_name. `emotion` e `rate` sono accettati per simmetria con Speechify
    e ignorati. `book` e' il `BookTicket` del libro: se il libro perde il
    turno (423, un libro con priorita' piu' alta) si aspetta il turno e il
    tentativo si rifa'. Raises PocketUnavailable, PocketFatalError,
    ValueError (voce), RuntimeError a tentativi esauriti.
    """
    if not is_available():
        raise PocketUnavailable("Pocket TTS not available (check ABM_POCKET_URL / ABM_POCKET_TOKEN)")
    _, locale, name = parse_voice_id(voice_id)
    if session is None:
        session = requests.Session()
    payload = {"text": text, "voice": f"{locale}/{name}", "lang": locale[:2], "normalize": True,
               **(book.chunk_fields() if book is not None else {})}
    headers = _headers()
    url = base_url() + "/v1/synthesize"
    tries = max_attempts or attempts()

    def _post():
        try:
            with slot():
                return session.post(url, json=payload, headers=headers, timeout=_HTTP_TIMEOUT_S)
        except _NET_ERRORS as e:
            raise _PocketRetry(f"{type(e).__name__}: {e}") from e

    def _once(_attempt):
        resp = _post()
        while resp.status_code == 423 and book is not None:
            # Il libro non e' di turno: attesa in coda fuori dallo slot, poi
            # lo stesso tentativo riparte (l'attesa non e' un errore).
            try:
                book.note_queued(resp.json())
            except ValueError:
                book.note_queued(None)
            if not book.wait_turn():
                raise PocketFatalError("Pocket: job cancelled while queued")
            resp = _post()
        if resp.status_code == 200:
            pcm = resp.content
            if not pcm:
                raise _PocketRetry("risposta senza audio")
            with open(output_path, "wb") as fp:
                fp.write(pcm)
            return {
                "success": True,
                "bytes_written": len(pcm),
                "sample_rate": SAMPLE_RATE,
                "channels": 1,
                "billable_chars": len(text),
                "voice_name": name,
            }
        detail = (getattr(resp, "text", "") or "")[:200]
        if _retry.is_transient_http(resp.status_code, none_is_transient=False):
            raise _PocketRetry(f"HTTP {resp.status_code}: {detail}")
        raise PocketFatalError(f"Pocket HTTP {resp.status_code} (fatal): {detail}")

    kw = {} if sleep is None else {"sleep": sleep}
    try:
        return _retry.retry_call(
            _once, attempts=tries, is_retryable=lambda e: isinstance(e, _PocketRetry),
            wait=lambda attempt, _e: _retry.backoff(attempt, base=5.0, cap=60.0), **kw)
    except _PocketRetry as e:
        raise RuntimeError(f"Pocket synthesis failed after {tries} attempts: {e}") from e
