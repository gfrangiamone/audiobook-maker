"""Rientro automatico su Cloudflare tramite sonda in background.

Il rientro automatico e' ammissibile solo perche' non passa MAI da un job
vero: la sonda sintetizza due parole senza alcun utente collegato e butta via
l'audio. Una sonda fallita costa una richiesta HTTP rifiutata; un job vero
rimandato su un backend ancora guasto costerebbe un audiolibro - ed e'
esattamente l'obiezione che teneva il rientro manuale.

Cosa mordono questi test, oltre al cammino felice:
 - la sonda parla DIRETTAMENTE all'adapter Cloudflare, perche'
   `_resolve_backend` risponderebbe "vertex" proprio in virtu' del trip;
 - a rientro riuscito la cache in-process `_BACKEND` viene svuotata con
   `pop`, mai scrivendoci "cloudflare": un valore forzato scavalcherebbe
   `_resolve_backend` e inchioderebbe su Cloudflare anche un modello che
   Cloudflare non ospita;
 - le cause di trip sondabili sono una whitelist: lo stato illeggibile del
   fail-safe non si riarma mai da solo.
"""
import time

import pytest

import email_service
import gemini_tts
import tts_backend_state as st
from gemini_transport import TransportError


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.delenv("ABM_CF_PROBE_ENABLE", raising=False)
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "0")
    gemini_tts.set_backend_return_notifier(None)
    yield
    gemini_tts._BACKEND = {}
    gemini_tts.set_backend_return_notifier(None)
    # La cache di tts_backend_state e' globale al processo: senza reset un
    # trip resterebbe visibile ai file di test successivi.
    st.reset("flash31")


def _trip(reason="cf_consecutive_failures"):
    st.trip("flash31", reason=reason, detail="timeout verso Cloudflare",
            job_id="j1")


def _pcm(n=4800):
    return {"pcm": b"\x00" * n, "input_tokens": None, "output_tokens": None}


# --- cammino felice --------------------------------------------------------

def test_a_successful_probe_returns_the_model_to_cloudflare(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 1)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: _pcm())
    assert gemini_tts.probe_cloudflare("flash31") == "returned"
    assert st.is_tripped("flash31") is False
    assert st.probe_info("flash31")["next_at"] is None


def test_the_probe_talks_to_cloudflare_directly_not_through_resolve(monkeypatch):
    # `_resolve_backend` risponde "vertex" per un modello scattato: se la
    # sonda passasse di li' non toccherebbe mai Cloudflare e il rientro non
    # avverrebbe mai.
    _trip()
    visti = []
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: visti.append(kw) or _pcm())
    gemini_tts.probe_cloudflare("flash31")
    assert len(visti) == 1
    assert visti[0]["model_id"] == gemini_tts.GEMINI_MODELS["flash31"]["id_cloudflare"]
    assert visti[0]["voice_name"] in gemini_tts.GEMINI_VOICE_NAMES
    # Timeout della sola sonda, piu' corto di quello di produzione: una sonda
    # lenta e' gia' una risposta, e nessun utente sta aspettando questo audio.
    assert visti[0]["timeout_ms"] < gemini_tts._cf_timeout_ms()


def test_the_return_pops_the_cache_and_never_forces_cloudflare(monkeypatch):
    _trip()
    gemini_tts._BACKEND["flash31"] = "vertex"
    gemini_tts._BACKEND["flash25"] = "vertex"
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: _pcm())
    gemini_tts.probe_cloudflare("flash31")
    assert "flash31" not in gemini_tts._BACKEND
    assert "flash25" not in gemini_tts._BACKEND


def test_the_probe_charges_the_ledger(monkeypatch):
    # La sonda e' audio vero prodotto da Cloudflare: si paga, quindi si
    # addebita. Un rientro che non passasse dal ledger farebbe divergere in
    # silenzio il residuo stimato dal saldo reale.
    _trip()
    st.reset_spend()
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: _pcm())
    gemini_tts.probe_cloudflare("flash31")
    assert st.credit_spent_usd() > 0


def test_the_return_notifier_gets_attempts_and_downtime(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 1800)
    st.record_probe_failure("flash31", "boom")
    st.record_probe_failure("flash31", "boom")
    visti = []
    gemini_tts.set_backend_return_notifier(
        lambda mk, att, giu: visti.append((mk, att, giu)))
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: _pcm())
    gemini_tts.probe_cloudflare("flash31")
    assert len(visti) == 1
    assert visti[0][0] == "flash31"
    assert visti[0][1] == 2
    assert visti[0][2] is not None and visti[0][2] >= 0


