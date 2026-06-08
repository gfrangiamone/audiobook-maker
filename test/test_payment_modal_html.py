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


def test_no_duplicate_id_with_old_modal():
    """I nuovi ID del payment modal non devono collidere con il vecchio payModal."""
    import re
    for old_shared_id in ('payVoucherCode', 'payVoucherEmail'):
        # Il vecchio payModal aveva questi ID. Il nuovo modal NON deve usarli.
        # Estrai il blocco del nuovo modal e verifica che NON contengano questi ID
        m = re.search(r'id="geminiPayModal"(.*?)</div>\s*</div>\s*</div>', HTML, re.DOTALL)
        assert m, "geminiPayModal block not found"
        block = m.group(0)
        assert f'id="{old_shared_id}"' not in block, \
            f"new modal must not reuse old payModal id '{old_shared_id}'"


def test_new_modal_uses_prefixed_ids():
    """Nuovi ID dentro #geminiPayModal usano prefisso 'geminiPay'."""
    import re
    m = re.search(r'id="geminiPayModal"(.*?)</div>\s*</div>\s*</div>', HTML, re.DOTALL)
    assert m, "geminiPayModal block not found"
    block = m.group(0)
    assert 'id="geminiPayVoucherCode"' in block
    assert 'id="geminiPayVoucherEmail"' in block
    assert 'id="geminiPayModalTitle"' in block


def test_modal_aria_labelledby_points_to_new_title():
    import re
    m = re.search(r'id="geminiPayModal"[^>]*aria-labelledby="(\w+)"', HTML)
    assert m, "aria-labelledby not found on modal"
    assert m.group(1) == 'geminiPayModalTitle'


def test_tabs_have_aria_controls():
    import re
    # estrai i tag dei due tab
    m1 = re.search(r'id="payTabVoucher"[^>]*', HTML)
    m2 = re.search(r'id="payTabPaypal"[^>]*', HTML)
    assert m1, "payTabVoucher not found"
    assert m2, "payTabPaypal not found"
    assert 'aria-controls="payPanelVoucher"' in m1.group(0)
    assert 'aria-controls="payPanelPaypal"' in m2.group(0)


def test_extra_ids_present():
    for needed in ('payLineLlm', 'payVoucherError', 'payPaypalError', 'btnPayCancel2'):
        assert f'id="{needed}"' in HTML, f"required id missing: {needed}"


def test_css_uses_correct_variables():
    """CSS payment modal deve usare --ac (non --accent) e --srf2 (non --bgm)."""
    # Estrai il blocco CSS del payment modal
    marker_start = "/* ── Payment modal"
    idx = CSS.find(marker_start)
    assert idx != -1, "payment modal CSS block not found"
    css_block = CSS[idx:]
    assert "var(--accent" not in css_block, "do not use --accent; use --ac"
    assert "var(--bgm" not in css_block, "do not use --bgm; use --srf2"
    assert "var(--ac" in css_block, "must reference --ac for accent"


def test_modal_zindex_distinct():
    """z-index del nuovo backdrop non deve essere 1000 (collide con .modal-overlay)."""
    marker_start = "/* ── Payment modal"
    idx = CSS.find(marker_start)
    assert idx != -1, "payment modal CSS block not found"
    css_block = CSS[idx:]
    import re
    m = re.search(r'\.modal-backdrop\s*\{[^}]*z-index:\s*(\d+)', css_block)
    assert m, ".modal-backdrop z-index not found"
    z = int(m.group(1))
    assert z != 1000, "z-index 1000 collides with .modal-overlay"


def test_pay_line_labels_have_ids():
    """Le etichette delle pay-line devono avere id per il rendering dal contesto."""
    assert 'id="payLineGeminiLabel"' in HTML
    assert 'id="payLineLlmLabel"' in HTML
