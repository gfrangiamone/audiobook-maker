"""i18n completeness: new Premium/payment keys present in all 7 languages."""
from pathlib import Path
import re

I18N_PATH = Path("templates/_fragments/i18n_data.js")
NEW_KEYS = [
    "tab_voices_standard","tab_voices_premium","lbl_model","lbl_style_instruction",
    "cost_estimate_label","cost_free","cost_under_threshold",
    "pay_modal_title","pay_premium_voices","pay_text_ai_optimization","pay_total",
    "pay_tab_voucher","pay_tab_paypal","pay_voucher_code","pay_voucher_email",
    "pay_cancel","pay_confirm","pay_err_empty","pay_err_voucher_not_found",
    "pay_err_email_mismatch","pay_err_revoked","pay_err_insufficient",
    "pay_err_unknown","pay_err_network","pay_ok_remaining",
    "pay_paypal_unavailable","pay_paypal_captured","pay_paypal_capture_failed",
    "pay_paypal_error","p3_subtitle",
]
LANGS = ["it","en","fr","es","de","zh","hi"]


def _lang_block(text, lang):
    # match `lang:{ ... }` allowing nested braces by greedy depth-aware scan.
    # Search for `<lang>:{` or `"<lang>":{` (with optional whitespace) to avoid
    # matching `<lang>:"..."` value entries inside an inner `langs:{}` object.
    patterns = [
        re.compile(rf'(?:^|[,\s{{]){re.escape(lang)}\s*:\s*\{{', re.MULTILINE),
        re.compile(rf'(?:^|[,\s{{])"{re.escape(lang)}"\s*:\s*\{{', re.MULTILINE),
    ]
    m = None
    for pat in patterns:
        m = pat.search(text)
        if m:
            break
    if not m:
        return ""
    brace = text.rfind("{", m.start(), m.end())
    if brace < 0:
        return ""
    depth = 0
    end = brace
    for i in range(brace, len(text)):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    return text[brace:end]


def test_all_keys_in_all_langs():
    text = I18N_PATH.read_text(encoding="utf-8")
    missing = []
    for lang in LANGS:
        block = _lang_block(text, lang)
        assert block, f"language block {lang} not found"
        for k in NEW_KEYS:
            if f"{k}:" not in block and f'"{k}":' not in block:
                missing.append(f"{lang}.{k}")
    assert not missing, f"missing keys: {missing}"


def test_no_provider_names_in_premium_keys():
    """User-facing premium labels must not name AI providers."""
    text = I18N_PATH.read_text(encoding="utf-8")
    for lang in LANGS:
        block = _lang_block(text, lang)
        # Extract the values of premium-related keys
        for k in ("tab_voices_premium", "pay_premium_voices", "pay_text_ai_optimization"):
            m = re.search(rf'\b{k}\s*:\s*"([^"]*)"', block)
            if m:
                val = m.group(1)
                low = val.lower()
                assert "gemini" not in low, f"{lang}.{k} contains 'Gemini': {val!r}"
                assert "deepseek" not in low, f"{lang}.{k} contains 'DeepSeek': {val!r}"
                assert "openai" not in low, f"{lang}.{k} contains 'OpenAI': {val!r}"
                assert "google" not in low, f"{lang}.{k} contains 'Google': {val!r}"
                assert "anthropic" not in low, f"{lang}.{k} contains 'Anthropic': {val!r}"
