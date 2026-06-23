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
