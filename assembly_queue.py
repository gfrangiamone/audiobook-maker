"""Coda di ammissione per la fase di assembly audio (encode FFmpeg finali).

Modulo FOGLIA: nessun import di progetto (regola anti-import-circolare,
CLAUDE.md §1).

Perche' esiste
--------------
La sintesi TTS gira su servizi esterni (Edge/Google/Gemini/Speechify): la CPU
locale e' quasi ferma durante la generazione dei chunk. Il carico vero arriva
alla fine del job, quando i chunk vengono composti nel file finale:

  - PCM -> AAC/M4B (`pcm_to_aac_m4b`)
  - PCM -> MP3     (`pcm_to_mp3`)
  - MP3 -> M4B     (`_convert_mp3_to_m4b`)
  - ZIP dei capitoli (deflate)

Nessuno di questi comandi passa `-threads` a FFmpeg: ognuno prende da solo
tutti i core disponibili. Con N job che arrivano insieme all'assembly su una
VM a 2 vCPU non si ottiene N volte il throughput, si ottengono N encode
ciascuno N volte piu' lento — e quindi N job vivi in RAM N volte piu' a lungo,
che e' esattamente la pressione che ha portato al freeze del 2026-08-21.

Questa coda e' complementare a `ABM_MAX_CONCURRENT_GLOBAL`: quello RIFIUTA
utenti in ingresso, questa AMMORTIZZA il picco senza rifiutare nessuno.

Priorita'
---------
Gli slot non si servono in ordine di arrivo ma per PRIORITA'. Un job PREMIUM
(voce a pagamento, oppure job con un pagamento consumato) ha gia' bruciato
denaro dell'utente e credito del servizio: tenerlo mezz'ora in fila dietro a
conversioni gratuite e' il modo peggiore di spendere l'unica risorsa scarsa
della macchina. I premium passano davanti; fra pari resta l'ordine di arrivo.

Perche' nessuno resta indietro per sempre: dopo `ABM_ASSEMBLY_STARVE_SEC` in
coda un waiter pesa quanto un premium (anti-starvation), quindi un job
gratuito non puo' essere scavalcato all'infinito da un flusso continuo di
premium — al piu' attende quella finestra oltre il proprio turno naturale.

Nota: gli encode per-capitolo del ramo multi-file restano fuori dalla coda.
Sono interlacciati con la sintesi (uno per capitolo, gia' spalmati nel tempo):
metterli sotto semaforo serializzerebbe l'intera generazione, non l'assembly.

Nota: l'attesa NON e' interrompibile dalla cancellazione. E' voluto: oggi
l'assembly non e' un punto di cancellazione (dopo la sintesi non esiste alcun
check), quindi rendere abortibile la coda cambierebbe la semantica e potrebbe
buttare via un audiolibro gia' sintetizzato e pagato.
"""
import os
import threading
import time

# Attesa massima per uno slot. Scaduta, il job procede COMUNQUE senza slot:
# un permesso trattenuto da un encode patologico non deve appendere per sempre
# un audiolibro gia' sintetizzato (e gia' pagato).
ASSEMBLY_WAIT_TIMEOUT_SEC = float(os.environ.get("ABM_ASSEMBLY_WAIT_TIMEOUT_SEC", "1800"))


def _default_slots():
    """Un core lasciato libero al resto dell'app (Flask, cleanup, SSE)."""
    try:
        n = os.cpu_count() or 2
    except Exception:
        n = 2
    return max(1, n - 1)


def _configured_slots():
    raw = (os.environ.get("ABM_MAX_CONCURRENT_ASSEMBLY") or "").strip()
    if raw:
        try:
            v = int(raw)
            if v > 0:
                return v
        except ValueError:
            pass
    return _default_slots()


MAX_CONCURRENT_ASSEMBLY = _configured_slots()

# Livelli di priorita'. Numeri e non booleani: lasciano spazio a gradazioni
# future (es. un livello intermedio) senza toccare la meccanica della coda.
PRIORITY_NORMAL = 0
PRIORITY_PREMIUM = 10

# Anti-starvation: secondi in coda oltre i quali un waiter viene pesato come
# un premium. Con 0 la promozione e' disattivata (priorita' pura).
ASSEMBLY_STARVE_SEC = float(os.environ.get("ABM_ASSEMBLY_STARVE_SEC", "900"))

_state_lock = threading.Lock()
_waiters = []   # _Waiter in attesa di uno slot
_held = 0       # slot attualmente occupati
_seq = 0        # progressivo di arrivo, per il FIFO a parita' di priorita'


class _Waiter:
    """Un chiamante in coda, con l'Event su cui viene svegliato."""

    __slots__ = ("priority", "seq", "t0", "event", "granted", "job_id")

    def __init__(self, priority, seq, t0, job_id):
        self.priority = priority
        self.seq = seq
        self.t0 = t0
        self.event = threading.Event()
        self.granted = False
        self.job_id = job_id


def _effective_priority(w, now):
    """Priorita' con cui il waiter concorre ADESSO.

    Chi ha superato la finestra di starvation pesa quanto un premium: e' cio'
    che impedisce a un flusso continuo di job PREMIUM di tenere fermo per
    sempre un job gratuito gia' sintetizzato.
    """
    if ASSEMBLY_STARVE_SEC > 0 and (now - w.t0) >= ASSEMBLY_STARVE_SEC:
        return w.priority + PRIORITY_PREMIUM
    return w.priority


def _sort_key(w, now):
    # Priorita' effettiva decrescente, poi ordine di arrivo crescente.
    return (_effective_priority(w, now), -w.seq)


