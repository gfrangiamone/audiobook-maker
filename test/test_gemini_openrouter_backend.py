"""Backend OpenRouter: risoluzione, ripiego del breaker, stile, tariffe.

Schema del 12/10/2026: flash38 su OpenRouter con l'API key di ripiego;
flash31 su Cloudflare con OpenRouter di ripiego al posto di Vertex.
"""
import pytest

import gemini_tts
import tts_backend_state as st
from gemini_transport import TransportError


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    for env in ("ABM_GEMINI_BACKEND", "ABM_GEMINI_BACKEND_FLASH38",
                "ABM_GEMINI_BACKEND_FLASH31", "ABM_OPENROUTER_API_KEY",
                "ABM_GEMINI_API_KEY", "ABM_GCP_PROJECT_ID",
                "ABM_GOOGLE_CREDENTIALS_FILE", "ABM_CF_ACCOUNT_ID",
                "ABM_CF_API_TOKEN", "ABM_OR_CREDIT_TOPUP_FEE", "ABM_OR_TIMEOUT_MS"):
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "22")
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
    st.reset("flash38")


def _vertex(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "p")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))


def _cf(monkeypatch):
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")


def _pcm(n=48):
    return {"pcm": b"\x00" * n, "input_tokens": None, "output_tokens": None}


# --- risoluzione -------------------------------------------------------------

def test_explicit_openrouter_is_honoured_per_model(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    assert gemini_tts._resolve_backend("flash38") == "openrouter"
    assert gemini_tts.configured_primary_backend("flash38") == "openrouter"
    assert gemini_tts.configured_primary_backend("flash31") == "cloudflare"


def test_openrouter_without_key_is_disabled_not_apikey(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    assert gemini_tts._resolve_backend("flash38") is None


def test_auto_never_selects_openrouter(monkeypatch):
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "g")
    assert gemini_tts._resolve_backend("flash38") == "apikey"


def test_flash38_never_lands_on_vertex_even_with_openrouter_selected(monkeypatch, tmp_path):
    _vertex(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "openrouter")
    monkeypatch.delenv("ABM_OPENROUTER_API_KEY", raising=False)
    assert gemini_tts._resolve_backend("flash38") is None


def test_a_tripped_flash38_resolves_to_apikey(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "g")
    st.trip("flash38", reason="or_backend_down", detail="d", job_id=None, active="apikey")
    assert gemini_tts._resolve_backend("flash38") == "apikey"


def test_a_tripped_flash31_prefers_openrouter_over_vertex(monkeypatch, tmp_path):
    _vertex(monkeypatch, tmp_path)
    _cf(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    st.trip("flash31", reason="cf_backend_down", detail="d", job_id=None)
    assert gemini_tts._resolve_backend("flash31") == "openrouter"


def test_fallback_target_falls_through_to_vertex_without_openrouter(monkeypatch, tmp_path):
    _vertex(monkeypatch, tmp_path)
    assert gemini_tts._fallback_target("flash31") == "vertex"
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    assert gemini_tts._fallback_target("flash31") == "openrouter"
    assert gemini_tts._fallback_target("flash38") is False
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "g")
    assert gemini_tts._fallback_target("flash38") == "apikey"


# --- failover in sintesi -------------------------------------------------------

def _synth(tmp_path, voice="gemini:flash38:Kore", **kw):
    return gemini_tts.synthesize("ciao mondo", voice,
                                 output_path=str(tmp_path / "o.pcm"), **kw)


def test_flash38_credit_exhausted_on_openrouter_continues_on_apikey(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "g")
    apikey_calls = []

    def _or(**kw):
        raise TransportError("credito esaurito", kind="backend_down", http_status=402)

    def _vx(**kw):
        apikey_calls.append(kw)
        return {"pcm": b"\x01" * 48, "input_tokens": 10, "output_tokens": 200}

    monkeypatch.setattr(gemini_tts._transport, "openrouter_call", _or)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _vx)
    out = _synth(tmp_path, job_id="j1")
    assert out["success"] and out["backend"] == "apikey"
    assert len(apikey_calls) == 1
    assert st.is_tripped("flash38") and st.state("flash38")["active"] == "apikey"
    assert st.state("flash38")["trip_reason"] == "or_backend_down"
    assert gemini_tts._resolve_backend("flash38") == "apikey"


def test_flash38_without_apikey_fallback_is_unavailable_after_the_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(gemini_tts._transport, "openrouter_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down")))
    with pytest.raises(gemini_tts.GeminiUnavailable):
        _synth(tmp_path)
    assert st.is_tripped("flash38")


