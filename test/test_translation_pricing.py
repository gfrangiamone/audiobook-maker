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
