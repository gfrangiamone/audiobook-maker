"""Ledger del credito Cloudflare (spesa reale) e provenienza mista nei chunk
spezzati.

La stima dei token quando il trasporto non li fornisce (spec §4.6,
`tokens_measured`) e' gia' coperta da test_gemini_synthesize_contract.py e
NON viene ridiscussa qui. Questo file copre solo cio' che mancava davvero:

- l'addebito sul ledger locale (`tts_backend_state.add_spend`, gia'
  implementato e testato in test_cf_credit_ledger.py, ma senza nessun
  chiamante in produzione prima di questo task);
- la provenienza onesta del backend quando un chunk lungo viene spezzato in
  piu' pezzi (`tts_split._synthesize_pcm_pieces_and_concat`), nel caso in cui
  il circuit breaker scatti a meta' chunk.
"""
import pytest

import gemini_tts
import tts_backend_state as st


PCM_60_SECONDI = b"\x00" * (24000 * 2 * 60)
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
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    monkeypatch.setattr(gemini_tts.time, "sleep", lambda s: None)
    gemini_tts.set_backend_switch_notifier(None)
    yield
    gemini_tts._BACKEND = {}
    gemini_tts.set_backend_switch_notifier(None)
    st.reset("flash31")
    st.reset("flash25")


def _synth(tmp_path, text="ciao mondo, questa e' una frase di prova ragionevole"):
    return gemini_tts.synthesize(
        text, "gemini:flash31:Kore", output_path=str(tmp_path / "o.pcm"))


# ---------------------------------------------------------------------------
# Correzione 1 (completamento): il ledger riceve davvero la spesa reale
# ---------------------------------------------------------------------------

def test_a_cloudflare_call_debits_the_credit_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_60_SECONDI,
                                      "input_tokens": None, "output_tokens": None})
    before = st.credit_left_eur()

    out = _synth(tmp_path)

    assert out["backend"] == "cloudflare"
    after = st.credit_left_eur()
    assert after < before
    # L'addebito deve corrispondere esattamente al costo reale calcolato sugli
    # stessi token che la chiamata ha restituito (nessuna euristica separata).
    expected = gemini_tts.actual_cost_breakdown(
        out["input_tokens"], out["output_tokens"], out["model_key"], "cloudflare")
    assert (before - after) == pytest.approx(expected["total_eur"])


def test_a_vertex_call_does_not_touch_the_cloudflare_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 5, "output_tokens": 25})
    before = st.credit_left_eur()

    out = _synth(tmp_path)

    assert out["backend"] == "vertex"
    assert st.credit_left_eur() == pytest.approx(before)


