"""Contratto di `synthesize()`: token, costo, eccezioni di dominio, quote.

Copre i tre punti che la review finale ha trovato scoperti proprio dove il
rischio e' massimo:

- il **denaro**: su Cloudflare i token non arrivano dal provider e vanno
  derivati (spec §4.6). Senza derivazione il costo calcolato e' zero e il cap
  di spesa giornaliero si disarma;
- il **vocabolario delle eccezioni**: `TransportError` e' interna al trasporto
  e non deve mai uscire da `synthesize()`;
- le **quote Google**: non si applicano a una chiamata servita da Cloudflare
  (spec §6).
"""
import pytest

import gemini_tts
import tts_backend_state as st
from gemini_transport import TRANSPORT_KINDS, TransportError


PCM_20_SECONDI = b"\x00" * (24000 * 2 * 20)


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    creds = tmp_path / "sa.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "progetto")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts.time, "sleep", lambda s: None)
    gemini_tts.set_backend_switch_notifier(None)
    yield
    gemini_tts._BACKEND = {}
    gemini_tts.set_backend_switch_notifier(None)
    st.reset("flash31")
    st.reset("flash25")


def _no_quota_guards(monkeypatch):
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)


def _synth(tmp_path, text="ciao mondo, questa e' una frase di prova"):
    return gemini_tts.synthesize(
        text, "gemini:flash31:Kore", output_path=str(tmp_path / "o.pcm"))


# ---------------------------------------------------------------------------
# Denaro: derivazione dei token (spec §4.6) e costo diverso da zero
# ---------------------------------------------------------------------------

def test_cloudflare_tokens_are_derived_not_zero(tmp_path, monkeypatch):
    """20 s di PCM valgono 500 token audio, non 0.

    Il trasporto Cloudflare dichiara onestamente `None`; se `synthesize()` li
    traducesse in 0 (com'era prima del fix) l'intero consuntivo economico a
    valle sarebbe zero: costo del job zero, speso oggi zero, cap giornaliero
    inerte.
    """
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    _no_quota_guards(monkeypatch)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None,
                                      "output_tokens": None})

    out = _synth(tmp_path)

    assert out["backend"] == "cloudflare"
    assert out["tokens_measured"] is False
    assert out["audio_seconds_real"] == pytest.approx(20.0)
    # 20 s x _audio_tokens_per_second("flash31") = 20 x 25 = 500
    assert out["output_tokens"] == 500
    assert out["input_tokens"] > 0


def test_the_derived_tokens_follow_the_per_model_rate(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH31", "29")
    _no_quota_guards(monkeypatch)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None,
                                      "output_tokens": None})

    assert _synth(tmp_path)["output_tokens"] == 580  # 20 x 29


def test_the_cost_of_a_cloudflare_call_is_not_zero(tmp_path, monkeypatch):
    """Il collegamento fra la derivazione e il cap di spesa giornaliero.

    `google_cost_breakdown` e' esattamente la funzione che
    `generation_engine` applica ai token accumulati per ottenere
    `google_cost_eur_actual`, che `get_daily_spent_eur()` somma e
    `preflight_budget_check()` confronta con il cap.
    """
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    _no_quota_guards(monkeypatch)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None,
                                      "output_tokens": None})

    out = _synth(tmp_path)
    costo = gemini_tts.google_cost_breakdown(
        out["input_tokens"], out["output_tokens"], out["model_key"])

    assert costo["total_eur"] > 0
    assert costo["output_usd"] > 0


def test_vertex_tokens_stay_measured(tmp_path, monkeypatch):
    """Il percorso Vertex non deriva nulla: i token li misura il provider."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    _no_quota_guards(monkeypatch)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 7,
                                      "output_tokens": 493})

    out = _synth(tmp_path)

    assert out["backend"] == "vertex"
    assert out["tokens_measured"] is True
    # Nessuna sovrascrittura con la stima: 493 misurati restano 493.
    assert (out["input_tokens"], out["output_tokens"]) == (7, 493)


def test_a_measured_zero_is_not_confused_with_an_absent_measure(tmp_path, monkeypatch):
    """Vertex senza `usage_metadata` riporta 0: e' una misura, non un buco.

    Distinguere i due casi e' l'intero scopo di `tokens_measured`: un
    consuntivo che non sa dire se sta guardando una misura o una stima
    riconcilierebbe una stima contro se' stessa.
    """
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    _no_quota_guards(monkeypatch)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 0, "output_tokens": 0})

    out = _synth(tmp_path)

    assert out["tokens_measured"] is True
    assert out["output_tokens"] == 0


def test_after_a_failover_the_backend_reported_is_the_one_that_executed(tmp_path, monkeypatch):
    """Il consuntivo deve dire chi ha eseguito, non chi era stato scelto."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    _no_quota_guards(monkeypatch)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("credito finito", kind="backend_down",
                                           http_status=402, provider_code=2021)))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 7, "output_tokens": 493})

    out = _synth(tmp_path)

    assert out["backend"] == "vertex"
    assert out["tokens_measured"] is True
    assert out["output_tokens"] == 493


