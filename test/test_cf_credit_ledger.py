"""Ledger locale della spesa Cloudflare e pre-allarme sul credito."""
import json
import math
import os
import threading
import time

import pytest

import tts_backend_state as st


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_USD", "5")
    yield


def test_spend_accumulates():
    st.add_spend("flash31", 1.25)
    st.add_spend("flash31", 0.75)
    assert st.credit_left_usd() == pytest.approx(48.0)


def test_spend_is_global_not_per_model():
    # Il credito AI Gateway e' uno solo: la spesa di ogni modello lo intacca.
    st.add_spend("flash31", 10.0)
    st.add_spend("flash25", 10.0)
    assert st.credit_left_usd() == pytest.approx(30.0)


def test_no_alert_while_the_balance_is_comfortable():
    st.add_spend("flash31", 40.0)
    assert st.credit_alert_pending() is False


def test_pending_reports_true_below_threshold():
    st.add_spend("flash31", 46.0)
    assert st.credit_alert_pending() is True


def test_pending_is_pure_and_repeatable(tmp_path):
    # Fix round 2: credit_alert_pending() non deve mutare nulla ne' scrivere
    # su disco - una futura pagina di stato admin deve poterla chiamare N
    # volte senza mai consumare l'unico allarme disponibile.
    st.add_spend("flash31", 46.0)
    state_path = tmp_path / "_tts_backend_state.json"
    before = state_path.read_text("utf-8")
    for _ in range(10):
        assert st.credit_alert_pending() is True
    after = state_path.read_text("utf-8")
    assert before == after
    # L'allarme e' ancora integro: claim_credit_alert() lo trova non ancora
    # consumato e lo consegna al primo (e unico) chiamante reale.
    assert st.claim_credit_alert() is True
    # Da qui in poi anche la lettura pura riflette il consumo.
    assert st.credit_alert_pending() is False


def test_claim_fires_only_once():
    st.add_spend("flash31", 46.0)
    assert st.claim_credit_alert() is True
    assert st.claim_credit_alert() is False


def test_a_topup_rearms_the_alert(monkeypatch):
    st.add_spend("flash31", 46.0)
    assert st.claim_credit_alert() is True
    # L'admin ricarica: alza il saldo dichiarato e azzera il ledger.
    st.reset_spend()
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "100")
    assert st.credit_left_usd() == pytest.approx(100.0)
    assert st.credit_alert_pending() is False
    assert st.claim_credit_alert() is False


def test_a_zero_balance_disables_the_alert(monkeypatch):
    # Saldo non dichiarato (default 0): l'allarme sarebbe rumore costante.
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "0")
    st.add_spend("flash31", 5.0)
    assert st.credit_alert_pending() is False
    assert st.claim_credit_alert() is False


def test_mark_credit_alerted_is_idempotent_and_used_for_rearm_tests():
    st.add_spend("flash31", 46.0)
    st.mark_credit_alerted()
    assert st.credit_alert_pending() is False
    assert st.claim_credit_alert() is False
    st.mark_credit_alerted()  # idempotente, nessun effetto aggiuntivo
    assert st.claim_credit_alert() is False


def test_the_ledger_survives_a_reload(tmp_path):
    st.add_spend("flash31", 12.0)
    st.init(str(tmp_path))
    assert st.credit_left_usd() == pytest.approx(38.0)


def _read_raw(tmp_path):
    with open(os.path.join(str(tmp_path), "_tts_backend_state.json"),
               "r", encoding="utf-8") as f:
        return json.load(f)


def _write_raw(tmp_path, raw):
    with open(os.path.join(str(tmp_path), "_tts_backend_state.json"),
              "w", encoding="utf-8") as f:
        json.dump(raw, f)


def _corrupt_spent_usd(tmp_path, bad_value):
    """Scrive `bad_value` come `_credit.spent_usd` sul file di stato e
    ricarica, come farebbe un file modificato a mano o corrotto a meta'."""
    raw = _read_raw(tmp_path)
    raw.setdefault("_credit", {})["spent_usd"] = bad_value
    _write_raw(tmp_path, raw)
    st.init(str(tmp_path))


