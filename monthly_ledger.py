"""monthly_ledger — documenti JSON di stato con lock, riparazione, potatura
e scrittura atomica; sopra, il libro mastro mensile per client.

Modulo foglia (stdlib + `fileio`). Prima: `free_quota` e `free_tts_quota`
avevano lo stesso `_quota_file/_month/_load/_save`, lo stesso bucket
`{"YYYY-MM": {cid: {<importo>, "jobs": {job: importo}}}}` riparato a mano,
la stessa potatura a 3 mesi e la stessa idempotenza per job; `metrics_store`
rifaceva load/prune/save per conto suo.

- `JsonDoc(path_fn, default, repair, prune)`: `read()`, `mutate()` (lock +
  load + riparazione + yield + potatura + scrittura atomica best-effort).
- `MonthlyLedger(path_fn, amount_key, cast=float|int)`: `used(key)`,
  `job_charged(key, job)`, `consume(key, amount, job, extra_keys=...)`,
  `refund(key, job, extra_keys=...)`, `month_bucket(d)`; i bucket si
  riparano se lo schema non torna; i mesi oltre `keep_months` si potano.
- `month_key()`, `day_key()`, `prune_sorted_keys(d, keep)`,
  `prune_keys_before(d, cutoff, key_len)`.

Fuso orario: ora locale, come i contatori che ne usano le chiavi (gli
audit JSONL sono in UTC, vedi `jsonl_audit`).
"""
import contextlib
import threading
from datetime import datetime

from fileio import atomic_write_json, load_json


def month_key(now=None):
    return (now or datetime.now()).strftime("%Y-%m")


def day_key(now=None):
    return (now or datetime.now()).strftime("%Y-%m-%d")


def prune_sorted_keys(d, keep):
    """Tiene le `keep` chiavi piu' alte in ordine lessicale (mesi/giorni
    `YYYY-MM[-DD]` si ordinano come il tempo). `keep <= 0` = non potare."""
    if keep and keep > 0:
        for old in sorted(d.keys())[:-keep]:
            d.pop(old, None)
    return d


def prune_keys_before(d, cutoff, key_len=None):
    """Toglie le chiavi stringa minori di `cutoff` (stesso formato); con
    `key_len` solo quelle di quella lunghezza, le altre restano intatte."""
    for k in [k for k in d if isinstance(k, str) and (key_len is None or len(k) == key_len) and k < cutoff]:
        d.pop(k, None)
    return d


class JsonDoc:
    def __init__(self, path_fn, *, default=dict, repair=None, prune=None, lock=None,
                 raise_on_save=False):
        self._path_fn = path_fn
        self._default = default
        self._repair = repair
        self._prune = prune
        self.lock = lock if lock is not None else threading.RLock()
        self._raise_on_save = raise_on_save

    def path(self):
        return self._path_fn()

    def load(self):
        """Il documento riparato (senza lock: chi chiama lo tiene)."""
        d = load_json(self.path(), self._default())
        if not isinstance(d, dict):
            d = self._default()
        if self._repair is not None:
            d = self._repair(d) or d
        return d

    def save(self, d):
        """Potatura e scrittura atomica; un errore di disco non ferma chi
        chiama (best-effort), salvo `raise_on_save`."""
        if self._prune is not None:
            self._prune(d)
        try:
            atomic_write_json(self.path(), d)
            return True
        except Exception:  # noqa: BLE001
            if self._raise_on_save:
                raise
            return False

    def read(self):
        with self.lock:
            return self.load()

    @contextlib.contextmanager
    def mutate(self, *, save=True):
        """`with doc.mutate() as d:` — lock, documento riparato, poi
        potatura e scrittura. Con `save=False` niente scrittura (letture)."""
        with self.lock:
            d = self.load()
            yield d
            if save:
                self.save(d)


