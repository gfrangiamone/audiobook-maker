"""Il wizard «Campiona la tua voce» e le voci personali nella combo: markup,
script, i18n e cablaggi in app.js. Asserzioni statiche sul sorgente, come
test_voxcpm_frontend_assets.py; la logica pura gira in test/js/."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
TAIL = (ROOT / "templates/_fragments/html_tail.html").read_text(encoding="utf-8")
JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
CASCATA = (ROOT / "static/js/audio_cascade.js").read_text(encoding="utf-8")
I18N = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
VC_PATH = ROOT / "static/js/voice_clone.js"

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]


def _estrai_funzione(src, nome):
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


def _chiavi_i18n(lang):
    chiavi = set()
    for blocco in re.findall(r"Object\.assign\(L\." + lang + r",\{(.*?)\}\);", I18N, re.S):
        chiavi.update(re.findall(r"(?:^|,)\s*([a-z_0-9]+)\s*:", blocco))
    return chiavi


def test_vociMie_esportata():
    assert "function vociMie(" in CASCATA
    assert re.search(r"module\.exports\s*=\s*\{[^}]*vociMie", CASCATA, re.S)
    assert "window.vociMie = vociMie" in CASCATA


def test_combo_voxcpm_mette_le_voci_personali_in_testa():
    corpo = _estrai_funzione(JS, "updVoicesPremium")
    ramo = corpo[corpo.index("vmEl.value==='voxcpm'"):corpo.index("simba-3.2")]
    assert "vociMie(" in ramo
    assert "t('vc_group_mine')" in ramo
    assert ramo.index("vc_group_mine") < ramo.index("'♀'"), "il gruppo Le tue voci deve precedere i gruppi di catalogo"
    assert "_vcJustCreated" in ramo


def test_voce_selezionata_cerca_anche_le_voci_personali():
    corpo = _estrai_funzione(JS, "_voxcpmSelectedVoice")
    assert "vociMie(" in corpo


def test_chiavi_combo_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        for k in ("vc_group_mine", "vc_voice_own", "vc_voice_shared"):
            assert k in chiavi, f"{k} manca in {lang}"