def test_ledger_debit_is_non_fatal_if_add_spend_raises(tmp_path, monkeypatch):
    """Il ledger e' una diagnostica di supporto, non deve mai far fallire la
    sintesi vera e propria (che ha gia' consegnato l'audio al chiamante)."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None, "output_tokens": None})
    monkeypatch.setattr(gemini_tts._backend_state, "add_spend",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("disk full")))

    out = _synth(tmp_path)  # non deve sollevare

    assert out["success"] is True


def test_the_ledger_is_precise_per_piece_across_a_split_chunk(tmp_path, monkeypatch):
    """Un chunk spezzato in due pezzi, entrambi su Cloudflare: ogni pezzo
    chiama synthesize() per conto proprio (tts_split.py), quindi ognuno si
    addebita da solo. L'addebito totale deve corrispondere esattamente alla
    somma dei due, non al doppio ne' alla meta'."""
    import tts_split

    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None, "output_tokens": None})
    before = st.credit_left_eur()

    agg = tts_split._synthesize_pcm_pieces_and_concat(
        ["primo pezzo di testo", "secondo pezzo di testo"],
        "gemini:flash31:Kore", str(tmp_path / "unito.pcm"), None, 1)

    assert agg is not False
    spent = before - st.credit_left_eur()
    expected_per_piece = gemini_tts.actual_cost_breakdown(
        agg["input_tokens"] // 2, agg["output_tokens"] // 2,
        agg["model_key"], "cloudflare")["total_eur"]
    assert spent == pytest.approx(expected_per_piece * 2, rel=1e-6)


# ---------------------------------------------------------------------------
# Correzione 2: provenienza mista nei chunk spezzati (trip a meta' chunk)
# ---------------------------------------------------------------------------

def test_split_aggregate_flags_cf_used_when_every_piece_is_cloudflare(tmp_path, monkeypatch):
    import tts_split

    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": None, "output_tokens": None})

    agg = tts_split._synthesize_pcm_pieces_and_concat(
        ["primo pezzo", "secondo pezzo"],
        "gemini:flash31:Kore", str(tmp_path / "unito.pcm"), None, 1)

    assert agg["cf_used"] is True
    assert agg["backend"] == "cloudflare"


def test_split_aggregate_flags_cf_used_false_when_every_piece_is_vertex(tmp_path, monkeypatch):
    import tts_split

    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 7, "output_tokens": 493})

    agg = tts_split._synthesize_pcm_pieces_and_concat(
        ["primo pezzo", "secondo pezzo"],
        "gemini:flash31:Kore", str(tmp_path / "unito.pcm"), None, 1)

    assert agg["cf_used"] is False
    assert agg["backend"] == "vertex"


def test_split_aggregate_flags_cf_used_true_even_after_a_mid_chunk_trip(tmp_path, monkeypatch):
    """Riproduce esattamente lo scenario della correzione 2: il primo pezzo
    gira su Cloudflare, poi il circuit breaker scatta e i pezzi successivi
    vanno su Vertex. L'aggregato riporta "vertex" come ultimo backend
    scritto (last-write-wins, comportamento preesistente e non cambiato) ma
    `cf_used` deve restare True: e' la sola verita' su cui una decisione
    "questo chunk ha toccato Cloudflare?" puo' fare affidamento senza
    rischiare di nascondere la spesa gia' avvenuta.
    """
    import tts_split
    import gemini_transport

    calls = {"n": 0}

    def _cf_then_trip(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"pcm": PCM_20_SECONDI, "input_tokens": None, "output_tokens": None}
        # kind="backend_down" e' cio' che fa scattare _trip_to_vertex dentro
        # synthesize(): da qui in poi _resolve_backend() torna "vertex" per
        # tutta la vita del processo (persistito da tts_backend_state).
        raise gemini_transport.TransportError("gateway Cloudflare irraggiungibile",
                                              kind="backend_down")

    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf_then_trip)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: {"pcm": PCM_20_SECONDI,
                                      "input_tokens": 7, "output_tokens": 493})

    agg = tts_split._synthesize_pcm_pieces_and_concat(
        ["primo pezzo, prima del trip", "secondo pezzo, dopo il trip",
         "terzo pezzo, ancora dopo il trip"],
        "gemini:flash31:Kore", str(tmp_path / "unito.pcm"), None, 1)

    assert agg is not False
    assert agg["backend"] == "vertex"
    assert agg["cf_used"] is True


# ---------------------------------------------------------------------------
# Correzione 4: riserva di budget preflight sul caso peggiore fra i backend
# abilitati, non sul listino
# ---------------------------------------------------------------------------

def test_worst_case_rates_fall_back_to_google_when_cloudflare_not_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    in_rate, out_rate = gemini_tts.worst_case_rates("flash31")
    g_in, g_out = gemini_tts.actual_rates("flash31", "vertex")
    assert (in_rate, out_rate) == (g_in, g_out)


def test_worst_case_rates_pick_the_more_expensive_side_when_cloudflare_is_configured(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    in_rate, out_rate = gemini_tts.worst_case_rates("flash31")
    g_in, g_out = gemini_tts.actual_rates("flash31", "vertex")
    c_in, c_out = gemini_tts.actual_rates("flash31", "cloudflare")
    assert in_rate == max(g_in, c_in)
    assert out_rate == max(g_out, c_out)
    # Su flash31 Cloudflare e' storicamente piu' economico: il caso peggiore
    # deve coincidere con la tariffa Google pura, mai sottostimarla.
    assert (in_rate, out_rate) == (g_in, g_out)


def test_worst_case_cost_breakdown_never_undercuts_the_pricing_listino_when_failover_is_possible(tmp_path, monkeypatch):
    """Se il modello e' configurato su Cloudflare, il caso peggiore (possibile
    failover a Vertex a meta' job) non deve mai riservare meno del listino
    misto che l'utente ha effettivamente pagato: altrimenti il preflight
    potrebbe far partire un job che sfora il cap se il breaker scatta."""
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    listino = gemini_tts.pricing_cost_breakdown(100000, 100000, "flash31")
    worst = gemini_tts.worst_case_cost_breakdown(100000, 100000, "flash31")
    assert worst["total_eur"] >= listino["total_eur"]
