import importlib


def _fresh(monkeypatch, ci=None, co=None):
    if ci is not None:
        monkeypatch.setenv("ABM_TRANSLATE_COST_IN_EUR_PER_MTOK", ci)
    if co is not None:
        monkeypatch.setenv("ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK", co)
    import payment
    importlib.reload(payment)
    return payment


def test_default_rates_gemini_flash(monkeypatch):
    monkeypatch.delenv("ABM_TRANSLATE_COST_IN_EUR_PER_MTOK", raising=False)
    monkeypatch.delenv("ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK", raising=False)
    pay = _fresh(monkeypatch)
    assert pay.TRANSLATE_COST_IN_EUR_PER_MTOK == 0.28
    assert pay.TRANSLATE_COST_OUT_EUR_PER_MTOK == 2.30


def test_cost_math(monkeypatch):
    pay = _fresh(monkeypatch, ci="1.0", co="2.0")
    # 1M input @1.0 + 0.5M output @2.0 = 1.0 + 1.0 = 2.0
    assert pay._translation_provider_cost_eur(1_000_000, 500_000) == 2.0


def test_cost_handles_none_and_zero(monkeypatch):
    pay = _fresh(monkeypatch, ci="1.0", co="2.0")
    assert pay._translation_provider_cost_eur(None, None) == 0.0
    assert pay._translation_provider_cost_eur(0, 0) == 0.0


def test_comma_decimal_env(monkeypatch):
    pay = _fresh(monkeypatch, ci="0,30", co="2,50")
    assert pay.TRANSLATE_COST_IN_EUR_PER_MTOK == 0.30
    assert pay.TRANSLATE_COST_OUT_EUR_PER_MTOK == 2.50


def test_fallback_role_without_rates_uses_blended(monkeypatch):
    monkeypatch.delenv("ABM_TRANSLATE_FALLBACK_COST_IN_EUR_PER_MTOK", raising=False)
    monkeypatch.delenv("ABM_TRANSLATE_FALLBACK_COST_OUT_EUR_PER_MTOK", raising=False)
    pay = _fresh(monkeypatch, ci="1.0", co="2.0")
    assert pay._translation_provider_cost_eur(1_000_000, 500_000, role="fallback") == \
        pay._optimization_provider_cost_eur(1_000_000, 500_000)


def test_fallback_role_own_rates(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_COST_IN_EUR_PER_MTOK", "0,5")
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_COST_OUT_EUR_PER_MTOK", "4")
    pay = _fresh(monkeypatch, ci="1.0", co="2.0")
    # 1M @0.5 + 0.5M @4 = 2.5; il primario resta 1M @1 + 0.5M @2 = 2.0
    assert pay._translation_provider_cost_eur(1_000_000, 500_000, role="fallback") == 2.5
    assert pay._translation_provider_cost_eur(1_000_000, 500_000) == 2.0
