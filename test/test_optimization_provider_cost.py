import payment


def test_optimization_provider_cost_basic():
    # 1M input @ IN rate + 1M output @ OUT rate
    payment.LLM_COST_IN_EUR_PER_MTOK = 0.28
    payment.LLM_COST_OUT_EUR_PER_MTOK = 1.10
    c = payment._optimization_provider_cost_eur(1_000_000, 1_000_000)
    assert round(c, 6) == round(0.28 + 1.10, 6)


def test_optimization_provider_cost_zero_and_none():
    assert payment._optimization_provider_cost_eur(0, 0) == 0.0
    assert payment._optimization_provider_cost_eur(None, None) == 0.0


def test_optimization_provider_cost_constants_exist():
    assert isinstance(payment.LLM_COST_IN_EUR_PER_MTOK, float)
    assert isinstance(payment.LLM_COST_OUT_EUR_PER_MTOK, float)
