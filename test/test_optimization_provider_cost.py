import payment


def test_optimization_provider_cost_basic():
    # Parametro unico blended in USD sui token TOTALI, convertito in EUR.
    payment.LLM_COST_USD_PER_MTOK = 0.18
    payment.USD_EUR_RATE = 0.86
    # 1M + 1M = 2M token totali -> 2 × 0.18 USD = 0.36 USD -> × 0.86 = 0.3096 EUR
    c = payment._optimization_provider_cost_eur(1_000_000, 1_000_000)
    assert round(c, 6) == round(2 * 0.18 * 0.86, 6)


def test_optimization_provider_cost_blends_prompt_and_completion():
    # Nessuna distinzione input/output: conta solo la somma dei token.
    payment.LLM_COST_USD_PER_MTOK = 0.18
    payment.USD_EUR_RATE = 0.86
    a = payment._optimization_provider_cost_eur(1_500_000, 500_000)
    b = payment._optimization_provider_cost_eur(500_000, 1_500_000)
    assert a == b


def test_optimization_provider_cost_zero_and_none():
    assert payment._optimization_provider_cost_eur(0, 0) == 0.0
    assert payment._optimization_provider_cost_eur(None, None) == 0.0


def test_optimization_provider_cost_constants_exist():
    assert isinstance(payment.LLM_COST_USD_PER_MTOK, float)
    assert isinstance(payment.USD_EUR_RATE, float)
