"""Il tab "Voci PREMIUM" deve sparire davvero quando il JS lo nasconde.

Difetto trovato in locale: `_applyPremiumAvailability()` fa `btn.hidden=true`
quando la capability Gemini e' KO, ma il CSS dichiarava
`.tab-bar #tabPremiumBtn { display:inline-block }` con un selettore che vince
sulla regola UA `[hidden]{display:none}`. Il tab restava quindi cliccabile e
apriva un pannello con i dropdown Lingua e Voce vuoti — esattamente lo stato
"sembra rotta" che quella funzione esiste per evitare.

Lo stesso inciampo era gia' documentato nel CSS per `.form-row[hidden]`: e' un
errore che questo progetto ha gia' fatto una volta, quindi vale un test.
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "static" / "css" / "style.css").read_text(encoding="utf-8")
APP_JS = (ROOT / "static" / "js" / "app.js").read_text(encoding="utf-8")


def test_il_js_nasconde_il_tab_premium_con_l_attributo_hidden():
    """Premessa del test sotto: se un giorno il JS passasse a una classe, la
    regola CSS controllata qui non servirebbe piu' e questo assert lo dice."""
    assert re.search(r"tabPremiumBtn['\"]\)\s*;?[\s\S]{0,400}?btn\.hidden\s*=",
                     APP_JS), (
        "app.js non nasconde piu' #tabPremiumBtn tramite l'attributo hidden: "
        "rivedere anche la regola CSS coperta dal test successivo."
    )


def test_il_css_onora_hidden_sul_tab_premium():
    assert re.search(r"#tabPremiumBtn\[hidden\]\s*\{[^}]*display\s*:\s*none",
                     CSS), (
        "manca la regola che onora [hidden] su #tabPremiumBtn: il selettore "
        "con id che imposta `display:inline-block` batte la regola UA "
        "[hidden]{display:none}, quindi btn.hidden=true non nasconde nulla."
    )


def test_la_regola_hidden_viene_dopo_quella_che_imposta_display():
    """Stessa specificita' fra le due regole: vince l'ultima dichiarata."""
    pos_display = CSS.find("#tabPremiumBtn { display:inline-block")
    pos_hidden = CSS.find("#tabPremiumBtn[hidden]")
    assert pos_display != -1 and pos_hidden != -1
    assert pos_hidden > pos_display, (
        "la regola [hidden] deve stare DOPO quella che imposta display, "
        "altrimenti a parita' di specificita' perde."
    )
