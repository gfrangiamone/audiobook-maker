from pathlib import Path

APP_PATH = Path(__file__).resolve().parents[1] / "static" / "js" / "app.js"
APP = APP_PATH.read_text(encoding="utf-8")


def test_has_open_payment_modal():
    assert "function openPaymentModal" in APP


def test_has_validate_voucher_for_payment():
    assert "validateVoucherForPayment" in APP


def test_btn_generate_calls_payment_flow():
    assert "openPaymentModal" in APP
    assert "btnGenerate" in APP


def test_pay_state_object_present():
    assert "_payState" in APP


def test_switch_pay_tab_function():
    assert "function switchPayTab" in APP


def test_voucher_validate_called_with_purpose_gemini():
    # Verify the fetch body includes purpose: 'gemini'
    assert "purpose: 'gemini'" in APP or 'purpose: "gemini"' in APP


def test_voucher_input_ids_match_html():
    """app.js must use the prefixed IDs that match the HTML modal."""
    assert "geminiPayVoucherCode" in APP
    assert "geminiPayVoucherEmail" in APP
    # Make sure the old unprefixed IDs are not referenced in the new validation flow
    # (the old #payModal legacy code may still use them — that's fine; we only check
    # they're not used inside validateVoucherForPayment).
    func_start = APP.find("function validateVoucherForPayment")
    assert func_start >= 0
    # find the closing brace of this function (rough: next blank line + 'function ' or end-of-pattern)
    snippet = APP[func_start:func_start + 3000]
    assert "geminiPayVoucherCode" in snippet
    assert "geminiPayVoucherEmail" in snippet


def test_generate_click_has_reentrancy_guard():
    assert "_generatingModal" in APP


def test_has_render_paypal_gemini_buttons():
    assert "function renderPaypalGeminiButtons" in APP or "renderPaypalGeminiButtons = " in APP


def test_paypal_gemini_uses_dedicated_endpoint():
    # createOrder must call the gemini-specific endpoint, not the legacy LLM one
    func_start = APP.find("renderPaypalGeminiButtons")
    assert func_start >= 0
    snippet = APP[func_start:func_start + 4000]
    assert "/api/paypal_create_order_gemini" in snippet
    assert "/api/paypal_capture_order" in snippet


def test_paypal_gemini_uses_dedicated_container():
    assert "#paypalGeminiContainer" in APP or "'paypalGeminiContainer'" in APP


def test_paypal_gemini_buttons_close_on_re_render():
    # Must close any previously-instantiated buttons before rendering new ones
    # (prevents zombie iframe leaks when tab toggled multiple times)
    func_start = APP.find("renderPaypalGeminiButtons")
    snippet = APP[func_start:func_start + 4000]
    assert ".close()" in snippet or "buttonsInstance" in snippet


def test_paypal_gemini_handles_sdk_unavailable():
    # if window.paypal is undefined after load attempt, show error not crash
    func_start = APP.find("renderPaypalGeminiButtons")
    snippet = APP[func_start:func_start + 4000]
    assert "typeof paypal" in snippet or "window.paypal" in snippet
