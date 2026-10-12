"""Listino fisso €/ora di audio (prezzo) e tariffe di costo reale per backend."""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "0")
    for env in ("ABM_GEMINI_31FLASH_EUR_PER_AUDIO_HOUR",
                "ABM_GEMINI_38FLASH_EUR_PER_AUDIO_HOUR",
                "ABM_GEMINI_CHARS_PER_SEC_IT", "ABM_GEMINI_CHARS_PER_SEC_ZH"):
        monkeypatch.delenv(env, raising=False)
    yield
    gemini_tts._BACKEND = {}


def _cf_configured(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")


class _Ch:
    def __init__(self, t):
        self.text = t


# --- costo reale per backend (contabilita') ---------------------------------

def test_flash31_carries_the_cloudflare_rates():
    m = gemini_tts.GEMINI_MODELS["flash31"]
    assert m["cf_input_usd_per_mtok"] == pytest.approx(0.75)
    assert m["cf_output_usd_per_mtok"] == pytest.approx(12.00)


def test_actual_rates_follow_the_executing_backend(monkeypatch):
    monkeypatch.setenv("ABM_CF_CREDIT_TOPUP_FEE", "0.05")
    assert gemini_tts.actual_rates("flash31", "cloudflare") == \
        pytest.approx((0.7875, 12.60))
    assert gemini_tts.actual_rates("flash31", "vertex") == \
        pytest.approx((1.00, 20.00))
    assert gemini_tts.actual_rates("flash31", "apikey") == \
        pytest.approx((1.00, 20.00))


# --- listino €/ora -----------------------------------------------------------

def test_tariffe_di_listino_per_modello():
    assert gemini_tts.eur_per_audio_hour("flash31") == pytest.approx(2.22)
    assert gemini_tts.eur_per_audio_hour("flash38") == pytest.approx(3.25)


def test_tariffa_da_env(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_31FLASH_EUR_PER_AUDIO_HOUR", "2.40")
    assert gemini_tts.eur_per_audio_hour("flash31") == pytest.approx(2.40)
    monkeypatch.setenv("ABM_GEMINI_31FLASH_EUR_PER_AUDIO_HOUR", "0")
    assert gemini_tts.eur_per_audio_hour("flash31") == pytest.approx(2.22)


def test_tariffa_modello_ignoto():
    with pytest.raises(ValueError):
        gemini_tts.eur_per_audio_hour("flash25")


def test_prezzo_e_ore_per_tariffa():
    p = gemini_tts.compute_user_price_eur(3600.0, "flash31")
    assert p["list_price_eur"] == pytest.approx(2.22)
    assert p["user_price_eur"] == pytest.approx(2.22)
    assert p["audio_hours"] == pytest.approx(1.0)
    assert p["is_free"] is False
    p38 = gemini_tts.compute_user_price_eur(1800.0, "flash38")
    assert p38["list_price_eur"] == pytest.approx(round(3.25 / 2, 2))


def test_sotto_soglia_e_gratis_ma_il_listino_resta():
    p = gemini_tts.compute_user_price_eur(600.0, "flash31")  # 0.37 EUR
    assert p["is_free"] is True
    assert p["user_price_eur"] == 0.0
    assert p["list_price_eur"] == pytest.approx(0.37)


def test_prezzo_non_dipende_dal_backend_ne_dall_iva(monkeypatch):
    base = gemini_tts.compute_user_price_eur(7200.0, "flash31")
    _cf_configured(monkeypatch)
    gemini_tts._set_backend("flash31", "vertex")
    monkeypatch.setenv("ABM_GEMINI_VAT_PERCENT", "22")
    monkeypatch.setitem(gemini_tts.GEMINI_MODELS["flash31"], "output_usd_per_mtok", 99.0)
    assert gemini_tts.compute_user_price_eur(7200.0, "flash31") == base


def test_chiavi_del_prezzo():
    p = gemini_tts.compute_user_price_eur(10.0, "flash31")
    assert set(p) == {"audio_seconds", "audio_hours", "eur_per_audio_hour",
                      "list_price_eur", "user_price_eur", "is_free",
                      "free_threshold_eur"}


# --- secondi di listino: tabella fissa per lingua ---------------------------

def test_tabella_car_s_per_lingua_e_override(monkeypatch):
    assert gemini_tts.list_chars_per_second("it") == gemini_tts.LANG_BASELINE_RATE["it"]
    assert gemini_tts.list_chars_per_second("zh") == gemini_tts.LANG_BASELINE_RATE["zh"]
    monkeypatch.setenv("ABM_GEMINI_CHARS_PER_SEC_IT", "12.0")
    assert gemini_tts.list_chars_per_second("it") == 12.0
    monkeypatch.setenv("ABM_GEMINI_CHARS_PER_SEC_IT", "-1")
    assert gemini_tts.list_chars_per_second("it") == gemini_tts.LANG_BASELINE_RATE["it"]


def test_il_cinese_costa_di_piu_a_parita_di_caratteri():
    testo = "x" * 14600
    it = gemini_tts.list_audio_seconds(testo, "it")
    zh = gemini_tts.list_audio_seconds(testo, "zh")
    assert it == pytest.approx(1000.0)
    assert zh > it * 3


def test_la_velocita_scala_i_secondi_di_listino():
    testo = "x" * 14600
    normale = gemini_tts.list_audio_seconds(testo, "it", rate_pct="+0%")
    lento = gemini_tts.list_audio_seconds(testo, "it", rate_pct="-20%")
    veloce = gemini_tts.list_audio_seconds(testo, "it", rate_pct=20)
    assert lento == pytest.approx(normale / 0.8)
    assert veloce == pytest.approx(normale / 1.2)


def test_il_listino_ignora_il_rate_empirico(monkeypatch):
    # Il log dei campioni muove la stima di COSTO, mai il prezzo.
    chs = [_Ch("Questo e' un capitolo di prova. " * 300)]
    base = gemini_tts.estimate_book_cost(chs, "gemini:flash31:Kore", language="it")
    monkeypatch.setattr(gemini_tts, "get_empirical_rate", lambda *a, **k: 7.0)
    dopo = gemini_tts.estimate_book_cost(chs, "gemini:flash31:Kore", language="it")
    assert dopo["list_price_eur"] == base["list_price_eur"]
    assert dopo["audio_seconds_est"] == base["audio_seconds_est"]
    assert dopo["audio_seconds_cost_est"] > base["audio_seconds_cost_est"]
    assert dopo["google_cost_eur"] > base["google_cost_eur"]


def test_estimate_book_cost_quota_sul_listino():
    chs = [_Ch("a" * 14600)]  # 1000 s in italiano
    est = gemini_tts.estimate_book_cost(chs, "gemini:flash31:Kore", language="it")
    assert est["audio_seconds_est"] == pytest.approx(1000.0)
    assert est["eur_per_audio_hour"] == pytest.approx(2.22)
    assert est["list_price_eur"] == pytest.approx(round(1000 / 3600 * 2.22, 2))
    assert est["user_price_eur"] == est["list_price_eur"]
    assert "margin_percent" not in est
