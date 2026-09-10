"""Regressione: cambiando la lingua del libro, il modello del pannello Premium
deve essere ricostruito e risincronizzato.

Difetto (utente): premium=inglese -> modello Simba; poi il libro passa
all'italiano. La lingua veniva propagata al tab Premium ma il modello restava
'simba-3.2' (solo inglese), stato incompatibile con l'italiano.

Causa storica: l'onchange della combo lingua Standard propagava il valore alla
combo lingua Premium e chiamava solo updVoicesPremium(), senza ricostruire i
modelli ne' risincronizzare le righe che dipendono dal modello.

Da quando la lingua e' una proprieta' del libro le due combo non esistono piu':
la ricostruzione e' compito di applyBookLanguage(), che ripopola #vmPremium
dalla lista di modelli della cascata (dove Simba non compare per lingue non
inglesi) e richiama _onPremiumModelChanged().
"""
import os


def _app_js():
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "static", "js", "app.js",
    )
    with open(os.path.abspath(path), "r", encoding="utf-8") as f:
        return f.read()


def _func_body(src, name):
    """Corpo di `function name(...)` per bilanciamento di graffe."""
    start = src.index("function " + name)
    brace = src.index("{", start)
    depth = 0
    i = brace
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace:i + 1]
        i += 1
    raise AssertionError("blocco non bilanciato: " + name)


def test_lang_change_rebuilds_premium_model():
    body = _func_body(_app_js(), "applyBookLanguage")
    assert "esito.premium.models" in body, (
        "applyBookLanguage non ricostruisce i modelli premium: il modello Simba "
        "resterebbe selezionato anche per lingue non inglesi"
    )
    assert "_onPremiumModelChanged" in body, (
        "applyBookLanguage non risincronizza le righe dipendenti dal modello"
    )


def test_niente_piu_combo_lingua_premium():
    """La propagazione fra due combo non deve tornare: la fonte e' una sola."""
    src = _app_js()
    assert "getElementById('vlPremium')" not in _func_body(src, "applyBookLanguage")
    assert "let bookLangState=" in src
