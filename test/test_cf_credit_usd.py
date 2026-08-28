"""Credito Cloudflare in USD: migrazione, ripiego sui nomi vecchi, spegnimento.

Il credito AI Gateway e' prepagato e denominato in DOLLARI, e non e'
leggibile via API: l'unico modo di sorvegliarlo e' un ledger locale
confrontato con un saldo che l'admin dichiara a mano. Finche' quel ledger
teneva i conti in euro, ogni verifica passava da un cambio mentale fra la
cifra del pannello e quella della dashboard del fornitore. Questo file copre
i tre punti in cui il passaggio a USD puo' rompersi in silenzio - cioe'
senza errori, continuando a rispondere numeri plausibili:

1. **La migrazione del ledger.** Un file scritto prima del passaggio porta
   `spent_eur`. Buttarlo significherebbe ripartire da 0 speso su un credito
   gia' consumato: il residuo stimato risalirebbe di colpo e il pre-allarme
   resterebbe muto fino all'esaurimento vero, cioe' fino al failover.

2. **Il ripiego sui nomi di variabile vecchi.** Un deploy che arriva prima
   dell'aggiornamento dell'unit systemd trova `ABM_CF_CREDIT_BALANCE_EUR` e
   non `..._USD`. Senza ripiego leggerebbe 0, e un saldo dichiarato a 0
   SPEGNE il pre-allarme senza dirlo a nessuno: l'admin scoprirebbe il
   credito finito dal failover, cioe' proprio dall'evento che il pre-allarme
   esiste per anticipare.

3. **Lo spegnimento esplicito del controllo** (`ABM_CF_CREDIT_CHECK=0`), per
   le installazioni che hanno attivato la ricarica automatica a soglia sul
   pannello Cloudflare: li' il residuo non descrive piu' nulla di azionabile
   e l'email diventerebbe rumore periodico su una condizione che il
   fornitore risolve da solo. Lo spegnimento non deve pero' CONSUMARE
   l'allarme, o riaccendere il controllo lo ritroverebbe gia' bruciato.

Nota sul cambio: `ABM_GEMINI_USD_EUR_RATE` serve qui a due sole cose -
migrare un ledger vecchio e affiancare l'equivalente in euro. Non entra MAI
nel confronto che decide un allarme: saldo, spesa e soglia si confrontano
fra loro sempre in USD, cosi' un ritocco del cambio non puo' far scattare
(ne' tacere) il pre-allarme. Il test `test_the_rate_never_moves_the_alarm`
e' la prova di questa proprieta'.
"""
import json

import pytest

import tts_backend_state as st


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    """Ambiente pulito: nessuna variabile di credito ereditata dalla shell.

    `delenv` esplicito su tutti e sei i nomi (nuovi, vecchi e interruttore):
    un valore rimasto nell'ambiente dello sviluppatore renderebbe verdi test
    che asseriscono proprio l'assenza di quella variabile.
    """
    for name in ("ABM_CF_CREDIT_BALANCE_USD", "ABM_CF_CREDIT_BALANCE_EUR",
                 "ABM_CF_CREDIT_ALERT_USD", "ABM_CF_CREDIT_ALERT_EUR",
                 "ABM_CF_CREDIT_CHECK", "ABM_GEMINI_USD_EUR_RATE"):
        monkeypatch.delenv(name, raising=False)
    st._LEGACY_ENV_WARNED.clear()
    st.init(str(tmp_path))
    yield
    st._LEGACY_ENV_WARNED.clear()


def _write_state(tmp_path, credit):
    """Scrive a mano un file di stato con il ledger dato, poi ricarica."""
    path = tmp_path / "_tts_backend_state.json"
    path.write_text(json.dumps({
        "version": 2,
        "_credit": credit,
        "models": {},
    }), encoding="utf-8")
    st.init(str(tmp_path))


# --------------------------------------------------------------------------
# 1. Migrazione del ledger EUR -> USD
# --------------------------------------------------------------------------

