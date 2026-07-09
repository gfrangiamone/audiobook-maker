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
