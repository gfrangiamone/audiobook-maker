import threading
import time
import speechify_tts


def setup_function():
    speechify_tts._reset_gate_for_test()


def test_acquire_release_counts(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "2")
    assert speechify_tts.active_slots() == 0
    assert speechify_tts.acquire_slot(timeout=1) is True
    assert speechify_tts.active_slots() == 1
    speechify_tts.release_slot()
    assert speechify_tts.active_slots() == 0


def test_gate_blocks_beyond_n(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "2")
    assert speechify_tts.acquire_slot(timeout=1) is True
    assert speechify_tts.acquire_slot(timeout=1) is True
    # Terzo acquire deve fallire in timeout (nessuno slot libero).
    t0 = time.time()
    assert speechify_tts.acquire_slot(timeout=0.3) is False
    assert time.time() - t0 >= 0.3
    speechify_tts.release_slot()
    speechify_tts.release_slot()


def test_blocked_acquire_unblocks_on_release(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "1")
    assert speechify_tts.acquire_slot(timeout=1) is True
    results = []

    def _worker():
        results.append(speechify_tts.acquire_slot(timeout=2))

    th = threading.Thread(target=_worker)
    th.start()
    time.sleep(0.2)
    assert results == []            # ancora bloccato
    speechify_tts.release_slot()    # libera lo slot
    th.join(timeout=2)
    assert results == [True]        # sbloccato
    speechify_tts.release_slot()


def test_context_manager(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "1")
    with speechify_tts.slot():
        assert speechify_tts.active_slots() == 1
    assert speechify_tts.active_slots() == 0
