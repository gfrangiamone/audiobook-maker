"""Test: coda di ammissione per la fase di assembly audio.

Il lavoro TTS gira su servizi esterni; la CPU della macchina viene saturata
dagli encode FFmpeg di fine job (PCM->AAC/MP3, MP3->M4B), che non passano
`-threads` e quindi prendono da soli tutti i core. Senza un tetto, N job che
arrivano insieme all'assembly finale si contendono 2 vCPU: ogni encode dura
N volte di piu' e i job restano vivi in RAM N volte piu' a lungo (incidente
2026-08-21). `assembly_queue` ammette al massimo
`ABM_MAX_CONCURRENT_ASSEMBLY` encode alla volta.
"""
import threading
import time

import pytest

import assembly_queue


@pytest.fixture(autouse=True)
def restore_config():
    saved = assembly_queue.MAX_CONCURRENT_ASSEMBLY
    yield
    assembly_queue.configure(saved)


def test_default_slots_leave_one_cpu_free(monkeypatch):
    monkeypatch.setattr(assembly_queue.os, "cpu_count", lambda: 8)
    assert assembly_queue._default_slots() == 7
    monkeypatch.setattr(assembly_queue.os, "cpu_count", lambda: 2)
    assert assembly_queue._default_slots() == 1
    monkeypatch.setattr(assembly_queue.os, "cpu_count", lambda: 1)
    assert assembly_queue._default_slots() == 1
    monkeypatch.setattr(assembly_queue.os, "cpu_count", lambda: None)
    assert assembly_queue._default_slots() >= 1


def test_configure_resets_the_semaphore():
    assembly_queue.configure(3)
    assert assembly_queue.MAX_CONCURRENT_ASSEMBLY == 3
    assert assembly_queue.stats()["free"] == 3


def test_no_more_than_max_slots_held_at_once():
    assembly_queue.configure(2)
    peak = [0]
    live = [0]
    lock = threading.Lock()
    start = threading.Event()

    def worker():
        start.wait(2)
        with assembly_queue.slot("J"):
            with lock:
                live[0] += 1
                peak[0] = max(peak[0], live[0])
            time.sleep(0.05)
            with lock:
                live[0] -= 1

    ths = [threading.Thread(target=worker) for _ in range(6)]
    for t in ths:
        t.start()
    start.set()
    for t in ths:
        t.join(10)
    assert peak[0] == 2
    assert assembly_queue.stats()["free"] == 2  # tutti rilasciati


def test_acquire_blocks_until_a_slot_is_freed():
    assembly_queue.configure(1)
    first = assembly_queue.acquire("A")
    assert first.held is True
    got = threading.Event()

    def worker():
        s = assembly_queue.acquire("B")
        got.set()
        s.release()

    t = threading.Thread(target=worker)
    t.start()
    assert not got.wait(0.2)  # bloccato: lo slot e' occupato
    first.release()
    assert got.wait(5)
    t.join(5)


def test_timeout_proceeds_without_the_slot():
    """Uno slot trattenuto da un encode patologico non deve appendere il job."""
    assembly_queue.configure(1)
    held = assembly_queue.acquire("A")
    try:
        s = assembly_queue.acquire("B", timeout=0.05)
        assert s.held is False  # degrada: procede comunque
        assert s.timed_out is True
        s.release()  # no-op: non deve restituire un permesso mai preso
        assert assembly_queue.stats()["free"] == 0
    finally:
        held.release()
    assert assembly_queue.stats()["free"] == 1


def test_release_is_idempotent():
    assembly_queue.configure(1)
    s = assembly_queue.acquire("A")
    s.release()
    s.release()
    s.release()
    assert assembly_queue.stats()["free"] == 1  # niente over-release


def test_on_wait_called_only_when_the_caller_has_to_queue():
    assembly_queue.configure(1)
    seen = []
    s1 = assembly_queue.acquire("A", on_wait=lambda n: seen.append(n))
    assert seen == []  # slot libero: nessuna attesa segnalata

    def worker():
        s = assembly_queue.acquire("B", on_wait=lambda n: seen.append(n))
        s.release()

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.1)
    s1.release()
    t.join(5)
    assert seen and seen[0] >= 1  # posizione in coda segnalata al chiamante


def test_stats_reports_waiting_callers():
    assembly_queue.configure(1)
    s1 = assembly_queue.acquire("A")
    started = threading.Event()

    def worker():
        started.set()
        s = assembly_queue.acquire("B")
        s.release()

    t = threading.Thread(target=worker)
    t.start()
    started.wait(2)
    time.sleep(0.1)
    st = assembly_queue.stats()
    assert st["waiting"] == 1
    assert st["max"] == 1
    assert st["free"] == 0
    s1.release()
    t.join(5)
    assert assembly_queue.stats()["waiting"] == 0


def test_slot_context_manager_releases_on_exception():
    assembly_queue.configure(1)
    with pytest.raises(ValueError):
        with assembly_queue.slot("A"):
            raise ValueError("boom")
    assert assembly_queue.stats()["free"] == 1


# --- integrazione con generation_engine ------------------------------------

def test_generation_helper_shows_queue_position_then_restores_message():
    """Senza messaggio dedicato la barra sembrerebbe piantata durante l'attesa."""
    import generation_engine

    assembly_queue.configure(1)
    busy = assembly_queue.acquire("OTHER")
    job = {"progress_message": "Merging audio..."}
    seen = []

    def worker():
        s = generation_engine._acquire_assembly_slot("J", job, "single-file")
        seen.append(s)

    t = threading.Thread(target=worker)
    t.start()
    time.sleep(0.15)
    # in attesa: l'utente vede la posizione in coda
    assert "queued for final assembly" in job["progress_message"]
    busy.release()
    t.join(5)
    # slot ottenuto: il messaggio di fase originale viene ripristinato
    assert job["progress_message"] == "Merging audio..."
    assert seen[0].held is True
    seen[0].release()
    assert assembly_queue.stats()["free"] == 1


def test_generation_helper_does_not_touch_message_when_slot_is_free():
    import generation_engine

    assembly_queue.configure(2)
    job = {"progress_message": "Merging audio..."}
    s = generation_engine._acquire_assembly_slot("J", job, "single-file")
    assert job["progress_message"] == "Merging audio..."
    assert s.waited_sec == 0.0
    s.release()
