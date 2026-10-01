"""Tests for /api/voices Gemini merge."""
import os
import pytest
import audiobook_app


@pytest.fixture(autouse=True)
def reset_voices_cache(monkeypatch):
    # get_voices() include le voci Gemini solo se gemini_tts.is_available() e'
    # True (audiobook_app.py, merge Gemini in _fetch_voices). Quel booleano e'
    # una cache di modulo risolta una sola volta per l'intera sessione pytest
    # (gia' all'import di audiobook_app, sulla base delle credenziali reali
    # della macchina) e non viene mai ricalcolata dopo: senza questo
    # monkeypatch il test dipenderebbe da uno stato globale fuori dal proprio
    # controllo (macchina locale / cosa ha girato prima nella sessione).
    # Auto-ripristinato da monkeypatch, nessun teardown manuale necessario.
    if audiobook_app.gemini_tts is not None:
        monkeypatch.setattr(audiobook_app.gemini_tts, "is_available", lambda: True)
    audiobook_app._invalidate_voices_cache()
    yield
    audiobook_app._invalidate_voices_cache()


def test_get_voices_includes_gemini_when_module_present(monkeypatch):
    """If gemini_tts is loaded, voices catalog should include 'gemini' engine entries."""
    if audiobook_app.gemini_tts is None:
        pytest.skip("gemini_tts module not importable")

    voices = audiobook_app.get_voices()
    found_gemini = False
    for lang_code, lang_data in voices.items():
        if lang_code.startswith("_"):
            continue
        for v in lang_data.get("voices", []):
            if v.get("engine") == "gemini":
                found_gemini = True
                assert "gender" in v
                assert "gender_icon" in v
                assert v["id"].startswith("gemini:")
                break
        if found_gemini:
            break
    assert found_gemini, "No Gemini voices found in catalog"


def test_get_voices_gemini_entry_shape(monkeypatch):
    if audiobook_app.gemini_tts is None:
        pytest.skip("gemini_tts module not importable")

    voices = audiobook_app.get_voices()
    it_voices = voices.get("it", {}).get("voices", [])
    gemini_it = [v for v in it_voices if v.get("engine") == "gemini"]
    assert len(gemini_it) >= 30  # at least one model × 30 voices
    sample = gemini_it[0]
    for key in ("id", "name", "gender", "gender_icon", "locale", "engine"):
        assert key in sample, f"Missing key: {key}"


def test_api_voices_esclude_modello_indisponibile(monkeypatch, tmp_path):
    """/api/voices toglie un modello marcato non disponibile, anche se la
    cache voci (costruita una volta per processo) lo conterrebbe ancora."""
    if audiobook_app.gemini_tts is None:
        pytest.skip("gemini_tts module not importable")

    import gemini_availability
    monkeypatch.setenv("ABM_FLASH38_ENABLE", "true")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    audiobook_app.gemini_tts._BACKEND = {}
    gemini_availability.init(str(tmp_path))

    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        r = c.get("/api/voices")
        assert r.status_code == 200
        body = r.get_json()
        it_voices = body.get("it", {}).get("voices", [])
        assert any(v.get("id", "").startswith("gemini:flash38:") for v in it_voices)

        gemini_availability.mark_unavailable("flash38", "403")
        try:
            r = c.get("/api/voices")
            assert r.status_code == 200
            body = r.get_json()
            it_voices = body.get("it", {}).get("voices", [])
            assert not any(v.get("id", "").startswith("gemini:flash38:") for v in it_voices)
        finally:
            gemini_availability.clear("flash38")
    audiobook_app.gemini_tts._BACKEND = {}
