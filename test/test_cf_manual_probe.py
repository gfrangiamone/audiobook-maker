"""Sonda di rientro manuale dalla console admin, e ritmo dimezzato.

Due modifiche del 21/09/2026, con lo stesso movente: la sonda costa una
frazione di centesimo, il failover costa il margine di TUTTI i job PREMIUM
finche' dura. Quindi (a) gli intervalli automatici sono dimezzati e (b)
l'admin puo' chiedere una misura subito, senza aspettare l'appuntamento.

Il pulsante manuale e' volutamente MENO potente del rientro manuale che gli
sta accanto: quello rimette il traffico vero su un backend non misurato,
questo sintetizza due parole e le butta. Per questo salta solo le condizioni
che descrivono il RITMO automatico, e per questo non puo' peggiorare lo stato
di chi non lo preme.
"""
import threading
import time

import pytest

import audiobook_app
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
    with audiobook_app._MANUAL_PROBE_LOCK:
        audiobook_app._manual_probe_running.clear()
    st.reset("flash31")


def _trip(reason="cf_consecutive_failures"):
    st.trip("flash31", reason=reason, detail="timeout verso Cloudflare",
            job_id="j1")


def _pcm(n=4800):
    return {"pcm": b"\x00" * n, "input_tokens": None, "output_tokens": None}


def _boom(**kw):
    raise TransportError("timeout verso Cloudflare", kind="retryable")


# --- ritmo dimezzato -------------------------------------------------------

def test_the_first_probe_now_waits_a_quarter_of_an_hour(monkeypatch):
    # Era 1800. Il dimezzamento e' il contenuto stesso della modifica: un
    # ripristino accidentale del vecchio default non darebbe alcun errore,
    # costerebbe solo mezz'ora di Vertex per ogni failover, in silenzio.
    monkeypatch.delenv("ABM_CF_PROBE_FIRST_SEC", raising=False)
    assert gemini_tts._cf_probe_first_sec() == 900


def test_the_backoff_cap_is_three_hours(monkeypatch):
    # Era 21600 (6 ore): un guasto notturno teneva spento il backend
    # economico fino al mattino dopo pur essendo rientrato da ore.
    monkeypatch.delenv("ABM_CF_PROBE_MAX_SEC", raising=False)
    assert gemini_tts._cf_probe_max_sec() == 10800


def test_both_intervals_stay_overridable_and_floored(monkeypatch):
    monkeypatch.setenv("ABM_CF_PROBE_FIRST_SEC", "120")
    monkeypatch.setenv("ABM_CF_PROBE_MAX_SEC", "600")
    assert gemini_tts._cf_probe_first_sec() == 120
    assert gemini_tts._cf_probe_max_sec() == 600
    # Il pavimento a 60s resta: un valore assurdo non trasforma la sonda in
    # un martellamento continuo del gateway.
    monkeypatch.setenv("ABM_CF_PROBE_FIRST_SEC", "1")
    monkeypatch.setenv("ABM_CF_PROBE_MAX_SEC", "0")
    assert gemini_tts._cf_probe_first_sec() == 60
    assert gemini_tts._cf_probe_max_sec() == 60


def test_a_failing_automatic_probe_still_doubles_up_to_the_new_cap(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 9000)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _boom)
    assert gemini_tts.probe_cloudflare("flash31") == "failed"
    assert st.probe_info("flash31")["delay_sec"] == 10800


# --- keep_schedule nello stato --------------------------------------------

def test_keep_schedule_records_the_outcome_without_moving_the_appointment():
    _trip()
    quando = st.schedule_probe("flash31", 1800)
    st.record_probe_failure("flash31", "boom", keep_schedule=True)
    info = st.probe_info("flash31")
    assert info["next_at"] == quando
    assert info["delay_sec"] == 1800
    # L'esito va comunque registrato: la misura c'e' stata.
    assert info["attempts"] == 1
    assert "boom" in (info["last_error"] or "")


