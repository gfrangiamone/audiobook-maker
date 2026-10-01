"""Modello flash38 (Gemini 3.8 PREMIUM+) via API key."""
import pytest

import gemini_tts
import voice_utils


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    gemini_tts._BACKEND = {}
    for env in ("ABM_GEMINI_BACKEND", "ABM_GEMINI_BACKEND_FLASH38",
                "ABM_GEMINI_RPM_FLASH38", "ABM_GEMINI_MIN_INTERVAL_FLASH38_MS",
                "ABM_GEMINI_38FLASH_MARGIN_PERCENT", "ABM_FLASH38_ENABLE"):
        monkeypatch.delenv(env, raising=False)
    yield
    gemini_tts._BACKEND = {}


def test_voce_catalogo():
    m = gemini_tts.GEMINI_MODELS["flash38"]
    assert m["id"] == m["id_vertex"] == "gemini-3.8-flash-tts"
    assert m["id_cloudflare"] is None
    assert m["label"] == "Gemini 3.8 (PREMIUM+)"
    assert (m["input_usd_per_mtok"], m["output_usd_per_mtok"]) == (1.00, 18.00)
    assert m["backends_allowed"] == ("apikey",)
    assert m["mark_unavailable_on_fatal"] is True


def test_limiti_tier3():
    assert gemini_tts._min_interval_ms("flash38") == 75   # 800 RPM
    assert gemini_tts._rpd_cap("flash38") == 0
    assert gemini_tts._http_timeout_ms("flash38") == 40000
    assert gemini_tts.preview_timeout_sec("flash38") == 45
    assert gemini_tts._audio_tokens_per_second("flash38") == pytest.approx(31.9)
    assert gemini_tts.get_margin_percent("flash38") == 25.0


def test_backend_per_modello_prevale(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_GEMINI_BACKEND_FLASH38", "apikey")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    assert gemini_tts._resolve_backend("flash38") == "apikey"


def test_senza_api_key_non_si_risolve(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "p")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.delenv("ABM_GEMINI_API_KEY", raising=False)
    # auto sceglierebbe vertex: vietato per flash38 (404 sul progetto).
    assert gemini_tts._resolve_backend("flash38") is None


def test_auto_con_api_key(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    assert gemini_tts._resolve_backend("flash38") == "apikey"


def test_modello_api_key_usa_id_pubblico(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    assert gemini_tts._resolve_model_id("flash38") == "gemini-3.8-flash-tts"


def test_prezzo_flash38_con_iva_e_margine(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "22")
    bd = gemini_tts.pricing_cost_breakdown(0, 1_000_000, "flash38")
    atteso = 18.0 * gemini_tts.USD_EUR_RATE * 1.22
    assert bd["total_eur"] == pytest.approx(atteso)
    p = gemini_tts.compute_user_price_eur(bd["total_eur"], "flash38")
    assert p["base_price_eur"] == pytest.approx(atteso * 1.25, rel=1e-3)


def test_flash38_spento_di_default():
    assert voice_utils.premium_model_enabled("flash38") is False
    assert "flash38" not in gemini_tts.enabled_model_keys()


def test_flash38_acceso_da_env(monkeypatch):
    monkeypatch.setenv("ABM_FLASH38_ENABLE", "true")
    assert voice_utils.premium_model_enabled("flash38") is True


def test_flash31_resta_acceso_di_default():
    assert voice_utils.premium_model_enabled("flash31") is True