def test_an_old_eur_ledger_is_converted_to_usd_at_the_declared_rate(
        tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.80")
    _write_state(tmp_path, {"spent_eur": 8.0, "alerted": False})
    # 8 EUR spesi a 0,80 EUR/USD sono 10 USD: la spesa NON cambia di valore,
    # cambia solo l'unita' in cui e' scritta.
    assert st.credit_spent_usd() == pytest.approx(10.0)


def test_the_migration_preserves_the_alerted_flag(tmp_path, monkeypatch):
    """Un allarme gia' dato non si riarma passando di valuta.

    Se la migrazione perdesse `alerted`, il primo addebito dopo il deploy
    rimanderebbe un'email che l'admin ha gia' ricevuto e su cui ha gia'
    agito.
    """
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.86")
    _write_state(tmp_path, {"spent_eur": 40.0, "alerted": True})
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    assert st.credit_alert_pending() is False


def test_a_usd_ledger_wins_over_a_stale_eur_field(tmp_path, monkeypatch):
    """Con entrambi i campi presenti vince `spent_usd`, mai la conversione.

    Il caso si presenta a un rollback: la versione nuova scrive `spent_usd`,
    la vecchia rimessa in linea riscrive `spent_eur` accanto senza togliere
    l'altro. Convertire il campo vecchio butterebbe via la spesa piu'
    recente.
    """
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.50")
    _write_state(tmp_path, {"spent_usd": 3.0, "spent_eur": 99.0})
    assert st.credit_spent_usd() == pytest.approx(3.0)


def test_a_ledger_with_neither_field_starts_from_zero(tmp_path):
    _write_state(tmp_path, {"alerted": False})
    assert st.credit_spent_usd() == 0.0


def test_a_malformed_eur_amount_degrades_to_zero_instead_of_raising(
        tmp_path, monkeypatch):
    """`spent_eur` illeggibile non deve uccidere il boot.

    La divisione per il cambio avviene su un valore gia' passato da
    `_safe_float`: una stringa non numerica vale 0, non un TypeError sul
    percorso di caricamento dello stato.
    """
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.86")
    _write_state(tmp_path, {"spent_eur": "non-un-numero"})
    assert st.credit_spent_usd() == 0.0


# --------------------------------------------------------------------------
# 2. Il cambio
# --------------------------------------------------------------------------

def test_the_rate_defaults_to_the_project_wide_value():
    assert st.usd_eur_rate() == pytest.approx(0.86)


@pytest.mark.parametrize("raw", ["0", "-1", "non-un-numero", ""])
def test_an_unusable_rate_degrades_to_the_default(raw, monkeypatch):
    """Zero, negativo o illeggibile: mai propagare un cambio inutilizzabile.

    Un cambio 0 dividerebbe per zero nella migrazione del ledger; uno
    negativo produrrebbe una spesa negativa, cioe' un residuo che cresce a
    ogni chiamata.
    """
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", raw)
    assert st.usd_eur_rate() == pytest.approx(0.86)


def test_to_eur_converts_for_display_only(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.90")
    assert st.to_eur(10.0) == pytest.approx(9.0)


def test_the_rate_never_moves_the_alarm(tmp_path, monkeypatch):
    """Il cambio non entra nel confronto che decide l'allarme.

    Stesso saldo, stessa spesa, stessa soglia, cambio spostato del 40%: il
    verdetto non si muove. Se un giorno qualcuno reintroducesse una
    conversione dentro `credit_alert_pending()`, questo test diventerebbe
    rosso prima che lo scopra un'email mancata in produzione.
    """
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_USD", "5")
    st.add_spend("flash31", 46.0)  # residuo 4,00 USD, sotto soglia

    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.60")
    sotto_con_cambio_basso = st.credit_alert_pending()
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "1.00")
    sotto_con_cambio_alto = st.credit_alert_pending()

    assert sotto_con_cambio_basso is True
    assert sotto_con_cambio_alto is True


# --------------------------------------------------------------------------
# 3. Ripiego sui nomi di variabile vecchi
# --------------------------------------------------------------------------

def test_a_legacy_eur_balance_is_still_honoured_converted(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.80")
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "40")
    # 40 EUR dichiarati a 0,80 sono 50 USD di saldo.
    assert st.declared_balance_usd() == pytest.approx(50.0)


def test_the_new_name_wins_when_both_are_declared(monkeypatch):
    """Durante la migrazione le due variabili convivono nell'unit systemd.

    Vince sempre quella nuova: e' il valore che l'admin ha appena scritto,
    l'altra e' il residuo di cio' che sta togliendo.
    """
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.80")
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "100")
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "40")
    assert st.declared_balance_usd() == pytest.approx(100.0)