def _next_waiter_locked():
    """Il prossimo da servire. Chiamare con _state_lock tenuto."""
    if not _waiters:
        return None
    now = time.time()
    return max(_waiters, key=lambda w: _sort_key(w, now))


def _position_locked(w):
    """Posizione di w nell'ordine di servizio corrente (1 = prossimo)."""
    now = time.time()
    key = _sort_key(w, now)
    return 1 + sum(1 for other in _waiters if _sort_key(other, now) > key)


def _grant_locked(w):
    """Passa lo slot direttamente a w. Chiamare con _state_lock tenuto.

    Handoff diretto invece di rilascio-e-riacquisto: lo slot non torna mai
    libero fra i due, quindi non puo' essere rubato da un arrivo nuovo
    scavalcando la priorita'. Per questo `_held` resta invariato.
    """
    _waiters.remove(w)
    w.granted = True
    w.event.set()


def configure(max_slots):
    """Reimposta il numero di slot. Da usare allo startup (o nei test).

    Non attende gli assembly in corso: la contabilita' riparte da zero. I
    waiter gia' in coda non devono pero' restare appesi al vecchio conteggio,
    quindi ne ammettiamo subito quanti ne entrano nei nuovi slot.
    """
    global MAX_CONCURRENT_ASSEMBLY, _held
    n = max(1, int(max_slots))
    with _state_lock:
        MAX_CONCURRENT_ASSEMBLY = n
        _held = 0
        while _waiters and _held < MAX_CONCURRENT_ASSEMBLY:
            _grant_locked(_next_waiter_locked())
            _held += 1
    return n


class Slot:
    """Permesso di assembly. `release()` e' idempotente e no-op se non tenuto."""

    __slots__ = ("job_id", "held", "timed_out", "waited_sec", "_lock")

    def __init__(self, job_id, held, timed_out, waited_sec):
        self.job_id = job_id
        self.held = held
        self.timed_out = timed_out
        self.waited_sec = waited_sec
        self._lock = threading.Lock()

    def release(self):
        global _held
        with self._lock:
            if not self.held:
                return  # mai acquisito (timeout) o gia' rilasciato
            self.held = False
        with _state_lock:
            w = _next_waiter_locked()
            if w is not None:
                _grant_locked(w)      # lo slot passa di mano: _held invariato
            else:
                _held = max(0, _held - 1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def acquire(job_id="", priority=PRIORITY_NORMAL, on_wait=None, timeout=None):
    """Occupa uno slot di assembly, attendendo se necessario.

    Args:
        job_id: solo per i log.
        priority: PRIORITY_PREMIUM per i job pagati, PRIORITY_NORMAL per gli
                  altri. A parita' di priorita' vale l'ordine di arrivo.
        on_wait: callback(posizione_in_coda) invocata SOLO se si deve
                 attendere. Serve a mostrare all'utente "in coda" invece di
                 una barra apparentemente bloccata.
        timeout: secondi di attesa massima (default ASSEMBLY_WAIT_TIMEOUT_SEC).

    Returns:
        Slot. `slot.held` False = timeout scaduto, il chiamante procede
        comunque (degrado controllato, mai un job appeso).
    """
    global _held, _seq
    if timeout is None:
        timeout = ASSEMBLY_WAIT_TIMEOUT_SEC

    with _state_lock:
        # Il secondo test non e' ridondante: senza `not _waiters` un arrivo
        # nuovo prenderebbe lo slot appena liberato scavalcando la coda, e la
        # priorita' varrebbe solo fra chi e' gia' in attesa.
        if _held < MAX_CONCURRENT_ASSEMBLY and not _waiters:
            _held += 1
            return Slot(job_id, True, False, 0.0)
        _seq += 1
        w = _Waiter(priority, _seq, time.time(), job_id)
        _waiters.append(w)
        position = _position_locked(w)
        queued = len(_waiters)

    if on_wait is not None:
        try:
            on_wait(position)
        except Exception:
            pass
    tag = "PREMIUM " if priority >= PRIORITY_PREMIUM else ""
    print(f"[{job_id or '-'}] assembly: {tag}in attesa di uno slot "
          f"(posizione {position} su {queued} in coda, "
          f"{MAX_CONCURRENT_ASSEMBLY} slot)", flush=True)

    t0 = time.time()
    w.event.wait(timeout)
    waited = time.time() - t0

    with _state_lock:
        # Il grant puo' arrivare fra lo scadere del wait e questo lock:
        # `w.granted` e' l'unica verita', altrimenti lo slot ceduto andrebbe
        # perso per sempre.
        granted = w.granted
        if not granted:
            try:
                _waiters.remove(w)
            except ValueError:
                pass

    if not granted:
        print(f"[{job_id or '-'}] assembly: timeout dopo {waited:.0f}s in coda "
              f"— procedo comunque senza slot", flush=True)
        return Slot(job_id, False, True, waited)

    print(f"[{job_id or '-'}] assembly: {tag}slot ottenuto dopo {waited:.0f}s "
          f"in coda", flush=True)
    return Slot(job_id, True, False, waited)


def slot(job_id="", priority=PRIORITY_NORMAL, on_wait=None, timeout=None):
    """Context manager equivalente ad acquire()/release()."""
    return acquire(job_id, priority=priority, on_wait=on_wait, timeout=timeout)


def stats():
    """Snapshot per log/monitoraggio."""
    with _state_lock:
        return {
            "max": MAX_CONCURRENT_ASSEMBLY,
            "held": _held,
            "free": max(0, MAX_CONCURRENT_ASSEMBLY - _held),
            "waiting": len(_waiters),
            "waiting_premium": sum(1 for w in _waiters
                                   if w.priority >= PRIORITY_PREMIUM),
        }
