"""Appuntamento della sonda di rientro nello stato persistito.

Questo modulo non esegue la sonda e non decide se vada fatta: custodisce
l'appuntamento, come gia' fa per la soglia di trip, che pure decide il
chiamante. Qui si verifica solo che l'appuntamento sopravviva al disco, che
il raddoppio parta dall'intervallo raggiunto (non da un contatore) e che il
trip "virtuale" del fail-safe non possa mai riarmarsi da solo.
"""
import json
import time

import pytest

import tts_backend_state as st


@pytest.fixture(autouse=True)
def _fresh(tmp_path):
    st.init(str(tmp_path))
    yield


def _trip():
    st.trip("flash31", reason="cf_consecutive_failures", detail="d", job_id="j")


def test_a_fresh_trip_has_no_appointment():
    # E' `gemini_tts._trip_to_vertex` a fissarlo, non `trip()`: la causa del
    # trip puo' non essere sondabile, e lo stato non la giudica.
    _trip()
    assert st.state("flash31")["probe_next_at"] is None
    assert st.probe_due("flash31") is False


def test_schedule_probe_sets_a_future_epoch_and_persists(tmp_path):
    _trip()
    when = st.schedule_probe("flash31", 1800)
    assert when > time.time() + 1700
    on_disk = json.loads((tmp_path / "_tts_backend_state.json").read_text("utf-8"))
    voce = on_disk["models"]["flash31"]
    assert voce["probe_next_at"] == pytest.approx(when)
    # Epoch, non marca ISO: e' l'unico campo dello stato che sia un istante
    # da confrontare, e una stringa costringerebbe ogni lettore a ri-parsarla.
    assert isinstance(voce["probe_next_at"], float)
    assert voce["probe_delay_sec"] == 1800


def test_probe_due_only_when_the_appointment_expired():
    _trip()
    st.schedule_probe("flash31", 3600)
    assert st.probe_due("flash31") is False
    st.schedule_probe("flash31", 1)
    time.sleep(1.1)
    assert st.probe_due("flash31") is True


def test_probe_due_is_false_for_a_model_that_is_not_tripped():
    # Niente da riguadagnare: una sonda su un modello sano sarebbe spesa pura.
    st.schedule_probe("flash31", 1)
    time.sleep(1.1)
    assert st.probe_due("flash31") is False


def test_failure_doubles_from_the_reached_delay_not_from_a_counter():
    # Il raddoppio parte da `probe_delay_sec`, cosi' un riavvio del processo
    # nel mezzo di un failover lungo riprende dal ritmo gia' raggiunto invece
    # di ricominciare a bussare ogni mezz'ora.
    _trip()
    st.schedule_probe("flash31", 1800)
    st.record_probe_failure("flash31", "boom")
    assert st.probe_info("flash31")["delay_sec"] == 3600
    st.record_probe_failure("flash31", "boom")
    assert st.probe_info("flash31")["delay_sec"] == 7200
    assert st.probe_info("flash31")["attempts"] == 2
    assert st.probe_info("flash31")["last_error"] == "boom"


def test_failure_respects_the_cap():
    _trip()
    st.schedule_probe("flash31", 14400)
    st.record_probe_failure("flash31", "boom", max_delay_sec=21600)
    assert st.probe_info("flash31")["delay_sec"] == 21600
    st.record_probe_failure("flash31", "boom", max_delay_sec=21600)
    assert st.probe_info("flash31")["delay_sec"] == 21600


def test_defer_moves_the_appointment_without_growing_the_delay():
    # Sonda NON eseguita (credito sotto soglia): contarla come fallita
    # spingerebbe il backoff verso il tetto durante un'attesa in cui non
    # abbiamo misurato nulla, cioe' proprio mentre l'admin sta ricaricando.
    _trip()
    st.schedule_probe("flash31", 1800)
    prima = st.probe_info("flash31")
    st.defer_probe("flash31")
    dopo = st.probe_info("flash31")
    assert dopo["delay_sec"] == prima["delay_sec"] == 1800
    assert dopo["attempts"] == 0
    assert dopo["next_at"] > prima["next_at"]


def test_clear_probe_disarms_but_keeps_the_trip():
    _trip()
    st.schedule_probe("flash31", 1)
    assert st.clear_probe("flash31") is True
    assert st.probe_info("flash31")["next_at"] is None
    assert st.is_tripped("flash31") is True
    # Idempotente: disarmare due volte non e' un errore.
    assert st.clear_probe("flash31") is False


def test_reset_clears_the_appointment():
    # Rientro manuale dalla console: l'appuntamento non deve sopravvivergli,
    # altrimenti una sonda cadrebbe su un modello gia' tornato sano.
    _trip()
    st.schedule_probe("flash31", 1800)
    st.reset("flash31")
    assert st.state("flash31")["probe_next_at"] is None
    assert st.probe_info("flash31")["attempts"] == 0


def test_a_new_trip_starts_from_a_clean_appointment():
    _trip()
    st.schedule_probe("flash31", 1800)
    st.record_probe_failure("flash31", "boom")
    st.reset("flash31")
    _trip()
    info = st.probe_info("flash31")
    assert info == {"next_at": None, "delay_sec": 0, "attempts": 0,
                    "last_error": None}


def test_the_failsafe_trip_never_arms_itself(tmp_path):
    # Stato illeggibile al boot: ogni modello e' considerato scattato, e
    # riarmarsi da solo sarebbe precisamente il ripristino silenzioso che il
    # fail-safe esiste per impedire.
    (tmp_path / "_tts_backend_state.json").write_text("{ questo non e' json",
                                                      encoding="utf-8")
    st.init(str(tmp_path))
    s = st.state("flash31")
    assert s["trip_reason"] == "state_file_unreadable"
    assert s["probe_next_at"] is None
    assert st.probe_due("flash31") is False


def test_a_malformed_appointment_degrades_to_due_now(tmp_path):
    # Un appuntamento illeggibile che bloccasse per sempre il rientro sarebbe
    # il difetto peggiore dei due: `_safe_float` lo porta a 0.0, la sonda
    # parte una volta di troppo e si ri-arma da sola col valore giusto.
    _trip()
    st.schedule_probe("flash31", 3600)
    with st._LOCK:
        st._CACHE["flash31"]["probe_next_at"] = "domani"
    assert st.probe_due("flash31") is True