@pytest.mark.parametrize("bad_value", ["not-a-number", None, [1, 2, 3], {"x": 1}])
def test_malformed_spent_usd_never_raises(tmp_path, bad_value):
    # Fixture accende gia' il ledger prima di corromperlo, cosi' il file
    # esiste ed ha davvero la chiave "_credit" da corrompere.
    st.add_spend("flash31", 1.0)
    _corrupt_spent_usd(tmp_path, bad_value)
    # Nessuna delle tre deve sollevare: un campo illeggibile vale 0, non
    # un'eccezione che ucciderebbe il percorso caldo della sintesi.
    assert st.credit_left_usd() == pytest.approx(50.0)
    assert st.credit_alert_pending() in (True, False)
    st.add_spend("flash31", 2.0)
    assert st.credit_left_usd() == pytest.approx(48.0)


@pytest.mark.parametrize("bad_value", [math.nan, math.inf, -math.inf])
def test_non_finite_spent_usd_never_raises_and_heals(tmp_path, bad_value, capsys):
    # Fix round 2 (Decisione 1): un valore non finito e' float valido per
    # Python/JSON e passava _safe_float senza filtro.
    # -Infinity spegneva il pre-allarme per sempre (residuo = +Infinity);
    # NaN, dopo un add_spend() reale, rompeva la rilettura di verifica di
    # _save() per l'INTERO modulo (non solo il ledger), da quel momento in
    # poi su qualunque trip/reset/record_failure di qualunque modello.
    st.add_spend("flash31", 1.0)
    _corrupt_spent_usd(tmp_path, bad_value)
    capsys.readouterr()  # scarta l'eventuale log di BOOT sul ledger corrotto

    # Un valore non finito degrada a 0 speso: mai un residuo infinito che
    # spegnerebbe l'allarme per sempre, mai un'eccezione.
    assert st.credit_left_usd() == pytest.approx(50.0)
    assert st.credit_alert_pending() in (True, False)

    # add_spend() reale successivo deve restare sano: il residuo torna
    # finito e prevedibile.
    st.add_spend("flash31", 2.0)
    assert st.credit_left_usd() == pytest.approx(48.0)
    out = capsys.readouterr().out
    assert "ERROR" not in out

    # La sanita' non e' limitata al ledger: un trip/reset su un modello
    # completamente indifferente al ledger deve persistere pulito, senza il
    # falso "stato NON persistito" che il NaN provocava su OGNI _save()
    # successivo nel round precedente.
    assert st.trip("some_other_model", reason="r", detail="d", job_id="j") is True
    out2 = capsys.readouterr().out
    assert "ERROR" not in out2
    assert st.is_tripped("some_other_model") is True
    st.init(str(tmp_path))  # simula un riavvio: il trip deve essere arrivato su disco
    assert st.is_tripped("some_other_model") is True


def test_claim_credit_alert_is_atomic_under_real_concurrency():
    # Residuo sotto soglia: ogni thread che chiama claim_credit_alert()
    # vedrebbe le condizioni per allarmare, se non fosse per l'atomicita'.
    st.add_spend("flash31", 46.0)

    n_threads = 200
    barrier = threading.Barrier(n_threads)
    true_count = 0
    count_lock = threading.Lock()

    def worker():
        nonlocal true_count
        barrier.wait()
        if st.claim_credit_alert():
            # Simula l'invio email (I/O reale, rilascia il GIL) nella
            # finestra in cui una versione non atomica lascerebbe altri
            # thread vedere ancora "non ancora segnalato".
            time.sleep(0.01)
            with count_lock:
                true_count += 1

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert true_count == 1


def test_pending_does_not_interfere_with_concurrent_claim():
    # Chiamate concorrenti a credit_alert_pending() (una pagina di stato
    # letta da piu' richieste) non devono mai rubare l'allarme a
    # claim_credit_alert(): resta esattamente un vincitore.
    st.add_spend("flash31", 46.0)
    barrier = threading.Barrier(21)
    results = []
    lock = threading.Lock()

    def pending_worker():
        barrier.wait()
        for _ in range(50):
            st.credit_alert_pending()

    def claim_worker():
        barrier.wait()
        won = st.claim_credit_alert()
        with lock:
            results.append(won)

    threads = [threading.Thread(target=pending_worker) for _ in range(20)]
    threads.append(threading.Thread(target=claim_worker))
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert results == [True]


