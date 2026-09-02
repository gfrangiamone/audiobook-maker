import re
from pathlib import Path

APP_JS = Path("static/js/app.js").read_text(encoding="utf-8")


def test_transfer_qr_popup_links_to_get_app():
    m = re.search(r"function openTransferQrModal\([^)]*\)\{.*?\n}", APP_JS, re.DOTALL)
    assert m, "openTransferQrModal non trovata"
    body = m.group(0)
    # l'hint del popup è dentro un anchor verso /get-app
    assert "createElement('a')" in body
    assert "/get-app" in body
    # SOLO "AudioBook Maker & Player" è cliccabile: il popup splitta l'hint
    # sull'app-name e usa createTextNode per le parti non cliccabili.
    assert "AudioBook Maker & Player" in body
    assert "createTextNode" in body


def test_is_mobile_like_helper_present():
    assert "function _isMobileLike(" in APP_JS
    # ramo touch per iPad in UA-desktop
    assert "pointer:coarse" in APP_JS
    assert "maxTouchPoints" in APP_JS


def test_mobile_transfer_button_targets_t_deeplink():
    m = re.search(r"function _bindTransferButtonForMobile\([^)]*\)\{.*?\n}", APP_JS, re.DOTALL)
    assert m, "_bindTransferButtonForMobile non trovata"
    body = m.group(0)
    # il target (deep link app) e' costruito da _appOpenUrl, non piu' inline
    assert "_appOpenUrl(token)" in body
    assert "window.location.href" in body
    # label mobile
    assert "transfer_cta_mobile" in body
    # _showTransferQr invoca il bind quando c'e' il token
    assert "_bindTransferButtonForMobile(" in APP_JS
    # _appOpenUrl costruisce il path /t/<token> (https di base / fallback)
    a = re.search(r"function _appOpenUrl\([^)]*\)\{.*?\n}", APP_JS, re.DOTALL)
    assert a and "'/t/'" in a.group(0)


def test_app_open_url_android_intent_branch():
    m = re.search(r"function _appOpenUrl\([^)]*\)\{.*?\n}", APP_JS, re.DOTALL)
    assert m, "_appOpenUrl non trovata"
    body = m.group(0)
    # Android: intent:// (scheme=abm) con package + fallback https; bypassa la
    # soppressione same-origin degli App Links in Chrome.
    assert "intent://" in body
    assert "scheme=' + ABM_SCHEME" in body
    assert "ABM_ANDROID_PKG" in body
    assert "browser_fallback_url" in body
    # _bindTransferButtonForMobile usa _appOpenUrl (non piu' /t/ inline)
    assert "_appOpenUrl(token)" in APP_JS
    # ABM_SCHEME definito e uguale al custom scheme dell'app
    assert "ABM_SCHEME = 'abm'" in APP_JS


def test_ios_single_button_uses_scheme_and_label():
    # su iOS il bottone unico punta al custom scheme abm:// con label "Apri nell'app"
    assert "function _appSchemeUrl(" in APP_JS
    a = re.search(r"function _appSchemeUrl\([^)]*\)\{.*?\n}", APP_JS, re.DOTALL)
    assert a and "ABM_SCHEME + '://'" in a.group(0)
    assert "function _isIOSUA(" in APP_JS
    # il bind sceglie scheme vs intent/https in base a iOS, e la label di conseguenza
    b = re.search(r"function _bindTransferButtonForMobile\([^)]*\)\{.*?\n}", APP_JS, re.DOTALL)
    assert b, "_bindTransferButtonForMobile non trovata"
    body = b.group(0)
    assert "_isIOSUA()" in body
    assert "_appSchemeUrl(token)" in body
    assert "transfer_open_in_app" in body
    # nessun link secondario residuo
    assert "_addIosOpenInAppLink" not in APP_JS


def test_i18n_has_mobile_transfer_cta():
    i18n = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    # una entry per lingua (7 blocchi: it/en/fr/es/de/zh/hi)
    assert i18n.count("transfer_cta_mobile:") == 7
    assert "Sposta su AudioBook Maker & Player" in i18n
    # label secondaria iOS presente in tutti i 7 blocchi
    assert i18n.count("transfer_open_in_app:") == 7
    assert "Apri nell'app" in i18n


HTML_HEAD = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
CSS = Path("static/css/style.css").read_text(encoding="utf-8")


def test_transfer_button_moves_beside_cancel_when_email_confirmed():
    """Confermata l'email, il box sparisce e il bottone "Trasferisci sull'app"
    non deve restare centrato da solo sopra un annullo a tutta larghezza: viene
    spostato in #transferCancelSlot, a destra del bottone di annullo."""
    m = re.search(r"function _syncTransferBtnPlacement\([^)]*\)\{.*?\n}",
                  APP_JS, re.DOTALL)
    assert m, "_syncTransferBtnPlacement non trovata"
    body = m.group(0)
    assert "transferCancelSlot" in body
    assert "emailLateArea" in body and "notifyEmailLate" in body
    # Sposta il nodo (conserva QR gia' scaricato e handler), non lo ricrea.
    assert "appendChild" in body
    # Lo slot e' fratello di #cnA: sopravvive agli innerHTML fatti su #cnA.
    assert 'id="transferCancelSlot"' in HTML_HEAD
    assert 'class="cancel-transfer-row"' in HTML_HEAD
    assert HTML_HEAD.index('id="cnA"') < HTML_HEAD.index('id="transferCancelSlot"')
    assert ".cancel-transfer-row{display:flex" in CSS


def test_email_confirm_triggers_transfer_button_replacement():
    m = re.search(r"function _setEmailLateConfirm\([^)]*\)\{.*?\n}",
                  APP_JS, re.DOTALL)
    assert m, "_setEmailLateConfirm non trovata"
    assert "_syncTransferBtnPlacement" in m.group(0)
