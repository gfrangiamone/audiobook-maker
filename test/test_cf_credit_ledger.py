"""Ledger locale della spesa Cloudflare e pre-allarme sul credito."""
import json
import os
import threading
import time

import pytest

import tts_backend_state as st


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_EUR", "5")
    yield


def test_spend_accumulates():
    st.add_spend("flash31", 1.25)
    st.add_spend("flash31", 0.75)
    assert st.credit_left_eur() == pytest.approx(48.0)


def test_spend_is_global_not_per_model():
    # Il credito AI Gateway e' uno solo: la spesa di ogni modello lo intacca.
    st.add_spend("flash31", 10.0)
    st.add_spend("flash25", 10.0)
    assert st.credit_left_eur() == pytest.approx(30.0)


def test_no_alert_while_the_balance_is_comfortable():
    st.add_spend("flash31", 40.0)
    assert st.should_alert_credit() is False


def test_alert_fires_below_the_threshold():
    st.add_spend("flash31", 46.0)
    assert st.should_alert_credit() is True


def test_alert_fires_only_once():
    st.add_spend("flash31", 46.0)
    assert st.should_alert_credit() is True
    st.mark_credit_alerted()
    assert st.should_alert_credit() is False


def test_a_topup_rearms_the_alert(monkeypatch):
    st.add_spend("flash31", 46.0)
    st.mark_credit_alerted()
    # L'admin ricarica: alza il saldo dichiarato e azzera il ledger.
    st.reset_spend()
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "100")
    assert st.credit_left_eur() == pytest.approx(100.0)
    assert st.should_alert_credit() is False


def test_a_zero_balance_disables_the_alert(monkeypatch):
    # Saldo non dichiarato (default 0): l'allarme sarebbe rumore costante.
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "0")
    st.add_spend("flash31", 5.0)
    assert st.should_alert_credit() is False


def test_the_ledger_survives_a_reload(tmp_path):
    st.add_spend("flash31", 12.0)
    st.init(str(tmp_path))
    assert st.credit_left_eur() == pytest.approx(38.0)


def _corrupt_spent_eur(tmp_path, bad_value):
    """Scrive `bad_value` come `_credit.spent_eur` sul file di stato e
    ricarica, come farebbe un file modificato a mano o corrotto a meta'."""
    path = os.path.join(str(tmp_path), "_tts_backend_state.json")
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    raw.setdefault("_credit", {})["spent_eur"] = bad_value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(raw, f)
    st.init(str(tmp_path))


@pytest.mark.parametrize("bad_value", ["not-a-number", None, [1, 2, 3], {"x": 1}])
def test_malformed_spent_eur_never_raises(tmp_path, bad_value):
    # Fixture accende gia' il ledger prima di corromperlo, cosi' il file
    # esiste ed ha davvero la chiave "_credit" da corrompere.
    st.add_spend("flash31", 1.0)
    _corrupt_spent_eur(tmp_path, bad_value)
    # Nessuna delle tre deve sollevare: un campo illeggibile vale 0, non
    # un'eccezione che ucciderebbe il percorso caldo della sintesi.
    assert st.credit_left_eur() == pytest.approx(50.0)
    assert st.should_alert_credit() in (True, False)
    st.add_spend("flash31", 2.0)
    assert st.credit_left_eur() == pytest.approx(48.0)


def test_should_alert_credit_is_atomic_under_real_concurrency():
    # Residuo sotto soglia: ogni thread che chiama should_alert_credit()
    # vedrebbe le condizioni per allarmare, se non fosse per l'atomicita'.
    st.add_spend("flash31", 46.0)

    n_threads = 200
    barrier = threading.Barrier(n_threads)
    true_count = 0
    count_lock = threading.Lock()

    def worker():
        nonlocal true_count
        barrier.wait()
        if st.should_alert_credit():
            # Simula l'invio email (I/O reale, rilascia il GIL) nella
            # finestra in cui una versione non atomica lascerebbe altri
            # thread vedere ancora "non ancora segnalato".
            time.sleep(0.01)
            with count_lock:
                true_count += 1
            st.mark_credit_alerted()

    threads = [threading.Thread(target=worker) for _ in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert true_count == 1
