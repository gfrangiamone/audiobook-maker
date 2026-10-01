"""Stato non disponibile per modello: persistenza, cooldown, reset."""
import pytest

import gemini_availability as ga


@pytest.fixture(autouse=True)
def _init(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_UNAVAILABLE_COOLDOWN_SEC", "900")
    ga.init(str(tmp_path))
    yield tmp_path


def test_mark_e_cooldown():
    assert ga.mark_unavailable("flash38", "403", now=1000.0) is True
    assert ga.is_unavailable("flash38", now=1000.0 + 899)
    assert not ga.is_unavailable("flash38", now=1000.0 + 900)


def test_seconda_marcatura_non_riapre():
    assert ga.mark_unavailable("flash38", "a", now=1000.0) is True
    assert ga.mark_unavailable("flash38", "b", now=1010.0) is False


def test_persistito_oltre_il_riavvio(_init):
    ga.mark_unavailable("flash38", "403", now=1000.0)
    ga.init(str(_init))
    assert ga.is_unavailable("flash38", now=1500.0)
    assert not ga.is_unavailable("flash38", now=1900.0)


def test_reset():
    ga.mark_unavailable("flash38", "403", now=1000.0)
    assert ga.clear("flash38") is True
    assert not ga.is_unavailable("flash38", now=1001.0)
    assert ga.clear("flash38") is False


def test_snapshot():
    ga.mark_unavailable("flash38", "403 key", now=1000.0)
    s = ga.snapshot(now=1100.0)
    assert s["flash38"]["unavailable"] is True
    assert s["flash38"]["retry_in_sec"] == 800
    assert s["flash38"]["reason"] == "403 key"


def test_file_corrotto_non_blocca(_init):
    (_init / "_gemini_model_availability.json").write_text("{", encoding="utf-8")
    ga.init(str(_init))
    assert not ga.is_unavailable("flash38")


def test_foglia_senza_import_di_progetto():
    import ast, pathlib
    tree = ast.parse(pathlib.Path(ga.__file__).read_text(encoding="utf-8"))
    nomi = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    nomi |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    assert nomi <= {"json", "os", "threading", "time", "pathlib"}


# --- integrazione con gemini_tts -------------------------------------------

import gemini_tts


def test_fatale_apikey_marca_e_notifica(monkeypatch):
    from gemini_transport import TransportError
    monkeypatch.setattr(gemini_tts, "_resolve_backend", lambda mk=None: "apikey")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)

    def _boom(**kw):
        raise TransportError("403 PERMISSION_DENIED", kind="fatal")

    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _boom)
    avvisi = []
    gemini_tts.set_model_unavailable_notifier(lambda mk, d, j: avvisi.append((mk, j)))
    try:
        with pytest.raises(gemini_tts.GeminiUnavailable):
            gemini_tts.synthesize("Ciao.", "gemini:flash38:Zephyr",
                                  output_path=str(ga._path.parent / "o.pcm"), job_id="J9")
    finally:
        gemini_tts.set_model_unavailable_notifier(None)
    assert ga.is_unavailable("flash38")
    assert avvisi == [("flash38", "J9")]


def test_fatale_vertex_flash31_non_marca(monkeypatch):
    from gemini_transport import TransportError
    monkeypatch.setattr(gemini_tts, "_resolve_backend", lambda mk=None: "vertex")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call",
                        lambda **kw: (_ for _ in ()).throw(TransportError("cred", kind="fatal")))
    with pytest.raises(gemini_tts.GeminiUnavailable):
        gemini_tts.synthesize("Ciao.", "gemini:flash31:Zephyr",
                              output_path=str(ga._path.parent / "o.pcm"))
    assert not ga.is_unavailable("flash31")


def test_offered_esclude_indisponibile(monkeypatch):
    monkeypatch.setenv("ABM_FLASH38_ENABLE", "true")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    gemini_tts._BACKEND = {}
    assert "flash38" in gemini_tts.offered_model_keys()
    ga.mark_unavailable("flash38", "403")
    assert "flash38" not in gemini_tts.offered_model_keys()
    gemini_tts._BACKEND = {}
