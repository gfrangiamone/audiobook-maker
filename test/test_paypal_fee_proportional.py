import audiobook_app as app
import gemini_tts


def _rates():
    return float(gemini_tts.PAYPAL_PERCENT_FEE), float(gemini_tts.PAYPAL_FIXED_FEE_EUR)


def test_single_service_full_fixed_fee():
    pct, fixed = _rates()
    # combined_total assente → fissa piena (comportamento storico invariato)
    fee = app._compute_paypal_fee_eur(2.00, "paypal")
    assert fee == round(2.00 * pct / 100.0 + fixed, 4)


def test_combined_split_sums_to_one_fixed_fee():
    pct, fixed = _rates()
    tts, llm = 2.00, 0.50
    total = tts + llm
    fee_tts = app._compute_paypal_fee_eur(tts, "paypal", combined_total_eur=total)
    fee_llm = app._compute_paypal_fee_eur(llm, "paypal", combined_total_eur=total)
    # la quota fissa è ripartita: le due fisse sommano a UNA fee fissa
    fixed_part = (fee_tts - tts * pct / 100.0) + (fee_llm - llm * pct / 100.0)
    assert round(fixed_part, 4) == round(fixed, 4)
    # e la percentuale è additiva sul totale
    pct_part = (tts + llm) * pct / 100.0
    assert round(fee_tts + fee_llm, 4) == round(pct_part + fixed, 4)


def test_voucher_zero_fee():
    assert app._compute_paypal_fee_eur(2.00, "voucher", combined_total_eur=2.50) == 0.0


def test_zero_combined_total_falls_back_to_full_fixed():
    pct, fixed = _rates()
    fee = app._compute_paypal_fee_eur(1.00, "paypal", combined_total_eur=0)
    assert fee == round(1.00 * pct / 100.0 + fixed, 4)
