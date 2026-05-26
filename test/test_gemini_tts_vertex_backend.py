import gemini_tts


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