def test_keep_schedule_returns_the_appointment_in_force(capsys):
    # Il ritorno e' l'epoch dell'appuntamento, e con `keep_schedule` deve
    # essere quello ancora in vigore: un chiamante che lo ri-persistesse
    # sposterebbe proprio cio' che questa modalita' esiste per non toccare.
    _trip()
    quando = st.schedule_probe("flash31", 1800)
    assert st.record_probe_failure("flash31", "boom", keep_schedule=True) == quando
    # E il log dice l'intervallo vigente, non il raddoppio mai applicato:
    # una forense leggerebbe altrimenti un ritmo mai in uso.
    assert "fra 1800s" in capsys.readouterr().out


# --- ammissibilita' della sonda manuale ------------------------------------

def test_a_manual_probe_runs_with_the_automatic_return_switched_off(monkeypatch):
    # `ABM_CF_PROBE_ENABLE=0` significa "non bussare da solo", non "vietato
    # misurare": e' proprio l'installazione in cui il pulsante serve di piu'.
    _trip()
    monkeypatch.setenv("ABM_CF_PROBE_ENABLE", "0")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: _pcm())
    assert gemini_tts.probe_cloudflare("flash31", manual=True) == "returned"
    assert st.is_tripped("flash31") is False


def test_a_manual_probe_may_measure_an_unprobeable_trip(monkeypatch):
    # Il fail-safe non si riarma DA SOLO; un admin che guarda lo stato puo'
    # comunque chiedergli una misura, ed e' comunque meno rischioso del
    # pulsante di rientro accanto.
    _trip(reason="state_file_unreadable")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: _pcm())
    assert gemini_tts.probe_cloudflare("flash31", manual=True) == "returned"


def test_a_manual_probe_without_credentials_is_skipped(monkeypatch):
    _trip()
    monkeypatch.setenv("ABM_CF_API_TOKEN", "")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: pytest.fail("sonda eseguita comunque"))
    assert gemini_tts.probe_cloudflare("flash31", manual=True) == "skipped"


def test_a_manual_probe_without_a_trip_is_skipped(monkeypatch):
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: pytest.fail("sonda eseguita comunque"))
    assert gemini_tts.probe_cloudflare("flash31", manual=True) == "skipped"


def test_a_skipped_manual_probe_never_disarms_the_automatic_one(monkeypatch):
    # Il difetto che questo test esiste per impedire: "skipped" nasce proprio
    # perche' `disarmed` chiama `clear_probe`. Un click premuto mentre un
    # deploy ha tolto le credenziali per due secondi spegnerebbe per sempre,
    # e in silenzio, il rientro automatico.
    _trip()
    quando = st.schedule_probe("flash31", 900)
    monkeypatch.setenv("ABM_CF_API_TOKEN", "")
    assert gemini_tts.probe_cloudflare("flash31", manual=True) == "skipped"
    assert st.probe_info("flash31")["next_at"] == quando
    assert st.is_tripped("flash31") is True


# --- un fallimento manuale non punisce chi guarda --------------------------

def test_a_failed_manual_probe_does_not_postpone_the_automatic_one(monkeypatch):
    _trip()
    quando = st.schedule_probe("flash31", 900)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _boom)
    assert gemini_tts.probe_cloudflare("flash31", manual=True) == "failed"
    info = st.probe_info("flash31")
    assert info["next_at"] == quando, (
        "bastavano pochi click per spingere al tetto l'appuntamento "
        "automatico: chi controlla piu' spesso lo farebbe ricontrollare "
        "piu' di rado")
    assert info["delay_sec"] == 900
    assert info["attempts"] == 1


def test_a_failed_manual_probe_is_marked_as_manual_in_the_state(monkeypatch):
    # Senza marca, l'admin legge "ultimo errore" e non sa se e' la misura che
    # ha appena chiesto o l'appuntamento automatico di un'ora fa.
    _trip()
    st.schedule_probe("flash31", 900)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _boom)
    gemini_tts.probe_cloudflare("flash31", manual=True)
    err = st.probe_info("flash31")["last_error"] or ""
    assert "[manuale]" in err
    assert "timeout verso Cloudflare" in err


