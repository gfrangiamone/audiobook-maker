"""Failover automatico da Cloudflare a Vertex."""
import pytest

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
    # Vertex PRONTO, dichiarato esplicitamente e non ereditato dall'ambiente
    # dello sviluppatore: dopo il fix M2 il failover controlla la prontezza di
    # Vertex, quindi questi test devono dire da soli in quale mondo vivono
    # (una macchina CI senza ABM_GCP_PROJECT_ID darebbe l'esito opposto).
    creds = tmp_path / "sa.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "progetto")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    gemini_tts.set_backend_switch_notifier(None)
    yield
    gemini_tts._BACKEND = {}
    gemini_tts.set_backend_switch_notifier(None)
    # La cache di tts_backend_state e' globale al processo: senza reset un
    # trip resterebbe visibile ai file di test successivi.
    st.reset("flash31")


def _pcm(n=48):
    return {"pcm": b"\x00" * n, "input_tokens": None, "output_tokens": None}


def _synth(tmp_path, **kw):
    return gemini_tts.synthesize(
        "ciao mondo", "gemini:flash31:Kore",
        output_path=str(tmp_path / "o.pcm"), **kw)


def test_credit_exhausted_trips_and_continues_on_vertex(tmp_path, monkeypatch):
    vertex_calls = []

    def _cf(**kw):
        raise TransportError("credito esaurito", kind="backend_down",
                             http_status=402, provider_code=2021)

    def _vx(**kw):
        vertex_calls.append(kw)
        return {"pcm": b"\x01" * 48, "input_tokens": 10, "output_tokens": 200}

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _vx)

    out = _synth(tmp_path, job_id="j42")

    assert out["success"] is True
    assert len(vertex_calls) == 1
    assert st.is_tripped("flash31") is True
    assert st.state("flash31")["trip_job_id"] == "j42"
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_the_notifier_fires_once_at_the_trip(tmp_path, monkeypatch):
    seen = []
    gemini_tts.set_backend_switch_notifier(
        lambda model_key, reason, detail, job_id: seen.append(
            (model_key, reason, job_id)))

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    _synth(tmp_path, job_id="j1")
    _synth(tmp_path, job_id="j2")

    assert len(seen) == 1
    assert seen[0][0] == "flash31"


def test_a_second_trip_on_the_same_model_does_not_re_notify(tmp_path, monkeypatch):
    """La guardia `first` in `_trip_to_vertex` e' l'UNICA cosa che garantisce
    una sola email quando N thread scoprono l'avaria insieme: `trip()` e'
    idempotente sotto lock e ritorna True a uno solo.

    Il test gemello `test_the_notifier_fires_once_at_the_trip` NON copre
    questa proprieta': dopo il primo trip `_resolve_backend` ritorna "vertex"
    e la seconda `synthesize()` non arriva mai a `_trip_to_vertex`. Rimuovere
    la guardia lo lasciava verde (rilievo F6 della revisione finale, 219 test
    verdi con la mutazione applicata). Qui `_trip_to_vertex` viene invocata
    DUE volte in modo diretto, che e' il concorso reale fra thread.
    """
    seen = []
    gemini_tts.set_backend_switch_notifier(
        lambda model_key, reason, detail, job_id: seen.append(job_id))

    gemini_tts._trip_to_vertex("flash31", reason="cf_backend_down",
                               detail="primo thread", job_id="j1")
    gemini_tts._trip_to_vertex("flash31", reason="cf_backend_down",
                               detail="secondo thread", job_id="j2")

    assert seen == ["j1"], (
        "il secondo trip sullo stesso modello non deve rinotificare: "
        "l'admin riceverebbe un'email per ogni job in corso")
    # Lo stato persistito resta quello del PRIMO trip, non sovrascritto dal
    # secondo: e' la stessa idempotenza vista dal lato del disco.
    assert st.state("flash31")["trip_job_id"] == "j1"


def test_transient_failures_trip_only_at_the_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_CF_TRIP_FAILURES", "3")
    monkeypatch.setattr(gemini_tts, "_synth_max_attempts", lambda: 1)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("glitch", kind="retryable")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    for _ in range(2):
        with pytest.raises(RuntimeError):
            _synth(tmp_path)
    assert st.is_tripped("flash31") is False

    # Il terzo fallimento consecutivo fa scattare il breaker: la chiamata
    # prosegue su Vertex invece di fallire.
    out = _synth(tmp_path)
    assert out["success"] is True
    assert st.is_tripped("flash31") is True


def test_a_success_resets_the_failure_counter(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_CF_TRIP_FAILURES", "3")
    monkeypatch.setattr(gemini_tts, "_synth_max_attempts", lambda: 1)
    outcomes = [TransportError("glitch", kind="retryable"), None,
                TransportError("glitch", kind="retryable")]

    def _cf(**kw):
        exc = outcomes.pop(0)
        if exc:
            raise exc
        return _pcm()

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(RuntimeError):
        _synth(tmp_path)
    _synth(tmp_path)  # successo: azzera
    with pytest.raises(RuntimeError):
        _synth(tmp_path)
    assert st.state("flash31")["consecutive_failures"] == 1


def test_content_rejected_does_not_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("moderazione", kind="content_rejected",
                                           provider_code=2017)))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    # Eccezione ESATTA, non `Exception`: con la raises larga il test passava
    # anche quando usciva una TransportError, cioe' proprio il difetto che
    # doveva impedire (spec §4.2: 422/2017 -> GeminiEmptyResponse).
    with pytest.raises(gemini_tts.GeminiEmptyResponse) as ei:
        _synth(tmp_path)
    assert ei.value.retryable is False
    assert not isinstance(ei.value, TransportError)
    # Un chunk sbagliato non deve buttare giu' il backend per tutti.
    assert st.is_tripped("flash31") is False


