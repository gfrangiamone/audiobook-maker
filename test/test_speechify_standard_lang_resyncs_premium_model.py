"""Regressione: cambiando lingua dal pannello Voci Standard, il modello del
pannello Premium deve essere ricostruito e risincronizzato.

Difetto (utente): premium=inglese -> modello Simba; poi Standard -> italiano.
La lingua italiana viene propagata a #vlPremium ma il modello resta 'simba-3.2'
(solo inglese), stato incompatibile con l'italiano.

Causa: l'onchange di #vl (in fillLangs) propagava la lingua a #vlPremium e
chiamava solo updVoicesPremium(), senza updModelsPremium()/_onPremiumModelChanged().

Fix: quando la lingua è compatibile col catalogo premium, l'handler deve
ricostruire i modelli (Simba non riproposto per lingue non-EN) e risincronizzare
le righe dipendenti dal modello, come già fanno il gestore di #vlPremium e
syncLanguageOptions.
"""
import os


def _app_js():
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "static", "js", "app.js",
    )
    with open(os.path.abspath(path), "r", encoding="utf-8") as f:
        return f.read()


def _vl_onchange_vlpremium_block(src):
    """Ritorna il blocco `if(dst){...}` che gestisce la propagazione a
    #vlPremium dentro l'onchange di #vl (fillLangs)."""
    anchor = src.index("const dst=document.getElementById('vlPremium')")
    open_brace = src.index("if(dst){", anchor) + len("if(dst)")
    depth = 0
    i = open_brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_brace:i + 1]
        i += 1
    raise AssertionError("blocco if(dst) non bilanciato")


def test_standard_lang_change_rebuilds_premium_model():
    block = _vl_onchange_vlpremium_block(_app_js())
    assert "updModelsPremium" in block, (
        "l'onchange di #vl non ricostruisce i modelli premium: il modello Simba "
        "resterebbe selezionato anche per lingue non inglesi"
    )
    assert "_onPremiumModelChanged" in block, (
        "l'onchange di #vl non risincronizza le righe dipendenti dal modello"
    )
