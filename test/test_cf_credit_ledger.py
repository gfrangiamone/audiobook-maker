"""Ledger locale della spesa Cloudflare e pre-allarme sul credito."""
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
