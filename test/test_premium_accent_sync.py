"""Regressione: la riga accento Simba deve comparire anche su un nuovo libro,
senza dover cambiare modello a mano.

Difetto: updModelsPremium() imposta il modello a Simba (default inglese) via
.value, che NON emette un evento 'change'; i controlli dipendenti dal modello
(riga accento/emozione/stile) vengono sincronizzati solo da _onPremiumModelChanged().
syncLanguageOptions() e switchAudioTab('premium') NON lo invocavano, quindi
ri-analizzando un secondo libro la riga accento restava nascosta finché l'utente
non cambiava modello.

Fix: entrambi i percorsi che (ri)popolano/mostrano i controlli premium devono
chiamare _onPremiumModelChanged() per allineare le righe al modello corrente.
"""
import os
import re


def _app_js():
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "static", "js", "app.js",
    )
    with open(os.path.abspath(path), "r", encoding="utf-8") as f:
        return f.read()


def _func_body(src, name):
    """Estrae grezzamente il corpo di `function name(...)` fino al bilanciamento
    delle graffe. Sufficiente per assert di presenza chiamata."""
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
    raise AssertionError("corpo funzione non bilanciato: " + name)


def test_sync_language_options_resyncs_premium_model():
    body = _func_body(_app_js(), "syncLanguageOptions")
    assert "_onPremiumModelChanged" in body, \
        "syncLanguageOptions non risincronizza i controlli dipendenti dal modello"


def test_switch_audio_tab_resyncs_premium_model():
    body = _func_body(_app_js(), "switchAudioTab")
    assert "_onPremiumModelChanged" in body, \
        "switchAudioTab non risincronizza i controlli premium all'ingresso nel tab"