def test_flash31_cloudflare_down_falls_back_on_openrouter(tmp_path, monkeypatch):
    _cf(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    seen = []
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down", http_status=402)))
    monkeypatch.setattr(gemini_tts._transport, "openrouter_call",
                        lambda **kw: seen.append(kw) or _pcm())
    out = _synth(tmp_path, voice="gemini:flash31:Kore")
    assert out["backend"] == "openrouter"
    assert seen[0]["model_id"] == "google/gemini-3.1-flash-tts-preview"
    assert st.state("flash31")["active"] == "openrouter"


def test_consecutive_openrouter_failures_trip_too(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "g")
    monkeypatch.setenv("ABM_CF_TRIP_FAILURES", "2")
    monkeypatch.setattr(gemini_tts._transport, "openrouter_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("502", kind="retryable", http_status=502)))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())
    out = _synth(tmp_path)
    assert out["backend"] == "apikey"
    assert st.state("flash38")["trip_reason"] == "or_consecutive_failures"


def test_openrouter_moderation_rejects_the_chunk_without_tripping(tmp_path, monkeypatch):
    # Job 8db7VnSUuZTMnsMJPm_Byg (15/10/2026): tre 400 di moderazione sullo
    # stesso chunk facevano scattare il breaker e spostavano flash38 su API key.
    import gemini_transport as gt

    class _R:
        status_code = 400
        headers = {"Content-Type": "application/json"}
        text = ""
        content = b""

        def json(self):
            return {"error": {"message": "Provider blocked this request through "
                              "content moderation (provider finish reason: "
                              "PROHIBITED_CONTENT)", "code": 400}}

    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "g")
    monkeypatch.setenv("ABM_CF_TRIP_FAILURES", "1")
    calls = []
    monkeypatch.setattr(gt.requests, "post",
                        lambda *a, **kw: calls.append(kw) or _R())
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: pytest.fail("nessun ripiego per un rifiuto"))
    with pytest.raises(gemini_tts.GeminiEmptyResponse) as ei:
        _synth(tmp_path)
    assert ei.value.retryable is False
    assert len(calls) == 1
    assert not st.is_tripped("flash38")
    assert st.state("flash38").get("consecutive_failures", 0) == 0