def test_an_automatic_failure_carries_no_manual_mark(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 900)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _boom)
    gemini_tts.probe_cloudflare("flash31")
    assert "[manuale]" not in (st.probe_info("flash31")["last_error"] or "")


def test_a_successful_manual_probe_returns_the_model_like_any_other(monkeypatch):
    _trip()
    st.schedule_probe("flash31", 900)
    gemini_tts._BACKEND["flash31"] = "vertex"
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: _pcm())
    assert gemini_tts.probe_cloudflare("flash31", manual=True) == "returned"
    assert st.is_tripped("flash31") is False
    assert st.probe_info("flash31")["next_at"] is None
    assert "flash31" not in gemini_tts._BACKEND


# --- il corridore in background -------------------------------------------

def _attendi(cond, limite=5.0):
    scadenza = time.time() + limite
    while time.time() < scadenza:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_the_runner_reports_the_probe_as_running_while_it_lasts(monkeypatch):
    # La sonda dura fino al timeout di produzione (65s in prod): l'endpoint
    # non puo' aspettarla dentro la richiesta, quindi il pannello deve poter
    # sapere che e' in volo.
    partita = threading.Event()
    libera = threading.Event()

    def _lenta(mk, *, manual=False):
        partita.set()
        libera.wait(5)
        return "failed"

    monkeypatch.setattr(gemini_tts, "probe_cloudflare", _lenta)
    assert audiobook_app._manual_probe_start("flash31") is True
    assert partita.wait(5)
    assert audiobook_app._probe_payload("flash31")["probe_running"] is True
    libera.set()
    assert _attendi(
        lambda: audiobook_app._probe_payload("flash31")["probe_running"] is False)


def test_a_second_click_does_not_start_a_second_probe(monkeypatch):
    # Due sonde sovrapposte sullo stesso modello scrivono due misure che si
    # sovrascrivono: l'admin leggerebbe l'esito della prima credendolo quello
    # della seconda. Il doppio click e' il caso normale, non il patologico.
    partita = threading.Event()
    libera = threading.Event()
    giri = []

    def _lenta(mk, *, manual=False):
        giri.append(mk)
        partita.set()
        libera.wait(5)
        return "failed"

    monkeypatch.setattr(gemini_tts, "probe_cloudflare", _lenta)
    assert audiobook_app._manual_probe_start("flash31") is True
    assert partita.wait(5)
    assert audiobook_app._manual_probe_start("flash31") is False
    libera.set()
    assert _attendi(lambda: not audiobook_app._manual_probe_running)
    assert giri == ["flash31"]


def test_the_guard_is_per_model_not_global(monkeypatch):
    libera = threading.Event()
    visti = []

    def _lenta(mk, *, manual=False):
        visti.append(mk)
        libera.wait(5)
        return "failed"

    monkeypatch.setattr(gemini_tts, "probe_cloudflare", _lenta)
    assert audiobook_app._manual_probe_start("flash31") is True
    assert audiobook_app._manual_probe_start("flash25") is True
    libera.set()
    assert _attendi(lambda: not audiobook_app._manual_probe_running)
    assert sorted(visti) == ["flash25", "flash31"]


def test_an_exploding_probe_does_not_wedge_the_button_forever(monkeypatch):
    # `probe_cloudflare` non solleva mai, ma se un giorno lo facesse il
    # pulsante resterebbe bloccato fino al riavvio del processo.
    monkeypatch.setattr(
        gemini_tts, "probe_cloudflare",
        lambda mk, **kw: (_ for _ in ()).throw(RuntimeError("inattesa")))
    assert audiobook_app._manual_probe_start("flash31") is True
    assert _attendi(lambda: not audiobook_app._manual_probe_running)
    assert audiobook_app._manual_probe_start("flash31") is True