# --- Decisione 3: isolamento del ledger dallo spazio dei model_key ---------

def test_old_flat_format_file_is_migrated_and_read_correctly(tmp_path):
    # Formato scritto dai commit precedenti a questo giro: model_key e
    # "_credit" mescolati al top level, nessuna chiave "models".
    _write_raw(tmp_path, {
        "flash31": {
            "active": "vertex", "tripped_at": "2026-01-01T00:00:00Z",
            "trip_reason": "cf_credit_exhausted", "trip_detail": "d",
            "trip_job_id": "j1", "consecutive_failures": 0, "notified": False,
        },
        "_credit": {"spent_usd": 12.0, "alerted": False},
    })
    st.init(str(tmp_path))
    assert st.is_tripped("flash31") is True
    assert st.credit_left_usd() == pytest.approx(38.0)
    # Il ledger non deve mai comparire come modello.
    assert st.state("_credit") == {}
    assert st.is_tripped("_credit") is False


def test_malformed_credit_key_does_not_appear_as_a_model(tmp_path, capsys):
    # Riprodotto in review: un "_credit" non-dict in testa al file veniva
    # trattato dal ramo per-modello come "voce scattata", mescolando
    # concettualmente il ledger nel circuit breaker.
    _write_raw(tmp_path, {
        "_credit": "not-a-dict",
        "flash31": {
            "active": "vertex", "tripped_at": "2026-01-01T00:00:00Z",
            "trip_reason": "r", "trip_detail": "d", "trip_job_id": "j1",
            "consecutive_failures": 0, "notified": False,
        },
    })
    capsys.readouterr()
    st.init(str(tmp_path))
    out = capsys.readouterr().out
    # La riga di BOOT che elenca i modelli scattati non deve mai citare
    # "_credit": solo "flash31" (il ledger corrotto e' un log a parte, non
    # una voce di modello).
    tripped_lines = [line for line in out.splitlines()
                      if "backend gia' scattato per" in line]
    assert tripped_lines and "_credit" not in tripped_lines[0]
    assert "flash31" in tripped_lines[0]
    assert st.state("_credit") == {}
    assert st.is_tripped("_credit") is False
    # Il modello reale non e' toccato dalla corruzione del ledger.
    assert st.is_tripped("flash31") is True
    # Ledger degradato a 0 speso, mai un'eccezione.
    assert st.credit_left_usd() == pytest.approx(50.0)


def test_model_key_literally_credit_does_not_collide_with_the_ledger():
    # Nel formato nuovo il ledger vive al top level sotto "_credit", le
    # voci di modello sotto "models": un model_key letterale "_credit"
    # finisce in models["_credit"], un percorso diverso dal ledger - mai
    # una fusione silenziosa dei due schemi.
    st.add_spend("flash31", 10.0)
    assert st.trip("_credit", reason="r", detail="d", job_id="j1") is True

    assert st.is_tripped("_credit") is True
    assert st.state("_credit")["active"] == "vertex"
    # Il ledger resta intatto e isolato dal trip sul model_key omonimo.
    assert st.credit_left_usd() == pytest.approx(40.0)
    assert st.credit_alert_pending() is False


def test_model_key_literally_credit_survives_a_reload(tmp_path):
    st.add_spend("flash31", 10.0)
    st.trip("_credit", reason="r", detail="d", job_id="j1")
    st.init(str(tmp_path))
    assert st.is_tripped("_credit") is True
    assert st.credit_left_usd() == pytest.approx(40.0)
    # Un reset del modello "_credit" non deve toccare il ledger.
    assert st.reset("_credit") is True
    assert st.is_tripped("_credit") is False
    assert st.credit_left_usd() == pytest.approx(40.0)


# --- Fix round 3: marcatore di versione esplicito, non piu' euristica -------
# Difetto trovato in re-review: un file vecchio con un modello reale chiamato
# letteralmente "models" veniva scambiato per il contenitore del formato
# nuovo, perdendo in silenzio ogni altro modello dello stesso file. Il
# formato si riconosce ora SOLO dal marcatore "version", mai dalla forma dei
# dati.

