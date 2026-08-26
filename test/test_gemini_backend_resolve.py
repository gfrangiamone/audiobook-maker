"""Risoluzione del backend Gemini, per modello."""
import pytest

import gemini_tts


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


def test_flash25_has_no_cloudflare_id_until_verified():
    # Nessuna verifica che Cloudflare ospiti flash25: finche' non c'e',
    # il modello resta su Vertex.
    assert gemini_tts.GEMINI_MODELS["flash25"]["id_cloudflare"] is None


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


def test_a_model_without_cloudflare_id_falls_back_to_vertex(monkeypatch, tmp_path):
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    # flash25 non e' su Cloudflare: non deve finirci per errore.
    assert gemini_tts._resolve_backend("flash25") == "vertex"


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