def test_fatal_does_not_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("voce inesistente", kind="fatal",
                                           provider_code=7003)))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(gemini_tts.GeminiUnavailable) as ei:
        _synth(tmp_path)
    assert not isinstance(ei.value, TransportError)
    assert st.is_tripped("flash31") is False


def test_trip_without_a_ready_vertex_raises_unavailable(tmp_path, monkeypatch):
    """Vertex davvero non configurato, non un mock che solleva l'atteso.

    La versione precedente monkeypatchava `_vertex_transport_call` perche'
    sollevasse GeminiUnavailable e poi verificava che uscisse
    GeminiUnavailable: verificava il proprio mock, e non poteva vedere il
    difetto reale (KeyError da `_get_client`). Qui Vertex e' irraggiungibile
    per configurazione, come nello scenario di produzione (chiave revocata o
    file credenziali rimosso mentre Cloudflare e' attivo).
    """
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("ABM_GOOGLE_CREDENTIALS_FILE", raising=False)
    vertex_calls = []
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: vertex_calls.append(kw) or _pcm())

    with pytest.raises(gemini_tts.GeminiUnavailable):
        _synth(tmp_path, job_id="j-no-vertex")

    # Nessun tentativo verso un backend che non c'e'...
    assert vertex_calls == []
    # ...ma il trip resta persistito e tracciabile: l'admin deve sapere che
    # Cloudflare e' caduto proprio quando non c'e' rete di sicurezza sotto.
    assert st.is_tripped("flash31") is True
    assert st.state("flash31")["trip_job_id"] == "j-no-vertex"
    assert gemini_tts._resolve_backend("flash31") is None


def test_the_notifier_still_fires_when_vertex_is_not_ready(tmp_path, monkeypatch):
    """La notifica precede il sollevamento: e' l'unico avviso che l'admin ha."""
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("ABM_GOOGLE_CREDENTIALS_FILE", raising=False)
    seen = []
    gemini_tts.set_backend_switch_notifier(
        lambda model_key, reason, detail, job_id: seen.append(model_key))
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(gemini_tts.GeminiUnavailable):
        _synth(tmp_path)
    assert seen == ["flash31"]
    assert st.state("flash31")["notified"] is True


def test_a_tripped_model_goes_straight_to_vertex(tmp_path, monkeypatch):
    st.trip("flash31", reason="cf_credit_exhausted", detail="d", job_id="j0")
    gemini_tts._set_backend("flash31", "vertex")
    cf_calls = []

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: cf_calls.append(kw) or _pcm())
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    _synth(tmp_path)
    assert cf_calls == []


def test_resolve_backend_forces_vertex_after_restart_when_tripped(tmp_path):
    """Rilievo B1 (fix-1): il breaker persiste su disco proprio perche' un
    riavvio del processo non debba poter rimettere un modello scattato su
    Cloudflare. Qui si riproduce esattamente lo scenario del review: stato
    scattato su disco, cache in-process azzerata come farebbe un riavvio
    reale (deploy, crash, systemctl restart), poi `init()` ricarica lo stato
    persistito SENZA che nessuno rieseguisca il failover in-process. Prima
    del fix, `_resolve_backend` rivalutava da zero ABM_GEMINI_BACKEND e
    tornava silenziosamente "cloudflare".
    """
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id="j0")

    # Simula il riavvio: la cache in-process del backend riparte vuota, ma lo
    # stato del breaker resta sullo stesso disco. init() lo ricarica.
    gemini_tts._BACKEND = {}
    st.init(str(tmp_path))

    assert st.is_tripped("flash31") is True
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_model_id_is_recomputed_for_the_backend_of_each_attempt(tmp_path, monkeypatch):
    """Rilievo M1 (fix-1): il model_id usato per la chiamata deve seguire il
    backend del tentativo CORRENTE, non quello congelato prima del loop di
    retry. Riproduce lo scenario generale segnalato dal review con un
    flash31 "finto" il cui id_vertex diverge da id_cloudflare/id legacy
    (oggi coincidono per flash31, ma il codice non puo' contare su questo).
    """
    monkeypatch.setitem(gemini_tts.GEMINI_MODELS["flash31"],
                        "id_vertex", "gemini-vertex-ga-name")

    vertex_calls = []

    def _cf(**kw):
        raise TransportError("giu'", kind="backend_down")

    def _vx(**kw):
        vertex_calls.append(kw)
        return _pcm()

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _vx)

    out = _synth(tmp_path, job_id="j-m1")

    assert out["success"] is True
    assert len(vertex_calls) == 1
    assert vertex_calls[0]["model_id"] == "gemini-vertex-ga-name"
