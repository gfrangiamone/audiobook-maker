"""Esercita la closure VERA registrata da audiobook_app su
gemini_tts.set_backend_switch_notifier, non una lambda di comodo del test.

Il gap che questo file chiude (review round 1, rilievo MAGGIORE): nessun
altro test invocava mai `audiobook_app._on_tts_backend_switch`.
`test_gemini_failover.py` sovrascrive sempre il notifier con una lambda
locale (verifica solo che *un* notifier venga chiamato, mai quale). I test
di `email_service` chiamano `admin_notify_tts_backend_switch` direttamente,
saltando la closure. Risultato: uno swap di
`tts_backend_state.claim_credit_alert()` (atomico, consuma l'allarme) con
`tts_backend_state.credit_alert_pending()` (pura, non consuma mai nulla) —
esattamente l'errore segnalato in review — lasciava tutta la suite verde.
Con `credit_alert_pending()` l'allarme resterebbe pendente per sempre e
l'email di credito ripartirebbe a ogni singolo switch: un allarme che arriva
mille volte e' un allarme spento.

Verificato manualmente (non solo per costruzione): sostituendo
`claim_credit_alert` con `credit_alert_pending` nella closure di
`audiobook_app.py` e rilanciando questo file,
`test_wired_notifier_claims_the_alert_not_just_peeks` diventa rosso
(l'assert su `calls == ["claim"]` fallisce, vede `["pending"]`); ripristinato
il codice torna verde. Vedi task-4-report.md, sezione "fix round 1".
"""
import pytest

import audiobook_app
import gemini_tts
import tts_backend_state
import email_service


@pytest.fixture
def _registered_notifier():
    """Ri-registra ESPLICITAMENTE la closure vera di audiobook_app nello slot
    globale di gemini_tts e la invoca passando per
    `gemini_tts._backend_switch_notifier`, cioe' esattamente il percorso che
    `_trip_to_vertex` usa in produzione.

    Non ci si puo' affidare al fatto che il notifier registrato all'IMPORT
    di audiobook_app sopravviva fino a qui: altri file di test (es.
    `test_gemini_failover.py`) mutano lo stesso slot globale con una lambda
    locale e lo resettano a `None` nel proprio teardown, indipendentemente
    dall'ordine di raccolta della suite.
    """
    original = gemini_tts._backend_switch_notifier
    gemini_tts.set_backend_switch_notifier(audiobook_app._on_tts_backend_switch)
    try:
        yield lambda *a: gemini_tts._backend_switch_notifier(*a)
    finally:
        gemini_tts.set_backend_switch_notifier(original)


def test_wired_notifier_claims_the_alert_not_just_peeks(monkeypatch, _registered_notifier):
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    calls = []
    monkeypatch.setattr(tts_backend_state, "claim_credit_alert",
                        lambda: calls.append("claim") or True)
    monkeypatch.setattr(tts_backend_state, "credit_alert_pending",
                        lambda: calls.append("pending") or True)
    monkeypatch.setattr(tts_backend_state, "credit_left_usd", lambda: 4.2)
    sent = []
    monkeypatch.setattr(email_service, "admin_notify_tts_backend_switch",
                        lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **kw: None)

    _registered_notifier("flash31", "cf_backend_down", "d", "job-x")

    assert calls == ["claim"], (
        "il notifier deve consumare l'allarme SOLO con claim_credit_alert() "
        "(atomico): con credit_alert_pending() l'allarme non si consuma mai "
        "e l'email di pre-allarme ripartirebbe dopo ogni switch")
    assert sent[0][1]["credit_left_usd"] == pytest.approx(4.2)


def test_wired_notifier_reports_credit_even_when_the_alert_was_already_claimed(
        monkeypatch, _registered_notifier):
    """N3: il claim e' a consumo unico. Se il pre-allarme e' gia' partito —
    cioe' se il credito era gia' sotto soglia, lo scenario in cui il residuo
    serve di piu' — il claim torna False, e legare a quel booleano la riga
    «credito residuo» la faceva sparire proprio dall'email che spiega il
    failover appena avvenuto."""
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    monkeypatch.setattr(tts_backend_state, "claim_credit_alert", lambda: False)
    monkeypatch.setattr(tts_backend_state, "credit_left_usd", lambda: 0.4)
    sent = []
    monkeypatch.setattr(email_service, "admin_notify_tts_backend_switch",
                        lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **kw: None)

    _registered_notifier("flash31", "cf_backend_down", "d", "job-y")

    assert sent[0][1]["credit_left_usd"] == pytest.approx(0.4)


