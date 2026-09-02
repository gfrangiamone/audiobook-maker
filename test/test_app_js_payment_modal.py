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


def test_voucher_validate_uses_context_purpose():
    """validateVoucherForPayment passa il purpose dal contesto, non hardcoded."""
    start = APP.find("function validateVoucherForPayment")
    assert start >= 0
    snippet = APP[start:start + 2000]
    assert "_payCtx.voucherPurpose" in snippet


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


def test_paypal_create_order_endpoint_from_context():
    """renderPaypalGeminiButtons usa l'endpoint dal contesto; la capture resta condivisa."""
    start = APP.find("function renderPaypalGeminiButtons")
    assert start >= 0
    snippet = APP[start:start + 4000]
    assert "_payCtx.paypal.endpoint" in snippet
    assert "_payCtx.paypal.buildBody" in snippet
    assert "/api/paypal_capture_order" in snippet


def test_gemini_create_endpoint_lives_in_builder():
    """L'endpoint create-order Gemini resta referenziato in openPaymentModal."""
    start = APP.find("function openPaymentModal")
    snippet = APP[start:start + 1500]
    assert "/api/paypal_create_order_gemini" in snippet


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


def test_paypal_sdk_loader_caches_in_flight_promise():
    """_loadPaypalSdk must reuse an in-flight promise to prevent duplicate script injection."""
    assert "_paypalSdkPromise" in APP


def test_paypal_capture_token_no_orderid_fallback():
    """onApprove must not silently fall back to data.orderID if payment_token missing."""
    # Locate the function body and verify the assignment line does NOT contain '|| data.orderID'
    func_start = APP.find("renderPaypalGeminiButtons")
    assert func_start >= 0
    snippet = APP[func_start:func_start + 4000]
    # The token assignment should NOT have the dead fallback
    assert "_payState.token = d.payment_token || data.orderID" not in snippet
    assert "_payState.token=d.payment_token||data.orderID" not in snippet
    # But it must still set the token from payment_token
    assert "d.payment_token" in snippet


def test_pay_ctx_object_present():
    assert "_payCtx" in APP


def test_open_pay_modal_ctx_function():
    assert "function _openPayModalCtx" in APP


def test_gemini_builder_sets_endpoint_and_purpose():
    """openPaymentModal costruisce il contesto Gemini con endpoint e purpose."""
    start = APP.find("function openPaymentModal")
    assert start >= 0
    snippet = APP[start:start + 1500]
    assert "/api/paypal_create_order_gemini" in snippet
    assert "voucherPurpose:'gemini'" in snippet or 'voucherPurpose: "gemini"' in snippet \
        or "voucherPurpose: 'gemini'" in snippet
    assert "_openPayModalCtx" in snippet


# ─────────── Ottimizzazione AI standalone (voci standard): modal condiviso ───────────

def test_llm_standalone_uses_shared_modal():
    """_showPaymentModal è un adapter sul modal condiviso Buono/PayPal:
    purpose 'llm' ed endpoint create-order dedicato all'ottimizzazione."""
    start = APP.find("function _showPaymentModal")
    assert start >= 0
    snippet = APP[start:start + 1500]
    assert "_openPayModalCtx" in snippet
    assert "voucherPurpose:'llm'" in snippet
    assert "/api/paypal_create_order" in snippet
    assert "onCancel" in snippet  # annullo -> resolve(null)


def test_llm_standalone_order_body_has_selected_chapters():
    """La create-order LLM passa i capitoli selezionati: il server ricalcola
    l'importo sullo stesso subset della stima."""
    start = APP.find("function _showPaymentModal")
    snippet = APP[start:start + 1500]
    assert "selected_chapters" in snippet


def test_legacy_voucher_only_modal_removed():
    """Il vecchio popup #payModal voucher-only non esiste più: niente ramo
    PayPal commentato né submit voucher legacy."""
    assert "PayPal SDK loading disabled" not in APP
    assert "payVoucherSubmit" not in APP
    assert "getElementById('payModal')" not in APP


def test_close_modal_fires_oncancel_once():
    """closePaymentModal notifica onCancel SOLO su chiusura senza conferma
    (flag _payConfirmed settato da onPayConfirm)."""
    assert "_payConfirmed" in APP
    start = APP.find("function closePaymentModal")
    assert start >= 0
    snippet = APP[start:start + 800]
    assert "onCancel" in snippet
    assert "_payConfirmed" in snippet
    start_c = APP.find("function onPayConfirm")
    snippet_c = APP[start_c:start_c + 600]
    assert "_payConfirmed = true" in snippet_c or "_payConfirmed=true" in snippet_c


def test_payment_happens_at_generate_not_at_toggle():
    """_fetchCostEstimate mostra solo la stima (nessun popup al toggle);
    il pagamento avviene in startCombinedGeneration col modal condiviso."""
    start = APP.find("async function _fetchCostEstimate")
    assert start >= 0
    end = APP.find("function _updateAiOptUI")
    snippet = APP[start:end]
    assert "_showPaymentModal" not in snippet
    assert "costEstimate" in snippet
    start_g = APP.find("async function startCombinedGeneration")
    snippet_g = APP[start_g:start_g + 4000]
    assert "_showPaymentModal" in snippet_g
    assert "_loadLlmPaymentConfig" in snippet_g


def test_pay_modal_opens_on_paypal_tab():
    """_openPayModalCtx deve aprire il popup sul pannello PayPal (metodo
    dominante), non su quello del buono."""
    assert "switchPayTab('paypal')" in APP
    assert "switchPayTab('voucher')" not in APP


def test_switch_pay_tab_syncs_aria_selected():
    """role=\"tab\": senza aggiornare aria-selected lo screen reader annuncia
    sempre la linguetta di default del markup."""
    body = APP[APP.index("function switchPayTab"):]
    body = body[:body.index(chr(10) + "function ", 1)]
    assert "aria-selected" in body
