import pytest


@pytest.fixture
def reset_backend_cache():
    """Reset cache backend Gemini tra test (module-level state)."""
    import gemini_tts as gt
    gt._BACKEND = {}
    gt._available = None
    gt._clients_by_location = {}
    yield
    gt._BACKEND = {}
    gt._available = None
    gt._clients_by_location = {}
