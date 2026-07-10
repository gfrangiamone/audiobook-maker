import importlib
import speechify_tts


def test_is_available_gated_by_key(monkeypatch):
    monkeypatch.delenv("ABM_SPEECHIFY_API_KEY", raising=False)
    assert speechify_tts.is_available() is False
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    assert speechify_tts.is_available() is True


def test_config_defaults(monkeypatch):
    for k in ("ABM_SPEECHIFY_MAX_CONCURRENCY", "ABM_SPEECHIFY_PER_JOB_CONCURRENCY",
              "ABM_SPEECHIFY_COST_USD_PER_MCHAR", "ABM_SPEECHIFY_MARGIN_PERCENT",
              "ABM_SPEECHIFY_FREE_THRESHOLD_EUR"):
        monkeypatch.delenv(k, raising=False)
    assert speechify_tts.max_concurrency() == 3
    assert speechify_tts.per_job_concurrency() == 1
    assert speechify_tts.cost_usd_per_mchar() == 11.18
    assert speechify_tts.margin_percent() == 60.0
    assert speechify_tts.free_threshold_eur() == 0.50


def test_config_overrides(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "5")
    monkeypatch.setenv("ABM_SPEECHIFY_PER_JOB_CONCURRENCY", "2")
    assert speechify_tts.max_concurrency() == 5
    assert speechify_tts.per_job_concurrency() == 2


def test_concurrency_floor_at_one(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_MAX_CONCURRENCY", "0")
    monkeypatch.setenv("ABM_SPEECHIFY_PER_JOB_CONCURRENCY", "-3")
    assert speechify_tts.max_concurrency() == 1
    assert speechify_tts.per_job_concurrency() == 1


def test_price_zero_chars_is_free():
    p = speechify_tts.compute_user_price_eur(0)
    assert p["user_price_eur"] == 0.0
    assert p["is_free"] is True


def test_price_matches_formula(monkeypatch):
    for k, v in {
        "ABM_SPEECHIFY_COST_USD_PER_MCHAR": "11.18",
        "ABM_SPEECHIFY_MARGIN_PERCENT": "60",
        "ABM_SPEECHIFY_FREE_THRESHOLD_EUR": "0.50",
        "ABM_GEMINI_USD_EUR_RATE": "0.86",
        "ABM_GEMINI_PAYPAL_FIXED_FEE_EUR": "0.34",
        "ABM_GEMINI_PAYPAL_PERCENT_FEE": "3.4",
    }.items():
        monkeypatch.setenv(k, v)
    chars = 200_000
    cost_usd = chars / 1e6 * 11.18
    base = cost_usd * 0.86 * 1.60
    gross = (base + 0.34) / (1 - 3.4 / 100)
    expected = round(gross, 2)
    p = speechify_tts.compute_user_price_eur(chars)
    assert p["user_price_eur"] == expected
    assert p["is_free"] is False


def test_estimate_book_cost_sums_chapters(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_COST_USD_PER_MCHAR", "11.18")

    class _Ch:
        def __init__(self, text):
            self.text = text

    chapters = [_Ch("a" * 100_000), _Ch("b" * 100_000)]
    est = speechify_tts.estimate_book_cost(chapters, language="en")
    assert est["chars_total"] == 200_000
    assert est["chars_per_chapter"] == [100_000, 100_000]
    assert est["model_key"] == "simba-3.2"
    assert est["user_price_eur"] == speechify_tts.compute_user_price_eur(200_000)["user_price_eur"]
