"""Test: privilegio in coda dei job PREMIUM per gli encode FFmpeg.

La CPU e' l'unica risorsa satura della macchina: la coda di assembly e' dove
si accumula l'attesa reale (nel picco del 23/08/2026: 97 attese, mediana
275 s, p90 921 s). Chi ha pagato non deve stare dietro a una fila di
conversioni gratuite — ma nemmeno un job gratuito puo' restare indietro per
sempre, da cui la promozione anti-starvation.
"""
import threading
import time

import pytest

import assembly_queue


@pytest.fixture(autouse=True)
def restore_config():
    saved = assembly_queue.MAX_CONCURRENT_ASSEMBLY
    saved_starve = assembly_queue.ASSEMBLY_STARVE_SEC
    yield
    assembly_queue.ASSEMBLY_STARVE_SEC = saved_starve
    assembly_queue.configure(saved)


def _wait_until(pred, timeout=5.0):
    """Attende una condizione sullo stato della coda (niente sleep a caso)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.005)
    return False


def _drain(runners):
    """Rilascia gli slot via via che vengono concessi, in qualunque ordine.

    Non si puo' attendere un runner specifico: con un solo slot, il secondo
    parte solo quando il primo servito rilascia — e chi sia il primo servito
    e' esattamente cio' che il test sta misurando.
    """
    pending = list(runners)
    while pending:
        got_one = _wait_until(lambda: any(r.slot is not None for r in pending))
        assert got_one, "nessuno ha ottenuto lo slot"
        for r in list(pending):
            if r.slot is not None:
                r.slot.release()
                r.join()
                pending.remove(r)


class _Runner:
    """Avvia acquire() in un thread e registra quando ottiene lo slot."""

    def __init__(self, order, name, priority, on_wait=None):
        self.order = order
        self.name = name
        self.priority = priority
        self.on_wait = on_wait
        self.slot = None
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        self.slot = assembly_queue.acquire(self.name, priority=self.priority,
                                           on_wait=self.on_wait, timeout=5)
        self.order.append(self.name)

    def start(self):
        self.thread.start()
        return self

    def join(self):
        self.thread.join(6)


def _queue_up(order, specs):
    """Accoda i runner UNO ALLA VOLTA, aspettando che ciascuno sia in coda.

    Senza questa sincronizzazione l'ordine di arrivo non sarebbe deterministico
    e il test non distinguerebbe la priorita' dal caso.
    """
    runners = []
    for i, (name, prio) in enumerate(specs, start=1):
        runners.append(_Runner(order, name, prio).start())
        assert _wait_until(lambda n=i: assembly_queue.stats()["waiting"] == n), \
            f"{name} non e' entrato in coda"
    return runners


def test_premium_scavalca_i_normali_gia_in_coda():
    assembly_queue.configure(1)
    held = assembly_queue.acquire("occupante")
    order = []
    runners = _queue_up(order, [("free1", assembly_queue.PRIORITY_NORMAL),
                                ("free2", assembly_queue.PRIORITY_NORMAL),
                                ("paid", assembly_queue.PRIORITY_PREMIUM)])

    held.release()
    _drain(runners)

    # Arrivato per ultimo, servito per primo; i due free restano in ordine.
    assert order == ["paid", "free1", "free2"]
    assert assembly_queue.stats()["free"] == 1


def test_a_parita_di_priorita_resta_l_ordine_di_arrivo():
    assembly_queue.configure(1)
    held = assembly_queue.acquire("occupante")
    order = []
    runners = _queue_up(order, [("a", assembly_queue.PRIORITY_PREMIUM),
                                ("b", assembly_queue.PRIORITY_PREMIUM),
                                ("c", assembly_queue.PRIORITY_PREMIUM)])

    held.release()
    _drain(runners)

    assert order == ["a", "b", "c"]


def test_la_posizione_mostrata_riflette_la_priorita():
    """Il messaggio all'utente deve dire la posizione VERA, non l'arrivo."""
    assembly_queue.configure(1)
    held = assembly_queue.acquire("occupante")
    order = []
    seen = []
    runners = _queue_up(order, [("free1", assembly_queue.PRIORITY_NORMAL),
                                ("free2", assembly_queue.PRIORITY_NORMAL)])

    paid = _Runner(order, "paid", assembly_queue.PRIORITY_PREMIUM,
                   on_wait=seen.append).start()
    assert _wait_until(lambda: len(seen) == 1)
    assert seen == [1]  # terzo ad arrivare, primo a essere servito

    held.release()
    _drain([paid] + runners)


def test_anti_starvation_promuove_chi_aspetta_da_troppo():
    assembly_queue.configure(1)
    assembly_queue.ASSEMBLY_STARVE_SEC = 0.15
    held = assembly_queue.acquire("occupante")
    order = []
    free = _queue_up(order, [("free", assembly_queue.PRIORITY_NORMAL)])[0]

    # Il free supera la finestra di starvation: da qui pesa come un premium
    # e, essendo arrivato prima, precede un premium fresco.
    time.sleep(0.2)
    paid = _Runner(order, "paid", assembly_queue.PRIORITY_PREMIUM).start()
    assert _wait_until(lambda: assembly_queue.stats()["waiting"] == 2)

    held.release()
    _drain([free, paid])

    assert order == ["free", "paid"]


def test_un_arrivo_nuovo_non_scavalca_la_coda():
    """Senza questo, la priorita' varrebbe solo fra chi e' gia' in attesa.

    Uno slot libero con la coda non vuota (finestra fra il rilascio e il
    risveglio del waiter) non deve essere afferrato da chi arriva ora.
    """
    assembly_queue.configure(1)
    ghost = assembly_queue._Waiter(assembly_queue.PRIORITY_PREMIUM, 999,
                                   time.time(), "ghost")
    with assembly_queue._state_lock:
        assembly_queue._waiters.append(ghost)
    try:
        assert assembly_queue.stats()["free"] == 1  # slot disponibile
        s = assembly_queue.acquire("intruso", timeout=0.1)
        assert not s.held and s.timed_out
    finally:
        with assembly_queue._state_lock:
            if ghost in assembly_queue._waiters:
                assembly_queue._waiters.remove(ghost)


def test_il_timeout_non_perde_lo_slot_ceduto_in_extremis():
    """Grant e scadenza possono incrociarsi: vince il grant, mai un buco.

    Se il chiamante uscisse "in timeout" dopo aver ricevuto l'handoff, quello
    slot resterebbe occupato da nessuno per sempre.
    """
    assembly_queue.configure(1)
    held = assembly_queue.acquire("occupante")
    result = {}

    def late():
        result["slot"] = assembly_queue.acquire("tardivo", timeout=0.2)

    th = threading.Thread(target=late, daemon=True)
    th.start()
    assert _wait_until(lambda: assembly_queue.stats()["waiting"] == 1)
    time.sleep(0.2)          # il wait scade...
    held.release()           # ...e il grant arriva subito dopo
    th.join(6)

    s = result["slot"]
    if s.held:               # handoff vinto: lo slot va rilasciato
        s.release()
    assert assembly_queue.stats()["free"] == 1
    assert assembly_queue.stats()["waiting"] == 0


def test_stats_conta_i_premium_in_coda():
    assembly_queue.configure(1)
    held = assembly_queue.acquire("occupante")
    order = []
    runners = _queue_up(order, [("free", assembly_queue.PRIORITY_NORMAL),
                                ("paid", assembly_queue.PRIORITY_PREMIUM)])
    st = assembly_queue.stats()
    assert st["waiting"] == 2
    assert st["waiting_premium"] == 1

    held.release()
    _drain(runners)
    assert assembly_queue.stats()["waiting_premium"] == 0


def test_configure_sblocca_i_waiter_gia_in_coda():
    """Cambiare gli slot non deve lasciare appeso chi sta gia' aspettando."""
    assembly_queue.configure(1)
    held = assembly_queue.acquire("occupante")
    order = []
    runners = _queue_up(order, [("a", assembly_queue.PRIORITY_NORMAL),
                                ("b", assembly_queue.PRIORITY_NORMAL)])

    assembly_queue.configure(2)   # ora c'e' posto per entrambi
    for r in runners:
        assert _wait_until(lambda r=r: r.slot is not None)
        r.join()
    assert sorted(order) == ["a", "b"]
    for r in runners:
        r.slot.release()
    held.release()


