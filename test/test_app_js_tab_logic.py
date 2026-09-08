import re
from pathlib import Path

APP_JS = Path("static/js/app.js").read_text(encoding="utf-8")


def _estrai_funzione(src, nome):
    """Corpo di `function nome(...)`, per bilanciamento di graffe.

    Serve dove il confine della funzione non e' ricavabile da una `}` a
    inizio riga: app.js e' scritto compatto e le funzioni annidano.
    """
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    assert m, "funzione %s non trovata" % nome
    apertura = src.index("{", m.end())
    profondita = 0
    for i in range(apertura, len(src)):
        if src[i] == "{":
            profondita += 1
        elif src[i] == "}":
            profondita -= 1
            if profondita == 0:
                return src[apertura:i + 1]
    raise AssertionError("corpo non bilanciato: %s" % nome)


def test_has_switch_audio_tab_function():
    assert "function switchAudioTab" in APP_JS


def test_has_updVoicesPremium_function():
    assert "function updVoicesPremium" in APP_JS


def test_standard_voices_arrivano_dalla_cascata():
    """Il tab Standard non riconosce piu' i motori a mano: l'elenco delle voci
    gratuite glielo passa la cascata (audio_cascade.js), che classifica per
    PREFISSO dell'id — mai per il campo `engine`, che e' vetrina e puo'
    mancare."""
    corpo = _estrai_funzione(APP_JS, "_renderStandardVoices")
    assert "std.voices" in corpo, "le voci non arrivano dal risultato della cascata"
    assert "engine" not in corpo, "il tab Standard non deve leggere il campo engine"
    assert "gemini:" not in corpo, "residuo del filtro per motore dentro app.js"


def test_wizardState_has_audioTab():
    assert "audioTab:" in APP_JS or "audioTab =" in APP_JS


def test_lingua_unica_niente_sync_fra_tab():
    """Non ci sono piu' due combo lingua da tenere allineate: la lingua e' una
    proprieta' del libro (bookLangState) e i tab la subiscono."""
    assert "let bookLangState=" in APP_JS, "stato della lingua del libro assente"
    assert "function applyBookLanguage" in APP_JS, "renderer della cascata assente"
    assert "function fillLangs" not in APP_JS, "residuo di fillLangs()"
    assert "function syncLanguageOptions" not in APP_JS, "residuo di syncLanguageOptions()"


# ── Issue 1: _updateSummary is tab-aware for voice display ──
def test_updateSummary_uses_vvPremium_when_premium():
    assert "audioTab" in APP_JS
    assert "vvPremium" in APP_JS
    assert "summaryVoice" in APP_JS
    # The fix: inside _updateSummary's body, wizardState.audioTab==='premium' branches to vvPremium
    m = re.search(r"function _updateSummary\(\)\{(.+?)^}", APP_JS, re.DOTALL | re.MULTILINE)
    assert m, "_updateSummary function not found"
    body = m.group(1)
    assert "audioTab" in body, "audioTab branch missing in _updateSummary"
    assert "vvPremium" in body, "vvPremium read missing in _updateSummary"


# ── Issue 2: la guardia lingua legge una sola fonte ──
def test_validateLanguage_legge_lo_stato_unico_della_lingua():
    """La guardia non confronta piu' due combo: ne esiste una sola fonte."""
    corpo = _estrai_funzione(APP_JS, "_validateLanguage")
    assert "bookLangState" in corpo
    assert "vlPremium" not in corpo, "residuo della vecchia combo premium"


def test_startCombinedGeneration_estimate_usa_lo_stato_lingua():
    # La URL di optimize_estimate manda la lingua del libro, non quella di un tab
    m = re.search(
        r"async function startCombinedGeneration\([^)]*\)(.+?)^(?:async function|function)\s",
        APP_JS, re.DOTALL | re.MULTILINE
    )
    assert m, "startCombinedGeneration function not found"
    body = m.group(1)
    assert "bookLangState" in body, "startCombinedGeneration non legge bookLangState"
    assert "vlPremium" not in body, "residuo della vecchia combo premium"


# ── Issue 3: switchAudioTab re-valuta l'anteprima al cambio tab ──
# Il reset/invalidazione anteprima è ora centralizzato in _onPreviewParamsChanged()
# (basato su firma): se la combinazione voce/parametri non è già nota, nasconde il
# player e forza la rigenerazione (cfr. commento app.js "Sostituisce _resetPreviewState()").
def test_switchAudioTab_resets_preview_on_change():
    m = re.search(r"function switchAudioTab\(tab\)\{(.+?)^}", APP_JS, re.DOTALL | re.MULTILINE)
    assert m, "switchAudioTab function not found"
    body = m.group(1)
    assert "_onPreviewParamsChanged" in body or "_resetPreviewState" in body or "previewStop" in body, \
        "preview re-evaluation/reset call missing in switchAudioTab"


# ── Issue 4: updVoicesPremium aggancia onchange per re-valutare l'anteprima ──
def test_updVoicesPremium_attaches_onchange_reset():
    m = re.search(r"function updVoicesPremium\(\)\{(.+?)^}", APP_JS, re.DOTALL | re.MULTILINE)
    assert m, "updVoicesPremium function not found"
    body = m.group(1)
    assert "onchange" in body, "onchange handler missing in updVoicesPremium"
    assert "_onPreviewParamsChanged" in body or "_resetPreviewState" in body or "previewStop" in body, \
        "preview re-evaluation/reset missing in updVoicesPremium onchange"


# ── tryGoToAudioSettings deve riasserire il percorso audio (no leak da translate) ──
def test_try_go_to_audio_resets_wizmode():
    """Il bottone "Prosegui" sotto i capitoli deve sempre portare al percorso
    TTS: tryGoToAudioSettings reimposta wizMode='audio' prima di goToStep(3),
    altrimenti dopo un giro nel percorso traduzione resterebbe 'translate'."""
    m = re.search(r"function tryGoToAudioSettings\(\)\{(.+?)^}", APP_JS, re.DOTALL | re.MULTILINE)
    assert m, "tryGoToAudioSettings function not found"
    body = m.group(1)
    assert "wizMode='audio'" in body or 'wizMode = "audio"' in body or 'wizMode="audio"' in body, \
        "tryGoToAudioSettings deve reimpostare wizMode='audio'"
