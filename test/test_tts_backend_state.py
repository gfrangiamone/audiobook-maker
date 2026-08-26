"""Stato persistito del backend TTS e circuit breaker."""
import json
import threading

import pytest

import tts_backend_state as st


@pytest.fixture(autouse=True)
def _fresh(tmp_path):
    st.init(str(tmp_path))
    yield


def test_unknown_model_has_empty_state():
    assert st.state("flash31") == {}
    assert st.is_tripped("flash31") is False


def test_trip_marks_the_model_and_persists(tmp_path):
    assert st.trip("flash31", reason="cf_credit_exhausted",
                   detail="HTTP 402 code 2021", job_id="j1") is True
    s = st.state("flash31")
    assert s["active"] == "vertex"
    assert s["trip_reason"] == "cf_credit_exhausted"
    assert s["trip_detail"] == "HTTP 402 code 2021"
    assert s["trip_job_id"] == "j1"
    assert s["tripped_at"]
    assert st.is_tripped("flash31") is True

    on_disk = json.loads((tmp_path / "_tts_backend_state.json").read_text("utf-8"))
    assert on_disk["flash31"]["active"] == "vertex"


def test_trip_is_idempotent_only_the_first_caller_gets_true():
    assert st.trip("flash31", reason="r", detail="d", job_id="j1") is True
    assert st.trip("flash31", reason="r2", detail="d2", job_id="j2") is False
    # Il primo trip resta quello registrato: la causa originale e' quella utile.
    assert st.state("flash31")["trip_job_id"] == "j1"


def test_trip_is_idempotent_under_concurrency():
    winners = []
    barrier = threading.Barrier(8)

    def _worker(i):
        barrier.wait()
        if st.trip("flash31", reason="r", detail=f"d{i}", job_id=f"j{i}"):
            winners.append(i)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1


def test_reset_clears_the_trip():
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    assert st.reset("flash31") is True
    assert st.is_tripped("flash31") is False
    assert st.state("flash31")["active"] == "cloudflare"
    # Un reset a vuoto e' innocuo e lo dichiara.
    assert st.reset("flash31") is False


def test_consecutive_failures_accumulate_and_reset():
    assert st.record_failure("flash31") == 1
    assert st.record_failure("flash31") == 2
    st.record_success("flash31")
    assert st.state("flash31")["consecutive_failures"] == 0


def test_failures_do_not_trip_on_their_own():
    for _ in range(10):
        st.record_failure("flash31")
    # Il conteggio e' un dato; la decisione di scattare spetta al chiamante,
    # che confronta con ABM_CF_TRIP_FAILURES.
    assert st.is_tripped("flash31") is False


def test_state_survives_a_reload(tmp_path):
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    st.init(str(tmp_path))  # simula un riavvio del processo
    assert st.is_tripped("flash31") is True


def test_a_corrupt_file_does_not_crash_the_module(tmp_path):
    (tmp_path / "_tts_backend_state.json").write_text("{non json", encoding="utf-8")
    st.init(str(tmp_path))
    # Uno stato illeggibile non deve impedire la sintesi: si riparte puliti.
    assert st.state("flash31") == {}
    assert st.trip("flash31", reason="r", detail="d", job_id="j") is True


def test_notified_flag_is_settable():
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    assert st.state("flash31")["notified"] is False
    st.mark_notified("flash31")
    assert st.state("flash31")["notified"] is True