# --- classificazione lato generation_engine -------------------------------

def _priority_of(job):
    import generation_engine
    return generation_engine._assembly_priority(job)


@pytest.mark.parametrize("job", [
    {"voice": "gemini:Kore"},
    {"voice": "speechify:henry"},
    {"voice": "it-IT-DiegoNeural", "payment_token": "VCH-123"},
    {"voice": "it-IT-DiegoNeural", "payment_amount_eur": 1.8},
    {"voice": "it-IT-DiegoNeural", "payment": {"token": "PAY-1"}},
    {"opt_voice": "gemini:Kore"},
])
def test_job_pagati_sono_premium(job):
    assert _priority_of(job) == assembly_queue.PRIORITY_PREMIUM


@pytest.mark.parametrize("job", [
    {"voice": "it-IT-DiegoNeural"},
    {"voice": "gcloud:it-IT-Chirp3-HD-Aoede"},   # free tier Google, non pagato
    {"voice": "it-IT-DiegoNeural", "payment_amount_eur": 0},
    {"voice": "it-IT-DiegoNeural", "payment_token": "  "},
    {"voice": "it-IT-DiegoNeural", "payment_amount_eur": "n/a"},
    {},
])
def test_job_gratuiti_sono_normali(job):
    assert _priority_of(job) == assembly_queue.PRIORITY_NORMAL
