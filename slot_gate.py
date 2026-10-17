"""slot_gate — tetto globale di chiamate simultanee verso un servizio esterno.

Un permesso per chiamata, valido su tutti i job e client del processo. Il
tetto e' una funzione riletta a ogni acquire, cosi' una variabile d'ambiente
cambiata a runtime vale subito; un tetto <= 0 vuol dire nessun limite.
Usato da `speechify_tts` (limite dell'abbonamento) ed `edge_engine`
(`ABM_EDGE_MAX_INFLIGHT`). Modulo foglia: solo stdlib.
"""
import contextlib
import threading
import time


class SlotGate:
    def __init__(self, limit):
        self._limit = limit
        self._cond = threading.Condition()
        self._active = 0
        self._peak = 0
        self._waits = 0
        self._wait_sec = 0.0

    def limit(self):
        return self._limit()

    def acquire(self, timeout=None):
        """Acquisisce un permesso, bloccando finche' `active < limit`.

        True se acquisito, False su timeout. timeout=None: attesa indefinita.
        """
        deadline = None if timeout is None else (time.monotonic() + timeout)
        t0 = None
        with self._cond:
            while 0 < self._limit() <= self._active:
                if t0 is None:
                    t0 = time.monotonic()
                if deadline is None:
                    self._cond.wait()
                else:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        return False
                    self._cond.wait(timeout=remaining)
            self._active += 1
            self._peak = max(self._peak, self._active)
            if t0 is not None:
                self._waits += 1
                self._wait_sec += time.monotonic() - t0
            return True

    def release(self):
        """Rilascia un permesso e sveglia un eventuale waiter."""
        with self._cond:
            if self._active > 0:
                self._active -= 1
            self._cond.notify()

    def active(self):
        with self._cond:
            return self._active

    def free(self):
        """Permessi liberi; None se il tetto e' spento."""
        with self._cond:
            n = self._limit()
            return None if n <= 0 else max(0, n - self._active)

    def take_stats(self):
        """(picco, attese, secondi di attesa) dall'ultima lettura, poi azzera.
        Il picco riparte dalle chiamate in volo adesso."""
        with self._cond:
            out = (self._peak, self._waits, self._wait_sec)
            self._peak, self._waits, self._wait_sec = self._active, 0, 0.0
            return out

    def reset(self):
        """Azzera lo stato (solo test)."""
        with self._cond:
            self._active = self._peak = self._waits = 0
            self._wait_sec = 0.0
            self._cond.notify_all()

    @contextlib.contextmanager
    def slot(self, timeout=None, what="slot"):
        """Context manager: un permesso per la durata del blocco."""
        if not self.acquire(timeout=timeout):
            raise TimeoutError(f"{what} not available")
        try:
            yield
        finally:
            self.release()