class MonthlyLedger(JsonDoc):
    """`{"YYYY-MM": {key: {amount_key: n, "jobs": {job_id: n}, ...}}}`."""

    def __init__(self, path_fn, amount_key, *, cast=float, keep_months=3, round_to=None,
                 month_fn=month_key, lock=None):
        super().__init__(path_fn, default=dict, lock=lock,
                         prune=lambda d: prune_sorted_keys(d, keep_months))
        self.amount_key = amount_key
        self.cast = cast
        self.round_to = round_to
        self.month_fn = month_fn

    def _num(self, value):
        try:
            v = self.cast(value or 0)
        except (TypeError, ValueError):
            v = self.cast(0)
        v = max(self.cast(0), v)
        return round(v, self.round_to) if self.round_to is not None else v

    def month_bucket(self, d, create=False):
        """Il dict del mese corrente, riparato; `None` se manca e non si crea."""
        month = self.month_fn()
        if not isinstance(d.get(month), dict):
            if not create:
                return None
            d[month] = {}
        return d[month]

    def bucket(self, d, key, create=False):
        """Il bucket di `key` nel mese corrente, con `amount_key` numerico e
        `jobs` dict (schema riparato); `None` se manca e non si crea."""
        mb = self.month_bucket(d, create)
        if mb is None:
            return None
        if not isinstance(mb.get(key), dict):
            if not create:
                return None
            mb[key] = {self.amount_key: self.cast(0), "jobs": {}}
        b = mb[key]
        if not isinstance(b.get("jobs"), dict):
            b["jobs"] = {}
        b[self.amount_key] = self._num(b.get(self.amount_key))
        return b

    def used(self, key):
        if not key:
            return self.cast(0)
        with self.lock:
            b = self.bucket(self.load(), key)
        return b[self.amount_key] if b else self.cast(0)

    def job_charged(self, key, job_id):
        jid = (job_id or "").strip()
        if not jid or not key:
            return False
        with self.lock:
            b = self.bucket(self.load(), key)
        return bool(b) and jid in b["jobs"]

    def charge(self, d, key, amount, job_id):
        """Somma `amount` su `key` (idempotente per `job_id`). Chi chiama tiene
        il lock e salva. Ritorna (totale, addebitato_adesso)."""
        b = self.bucket(d, key, create=True)
        jid = (job_id or "").strip()
        if jid and jid in b["jobs"]:
            return b[self.amount_key], False
        amount = self._num(amount)
        b[self.amount_key] = self._num(b[self.amount_key] + amount)
        if jid:
            b["jobs"][jid] = amount
        return b[self.amount_key], True

    def uncharge(self, d, key, job_id):
        """Storna `job_id` da `key`; ritorna l'importo stornato (0 se non c'era)."""
        b = self.bucket(d, key)
        jid = (job_id or "").strip()
        if not b or not jid or jid not in b["jobs"]:
            return self.cast(0)
        amount = self._num(b["jobs"].pop(jid))
        b[self.amount_key] = self._num(b[self.amount_key] - amount)
        return amount

    def consume(self, key, amount, job_id, *, extra_keys=(), on_charge=None, save_always=False):
        """Addebito sotto lock con scrittura. `extra_keys`: altre chiavi che
        ricevono lo stesso importo (es. `mail:<hash>`); `on_charge(bucket)`
        e' chiamata per ogni bucket addebitato adesso. Ritorna il totale del
        mese su `key`."""
        with self.lock:
            d = self.load()
            total, changed = self.charge(d, key, amount, job_id)
            if changed and on_charge is not None:
                on_charge(self.bucket(d, key))
            for k in extra_keys:
                if k:
                    _t, ch = self.charge(d, k, amount, job_id)
                    if ch and on_charge is not None:
                        on_charge(self.bucket(d, k))
                    changed = changed or ch
            if changed or save_always:
                self.save(d)
            return total

    def refund(self, key, job_id, *, extra_keys=()):
        """Storno sotto lock; ritorna l'importo stornato su `key`."""
        if not (job_id or "").strip():
            return self.cast(0)
        with self.lock:
            d = self.load()
            amount = self.uncharge(d, key, job_id)
            moved = any(self.uncharge(d, k, job_id) for k in extra_keys if k)
            if amount or moved:
                self.save(d)
            return amount
