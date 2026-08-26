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
    # Fix round 1: un file PRESENTE ma illeggibile NON deve mai essere
    # confuso con "nessun trip e' mai avvenuto" (riarmo silenzioso di un
    # interruttore a senso unico). Fail-safe: si considera scattato finche'
    # un reset esplicito non lo smentisce - mai un'eccezione propagata.
    assert st.is_tripped("flash31") is True
    assert st.state("flash31")["active"] == "vertex"
    # Non e' un secondo trip "vero": prima d'ora non esisteva un record
    # concreto per questo modello. trip() lo materializza con la causa reale
    # e ritorna True al primo che lo fa (idempotente come sempre sotto lock).
    assert st.trip("flash31", reason="r", detail="d", job_id="j") is True
    assert st.state("flash31")["trip_job_id"] == "j"
    # Un reset esplicito lo riporta pulito, come qualunque altro trip.
    assert st.reset("flash31") is True
    assert st.is_tripped("flash31") is False


def test_notified_flag_is_settable():
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    assert st.state("flash31")["notified"] is False
    st.mark_notified("flash31")
    assert st.state("flash31")["notified"] is True


def test_per_model_entry_with_wrong_schema_is_treated_as_tripped(tmp_path):
    # JSON valido a livello di file, ma la voce per-modello ha una forma
    # diversa da quella attesa (schema diverso, non un dict). Riprodotto dal
    # revisore come crash live (ValueError/AttributeError) nel round 1: qui
    # deve degradare pulito, mai sollevare, e trattare il modello come
    # scattato (mai "pulito" su una voce che non si sa leggere).
    (tmp_path / "_tts_backend_state.json").write_text(
        json.dumps({"flash31": "not-a-dict"}), encoding="utf-8")
    st.init(str(tmp_path))
    assert st.is_tripped("flash31") is True
    assert st.state("flash31")["active"] == "vertex"
    # Gia' scattato per schema corrotto: un trip() successivo non e' il primo.
    assert st.trip("flash31", reason="r", detail="d", job_id="j") is False


def test_reset_survives_a_reload(tmp_path):
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    st.reset("flash31")
    st.init(str(tmp_path))  # simula un riavvio del processo
    assert st.is_tripped("flash31") is False
    assert st.state("flash31")["active"] == "cloudflare"


def test_save_failure_is_logged_loudly_and_does_not_break_in_memory_state(monkeypatch, capsys):
    def _boom(*args, **kwargs):
        raise OSError("disco pieno (simulato)")

    monkeypatch.setattr(st.community_store, "atomic_write_json", _boom)
    capsys.readouterr()  # scarta eventuale output precedente

    # Anche se la persistenza fallisce, il primo chiamante deve comunque
    # vincere: l'idempotenza durante la vita del processo non dipende dal
    # disco. Il fallimento va pero' loggato in modo inequivocabile, perche'
    # e' il caso peggiore per un interruttore a senso unico (un riavvio
    # dimenticherebbe il trip).
    assert st.trip("flash31", reason="r", detail="d", job_id="j1") is True
    assert st.is_tripped("flash31") is True

    out = capsys.readouterr().out
    assert "ERROR" in out
    assert "tts-backend-state" in out


def test_boot_log_is_loud_when_reloading_a_tripped_state(tmp_path, capsys):
    st.trip("flash31", reason="cf_credit_exhausted", detail="d", job_id="j1")
    capsys.readouterr()  # scarta l'output del trip
    st.init(str(tmp_path))  # simula un riavvio: ricarica dal disco
    out = capsys.readouterr().out
    # Serve a distinguere, leggendo i log dopo un riavvio, "Cloudflare attivo
    # perche' non era mai scattato" da "Cloudflare attivo perche' lo stato
    # scattato non e' stato ricaricato" (allineato a gemini_tts._load_admin_state).
    assert "BOOT" in out
    assert "flash31" in out


def _make_failsafe(tmp_path):
    """File PRESENTE ma illeggibile: attiva _FAIL_SAFE globale senza che
    nessun modello abbia ancora una voce concreta in _CACHE."""
    (tmp_path / "_tts_backend_state.json").write_text("{non json", encoding="utf-8")
    st.init(str(tmp_path))


def test_record_failure_does_not_silently_clear_a_failsafe_trip(tmp_path):
    # Fix round 2 (Difetto 1): prima di questo fix, record_failure/success/
    # mark_notified creavano una voce vuota via _CACHE.setdefault(k, {}),
    # ignorando _FAIL_SAFE. Una voce vuota non ha tripped_at, quindi da quel
    # momento is_tripped() la leggeva come "pulita" senza che nessuno avesse
    # mai chiamato reset(): riarmo silenzioso del breaker.
    _make_failsafe(tmp_path)
    assert st.is_tripped("modelA") is True  # scattato solo virtualmente
    st.record_failure("modelA")
    assert st.is_tripped("modelA") is True  # deve restare scattato


def test_record_success_does_not_silently_clear_a_failsafe_trip(tmp_path):
    _make_failsafe(tmp_path)
    assert st.is_tripped("modelB") is True
    st.record_success("modelB")
    assert st.is_tripped("modelB") is True


def test_mark_notified_does_not_silently_clear_a_failsafe_trip(tmp_path):
    _make_failsafe(tmp_path)
    assert st.is_tripped("modelC") is True
    st.mark_notified("modelC")
    assert st.is_tripped("modelC") is True
    assert st.state("modelC")["notified"] is True


def test_first_real_trip_on_a_failsafe_model_records_the_real_cause(tmp_path):
    _make_failsafe(tmp_path)
    assert st.is_tripped("modelD") is True  # solo virtuale
    assert st.trip("modelD", reason="real_reason", detail="real detail",
                   job_id="jX") is True
    s = st.state("modelD")
    assert s["trip_reason"] == "real_reason"
    assert s["trip_detail"] == "real detail"
    assert s["trip_job_id"] == "jX"
    # E' comunque idempotente da qui in avanti: un secondo trip non vince piu'.
    assert st.trip("modelD", reason="other", detail="other",
                   job_id="jY") is False
    assert st.state("modelD")["trip_job_id"] == "jX"


def test_first_real_trip_on_a_failsafe_model_under_concurrency(tmp_path):
    _make_failsafe(tmp_path)
    assert st.is_tripped("modelE") is True  # solo virtuale, nessun record concreto
    winners = []
    barrier = threading.Barrier(8)

    def _worker(i):
        barrier.wait()
        if st.trip("modelE", reason="r", detail=f"d{i}", job_id=f"j{i}"):
            winners.append(i)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    # Esattamente un vincitore, anche partendo da uno stato scattato solo
    # virtualmente: la materializzazione fail-safe non deve ne' far vincere
    # piu' di un thread, ne' far perdere a tutti (0 vincitori sarebbe un trip
    # reale mai registrato).
    assert len(winners) == 1
    winner_job = f"j{winners[0]}"
    assert st.state("modelE")["trip_job_id"] == winner_job


def test_record_failure_with_non_numeric_counter_does_not_raise():
    # Difetto 2: consecutive_failures puo' essere una stringa (o altro tipo)
    # in una voce altrimenti valida, senza che l'intero file sia illeggibile
    # (quel caso e' gia' coperto da test_a_corrupt_file_does_not_crash_the_module).
    # _safe_int deve degradare a 0, mai sollevare ValueError sul percorso
    # caldo della sintesi.
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    st._CACHE["flash31"]["consecutive_failures"] = "not-a-number"
    assert st.record_failure("flash31") == 1
    assert st.state("flash31")["consecutive_failures"] == 1
