"""Test statici sul markup del modal di pagamento."""
from pathlib import Path

HTML = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
CSS = Path("static/css/style.css").read_text(encoding="utf-8")


def test_modal_exists():
    assert 'id="geminiPayModal"' in HTML


def test_modal_has_voucher_tab():
    assert 'id="payTabVoucher"' in HTML
    assert 'id="payVoucherCode"' in HTML


def test_modal_has_paypal_tab():
    assert 'id="payTabPaypal"' in HTML
    assert 'id="paypalGeminiContainer"' in HTML


def test_modal_has_total_display():
    assert 'id="payModalTotal"' in HTML


def test_modal_has_confirm_cancel():
    assert 'id="btnPayConfirm"' in HTML
    assert 'id="btnPayCancel"' in HTML


def test_modal_starts_hidden():
    """Modal deve essere hidden di default — apertura demandata al JS."""
    import re
    m = re.search(r'id="geminiPayModal"[^>]*', HTML)
    assert m, "modal not found"
    assert 'hidden' in m.group(0), "modal must start with hidden attribute"


def test_modal_no_provider_names_visible():
    """Regola di branding: l'UI utente non deve nominare i provider AI/TTS."""
    # Estrai solo il blocco del modal
    import re
    m = re.search(r'id="geminiPayModal"(.*?)</div>\s*</div>\s*</div>',
                  HTML, re.DOTALL)
    assert m, "modal block not extracted"
    block = m.group(0)
    # Stringhe ASCII visibili (tra > e <) non devono contenere nomi provider
    visible_texts = re.findall(r'>([^<]+)<', block)
    joined = ' '.join(visible_texts).lower()
    for forbidden in ('gemini', 'deepseek', 'google tts'):
        assert forbidden not in joined, f"forbidden provider name visible: {forbidden}"


def test_css_rules_present():
    assert '.payment-modal' in CSS
    assert '.pay-tabs' in CSS
    assert '.modal-backdrop' in CSS
