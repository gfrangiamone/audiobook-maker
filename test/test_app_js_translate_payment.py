from pathlib import Path

APP = (Path(__file__).resolve().parents[1] / "static" / "js" / "app.js").read_text(encoding="utf-8")


def test_start_translation_opens_param_modal():
    """startTranslation apre il popup parametrico con il contesto traduzione."""
    start = APP.find("function startTranslation")
    assert start >= 0
    snippet = APP[start:start + 2500]
    assert "_openPayModalCtx" in snippet
    assert "/api/paypal_create_order_translate" in snippet
    assert "voucherPurpose:'translate'" in snippet or "voucherPurpose: 'translate'" in snippet


def test_translate_modal_uses_translation_label():
    start = APP.find("function startTranslation")
    snippet = APP[start:start + 2500]
    assert "tr_pay_label" in snippet


def test_translate_submit_helper_present():
    assert "function _submitTranslation" in APP


def test_translate_no_longer_uses_legacy_show_payment_modal():
    """Il flusso traduzione non deve più usare _showPaymentModal (popup voucher-only)."""
    start = APP.find("function startTranslation")
    end = APP.find("function _trAutofillEmailLate")
    assert start >= 0 and end > start
    assert "_showPaymentModal" not in APP[start:end]


def test_inline_translate_coupon_functions_removed():
    assert "function validateCouponTr" not in APP
    assert "function showCouponTr" not in APP


def test_translate_loads_paypal_config():
    """Prima di aprire il popup, il flusso traduzione carica la config PayPal."""
    assert "function _loadLlmPaymentConfig" in APP
    start = APP.find("function startTranslation")
    snippet = APP[start:start + 2500]
    assert "_loadLlmPaymentConfig" in snippet
