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