def _model_entry(reason="cf_credit_exhausted", failures=0, notified=False):
    return {
        "active": "vertex", "tripped_at": "2026-01-01T00:00:00Z",
        "trip_reason": reason, "trip_detail": "d", "trip_job_id": "j1",
        "consecutive_failures": failures, "notified": notified,
    }


def test_old_format_model_literally_named_models_survives_migration(tmp_path):
    # Il caso che ha originato questo giro: file VECCHIO (nessuna chiave
    # "version") con due modelli reali, uno dei quali si chiama letteralmente
    # "models". Prima del marcatore esplicito, la sua voce (un dict, come
    # ogni voce di modello valida) veniva scambiata per il contenitore nuovo:
    # "flash31" spariva in silenzio e "models" stesso veniva distrutto in
    # sette voci fantasma. Con il marcatore, l'assenza di "version" basta da
    # sola a riconoscere il formato vecchio: entrambi i modelli sopravvivono.
    _write_raw(tmp_path, {
        "flash31": _model_entry(failures=3, notified=True),
        "models": _model_entry(reason="edge_tts_down"),
        "_credit": {"spent_usd": 5.0, "alerted": False},
    })
    st.init(str(tmp_path))

    assert st.is_tripped("flash31") is True
    assert st.state("flash31")["consecutive_failures"] == 3
    assert st.state("flash31")["notified"] is True

    assert st.is_tripped("models") is True
    assert st.state("models")["trip_reason"] == "edge_tts_down"

    assert st.credit_left_usd() == pytest.approx(45.0)

    # La migrazione diventa permanente alla prossima riscrittura (non alla
    # sola lettura): un trip su un terzo modello forza _save() a riscrivere
    # il file nel formato nuovo, e i due modelli originali devono restare
    # intatti sia in memoria sia sul file appena riscritto.
    assert st.trip("flash25", reason="r3", detail="d3", job_id="j3") is True
    on_disk = _read_raw(tmp_path)
    assert on_disk["version"] == 2
    assert set(on_disk["models"].keys()) == {"flash31", "models", "flash25"}
    assert "_credit" not in on_disk["models"]

    st.init(str(tmp_path))  # riavvio simulato, ora leggendo il formato nuovo
    assert st.is_tripped("flash31") is True
    assert st.is_tripped("models") is True
    assert st.is_tripped("flash25") is True


def test_old_format_model_literally_named_version(tmp_path, capsys):
    # File vecchio con un modello chiamato letteralmente "version": il suo
    # valore (un dict) non e' mai l'intero esatto _STATE_VERSION, quindi la
    # chiave "version" presente con un valore non riconosciuto attiva il
    # fail-safe sull'intero file (mai riletto come formato vecchio, per non
    # rischiare di reinterpretare in modo sbagliato un formato che non si
    # capisce). E' l'esito sicuro: nessun crash, nessun riarmo silenzioso -
    # "flash31" resta considerato scattato anche se sul disco non lo era.
    _write_raw(tmp_path, {
        "flash31": _model_entry(),
        "version": _model_entry(reason="whatever"),
    })
    capsys.readouterr()
    st.init(str(tmp_path))
    out = capsys.readouterr().out
    assert "non riconosciuto" in out

    assert st.is_tripped("flash31") is True
    assert st.is_tripped("version") is True
    assert st.is_tripped("anything_else_never_seen_before") is True


@pytest.mark.parametrize("bad_version", ["2", None, [2], 2.0, 0, 3])
def test_new_format_with_wrong_type_version_is_fail_safe_not_old_format(
        tmp_path, bad_version, capsys):
    # Un marcatore "version" di tipo sbagliato, o un numero di versione
    # sconosciuto/futuro, non deve MAI degradare a lettura "formato vecchio
    # piatto": interpretare un formato che non si conosce come piatto
    # perderebbe di nuovo dei trip in silenzio. Deve invece attivare il
    # fail-safe sull'intero file, esattamente come un JSON invalido.
    _write_raw(tmp_path, {
        "version": bad_version,
        "_credit": {"spent_usd": 1.0, "alerted": False},
        "models": {"flash31": _model_entry()},
    })
    capsys.readouterr()
    st.init(str(tmp_path))
    out = capsys.readouterr().out
    assert "non riconosciuto" in out

    # Fail-safe globale: qualunque modello, anche uno mai visto, e'
    # considerato scattato finche' un reset esplicito non lo smentisce.
    assert st.is_tripped("flash31") is True
    assert st.is_tripped("never_seen_before") is True
    # Neanche il ledger viene letto da un file di cui non ci fidiamo.
    assert st.credit_left_usd() == pytest.approx(50.0)


