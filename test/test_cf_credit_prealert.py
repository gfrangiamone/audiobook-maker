"""Pre-allarme sul credito Cloudflare: deve partire PRIMA del guasto.

Il difetto che questo file chiude (revisione finale, F2):
`tts_backend_state.claim_credit_alert()` aveva un solo chiamante, la closure
`audiobook_app._on_tts_backend_switch`, cioe' veniva interrogata solo DOPO
che il circuit breaker era gia' scattato. Il residuo di credito compariva
come riga informativa dentro l'email che annunciava un failover gia'
avvenuto: un post-allarme, non un pre-allarme. Con il credito che si
esaurisce di notte, il servizio girava su Vertex (margine 1,9% contro il
61,7% di Cloudflare) fino al mattino senza che nessuno fosse avvisato,
mentre spec §4.4/§11, `md_files/PARAMETRI_CONFIGURAZIONE.md` §7.8 e il
runbook §2 promettevano tutti un avviso sotto `ABM_CF_CREDIT_ALERT_USD`.

Il pre-allarme vive ora in `gemini_tts._maybe_alert_credit()`, chiamata da
`synthesize()` subito dopo `add_spend()` — l'unico istante in cui il residuo
stimato puo' essere sceso sotto soglia, e con il backend ancora sano.

Prova di mutazione (vedi final-fix-report.md): togliendo la chiamata a
`_maybe_alert_credit()` dopo `add_spend()` in `gemini_tts.synthesize()`
diventano rossi `test_a_cloudflare_call_under_threshold_fires_the_prealert`
e i due che ne dipendono; togliendo la guardia `if _credit_alert_notifier is
None: return` diventa rosso
`test_the_alert_is_not_burned_when_no_notifier_is_registered`.
"""
import pytest

import audiobook_app
import email_service
import gemini_tts
import tts_backend_state as st


PCM_20_SECONDI = b"\x00" * (24000 * 2 * 20)

# Catturato all'IMPORT del modulo di test, cioe' in fase di collection,
# prima che qualunque test possa mutare lo slot globale: e' il notifier che
# `audiobook_app` registra da solo all'avvio. Serve a
# `test_the_app_registers_a_credit_alert_notifier_at_startup`, che altrimenti
# non potrebbe distinguere "registrato in produzione" da "registrato da una
# fixture di questo file".
_NOTIFIER_AT_IMPORT = gemini_tts._credit_alert_notifier


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    creds = tmp_path / "sa.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "progetto")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    # Credenziali Cloudflare FINTE: il trasporto e' sempre monkeypatchato,
    # nessuna connessione viene mai aperta.
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "account-di-test")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "token-di-test")
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_USD", "5")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    monkeypatch.setattr(gemini_tts.time, "sleep", lambda s: None)
    original_switch = gemini_tts._backend_switch_notifier
    original_credit = gemini_tts._credit_alert_notifier
    gemini_tts.set_backend_switch_notifier(None)
    gemini_tts.set_credit_alert_notifier(None)
    yield
    gemini_tts._BACKEND = {}
    gemini_tts.set_backend_switch_notifier(original_switch)
    gemini_tts.set_credit_alert_notifier(original_credit)
    st.reset("flash31")
    st.reset("flash25")


def _cf_ok(**kw):
    return {"pcm": PCM_20_SECONDI, "input_tokens": None, "output_tokens": None}


def _synth(tmp_path):
    return gemini_tts.synthesize(
        "ciao mondo, questa e' una frase di prova ragionevole",
        "gemini:flash31:Kore", output_path=str(tmp_path / "o.pcm"))


# --- Il pre-allarme parte dalla sintesi, non dal trip ----------------------

def test_a_cloudflare_call_under_threshold_fires_the_prealert(tmp_path, monkeypatch):
    """Nessun trip, nessun failover: il backend e' sano e il credito e'
    appena sceso sotto soglia. E' esattamente il caso che prima non produceva
    alcuna notifica."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_ok)
    st.add_spend("flash31", 46.0)  # residuo stimato: 4,00 USD < soglia 5,00
    fired = []
    gemini_tts.set_credit_alert_notifier(
        lambda model_key, left: fired.append((model_key, left)))

    out = _synth(tmp_path)

    assert out["backend"] == "cloudflare"
    assert st.is_tripped("flash31") is False, (
        "il pre-allarme deve arrivare mentre il backend e' ancora sano")
    assert len(fired) == 1
    assert fired[0][0] == "flash31"
    assert fired[0][1] == pytest.approx(st.credit_left_usd())
    assert fired[0][1] < 5.0


def test_the_prealert_fires_only_once_across_repeated_calls(tmp_path, monkeypatch):
    """`claim_credit_alert()` consuma l'allarme: le sintesi successive, con il
    credito ancora sotto soglia, non devono ri-notificare nulla. Un allarme
    che arriva a ogni job e' un allarme spento."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_ok)
    st.add_spend("flash31", 46.0)
    fired = []
    gemini_tts.set_credit_alert_notifier(lambda mk, left: fired.append(mk))

    _synth(tmp_path)
    _synth(tmp_path)
    _synth(tmp_path)

    assert len(fired) == 1


