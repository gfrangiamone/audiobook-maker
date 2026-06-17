import inspect
import gemini_tts


def test_synthesize_has_style_instruction_param():
    sig = inspect.signature(gemini_tts.synthesize)
    assert "style_instruction" in sig.parameters
    assert sig.parameters["style_instruction"].default is None


def _make_fake_client(captured):
    class _FakeModels:
        @staticmethod
        def generate_content(*, model, contents, config):
            captured["contents"] = contents
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
            return _R()
    class _FakeClient:
        models = _FakeModels()
    return _FakeClient()


def test_style_instruction_prepended_to_text(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize(
        "Ciao mondo",
        "gemini:flash25:Zephyr",
        style_instruction="tono calmo e narrativo",
        output_path=str(out),
    )
    assert "tono calmo e narrativo" in captured["contents"]
    assert "Ciao mondo" in captured["contents"]
    assert "[style:" in captured["contents"]


def test_style_instruction_none_does_not_prepend(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize("Ciao", "gemini:flash25:Zephyr", style_instruction=None, output_path=str(out))
    assert captured["contents"] == "Ciao"


def test_style_instruction_truncated_at_200_chars(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    long_style = "a" * 500
    gemini_tts.synthesize("Testo", "gemini:flash25:Zephyr", style_instruction=long_style, output_path=str(out))
    # The style payload (between [style: and ]) must be capped at 200 chars
    assert "a" * 200 in captured["contents"]
    assert "a" * 201 not in captured["contents"]


def test_style_instruction_coexists_with_rate(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setenv("ABM_GEMINI_RATE_MODE", "prompt")
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize("Frase", "gemini:flash25:Zephyr", rate="+10%",
                          style_instruction="vivace", output_path=str(out))
    c = captured["contents"]
    # Le direttive rate sono in linguaggio naturale (refactor del +-10% in 7 step
    # distinti, vedi _GEMINI_RATE_DIRECTIVES). +10% -> step 1 -> "slightly brisk".
    assert "slightly brisk" in c and "[style:" in c
    assert "vivace" in c
    assert "Frase" in c


def test_style_instruction_whitespace_only_does_not_prepend(monkeypatch, tmp_path):
    """A whitespace-only style_instruction must not crash and must not add a prefix."""
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize("Solo testo", "gemini:flash25:Zephyr",
                          style_instruction="   \t  \n  ", output_path=str(out))
    assert captured["contents"] == "Solo testo"
    assert "[style:" not in captured["contents"]


def test_prefissi_oltre_soglia_qualita_non_sollevano(monkeypatch, tmp_path, capsys):
    """Testo entro soglia qualita`, prefissi che spingono il payload oltre: ok.

    MAX_BYTES_PER_CALL si applica SOLO al testo da sintetizzare. I prefissi
    style/rate sono direttive di prompt, non testo audio: non devono far
    fallire la sintesi se da soli sforano la soglia. La chiamata deve partire
    finche` il payload totale resta sotto API_HARD_BYTES_CAP.
    """
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    # Scenario realistico: target qualita` 700b, hard cap API 8000b.
    monkeypatch.setattr(gemini_tts, "MAX_BYTES_PER_CALL", 700)
    monkeypatch.setattr(gemini_tts, "API_HARD_BYTES_CAP", 8000)
    # Testo SOTTO soglia qualita`; prefissi consistenti che da soli spingerebbero
    # un check naive sul payload oltre il target ma sotto l'hard cap.
    near_cap_text = "x" * (gemini_tts.MAX_BYTES_PER_CALL - 50)
    style = "y" * 300
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize(near_cap_text, "gemini:flash25:Zephyr",
                          style_instruction=style, output_path=str(out))
    assert "[style:" in captured["contents"]
    # Niente warning: il testo puro sta sotto soglia.
    out_log = capsys.readouterr().out
    assert "oltre soglia qualita" not in out_log


def test_testo_oltre_soglia_qualita_warning_ma_non_solleva(monkeypatch, tmp_path, capsys):
    """Testo puro oltre MAX_BYTES_PER_CALL: warning loggato, sintesi prosegue.

    Caso difensivo: se lo splitter manca un chunk borderline, synthesize() non
    deve trasformarlo in silenzio -- logga e procede (la qualita` puo` calare,
    ma il job non si perde).
    """
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "MAX_BYTES_PER_CALL", 700)
    monkeypatch.setattr(gemini_tts, "API_HARD_BYTES_CAP", 8000)
    oversized_text = "x" * (gemini_tts.MAX_BYTES_PER_CALL + 100)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize(oversized_text, "gemini:flash25:Zephyr", output_path=str(out))
    out_log = capsys.readouterr().out
    assert "oltre soglia qualita" in out_log
    assert captured["contents"] == oversized_text


# ── Accent directive ────────────────────────────────────────────────────────

def test_synthesize_has_accent_directive_param():
    sig = inspect.signature(gemini_tts.synthesize)
    assert "accent_directive" in sig.parameters
    assert sig.parameters["accent_directive"].default is None


def test_build_accent_directive_variant_and_default():
    # Lingua del catalogo: variante esplicita.
    gb = gemini_tts.build_accent_directive("en", "gb")
    assert "British English" in gb
    # Default = primo del catalogo (en -> us).
    us = gemini_tts.build_accent_directive("en", None)
    assert "American English" in us
    # Codice non valido -> default.
    assert gemini_tts.build_accent_directive("en", "zz") == us
    # Locale lungo normalizzato (es-ES -> es), default castigliano.
    assert "Castilian" in gemini_tts.build_accent_directive("es-ES", None)


def test_build_accent_directive_mono_variant_anchors_language():
    # Lingua senza varianti multiple: ancora comunque al nome lingua.
    it = gemini_tts.build_accent_directive("it", None)
    assert "Italian" in it and "consistent accent" in it
    # Lingua sconosciuta: nessun ancoraggio.
    assert gemini_tts.build_accent_directive("xx", None) == ""
    assert gemini_tts.build_accent_directive("", None) == ""


def test_accent_options_and_default_code():
    assert gemini_tts.default_accent_code("en") == "us"
    assert gemini_tts.default_accent_code("es") == "es"
    assert gemini_tts.default_accent_code("pt") == "br"
    # de e ar inclusi nel selettore.
    assert len(gemini_tts.accent_options("de")) >= 2
    assert len(gemini_tts.accent_options("ar")) >= 2
    # Mono-variante: nessuna opzione (nessun dropdown UI).
    assert gemini_tts.accent_options("it") == []
    assert gemini_tts.default_accent_code("it") is None


def test_accent_directive_leads_style_block(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize(
        "Hello world",
        "gemini:flash25:Zephyr",
        style_instruction="calm tone",
        accent_directive=gemini_tts.build_accent_directive("en", "gb"),
        output_path=str(out),
    )
    c = captured["contents"]
    assert c.startswith("[style:")
    assert "British English" in c
    assert "calm tone" in c
    assert "Hello world" in c
    # L'accento precede lo stile utente dentro il blocco [style: ...].
    assert c.index("British English") < c.index("calm tone")


def test_accent_directive_none_keeps_legacy_behavior(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: _make_fake_client(captured))
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    out = tmp_path / "x.pcm"
    gemini_tts.synthesize("Solo testo", "gemini:flash25:Zephyr",
                          accent_directive=None, output_path=str(out))
    assert captured["contents"] == "Solo testo"


def test_payload_oltre_api_hard_cap_solleva(monkeypatch, tmp_path):
    """Payload totale oltre API_HARD_BYTES_CAP: ValueError (vero hard cap API)."""
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "MAX_BYTES_PER_CALL", 700)
    monkeypatch.setattr(gemini_tts, "API_HARD_BYTES_CAP", 8000)
    huge_text = "x" * (gemini_tts.API_HARD_BYTES_CAP + 100)
    import pytest
    with pytest.raises(ValueError, match="API hard cap"):
        gemini_tts.synthesize(huge_text, "gemini:flash25:Zephyr",
                              output_path="/tmp/x.pcm")
