import gemini_tts
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


def test_resolve_model_id_vertex(monkeypatch, tmp_path, reset_backend_cache):
    creds = tmp_path / "sa.json"; creds.write_text("{}")
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "p")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    import gemini_tts
    assert gemini_tts._resolve_model_id("flash25") == "gemini-2.5-flash-tts"
    assert gemini_tts._resolve_model_id("flash31") == "gemini-3.1-flash-tts-preview"


def test_resolve_model_id_apikey(monkeypatch, reset_backend_cache):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "apikey")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    import gemini_tts
    assert gemini_tts._resolve_model_id("flash25") == "gemini-2.5-flash-preview-tts"
    assert gemini_tts._resolve_model_id("flash31") == "gemini-3.1-flash-tts-preview"


def test_resolve_location_default(monkeypatch, tmp_path, reset_backend_cache):
    creds = tmp_path / "sa.json"; creds.write_text("{}")
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "p")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.delenv("ABM_VERTEX_LOCATION_FLASH25", raising=False)
    monkeypatch.delenv("ABM_VERTEX_LOCATION_FLASH31", raising=False)
    import gemini_tts
    assert gemini_tts._resolve_location("flash25") == "global"
    assert gemini_tts._resolve_location("flash31") == "us-central1"


def test_resolve_location_env_override(monkeypatch, tmp_path, reset_backend_cache):
    creds = tmp_path / "sa.json"; creds.write_text("{}")
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "p")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("ABM_VERTEX_LOCATION_FLASH25", "europe-west4")
    monkeypatch.setenv("ABM_VERTEX_LOCATION_FLASH31", "us-central1")
    import gemini_tts
    assert gemini_tts._resolve_location("flash25") == "europe-west4"
    assert gemini_tts._resolve_location("flash31") == "us-central1"


def test_resolve_model_id_unknown_key_raises(monkeypatch, reset_backend_cache):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "apikey")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    import gemini_tts
    with pytest.raises(ValueError, match="Unknown Gemini model"):
        gemini_tts._resolve_model_id("flash99")


def test_resolve_location_unknown_key_raises(monkeypatch, reset_backend_cache):
    import gemini_tts
    with pytest.raises(ValueError, match="Unknown Gemini model"):
        gemini_tts._resolve_location("flash99")


def test_is_available_vertex(monkeypatch, tmp_path, reset_backend_cache):
    creds = tmp_path / "sa.json"; creds.write_text("{}")
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "p")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    import gemini_tts
    gemini_tts._available = None  # reset cache
    assert gemini_tts.is_available() is True


def test_is_available_disabled(monkeypatch, reset_backend_cache):
    monkeypatch.delenv("ABM_GEMINI_BACKEND", raising=False)
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("ABM_GOOGLE_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("ABM_GEMINI_API_KEY", raising=False)
    import gemini_tts
    gemini_tts._available = None
    assert gemini_tts.is_available() is False
