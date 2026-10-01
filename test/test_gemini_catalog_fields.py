"""Helper per modello guidati dal catalogo GEMINI_MODELS."""
import pytest

import gemini_tts


def test_flash25_rimosso_dal_catalogo():
    assert "flash25" not in gemini_tts.GEMINI_MODELS
    with pytest.raises(ValueError):
        gemini_tts.parse_voice_id("gemini:flash25:Zephyr")


def test_campi_catalogo_presenti_per_ogni_modello():
    richiesti = {"env_prefix", "margin_default", "audio_tokens_per_second",
                 "default_rpm", "default_rpd", "http_timeout_ms",
                 "preview_timeout_sec", "backends_allowed",
                 "mark_unavailable_on_fatal"}
    for mk, m in gemini_tts.GEMINI_MODELS.items():
        assert richiesti <= set(m), mk


def test_flash31_valori_storici(monkeypatch):
    for env in ("ABM_GEMINI_31FLASH_MARGIN_PERCENT",
                "ABM_GEMINI_MIN_INTERVAL_FLASH31_MS", "ABM_GEMINI_RPM_FLASH31",
                "ABM_GEMINI_RPD_FLASH31", "ABM_GEMINI_HTTP_TIMEOUT_MS_FLASH31",
                "ABM_GEMINI_PREVIEW_TIMEOUT_SEC_FLASH31",
                "ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH31",
                "ABM_GEMINI_AUDIO_TOKENS_PER_SECOND"):
        monkeypatch.delenv(env, raising=False)
    assert gemini_tts.get_margin_percent("flash31") == 25.0
    assert gemini_tts._min_interval_ms("flash31") == 0
    assert gemini_tts._rpd_cap("flash31") == 0
    assert gemini_tts._http_timeout_ms("flash31") == 60000
    assert gemini_tts.preview_timeout_sec("flash31") == 65
    assert gemini_tts._audio_tokens_per_second("flash31") == 25.0


def test_alias_min_interval_flash31_rispettato(monkeypatch):
    monkeypatch.delenv("ABM_GEMINI_RPM_FLASH31", raising=False)
    monkeypatch.setenv("ABM_GEMINI_MIN_INTERVAL_FLASH31_MS", "200")
    assert gemini_tts._min_interval_ms("flash31") == 200


def test_rpm_vince_sull_alias(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_MIN_INTERVAL_FLASH31_MS", "200")
    monkeypatch.setenv("ABM_GEMINI_RPM_FLASH31", "600")
    assert gemini_tts._min_interval_ms("flash31") == 100


def test_margine_modello_ignoto():
    with pytest.raises(ValueError):
        gemini_tts.get_margin_percent("flash25")


def test_usage_e_rpd_iterano_il_catalogo():
    u = gemini_tts._empty_usage()
    assert set(u["by_model"]) == set(gemini_tts.GEMINI_MODELS)
    gemini_tts._rpd_cache = None
    saved = gemini_tts._rpd_file_path
    gemini_tts._rpd_file_path = None
    try:
        r = gemini_tts._rpd_load()
    finally:
        gemini_tts._rpd_file_path = saved
        gemini_tts._rpd_cache = None
    for mk in gemini_tts.GEMINI_MODELS:
        assert r[mk] == 0


def test_usage_legacy_flash25_resta_leggibile():
    data = {"by_model": {"flash25": {"chars": 7}}}
    gemini_tts._ensure_reconciliation_fields(data)
    assert data["by_model"]["flash25"]["chars"] == 7
    for mk in gemini_tts.GEMINI_MODELS:
        assert data["by_model"][mk]["chars"] == 0
