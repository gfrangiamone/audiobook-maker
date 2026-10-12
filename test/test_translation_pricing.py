# test/test_translation_pricing.py
import importlib
import pytest


@pytest.fixture
def pay(monkeypatch):
    """payment ricaricato con env di default note."""
    monkeypatch.setenv("ABM_TRANSLATE_COST", "3.0")
    monkeypatch.setenv("ABM_TRANSLATE_MIN_COST", "1.5")
    monkeypatch.setenv("ABM_LLM_RATE_EUR_PER_MCHAR", "1.10")
    monkeypatch.setenv("ABM_LLM_FREE_THRESHOLD_EUR", "0.50")
    import payment
    importlib.reload(payment)
    yield payment
    importlib.reload(payment)  # ripristina (env tornano com'erano)


def test_small_book_is_free(pay):
    # 100k chars: raw = 0.30 ≤ 0.50 → gratis
    est = pay._estimate_translation_cost_eur(100_000, optimize=False)
    assert est["raw_eur"] == 0.30
    assert est["requires_payment"] is False
    assert est["due_eur"] == 0.0


def test_floor_applies_when_paid(pay):
    # 300k chars: raw = 0.90 > 0.50 → dovuto = max(0.90, 1.5) = 1.5
    est = pay._estimate_translation_cost_eur(300_000, optimize=False)
    assert est["requires_payment"] is True
    assert est["due_eur"] == 1.5


def test_large_book_above_floor(pay):
    # 1M chars: raw = 3.0 → dovuto 3.0
    est = pay._estimate_translation_cost_eur(1_000_000, optimize=False)
    assert est["due_eur"] == 3.0


def test_optimize_adds_llm_rate(pay):
    # 1M chars + opt: raw = 3.0 + 1.10 = 4.10
    est = pay._estimate_translation_cost_eur(1_000_000, optimize=True)
    assert est["raw_eur"] == 4.10
    assert est["due_eur"] == 4.10


def test_optimize_counts_toward_free_threshold(pay):
    # 130k chars + opt: raw = 0.39 + 0.143 = 0.53 > 0.50 → si paga, floor 1.5
    est = pay._estimate_translation_cost_eur(130_000, optimize=True)
    assert est["requires_payment"] is True
    assert est["due_eur"] == 1.5


def test_comma_decimal_env(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_COST", "3,5")
    monkeypatch.setenv("ABM_TRANSLATE_MIN_COST", "1,5")
    import payment
    importlib.reload(payment)
    assert payment.TRANSLATE_RATE_EUR_PER_MCHAR == 3.5
    assert payment.TRANSLATE_MIN_COST_EUR == 1.5
    monkeypatch.delenv("ABM_TRANSLATE_COST")
    monkeypatch.delenv("ABM_TRANSLATE_MIN_COST")
    importlib.reload(payment)


# Scritture non latine: un carattere vale piu' token (stessa tabella della
# stima token del TTS Gemini). Job qkLGg8 (ja, 228k car., +AI): pagato 1,14 EUR
# con 0,94 EUR di costo provider; le traduzioni da ja costano ~2.5x il latino.
@pytest.mark.parametrize("lang", ["ja", "zh", "ko", "ja-JP", "ZH", "zh_CN",
                                  "jpn", "zho", "chi", "kor", "cmn", "yue"])
def test_cjk_source_weighs_chars_by_token_ratio(pay, lang):
    est = pay._estimate_translation_cost_eur(1_000_000, source_lang=lang)
    assert est["chars"] == 1_000_000
    assert est["billable_chars"] == 2_666_667
    assert est["raw_eur"] == 8.0
    assert est["due_eur"] == 8.0


def test_cjk_weight_applies_to_optimization_too(pay):
    est = pay._estimate_translation_cost_eur(228_530, optimize=True, source_lang="ja")
    assert est["raw_eur"] == round(609_413 / 1e6 * (3.0 + 1.10), 2)


@pytest.mark.parametrize("lang,weight", [
    ("ru", 1.3), ("rus", 1.3), ("uk", 1.3), ("ru-RU", 1.3),
    ("hi", 1.65), ("hin", 1.65), ("ar", 1.95), ("ara", 1.95),
    ("th", 2.0), ("tha", 2.0)])
def test_other_scripts_use_measured_weight(pay, lang, weight):
    est = pay._estimate_translation_cost_eur(1_000_000, source_lang=lang)
    assert est["billable_chars"] == round(1_000_000 * weight)
    assert est["due_eur"] == round(3.0 * weight, 2)


@pytest.mark.parametrize("lang", ["en", "it", "", None, "xx", "eng", "fr-FR"])
def test_latin_or_unknown_source_is_unweighted(pay, lang):
    est = pay._estimate_translation_cost_eur(1_000_000, source_lang=lang)
    assert est["billable_chars"] == 1_000_000
    assert est["due_eur"] == 3.0


def test_cjk_can_cross_free_threshold(pay):
    # 100k car. latini restano gratis (0.30); in giapponese valgono 0.80.
    assert pay._estimate_translation_cost_eur(100_000, source_lang="en")["requires_payment"] is False
    est = pay._estimate_translation_cost_eur(100_000, source_lang="ja")
    assert est["requires_payment"] is True
    assert est["due_eur"] == 1.5


def test_job_estimate_uses_book_language(pay):
    class _Info:
        language = "ja"
    est = pay.translation_estimate_for_job({"info": _Info()}, 1_000_000)
    assert est["due_eur"] == 8.0
    assert pay.translation_estimate_for_job({}, 1_000_000)["due_eur"] == 3.0
