"""Smoke test: synthesize() passa il model_id Vertex al client mock."""
import gemini_tts


def _fake_client(captured):
    class _Inline:
        data = b"\x00" * 200
    class _Part:
        inline_data = _Inline()
    class _Content:
        parts = [_Part()]
    class _Cand:
        content = _Content()
    class _Usage:
        prompt_token_count = 10
        candidates_token_count = 50
    class _R:
        candidates = [_Cand()]
        usage_metadata = _Usage()

    class _Models:
        @staticmethod
        def generate_content(*, model, contents, config):
            captured["model"] = model
            return _R()

    class _Client:
        models = _Models()

    return _Client()


def test_synthesize_uses_vertex_model_id_on_vertex_backend(
    monkeypatch, tmp_path, reset_backend_cache
):
    creds = tmp_path / "sa.json"; creds.write_text("{}")
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "p")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))

    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda *_: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda *_: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda *_: None)

    out = tmp_path / "x.pcm"
    res = gemini_tts.synthesize(
        text="Ciao",
        voice_id="gemini:flash25:Kore",
        output_path=str(out),
    )
    assert res["success"] is True
    assert captured["model"] == "gemini-2.5-flash-tts"


def test_synthesize_uses_apikey_model_id_on_apikey_backend(
    monkeypatch, tmp_path, reset_backend_cache
):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "apikey")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)

    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda *_: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda *_: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda *_: None)

    out = tmp_path / "x.pcm"
    gemini_tts.synthesize(
        text="Hi",
        voice_id="gemini:flash25:Kore",
        output_path=str(out),
    )
    assert captured["model"] == "gemini-2.5-flash-preview-tts"