def test_no_prealert_while_the_credit_is_above_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_ok)
    st.add_spend("flash31", 10.0)  # residuo 40,00 USD
    fired = []
    gemini_tts.set_credit_alert_notifier(lambda mk, left: fired.append(mk))

    _synth(tmp_path)

    assert fired == []


def test_a_vertex_call_never_fires_the_prealert(tmp_path, monkeypatch):
    """Il ledger e' quello Cloudflare: una chiamata eseguita su Vertex non lo
    intacca, quindi non puo' far scendere il residuo e non deve nemmeno
    guardare la soglia."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 5, "output_tokens": 25})
    st.add_spend("flash31", 46.0)  # gia' sotto soglia
    fired = []
    gemini_tts.set_credit_alert_notifier(lambda mk, left: fired.append(mk))

    out = _synth(tmp_path)

    assert out["backend"] == "vertex"
    assert fired == []


def test_the_prealert_is_disabled_when_no_balance_is_declared(tmp_path, monkeypatch):
    """Con `ABM_CF_CREDIT_BALANCE_USD=0` (default) il residuo non e'
    conoscibile: silenzio totale, non rumore costante."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "0")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_ok)
    fired = []
    gemini_tts.set_credit_alert_notifier(lambda mk, left: fired.append(mk))

    _synth(tmp_path)

    assert fired == []


# --- L'allarme e' una risorsa a consumo singolo: non va bruciato ----------

def test_the_alert_is_not_burned_when_no_notifier_is_registered(tmp_path, monkeypatch):
    """`claim_credit_alert()` e' un check-and-set che consuma l'unica
    notifica disponibile. Interrogarlo senza avere un notifier a cui
    consegnarla la spegnerebbe per sempre in silenzio: la guardia sul
    notifier deve venire PRIMA della claim."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_ok)
    st.add_spend("flash31", 46.0)
    gemini_tts.set_credit_alert_notifier(None)

    _synth(tmp_path)

    assert st.credit_alert_pending() is True, (
        "senza notifier registrato l'allarme non deve essere consumato")
    assert st.claim_credit_alert() is True


def test_a_failing_notifier_never_breaks_a_successful_synthesis(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_ok)
    st.add_spend("flash31", 46.0)
    gemini_tts.set_credit_alert_notifier(
        lambda mk, left: (_ for _ in ()).throw(RuntimeError("SMTP giu'")))

    out = _synth(tmp_path)  # non deve sollevare

    assert out["success"] is True


# --- La closure vera di audiobook_app -------------------------------------

def test_the_app_registers_a_credit_alert_notifier_at_startup():
    """Il confronto e' per identita' logica (modulo + qualname), non per
    identita' di oggetto: parecchi file della suite (`test_cold_*.py`,
    `test_admin_translation_audit_endpoint.py`, ...) fanno
    `importlib.reload(audiobook_app)`, che ricrea la closure e farebbe fallire
    un `is` pur essendo la registrazione perfettamente in piedi. La mutazione
    che questo test deve intercettare — togliere
    `gemini_tts.set_credit_alert_notifier(_on_cf_credit_alert)` dall'avvio —
    lascia lo slot a `None` e resta rossa lo stesso.
    """
    assert _NOTIFIER_AT_IMPORT is not None, (
        "audiobook_app deve registrare il notifier di pre-allarme credito "
        "all'avvio: senza registrazione _maybe_alert_credit non manda nulla")
    assert _NOTIFIER_AT_IMPORT.__module__ == "audiobook_app"
    assert _NOTIFIER_AT_IMPORT.__qualname__ == "_on_cf_credit_alert"
    assert callable(getattr(audiobook_app, "_on_cf_credit_alert", None))


def test_the_wired_closure_sends_a_dedicated_email(monkeypatch):
    """L'email di pre-allarme deve essere la sua, non quella di switch: la
    seconda annuncia un failover gia' avvenuto e direbbe il falso."""
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_USD", "7.5")
    sent = []
    switch_sent = []
    monkeypatch.setattr(email_service, "admin_notify_cf_credit_low",
                        lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(email_service, "admin_notify_tts_backend_switch",
                        lambda *a, **kw: switch_sent.append((a, kw)))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **kw: None)

    gemini_tts.set_credit_alert_notifier(audiobook_app._on_cf_credit_alert)
    gemini_tts._credit_alert_notifier("flash31", 3.25)

    assert switch_sent == [], (
        "il pre-allarme non deve riusare l'email di failover")
    assert len(sent) == 1
    args, _kwargs = sent[0]
    assert args[0] == "flash31"
    assert args[1] == pytest.approx(3.25)
    # La soglia arriva da tts_backend_state, non riletta a mano dal
    # chiamante: due letture dell'ambiente divergono nel tempo.
    assert args[2] == pytest.approx(7.5)