def test_new_format_with_non_dict_models_is_fail_safe(tmp_path, capsys):
    _write_raw(tmp_path, {
        "version": 2,
        "_credit": {"spent_usd": 3.0, "alerted": False},
        "models": "not-a-dict",
    })
    capsys.readouterr()
    st.init(str(tmp_path))
    out = capsys.readouterr().out
    assert "non e' un dict" in out

    assert st.is_tripped("flash31") is True
    assert st.credit_left_usd() == pytest.approx(50.0)


def test_new_format_ignores_stray_top_level_keys(tmp_path):
    # Formato nuovo valido: solo "models" contiene voci di modello. Una
    # chiave top-level estranea (non "_credit", non "models", non
    # "version") non e' mai un modello e non deve dare fastidio.
    _write_raw(tmp_path, {
        "version": 2,
        "_credit": {"spent_usd": 0.0, "alerted": False},
        "models": {"flash31": _model_entry()},
        "some_future_field": {"whatever": True},
    })
    st.init(str(tmp_path))
    assert st.is_tripped("flash31") is True
    assert st.is_tripped("some_future_field") is False
    assert st.state("some_future_field") == {}


def test_migration_is_idempotent_across_multiple_reload_cycles(tmp_path):
    # Il file resta nel formato vecchio finche' nessuna mutazione lo
    # riscrive (la migrazione avviene "alla prossima _save()", non alla sola
    # lettura): ogni ciclo qui sotto forza una riscrittura con una spesa
    # nulla (add_spend(..., 0.0) chiama sempre _save() senza alterare il
    # ledger) per verificare che formato nuovo -> nuovo resti stabile quanto
    # vecchio -> nuovo, su piu' cicli consecutivi.
    _write_raw(tmp_path, {
        "flash31": _model_entry(failures=2),
        "models": _model_entry(reason="edge_tts_down", failures=1),
        "_credit": {"spent_usd": 7.0, "alerted": True},
    })
    for _ in range(3):
        st.init(str(tmp_path))
        assert st.is_tripped("flash31") is True
        assert st.state("flash31")["consecutive_failures"] == 2
        assert st.is_tripped("models") is True
        assert st.state("models")["consecutive_failures"] == 1
        assert st.state("models")["trip_reason"] == "edge_tts_down"
        assert st.credit_left_usd() == pytest.approx(43.0)
        assert st.credit_alert_pending() is False  # gia' segnalato ("alerted": True)
        st.add_spend("flash31", 0.0)  # forza la riscrittura senza alterare il ledger

    on_disk = _read_raw(tmp_path)
    assert on_disk["version"] == 2
    assert set(on_disk["models"].keys()) == {"flash31", "models"}
    assert on_disk["_credit"]["spent_usd"] == pytest.approx(7.0)


def test_credit_never_enumerable_as_a_model_in_either_format(tmp_path):
    # Invariante ribadita dalla re-review: "_credit" resta al livello
    # superiore in entrambe le forme e non compare mai fra i modelli
    # resettabili (in _CACHE), ne' nel formato vecchio ne' in quello nuovo.
    _write_raw(tmp_path, {
        "flash31": _model_entry(),
        "_credit": {"spent_usd": 9.0, "alerted": False},
    })
    st.init(str(tmp_path))
    assert st.state("_credit") == {}
    assert "_credit" not in st._CACHE

    # Forza la riscrittura nel formato nuovo: il vincolo resta anche li'.
    st.add_spend("flash31", 0.0)
    on_disk = _read_raw(tmp_path)
    assert on_disk["version"] == 2
    assert "_credit" not in on_disk["models"]

    st.init(str(tmp_path))
    assert "_credit" not in st._CACHE
    assert st.is_tripped("flash31") is True
