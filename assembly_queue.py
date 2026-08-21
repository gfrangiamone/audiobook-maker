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

_sem = threading.BoundedSemaphore(MAX_CONCURRENT_ASSEMBLY)
_state_lock = threading.Lock()
_waiting = 0   # chiamanti attualmente in coda
_held = 0      # slot attualmente occupati


def configure(max_slots):
    """Reimposta il numero di slot. Da usare allo startup (o nei test).

    Non attende i permessi in corso: i vecchi Slot rilasciano sul semaforo che
    hanno acquisito, quindi la sostituzione e' sicura.
    """
    global MAX_CONCURRENT_ASSEMBLY, _sem, _held, _waiting
    n = max(1, int(max_slots))
    with _state_lock:
        MAX_CONCURRENT_ASSEMBLY = n
        _sem = threading.BoundedSemaphore(n)
        _held = 0
        _waiting = 0
    return n


class Slot:
    """Permesso di assembly. `release()` e' idempotente e no-op se non tenuto."""

    __slots__ = ("job_id", "held", "timed_out", "waited_sec", "_sem", "_lock")

    def __init__(self, job_id, held, timed_out, waited_sec, sem):
        self.job_id = job_id
        self.held = held
        self.timed_out = timed_out
        self.waited_sec = waited_sec
        self._sem = sem
        self._lock = threading.Lock()

    def release(self):
        global _held
        with self._lock:
            if not self.held:
                return  # mai acquisito (timeout) o gia' rilasciato
            self.held = False
        try:
            self._sem.release()
        except ValueError:
            # BoundedSemaphore: release oltre il conteggio iniziale. Puo'
            # accadere solo dopo una configure() concorrente; non fatale.
            pass
        with _state_lock:
            _held = max(0, _held - 1)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.release()
        return False


def acquire(job_id="", on_wait=None, timeout=None):
    """Occupa uno slot di assembly, attendendo se necessario.

    Args:
        job_id: solo per i log.
        on_wait: callback(posizione_in_coda) invocata SOLO se si deve
                 attendere. Serve a mostrare all'utente "in coda" invece di
                 una barra apparentemente bloccata.
        timeout: secondi di attesa massima (default ASSEMBLY_WAIT_TIMEOUT_SEC).

    Returns:
        Slot. `slot.held` False = timeout scaduto, il chiamante procede
        comunque (degrado controllato, mai un job appeso).
    """
    global _waiting, _held
    if timeout is None:
        timeout = ASSEMBLY_WAIT_TIMEOUT_SEC
    sem = _sem  # snapshot: un configure() concorrente non deve spostare il target

    if sem.acquire(blocking=False):
        with _state_lock:
            _held += 1
        return Slot(job_id, True, False, 0.0, sem)

    with _state_lock:
        _waiting += 1
        position = _waiting
    if on_wait is not None:
        try:
            on_wait(position)
        except Exception:
            pass
    print(f"[{job_id or '-'}] assembly: in attesa di uno slot "
          f"({position} in coda, {MAX_CONCURRENT_ASSEMBLY} slot)", flush=True)

    t0 = time.time()
    try:
        ok = sem.acquire(timeout=timeout)
    finally:
        with _state_lock:
            _waiting = max(0, _waiting - 1)
    waited = time.time() - t0

    if not ok:
        print(f"[{job_id or '-'}] assembly: timeout dopo {waited:.0f}s in coda "
              f"— procedo comunque senza slot", flush=True)
        return Slot(job_id, False, True, waited, sem)

    with _state_lock:
        _held += 1
    print(f"[{job_id or '-'}] assembly: slot ottenuto dopo {waited:.0f}s "
          f"in coda", flush=True)
    return Slot(job_id, True, False, waited, sem)


def slot(job_id="", on_wait=None, timeout=None):
    """Context manager equivalente ad acquire()/release()."""
    return acquire(job_id, on_wait=on_wait, timeout=timeout)


def stats():
    """Snapshot per log/monitoraggio."""
    with _state_lock:
        return {
            "max": MAX_CONCURRENT_ASSEMBLY,
            "held": _held,
            "free": max(0, MAX_CONCURRENT_ASSEMBLY - _held),
            "waiting": _waiting,
        }