def test_the_wired_closure_logs_the_event_with_a_fresh_epoch(monkeypatch):
    monkeypatch.setattr(email_service, "admin_notify_cf_credit_low",
                        lambda *a, **kw: None)
    logged = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: logged.append((a, kw)))

    gemini_tts.set_credit_alert_notifier(audiobook_app._on_cf_credit_alert)
    gemini_tts._credit_alert_notifier("flash31", 3.25)

    assert logged
    args, kwargs = logged[0]
    assert args[2] == "TTS_CF_CREDIT_LOW"
    assert kwargs.get("epoch") is not None


# --- Il corpo dell'email --------------------------------------------------

def test_the_email_states_residue_threshold_and_what_to_do(monkeypatch):
    captured = {}
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(email_service, "_send_email",
                        lambda to, subject, body: captured.update(
                            to=to, subject=subject, body=body) or True)

    email_service.admin_notify_cf_credit_low("flash31", 3.25, 5.0)

    assert "3.25" in captured["subject"]
    assert "3.25" in captured["body"]
    assert "5.00" in captured["body"]
    assert "ABM_CF_CREDIT_BALANCE_USD" in captured["body"]
    # Non deve mai apparire il nome della variabile del token, ne' un valore.
    assert "ABM_CF_API_TOKEN" not in captured["body"]
    # E non deve annunciare un failover che non e' avvenuto.
    assert "Vertex" in captured["body"]  # citato solo come conseguenza futura
    assert "switch automatico" not in captured["subject"]


def test_the_email_is_silent_without_an_admin_address(monkeypatch):
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(email_service, "_send_email",
                        lambda *a: pytest.fail("nessuna email senza ADMIN_EMAIL"))

    email_service.admin_notify_cf_credit_low("flash31", 3.25, 5.0)


def test_the_email_survives_a_non_numeric_residue(monkeypatch):
    """Il residuo attraversa una formattazione `:.2f`: un valore inatteso non
    deve trasformare un avviso mancato in un'eccezione dentro il percorso di
    sintesi."""
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(email_service, "_send_email", lambda *a: True)

    email_service.admin_notify_cf_credit_low("flash31", None, None)


def test_no_prealert_when_the_admin_turned_the_check_off(tmp_path, monkeypatch):
    """`ABM_CF_CREDIT_CHECK=0`: la sintesi non deve piu' allarmare nessuno.

    E' il caso delle installazioni che hanno attivato la ricarica automatica
    a soglia sul pannello Cloudflare: il credito si rialza da solo, quindi il
    residuo stimato da questo modulo non descrive nulla di azionabile e
    l'email diventerebbe rumore periodico su una condizione gia' risolta dal
    fornitore. Il percorso esercitato e' quello vero (`synthesize` ->
    `add_spend` -> `_maybe_alert_credit`), non la sola funzione di stato.
    """
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "0")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_ok)
    st.add_spend("flash31", 46.0)  # residuo 4,00 USD: sotto soglia
    fired = []
    gemini_tts.set_credit_alert_notifier(lambda mk, left: fired.append(mk))

    _synth(tmp_path)

    assert fired == []
    # L'allarme e' sospeso, non consumato: riaccendendo il controllo deve
    # essere ancora disponibile, altrimenti il periodo di silenzio lo avrebbe
    # bruciato e nessuna email arriverebbe piu' nemmeno dopo.
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "1")
    _synth(tmp_path)
    assert fired == ["flash31"]


def test_spending_is_still_recorded_while_the_check_is_off(tmp_path, monkeypatch):
    """Lo spegnimento tocca l'allarme, mai la contabilita' della spesa."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "0")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_ok)
    prima = st.credit_spent_usd()

    _synth(tmp_path)

    assert st.credit_spent_usd() > prima