def test_wired_notifier_omits_credit_when_no_balance_is_declared(
        monkeypatch, _registered_notifier):
    """Senza saldo dichiarato (`ABM_CF_CREDIT_BALANCE_USD` a 0, il default) il
    residuo non e' conoscibile: `credit_left_usd()` varrebbe -spesa, un numero
    privo di significato che nell'email sembrerebbe un dato reale."""
    monkeypatch.delenv("ABM_CF_CREDIT_BALANCE_USD", raising=False)
    monkeypatch.setattr(tts_backend_state, "claim_credit_alert", lambda: False)
    monkeypatch.setattr(tts_backend_state, "credit_left_usd", lambda: -9.9)
    sent = []
    monkeypatch.setattr(email_service, "admin_notify_tts_backend_switch",
                        lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **kw: None)

    _registered_notifier("flash31", "cf_backend_down", "d", "job-z")

    assert sent[0][1]["credit_left_usd"] is None


def test_wired_notifier_forwards_reason_model_and_job(monkeypatch, _registered_notifier):
    monkeypatch.setattr(tts_backend_state, "claim_credit_alert", lambda: False)
    sent = []
    monkeypatch.setattr(email_service, "admin_notify_tts_backend_switch",
                        lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **kw: None)

    _registered_notifier("flash31", "cf_consecutive_failures", "HTTP 402", "job-w")

    args, kwargs = sent[0]
    assert args[:4] == ("flash31", "cf_consecutive_failures", "HTTP 402", "job-w")


def test_wired_notifier_logs_activity_with_a_fresh_epoch(monkeypatch, _registered_notifier):
    """Rilievo 3: la chiave di dedup di _log_activity non deve restare
    costante, altrimenti il secondo switch nel mese sparisce in silenzio dal
    business log."""
    monkeypatch.setattr(tts_backend_state, "claim_credit_alert", lambda: False)
    monkeypatch.setattr(email_service, "admin_notify_tts_backend_switch",
                        lambda *a, **kw: None)
    logged = []
    monkeypatch.setattr(audiobook_app, "_log_activity",
                        lambda *a, **kw: logged.append((a, kw)))

    _registered_notifier("flash31", "cf_backend_down", "d", "job-z")

    assert logged, "il notifier deve chiamare _log_activity"
    args, kwargs = logged[0]
    assert args[2] == "TTS_BACKEND_SWITCH"
    assert kwargs.get("epoch") is not None, (
        "senza epoch la chiave di dedup (session_id, operation) resta "
        "costante e gli switch successivi nello stesso mese spariscono")


def test_wired_notifier_omits_credit_when_the_check_is_off(
        monkeypatch, _registered_notifier):
    """A controllo spento il residuo non entra nell'email di failover.

    Con la ricarica automatica attiva sul pannello Cloudflare nessuno
    aggiorna piu' `ABM_CF_CREDIT_BALANCE_USD`: il residuo calcolato su quel
    saldo fermo e' un numero plausibile e falso, e in un'email che annuncia
    un failover manderebbe l'admin a cercare un credito esaurito che non e'
    la causa del guasto.
    """
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "0")
    monkeypatch.setattr(tts_backend_state, "claim_credit_alert", lambda: False)
    monkeypatch.setattr(tts_backend_state, "credit_left_usd", lambda: 12.0)
    sent = []
    monkeypatch.setattr(email_service, "admin_notify_tts_backend_switch",
                        lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **kw: None)

    _registered_notifier("flash31", "cf_backend_down", "d", "job-k")

    assert sent[0][1]["credit_left_usd"] is None


def test_wired_notifier_still_reports_credit_when_the_check_is_on(
        monkeypatch, _registered_notifier):
    """Controprova del test precedente: acceso, il residuo c'e'.

    Senza questa coppia, una guardia scritta al contrario (o sempre vera)
    resterebbe verde nel test che conta l'assenza.
    """
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_CHECK", "1")
    monkeypatch.setattr(tts_backend_state, "claim_credit_alert", lambda: False)
    monkeypatch.setattr(tts_backend_state, "credit_left_usd", lambda: 12.0)
    sent = []
    monkeypatch.setattr(email_service, "admin_notify_tts_backend_switch",
                        lambda *a, **kw: sent.append((a, kw)))
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **kw: None)

    _registered_notifier("flash31", "cf_backend_down", "d", "job-k")

    assert sent[0][1]["credit_left_usd"] == pytest.approx(12.0)