def test_a_failing_notifier_does_not_undo_the_return(monkeypatch):
    # Il rientro e' gia' avvenuto e persistito: l'email e' un di piu'.
    _trip()
    gemini_tts.set_backend_return_notifier(
        lambda *a: (_ for _ in ()).throw(RuntimeError("smtp giu'")))
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: _pcm())
    assert gemini_tts.probe_cloudflare("flash31") == "returned"
    assert st.is_tripped("flash31") is False


# --- sonda fallita ---------------------------------------------------------

def test_a_failed_probe_keeps_the_trip_and_doubles_the_appointment(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 1800)

    def _boom(**kw):
        raise TransportError("timeout verso Cloudflare", kind="retryable")

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _boom)
    assert gemini_tts.probe_cloudflare("flash31") == "failed"
    assert st.is_tripped("flash31") is True
    assert st.probe_info("flash31")["delay_sec"] == 3600
    assert st.probe_info("flash31")["attempts"] == 1


def test_an_unexpected_exception_is_a_failure_not_a_crash(monkeypatch):
    # La sonda gira in un thread di servizio: un'eccezione inattesa non deve
    # poter uccidere il sorvegliante, o il failover resterebbe aperto per
    # sempre senza che nulla lo segnali.
    _trip()
    st.schedule_probe("flash31", 1800)

    def _boom(**kw):
        raise ZeroDivisionError("inattesa")

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _boom)
    assert gemini_tts.probe_cloudflare("flash31") == "failed"
    assert "ZeroDivisionError" in (st.probe_info("flash31")["last_error"] or "")


def test_an_empty_response_is_a_failure(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 1800)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": b"", "input_tokens": None,
                                      "output_tokens": None})
    assert gemini_tts.probe_cloudflare("flash31") == "failed"
    assert st.is_tripped("flash31") is True


def test_content_rejected_counts_as_reachability_not_as_failure(monkeypatch):
    # Il filtro contenuti risponde solo se il backend RISPONDE: trattarlo
    # come fallimento rimanderebbe il rientro di ore per il motivo sbagliato.
    _trip()

    def _rifiuto(**kw):
        raise TransportError("contenuto rifiutato", kind="content_rejected",
                             http_status=422, provider_code=2017)

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _rifiuto)
    assert gemini_tts.probe_cloudflare("flash31") == "returned"
    assert st.is_tripped("flash31") is False


# --- ammissibilita' --------------------------------------------------------

def test_the_probe_is_disarmed_when_the_switch_is_off(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 1)
    monkeypatch.setenv("ABM_CF_PROBE_ENABLE", "0")
    chiamate = []
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: chiamate.append(kw) or _pcm())
    assert gemini_tts.probe_cloudflare("flash31") == "disarmed"
    assert chiamate == []
    # Disarmata, non riarmata: il trip resta, e il rientro torna manuale.
    assert st.is_tripped("flash31") is True
    assert st.probe_info("flash31")["next_at"] is None


def test_the_probe_is_disarmed_when_the_env_no_longer_selects_cloudflare(monkeypatch):
    # Continuare a bussare su un backend che nessuna sintesi userebbe piu' e'
    # spesa e rumore puri.
    _trip()
    st.schedule_probe("flash31", 1)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: pytest.fail("sonda eseguita comunque"))
    assert gemini_tts.probe_cloudflare("flash31") == "disarmed"


def test_the_probe_is_disarmed_without_credentials(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 1)
    monkeypatch.setenv("ABM_CF_API_TOKEN", "")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: pytest.fail("sonda eseguita comunque"))
    assert gemini_tts.probe_cloudflare("flash31") == "disarmed"


def test_the_failsafe_trip_is_never_probed(monkeypatch):
    # Uno stato che non sappiamo leggere non si riarma da solo, per
    # definizione: e' precisamente cio' che il fail-safe esiste per impedire.
    st.trip("flash31", reason="state_file_unreadable", detail="d", job_id="")
    st.schedule_probe("flash31", 1)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: pytest.fail("sonda eseguita comunque"))
    assert gemini_tts.probe_cloudflare("flash31") == "disarmed"
    assert st.is_tripped("flash31") is True


def test_a_low_credit_defers_without_counting_a_failure(monkeypatch):
    # Una sonda direbbe solo cio' che gia' sappiamo (il 402 arriverebbe
    # comunque) e il rientro non dipende da noi ma da una ricarica.
    _trip()
    st.schedule_probe("flash31", 1800)
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_USD", "10")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_USD", "50")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: pytest.fail("sonda eseguita comunque"))
    assert gemini_tts.probe_cloudflare("flash31") == "deferred"
    info = st.probe_info("flash31")
    assert info["attempts"] == 0
    assert info["delay_sec"] == 1800     # nessun raddoppio


# --- armamento allo scatto del breaker -------------------------------------