# ---------------------------------------------------------------------------
# Vocabolario delle eccezioni: TransportError non esce mai da synthesize()
# ---------------------------------------------------------------------------

# kind del trasporto -> eccezione di dominio attesa all'uscita di synthesize().
# La tabella e' esaustiva sull'enum: il test sotto lo verifica.
_KIND_TO_DOMAIN = {
    "retryable": RuntimeError,
    "rate_limited": RuntimeError,
    "quota_daily": gemini_tts.GeminiQuotaExhausted,
    "content_rejected": gemini_tts.GeminiEmptyResponse,
    "backend_down": RuntimeError,
    "fatal": gemini_tts.GeminiUnavailable,
}


def test_the_mapping_table_covers_the_whole_enum():
    assert set(_KIND_TO_DOMAIN) == set(TRANSPORT_KINDS)


@pytest.mark.parametrize("kind", sorted(TRANSPORT_KINDS))
def test_no_kind_lets_a_transport_error_escape(kind, tmp_path, monkeypatch):
    """Su ogni kind esce un'eccezione di DOMINIO, mai la TransportError.

    Backend Vertex di proposito: qui si misura la sola mappatura, senza il
    circuit breaker di mezzo (che e' esercitato in test_gemini_failover.py).
    """
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GEMINI_SYNTH_MAX_ATTEMPTS", "1")
    _no_quota_guards(monkeypatch)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError(f"guasto {kind}", kind=kind)))

    with pytest.raises(Exception) as ei:
        _synth(tmp_path)

    assert not isinstance(ei.value, TransportError)
    attesa = _KIND_TO_DOMAIN[kind]
    if attesa is RuntimeError:
        # Tipo ESATTO: le eccezioni di dominio sono tutte sottoclassi di
        # RuntimeError, quindi un `isinstance` largo non distinguerebbe
        # "esaurimento dei tentativi" da "quota" o da "config rotta".
        assert type(ei.value) is RuntimeError
    else:
        assert isinstance(ei.value, attesa)


