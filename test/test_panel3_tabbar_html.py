import re
from pathlib import Path

HTML = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")


def _estrai_funzione(src, nome):
    """Corpo di `function nome(...)`, per bilanciamento di graffe.

    Un `in` sul sorgente intero non distingue la funzione viva da un
    residuo altrove: qui l'assert si ancora al corpo giusto.
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

def test_panel3_has_tab_bar():
    assert 'id="panel3"' in HTML
    assert 'class="tab-bar"' in HTML
    assert 'data-tab="standard"' in HTML
    assert 'data-tab="premium"' in HTML

def test_panel3_has_two_tab_panels():
    assert 'id="tabStandard"' in HTML
    assert 'id="tabPremium"' in HTML
    assert 'role="tabpanel"' in HTML

def test_panel3_premium_tab_has_model_selector():
    # Il <select> del modello e' nel markup, ma le <option> le inietta il
    # percorso vivo: modelliPer() (audio_cascade.js) decide QUALI modelli la
    # lingua del libro ammette, applyBookLanguage() (app.js) li riversa in
    # #vmPremium. updModelsPremium() non esiste piu'.
    assert 'id="vmPremium"' in HTML
    APPJS = Path("static/js/app.js").read_text(encoding="utf-8")
    CASCATA = Path("static/js/audio_cascade.js").read_text(encoding="utf-8")
    assert "updModelsPremium" not in APPJS, "risorto il popolatore morto"
    corpo = _estrai_funzione(APPJS, "applyBookLanguage")
    assert "vmPremium" in corpo, "applyBookLanguage() non popola piu' #vmPremium"
    assert "of esito.premium.models" in corpo, "le option non vengono dalla cascata"
    assert "_modelLabel" in corpo, "le option non passano dalle etichette i18n"
    modelli = _estrai_funzione(CASCATA, "modelliPer")
    assert "flash25" in modelli
    assert "flash31" in modelli

def test_panel3_premium_tab_has_style_textarea():
    assert 'id="geminiStyle"' in HTML
    assert 'maxlength="200"' in HTML

def test_panel3_premium_tab_has_cost_preview_box():
    assert 'id="costPreviewBox"' in HTML
    assert 'id="costPreviewValue"' in HTML


def test_shared_controls_outside_tab_panels():
    """Speed slider, output format and preview must be siblings of tab-panels (shared), not inside tabStandard."""
    import re
    # Estrai il contenuto INTERNO di tabStandard (dal primo tab-panel al successivo)
    m = re.search(r'id="tabStandard"[^>]*>(.*?)<div class="tab-panel"', HTML, re.DOTALL)
    assert m, "tabStandard markup not found"
    inside_std = m.group(1)
    assert 'id="speedSlider"' not in inside_std, "speed slider must be shared, not inside Standard tab"
    assert 'id="vOut"' not in inside_std, "output format must be shared, not inside Standard tab"
    assert 'id="previewSection"' not in inside_std, "preview must be shared, not inside Standard tab"


def test_shared_controls_between_tabpremium_and_footer():
    """Shared controls must appear after tabPremium closes and before panel-footer of panel3."""
    import re
    # Trova la sezione panel3 fino al primo panel-footer dopo tabPremium
    sec = re.search(r'id="panel3"(.*?)class="panel-footer"', HTML, re.DOTALL)
    assert sec, "panel3 section not found"
    block = sec.group(1)
    # tabPremium chiude prima dei controlli condivisi
    pos_premium_open = block.find('id="tabPremium"')
    pos_speed = block.find('id="speedSlider"')
    pos_vout = block.find('id="vOut"')
    pos_prev = block.find('id="previewSection"')
    assert pos_premium_open != -1, "tabPremium not found in panel3"
    assert pos_speed > pos_premium_open, "speedSlider must come after tabPremium opens"
    assert pos_vout > pos_premium_open, "vOut must come after tabPremium opens"
    assert pos_prev > pos_premium_open, "previewSection must come after tabPremium opens"
