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
    # bottone mobile naviga al deep link /t/<token>, non a /dl/
    assert "'/t/'" in body
    assert "window.location.href" in body
    # label mobile
    assert "transfer_cta_mobile" in body
    # _showTransferQr invoca il bind quando c'e' il token
    assert "_bindTransferButtonForMobile(" in APP_JS


def test_i18n_has_mobile_transfer_cta():
    i18n = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    # una entry per lingua (7 blocchi: it/en/fr/es/de/zh/hi)
    assert i18n.count("transfer_cta_mobile:") == 7
    assert "Sposta su AudioBook Maker & Player" in i18n