def test_content_rejected_from_vertex_keeps_its_diagnostics(tmp_path, monkeypatch):
    """Sul percorso Vertex la causa E' gia' l'eccezione di dominio: si
    rilancia identica, con block_reason/finish_reason intatti."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    _no_quota_guards(monkeypatch)
    originale = gemini_tts.GeminiEmptyResponse(
        "bloccata", block_reason="SAFETY", finish_reason="SAFETY",
        retryable=False)

    def _vx(**kw):
        raise TransportError(str(originale), kind="content_rejected") from originale

    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _vx)

    with pytest.raises(gemini_tts.GeminiEmptyResponse) as ei:
        _synth(tmp_path)
    assert ei.value is originale
    assert ei.value.block_reason == "SAFETY"


def test_content_rejected_from_cloudflare_is_non_retryable(tmp_path, monkeypatch):
    """Spec §4.2: 422 / codice 2017 -> GeminiEmptyResponse(retryable=False).

    Senza la mappatura il chiamante perdeva l'informazione "contenuto
    rifiutato, non ritentabile" che su Vertex aveva.
    """
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    _no_quota_guards(monkeypatch)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("contenuto rifiutato da Cloudflare "
                                           "(codice 2017): moderazione",
                                           kind="content_rejected",
                                           http_status=422, provider_code=2017)))

    with pytest.raises(gemini_tts.GeminiEmptyResponse) as ei:
        _synth(tmp_path)
    assert ei.value.retryable is False
    assert "2017" in str(ei.value)


# ---------------------------------------------------------------------------
# Quote Google saltate su Cloudflare (spec §6)
# ---------------------------------------------------------------------------

def _spia_quote(monkeypatch):
    visti = {"rpd_cap": 0, "throttle": 0, "increment": 0}
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap",
                        lambda mk: visti.__setitem__("rpd_cap", visti["rpd_cap"] + 1))
    monkeypatch.setattr(gemini_tts, "_throttle_rpm",
                        lambda mk: visti.__setitem__("throttle", visti["throttle"] + 1))
    monkeypatch.setattr(gemini_tts, "_rpd_increment",
                        lambda mk: visti.__setitem__("increment", visti["increment"] + 1))
    return visti


def test_google_quotas_are_skipped_on_cloudflare(tmp_path, monkeypatch):
    """RPD e RPM sono quote del progetto Google: su Cloudflare non esistono.

    Con i default (cap a 0) il difetto era innocuo; con un cap configurato in
    produzione il traffico Cloudflare verrebbe strozzato al ritmo di Google e
    potrebbe sollevare GeminiQuotaExhausted per una quota che non lo riguarda.
    """
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    visti = _spia_quote(monkeypatch)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None, "output_tokens": None})

    _synth(tmp_path)

    assert visti == {"rpd_cap": 0, "throttle": 0, "increment": 0}


def test_google_quotas_still_apply_on_vertex(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    visti = _spia_quote(monkeypatch)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 7, "output_tokens": 493})

    _synth(tmp_path)

    assert visti == {"rpd_cap": 1, "throttle": 1, "increment": 1}


def test_a_configured_rpd_cap_does_not_block_a_cloudflare_job(tmp_path, monkeypatch):
    """Lo scenario concreto: cap RPD gia' esaurito, backend Cloudflare.

    Prima del fix usciva GeminiQuotaExhausted — job sospeso per una quota
    altrui. Le guardie vere (non mockate) vengono lasciate al loro posto.
    """
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_GEMINI_RPD_FLASH31", "1")
    monkeypatch.setattr(gemini_tts, "_rpd_load", lambda: {"flash31": 99})
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None, "output_tokens": None})

    assert _synth(tmp_path)["success"] is True


def test_the_same_exhausted_cap_still_stops_a_vertex_job(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GEMINI_RPD_FLASH31", "1")
    monkeypatch.setattr(gemini_tts, "_rpd_load", lambda: {"flash31": 99})
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 7, "output_tokens": 493})

    with pytest.raises(gemini_tts.GeminiQuotaExhausted):
        _synth(tmp_path)


# ---------------------------------------------------------------------------
# Il chunk lungo, spezzato in piu' pezzi, non deve perdere l'onesta' dei token
# ---------------------------------------------------------------------------

def test_the_split_aggregate_keeps_backend_and_token_provenance(tmp_path, monkeypatch):
    """Un chunk troppo lungo passa da `_synthesize_pcm_pieces_and_concat`, che
    ricostruisce a mano un dict "in stile synthesize()". Se quel dict perde
    `backend` e `tokens_measured`, il chiamante che contabilizza la spesa vede
    un pezzo di verita' in meno proprio sui job piu' costosi.
    """
    import tts_split

    _no_quota_guards(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None, "output_tokens": None})

    agg = tts_split._synthesize_pcm_pieces_and_concat(
        ["primo pezzo di testo", "secondo pezzo di testo"],
        "gemini:flash31:Kore", str(tmp_path / "unito.pcm"), None, 1)

    assert agg["backend"] == "cloudflare"
    assert agg["tokens_measured"] is False
    assert agg["output_tokens"] == 1000  # 2 x 20 s a 25 tok/s
    assert agg["input_tokens"] > 0


def test_the_split_aggregate_reports_measured_tokens_on_vertex(tmp_path, monkeypatch):
    import tts_split

    _no_quota_guards(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 7, "output_tokens": 493})

    agg = tts_split._synthesize_pcm_pieces_and_concat(
        ["primo pezzo di testo", "secondo pezzo di testo"],
        "gemini:flash31:Kore", str(tmp_path / "unito.pcm"), None, 1)

    assert agg["backend"] == "vertex"
    assert agg["tokens_measured"] is True
    assert (agg["input_tokens"], agg["output_tokens"]) == (14, 986)
