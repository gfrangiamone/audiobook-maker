"""Risoluzione del backend Gemini, per modello."""
import pytest

import gemini_tts
import tts_backend_state as st


@pytest.fixture(autouse=True)
def _reset_backend_cache():
    gemini_tts._BACKEND = {}
    yield
    gemini_tts._BACKEND = {}


def _vertex_env(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "progetto")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))


def test_flash31_has_a_cloudflare_id():
    assert gemini_tts.GEMINI_MODELS["flash31"]["id_cloudflare"] == \
        "google/gemini-3.1-flash-tts"


def test_auto_never_selects_cloudflare(monkeypatch, tmp_path):
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_explicit_cloudflare_is_honoured(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    assert gemini_tts._resolve_backend("flash31") == "cloudflare"


def test_cloudflare_without_credentials_is_disabled(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.delenv("ABM_CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ABM_CF_API_TOKEN", raising=False)
    assert gemini_tts._resolve_backend("flash31") is None


def test_resolution_is_cached_per_model(monkeypatch, tmp_path):
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    assert gemini_tts._resolve_backend("flash31") == "vertex"
    # Cambiare l'ambiente dopo la risoluzione non deve muovere nulla.
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "apikey")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_set_backend_overrides_the_cache(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    assert gemini_tts._resolve_backend("flash31") == "cloudflare"
    gemini_tts._set_backend("flash31", "vertex")
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_set_backend_rejects_an_unknown_backend():
    with pytest.raises(ValueError):
        gemini_tts._set_backend("flash31", "piccione-viaggiatore")


def test_resolve_without_model_key_still_works(monkeypatch, tmp_path):
    # Retro-compatibilita': i caller storici chiamano _resolve_backend() nudo.
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    assert gemini_tts._resolve_backend() == "vertex"


# --- Regressione review task-6 Important #1 --------------------------------
# tts_backend_state._FAIL_SAFE (stato su disco illeggibile al boot) fa
# risultare is_tripped() True per QUALUNQUE model_key non ancora in cache,
# anche uno nuovo come flash38. Prima del fix, il ramo di precedenza del
# breaker in _resolve_backend forzava "vertex" senza passare dal filtro
# backends_allowed: un modello apikey-only finiva su Vertex (404 ad ogni
# chunk) proprio nel caso che backends_allowed esiste per escludere.

@pytest.fixture
def _fail_safe(monkeypatch):
    monkeypatch.setattr(st, "_FAIL_SAFE", True)
    st._CACHE.pop("flash38", None)
    yield
    st._CACHE.pop("flash38", None)


def test_fail_safe_trip_non_forza_vertex_su_flash38_senza_api_key(
        monkeypatch, tmp_path, _fail_safe):
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.delenv("ABM_GEMINI_API_KEY", raising=False)
    # Vertex e' pronto (credenziali complete): senza il fix, is_tripped()
    # forzerebbe "vertex" qui, in violazione di backends_allowed=("apikey",).
    assert gemini_tts._resolve_backend("flash38") is None


def test_fail_safe_trip_su_flash38_con_api_key_usa_apikey(
        monkeypatch, tmp_path, _fail_safe):
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    assert gemini_tts._resolve_backend("flash38") == "apikey"
