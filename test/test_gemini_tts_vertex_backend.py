import gemini_tts
import importlib
import pytest


def test_gemini_models_has_vertex_metadata_flash25():
    m = gemini_tts.GEMINI_MODELS["flash25"]
    assert m["id"] == "gemini-2.5-flash-preview-tts"
    assert m["id_vertex"] == "gemini-2.5-flash-tts"
    assert m["location_vertex"] == "global"


def test_gemini_models_has_vertex_metadata_flash31():
    m = gemini_tts.GEMINI_MODELS["flash31"]
    assert m["id"] == "gemini-3.1-flash-tts-preview"
    assert m["id_vertex"] == "gemini-3.1-flash-tts-preview"
    assert m["location_vertex"] == "us-central1"


@pytest.fixture
def reset_backend_cache():
    """Reset cache backend tra test (importante: la cache vive a module level)."""
    import gemini_tts as gt
    gt._BACKEND = None
    yield
    gt._BACKEND = None


def test_backend_vertex_explicit(monkeypatch, tmp_path, reset_backend_cache):
    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "my-project")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    import gemini_tts
    assert gemini_tts._resolve_backend() == "vertex"


def test_backend_apikey_explicit(monkeypatch, reset_backend_cache):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "apikey")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "fake-key")
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    import gemini_tts
    assert gemini_tts._resolve_backend() == "apikey"


def test_backend_auto_prefers_vertex(monkeypatch, tmp_path, reset_backend_cache):
    creds = tmp_path / "sa.json"
    creds.write_text("{}")
    monkeypatch.delenv("ABM_GEMINI_BACKEND", raising=False)
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "my-project")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "fake-key")
    import gemini_tts
    assert gemini_tts._resolve_backend() == "vertex"


def test_backend_auto_falls_back_to_apikey(monkeypatch, reset_backend_cache):
    monkeypatch.delenv("ABM_GEMINI_BACKEND", raising=False)
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("ABM_GOOGLE_CREDENTIALS_FILE", raising=False)
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "fake-key")
    import gemini_tts
    assert gemini_tts._resolve_backend() == "apikey"


def test_backend_disabled_when_no_config(monkeypatch, reset_backend_cache):
    monkeypatch.delenv("ABM_GEMINI_BACKEND", raising=False)
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("ABM_GOOGLE_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("ABM_GEMINI_API_KEY", raising=False)
    import gemini_tts
    assert gemini_tts._resolve_backend() is None


def test_backend_vertex_disabled_when_creds_missing(monkeypatch, tmp_path, reset_backend_cache):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "my-project")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(tmp_path / "missing.json"))
    import gemini_tts
    assert gemini_tts._resolve_backend() is None