def _arma(monkeypatch, reason):
    monkeypatch.setattr(gemini_tts, "_vertex_ready", lambda: True)
    monkeypatch.setattr(gemini_tts, "_set_backend", lambda mk, b: None)
    gemini_tts._trip_to_vertex("flash31", reason=reason, detail="d",
                               job_id="j1")


def test_a_measured_trip_arms_the_first_probe(monkeypatch):
    _arma(monkeypatch, "cf_consecutive_failures")
    atteso = gemini_tts._cf_probe_first_sec()
    info = st.probe_info("flash31")
    assert info["next_at"] is not None
    assert info["delay_sec"] == atteso
    assert info["next_at"] > time.time() + atteso - 10


def test_the_exhausted_credit_trip_is_armed_too(monkeypatch):
    # `cf_backend_down` e' emesso SOLO per credito esaurito (HTTP 402 / codice
    # 2021): sondarlo costa una richiesta rifiutata e si risolve da solo dopo
    # una ricarica, senza che l'admin debba ricordarsi della console.
    _arma(monkeypatch, "cf_backend_down")
    assert st.probe_info("flash31")["next_at"] is not None


def test_an_unprobeable_trip_arms_nothing(monkeypatch):
    _arma(monkeypatch, "state_entry_corrupt")
    assert st.probe_info("flash31")["next_at"] is None


def test_the_probe_is_armed_before_the_switch_notifier_runs(monkeypatch):
    # L'email di switch annuncia quando cadra' la prima sonda e lo legge
    # dallo stato persistito: armare dopo la notifica la manderebbe a dire
    # "nessuna sonda armata" a ogni failover.
    visto = {}
    gemini_tts.set_backend_switch_notifier(
        lambda mk, r, d, j: visto.update(st.probe_info(mk)))
    try:
        _arma(monkeypatch, "cf_consecutive_failures")
    finally:
        gemini_tts.set_backend_switch_notifier(None)
    assert visto.get("next_at") is not None


def test_only_the_first_tripper_arms_the_appointment(monkeypatch):
    # Con N thread che scoprono l'avaria insieme, ri-armare a ogni scatto
    # rimanderebbe la prima sonda a ogni chiamata.
    _arma(monkeypatch, "cf_consecutive_failures")
    primo = st.probe_info("flash31")["next_at"]
    time.sleep(1.1)
    _arma(monkeypatch, "cf_consecutive_failures")
    assert st.probe_info("flash31")["next_at"] == primo


# --- email di rientro ------------------------------------------------------

@pytest.fixture
def _sent(monkeypatch):
    box = []
    monkeypatch.setattr(email_service, "ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(email_service, "_smtp_available", lambda: True)
    monkeypatch.setattr(
        email_service, "_send_email",
        lambda to, subject, html, **kw: box.append((to, subject, html)) or True)
    return box


def test_the_return_email_says_the_opposite_of_the_switch_one(_sent):
    email_service.admin_notify_tts_backend_return("flash31", probe_attempts=3,
                                                  down_seconds=9312)
    assert len(_sent) == 1
    oggetto, html = _sent[0][1], _sent[0][2]
    assert "flash31" in oggetto
    assert "rientro" in oggetto.lower()
    assert "Cloudflare" in oggetto
    # Durata leggibile a colpo d'occhio: "9312 s" obbligherebbe chi legge di
    # notte a fare una divisione.
    assert "2 ore e 35 minuti" in html
    assert "3" in html


def test_the_return_email_omits_an_unknown_downtime(_sent):
    # Uno zero significherebbe "nessun disservizio", cioe' il contrario del
    # vero: la riga va omessa, non riempita con un segnaposto.
    email_service.admin_notify_tts_backend_return("flash31", probe_attempts=1,
                                                  down_seconds=None)
    assert "Durata del failover" not in _sent[0][2]


def test_the_switch_email_announces_the_first_probe(_sent):
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_consecutive_failures", "timeout", "j1",
        probe_first_sec=1800)
    html = _sent[0][2]
    assert "30 minuti" in html
    assert "Il rientro e' manuale" not in html


def test_the_switch_email_still_says_manual_when_no_probe_is_armed(_sent):
    # Non deve promettere un appuntamento che nessuno ha fissato.
    email_service.admin_notify_tts_backend_switch(
        "flash31", "cf_consecutive_failures", "timeout", "j1",
        probe_first_sec=None)
    html = _sent[0][2]
    assert "Il rientro e' manuale" in html
    assert "Prima sonda di rientro" not in html


def test_durata_it_formats_the_common_cases():
    f = email_service._fmt_durata_it
    assert f(1) == "1 secondo"
    assert f(45) == "45 secondi"
    assert f(60) == "1 minuto"
    assert f(1800) == "30 minuti"
    assert f(3600) == "1 ora"
    assert f(9312) == "2 ore e 35 minuti"
    assert f(None) == ""
    assert f("domani") == ""
