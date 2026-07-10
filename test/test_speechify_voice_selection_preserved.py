"""Regressione: la voce/accento Speechify scelti dall'utente devono sopravvivere
ai rebuild dei dropdown premium.

Difetto (utente sceglie hugh_32 en-GB, la generazione parte con harper_32 en-US):
il dropdown accento `geminiAccent` e' CONDIVISO con Gemini. Quando il ramo Gemini
di updVoicesPremium (o _onPremiumModelChanged) invoca _updateAccentDropdown(),
il dropdown viene ripopolato con codici accento Gemini. Il successivo
_populateSpeechifyAccents() leggeva `prev` da acc.value (ora un codice Gemini),
non lo trovava in _SPEECHIFY_ACCENTS e resettava ad en-US; poi il ramo Simba di
updVoicesPremium ricostruiva la lista voci SENZA preservare la selezione,
azzerando la voce alla prima del locale (harper_32 per en-US).

Fix: due variabili di modulo (_speechifyAccentSel/_speechifyVoiceSel) sono la
fonte di verita' per accento e voce Speechify, aggiornate dagli onchange utente e
usate per ripristinare dopo ogni rebuild, indipendentemente dallo stato del DOM
condiviso.
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


def test_module_state_vars_declared():
    src = _app_js()
    assert "_speechifyAccentSel" in src, "manca la variabile di stato accento Speechify"
    assert "_speechifyVoiceSel" in src, "manca la variabile di stato voce Speechify"


def test_populate_accents_uses_persistent_state_not_only_dom():
    body = _func_body(_app_js(), "_populateSpeechifyAccents")
    # prev deve derivare dallo stato persistito, non solo da acc.value (clobberabile).
    assert "_speechifyAccentSel" in body, \
        "_populateSpeechifyAccents non usa lo stato accento persistito"
    # l'onchange deve aggiornare lo stato persistito.
    assert re.search(r"_speechifyAccentSel\s*=", body), \
        "_populateSpeechifyAccents non aggiorna lo stato accento persistito"


def test_upd_voices_premium_preserves_selected_voice_on_rebuild():
    body = _func_body(_app_js(), "updVoicesPremium")
    # Il ramo Simba deve salvare la voce prima del rebuild e ripristinarla dopo.
    assert "_speechifyVoiceSel" in body, \
        "updVoicesPremium non usa lo stato voce persistito nel ramo Simba"
    # Deve esserci un ripristino via .value dopo aver svuotato la select.
    idx_clear = body.find("sel.innerHTML=''")
    assert idx_clear != -1
    tail = body[idx_clear:]
    assert re.search(r"sel\.value\s*=\s*prevVoice", tail), \
        "updVoicesPremium non ripristina la voce selezionata dopo il rebuild"