def test_openrouter_tokens_are_derived_from_the_audio(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    monkeypatch.setattr(gemini_tts._transport, "openrouter_call",
                        lambda **kw: _pcm(24000 * 2 * 10))
    out = _synth(tmp_path)
    assert out["tokens_measured"] is False
    assert out["output_tokens"] == round(10 * gemini_tts._audio_tokens_per_second("flash38"))


# --- stile ---------------------------------------------------------------------

def test_flash38_style_goes_into_instructions_on_openrouter(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    seen = {}
    monkeypatch.setattr(gemini_tts._transport, "openrouter_call",
                        lambda **kw: seen.update(kw) or _pcm())
    _synth(tmp_path, style_instruction="calm storyteller",
           accent_directive="Read in Italian, keeping one consistent accent throughout.")
    assert seen["model_id"] == "google/gemini-3.8-flash-tts"
    assert "calm storyteller" in seen["instructions"]
    assert "Read in Italian" in seen["instructions"]
    assert not seen["final_text"].startswith("[style:")
    assert "ciao mondo" in seen["final_text"]


def test_flash31_style_stays_inline_on_openrouter(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH31", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    seen = {}
    monkeypatch.setattr(gemini_tts._transport, "openrouter_call",
                        lambda **kw: seen.update(kw) or _pcm())
    _synth(tmp_path, voice="gemini:flash31:Kore", style_instruction="calm storyteller")
    assert seen["instructions"] is None
    assert seen["final_text"].startswith("[style:")


def test_openrouter_timeout_never_below_the_model_one(monkeypatch):
    assert gemini_tts._or_timeout_ms("flash38") == 60000
    monkeypatch.setenv("ABM_OR_TIMEOUT_MS", "1000")
    assert gemini_tts._or_timeout_ms("flash31") == gemini_tts._http_timeout_ms("flash31")


# --- tariffe (contabilita') ------------------------------------------------------

def test_openrouter_rates_carry_the_topup_fee_and_no_vat(monkeypatch):
    monkeypatch.setenv("ABM_OR_CREDIT_VAT_PERCENT", "0")
    assert gemini_tts.actual_rates("flash38", "openrouter") == \
        pytest.approx((0.50 * 1.055, 9.00 * 1.055))
    assert gemini_tts.actual_rates("flash31", "openrouter") == \
        pytest.approx((1.00 * 1.055, 20.00 * 1.055))
    bd = gemini_tts.actual_cost_breakdown(0, 1_000_000, "flash38", "openrouter")
    assert bd["vat_eur"] == 0.0
    assert bd["total_eur"] == pytest.approx(9.00 * 1.055 * gemini_tts.USD_EUR_RATE)


def test_openrouter_fee_from_env(monkeypatch):
    monkeypatch.setenv("ABM_OR_CREDIT_VAT_PERCENT", "0")
    monkeypatch.setenv("ABM_OR_CREDIT_TOPUP_FEE", "0.10")
    assert gemini_tts.actual_rates("flash38", "openrouter")[1] == pytest.approx(9.90)


def test_openrouter_is_cheaper_than_google_for_flash38_per_hour():
    tok = 3600 * gemini_tts._audio_tokens_per_second("flash38")
    goog = gemini_tts.actual_cost_breakdown(0, tok, "flash38", "apikey")["total_eur"]
    orr = gemini_tts.actual_cost_breakdown(0, tok, "flash38", "openrouter")["total_eur"]
    assert orr < goog


def test_worst_case_includes_openrouter_when_it_may_execute(monkeypatch):
    # flash38 su OpenRouter con API key di ripiego: il caso peggiore e'
    # Google con IVA (18 USD/Mtok lordi), non OpenRouter.
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    assert gemini_tts._model_may_use_openrouter("flash38") is True
    assert gemini_tts.worst_case_rates("flash38") == \
        pytest.approx(gemini_tts.actual_rates("flash38", "apikey"))
    # flash31 su Cloudflare con OpenRouter di ripiego: vale la tariffa piu' cara.
    _cf(monkeypatch)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    assert gemini_tts._model_may_use_openrouter("flash31") is True
    w = gemini_tts.worst_case_rates("flash31")
    assert w[1] >= gemini_tts.actual_rates("flash31", "openrouter")[1]


def test_openrouter_not_counted_without_key(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    assert gemini_tts._model_may_use_openrouter("flash31") is False


# --- sonda di rientro -----------------------------------------------------------

def test_probe_eligibility_follows_the_per_model_primary(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    st.trip("flash38", reason="or_backend_down", detail="d", job_id=None, active="apikey")
    ok, why = gemini_tts._cf_probe_eligible("flash38")
    assert ok, why
    monkeypatch.delenv("ABM_OPENROUTER_API_KEY")
    ok, why = gemini_tts._cf_probe_eligible("flash38")
    assert not ok and "OpenRouter" in why


def test_a_successful_probe_returns_flash38_to_openrouter(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "openrouter")
    monkeypatch.setenv("ABM_OPENROUTER_API_KEY", "k")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "g")
    st.trip("flash38", reason="or_backend_down", detail="d", job_id=None, active="apikey")
    seen = {}
    monkeypatch.setattr(gemini_tts._transport, "openrouter_call",
                        lambda **kw: seen.update(kw) or _pcm())
    assert gemini_tts.probe_cloudflare("flash38") == "returned"
    assert seen["model_id"] == "google/gemini-3.8-flash-tts"
    assert not st.is_tripped("flash38")
    assert gemini_tts._resolve_backend("flash38") == "openrouter"


# --- tassa sulla ricarica OpenRouter (dal 16/10/2026) -----------------------------

def test_openrouter_vat_defaults_to_the_16_10_2026_receipt(monkeypatch):
    monkeypatch.delenv("ABM_OR_CREDIT_VAT_PERCENT", raising=False)
    assert gemini_tts.or_vat_percent() == 5.0
    monkeypatch.setenv("ABM_OR_CREDIT_VAT_PERCENT", "0")
    bd = gemini_tts.actual_cost_breakdown(0, 1_000_000, "flash38", "openrouter")
    assert bd["vat_eur"] == 0.0


def test_openrouter_vat_applies_on_top_of_the_topup_fee(monkeypatch):
    # Ricevuta del 16/10/2026: 100 $ di credito + 5,50 $ di fee + 5,28 $ di
    # tassa = 110,78 $. Con fee 5,5% e tassa 5,0% (su credito + fee) il costo
    # per dollaro di credito speso torna esattamente.
    monkeypatch.setenv("ABM_OR_CREDIT_TOPUP_FEE", "0.055")
    monkeypatch.setenv("ABM_OR_CREDIT_VAT_PERCENT", "5")
    assert gemini_tts.actual_rates("flash38", "openrouter")[1] ==         pytest.approx(9.00 * 1.055 * 1.05)
    assert 100 * 1.055 * 1.05 == pytest.approx(110.78, abs=0.01)
    bd = gemini_tts.actual_cost_breakdown(0, 1_000_000, "flash38", "openrouter")
    net = 9.00 * 1.055 * gemini_tts.USD_EUR_RATE
    assert bd["net_eur"] == pytest.approx(net)
    assert bd["vat_eur"] == pytest.approx(net * 0.05)


def test_openrouter_vat_does_not_touch_google_or_cloudflare(monkeypatch):
    monkeypatch.setenv("ABM_OR_CREDIT_VAT_PERCENT", "5")
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "22")
    assert gemini_tts._vat_factor("apikey") == pytest.approx(1.22)
    assert gemini_tts._vat_factor("cloudflare") == 1.0
    assert gemini_tts._vat_factor("openrouter") == pytest.approx(1.05)


def test_openrouter_vat_never_changes_the_user_price(monkeypatch):
    p0 = gemini_tts.compute_user_price_eur(3600.0, "flash38")["list_price_eur"]
    monkeypatch.setenv("ABM_OR_CREDIT_VAT_PERCENT", "22")
    assert gemini_tts.compute_user_price_eur(3600.0, "flash38")["list_price_eur"] == p0