def test_a_legacy_eur_threshold_is_still_honoured_converted(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.80")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_EUR", "4")
    assert st.credit_alert_threshold_usd() == pytest.approx(5.0)


def test_the_threshold_falls_back_to_the_default_when_nothing_is_declared():
    assert st.credit_alert_threshold_usd() == pytest.approx(5.0)


def test_the_legacy_warning_is_printed_once_per_process(monkeypatch, capsys):
    """L'avviso sta sul percorso caldo: un print per chunk sarebbe rumore.

    `_declared_balance_usd()` viene interrogata a ogni pre-allarme, cioe'
    dopo ogni chiamata sintetizzata su Cloudflare.
    """
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "40")
    for _ in range(5):
        st.declared_balance_usd()
    uscita = capsys.readouterr().out
    assert uscita.count("ABM_CF_CREDIT_BALANCE_EUR e' obsoleta") == 1
    assert "ABM_CF_CREDIT_BALANCE_USD" in uscita


def test_the_legacy_balance_still_drives_the_prealert(monkeypatch):
    """Il punto per cui il ripiego esiste: l'allarme continua a scattare.

    Senza ripiego il saldo varrebbe 0, e con saldo 0 il pre-allarme e' spento
    per costruzione: nessun errore, nessun log, solo silenzio fino al
    failover.
    """
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0.80")
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "40")   # = 50 USD
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_EUR", "4")      # = 5 USD
    st.add_spend("flash31", 46.0)                           # residuo 4 USD
    assert st.credit_alert_pending() is True


# --------------------------------------------------------------------------
# 4. Spegnimento del controllo (ricarica automatica lato Cloudflare)
# --------------------------------------------------------------------------

def test_the_check_is_enabled_by_default():
    assert st.credit_check_enabled() is True


@pytest.mark.parametrize("raw", ["0", "false", "no", "off", "FALSE", " 0 "])
def test_the_check_can_be_turned_off(raw, monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", raw)
    assert st.credit_check_enabled() is False


@pytest.mark.parametrize("raw", ["1", "true", "yes", "on", "TRUE", ""])
def test_the_check_stays_on_for_affirmative_and_empty_values(raw, monkeypatch):
    """Vuoto = non dichiarata = acceso: solo un no esplicito spegne."""
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", raw)
    assert st.credit_check_enabled() is True


def test_no_prealert_when_the_check_is_off(monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_USD", "5")
    st.add_spend("flash31", 46.0)      # residuo 4 USD: sotto soglia
    assert st.credit_alert_pending() is True

    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "0")
    assert st.credit_alert_pending() is False
    assert st.claim_credit_alert() is False


def test_turning_the_check_off_does_not_burn_the_alert(monkeypatch):
    """Lo spegnimento sospende l'allarme, non lo consuma.

    Se `claim_credit_alert()` marcasse `alerted` prima di uscire, chi
    riaccende il controllo (ricarica automatica sospesa, carta scaduta) si
    ritroverebbe l'unica occasione di allarme gia' bruciata durante il
    periodo di silenzio, e nessuna email arriverebbe mai piu'.
    """
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_USD", "5")
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "0")
    st.add_spend("flash31", 46.0)
    assert st.claim_credit_alert() is False

    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "1")
    assert st.claim_credit_alert() is True


def test_spending_is_still_accounted_while_the_check_is_off(monkeypatch):
    """Lo spegnimento tocca l'allarme, mai la contabilita'.

    Sapere quanto costa Cloudflare resta utile anche quando il credito si
    ricarica da solo: e' il "quanto ne resta" a perdere significato, non il
    "quanto ne ho speso".
    """
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "0")
    st.add_spend("flash31", 1.25)
    st.add_spend("flash31", 0.75)
    assert st.credit_spent_usd() == pytest.approx(2.0)
