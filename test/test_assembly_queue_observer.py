"""assembly_queue: notifica all'observer di attesa e durata di possesso."""
import time

import pytest

import assembly_queue as aq


@pytest.fixture(autouse=True)
def clean():
    aq.configure(2)
    aq.set_observer(None)
    yield
    aq.set_observer(None)
    aq.configure(2)


def test_release_notifies_with_wait_and_held_time():
    seen = []
    aq.set_observer(lambda *a: seen.append(a))
    slot = aq.acquire("job-1", priority=aq.PRIORITY_PREMIUM)
    time.sleep(0.05)
    slot.release()
    assert len(seen) == 1
    event, job_id, priority, waited, held = seen[0]
    assert event == "release"
    assert job_id == "job-1"
    assert priority == aq.PRIORITY_PREMIUM
    assert waited == 0.0
    assert held >= 0.04


def test_release_is_notified_only_once():
    seen = []
    aq.set_observer(lambda *a: seen.append(a))
    slot = aq.acquire("job-2")
    slot.release()
    slot.release()
    assert len(seen) == 1


def test_timeout_notifies_a_timeout_event():
    aq.configure(1)
    seen = []
    held = aq.acquire("holder")
    aq.set_observer(lambda *a: seen.append(a))
    late = aq.acquire("job-3", timeout=0.05)
    assert late.held is False
    assert [s[0] for s in seen] == ["timeout"]
    assert seen[0][1] == "job-3"
    assert seen[0][3] >= 0.04
    held.release()


def test_observer_exception_never_breaks_the_queue():
    def boom(*_a):
        raise RuntimeError("observer rotto")

    aq.set_observer(boom)
    slot = aq.acquire("job-4")
    slot.release()                       # non deve sollevare
    assert aq.stats()["held"] == 0
