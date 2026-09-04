import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _estrai_funzione(src, nome):
    """Corpo di `function nome(...)`, per bilanciamento di graffe."""
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


def test_html_has_speechify_emotion_combo():
    html = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
    assert 'id="speechifyEmotion"' in html
    # Accento deve precedere la voce nel markup del tab Premium.
    i_accent = html.find('id="geminiAccentRow"')
    i_voice = html.find('id="vvPremium"')
    assert i_accent != -1 and i_voice != -1
    assert i_accent < i_voice, "accent row must come before the voice select"


def test_appjs_has_model_population():
    """Il modello Express (id 'simba-3.2') entra nel selettore dal percorso
    vivo: modelliPer() lo aggiunge solo se la lingua e' 'en' E il catalogo
    espone voci speechify, applyBookLanguage() riversa la lista in #vmPremium.
    updModelsPremium(), che duplicava la regola con un default diverso, e'
    stata cancellata: se torna, questo test lo dice."""
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    cascata = (ROOT / "static/js/audio_cascade.js").read_text(encoding="utf-8")
    assert "updModelsPremium" not in js, "risorto il popolatore morto"
    modelli = _estrai_funzione(cascata, "modelliPer")
    assert "simba-3.2" in modelli, "il modello Express non e' piu' nella cascata"
    assert "speechify:simba-3.2:" in modelli, "il filtro non guarda piu' il prefisso dell'id"
    assert "'en'" in modelli, "il modello Express non e' piu' legato all'inglese"
    corpo = _estrai_funzione(js, "applyBookLanguage")
    assert "esito.premium.models" in corpo, "#vmPremium non si popola piu' dalla cascata"


def test_appjs_toggle_and_payload():
    js = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
    assert "_onPremiumModelChanged" in js
    assert "speechifyEmotionRow" in js
    assert "speechify_emotion" in js  # payload key
    assert "_isSpeechifyVoiceId" in js


def test_i18n_has_emotion_keys():
    # NOTE: i18n/en.json et al. were intentionally dropped in commit 86c4594
    # ("chore: remove dead code and unused i18n keys" - orphan files, never
    # loaded). The single source of truth for UI translations is the inline
    # `const L={...}` dict in templates/_fragments/i18n_data.js.
    js = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
    assert "lbl_emotion" in js
    assert "lbl_model_simba" in js
    assert "emotion_none" in js
    # Now present in all seven locales: 'hi' was added together with the
    # neutral relabelling ("Express (English only)"), because the fallback to
    # L.en propagated the provider name instead of masking it.
    assert js.count("lbl_model_simba") == 7
