"""Le etichette del pannello VoxCPM esistono nelle sei lingue.

Il file i18n mette le chiavi in due posti: il blocco base `L.<lingua>:{...}`
e gli `Object.assign(L.<lingua>,{...})` in coda. Le chiavi premium stanno nei
secondi, quindi qui si guardano entrambi — test_i18n_completeness.py legge
solo il primo, ed e' il motivo per cui non copre queste chiavi.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
I18N = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")

LANGS = ["it", "en", "fr", "es", "de", "zh"]

CHIAVI_PANNELLO = [
    "lbl_model_voxcpm", "lbl_character", "character_all",
    "voxcpm_sample_title", "voxcpm_sample_hint",
]
# Snapshot dei caratteri del catalogo al 2026-08-28. NON e' un requisito:
# serve solo a verificare che il dizionario copra le sei lingue in modo
# uniforme. Nessun test confronta questa lista con voices.json (D10).
CHIAVI_PERSONA = [
    "persona_audiobook_slow", "persona_bright_lively", "persona_casual_drawl",
    "persona_deep_adventure", "persona_elder_sage", "persona_grave_narrator",
    "persona_intimate", "persona_neutral_pro", "persona_poised_dry",
    "persona_warm_pro", "persona_warm_young", "persona_weathered",
]


def _blocchi(lang):
    """Tutti i frammenti che assegnano chiavi a una lingua."""
    fuori = re.findall(
        r"Object\.assign\(L\.%s\s*,\s*\{(.*?)\}\s*\)\s*;" % re.escape(lang),
        I18N, re.DOTALL)
    return "\n".join(fuori)


def _ha(lang, chiave):
    return re.search(r'(?:^|[,{])\s*"?%s"?\s*:' % re.escape(chiave),
                     _blocchi(lang)) is not None


def test_le_etichette_del_pannello_ci_sono_in_tutte_le_lingue():
    mancanti = [f"{l}.{k}" for l in LANGS for k in CHIAVI_PANNELLO if not _ha(l, k)]
    assert not mancanti, f"chiavi mancanti: {mancanti}"


def test_i_caratteri_noti_sono_tradotti_in_tutte_le_lingue():
    mancanti = [f"{l}.{k}" for l in LANGS for k in CHIAVI_PERSONA if not _ha(l, k)]
    assert not mancanti, f"chiavi mancanti: {mancanti}"


def test_le_traduzioni_non_sono_la_chiave_tecnica():
    # Una traduzione uguale alla chiave sarebbe peggio di nessuna traduzione:
    # passerebbe il test sopra fingendo un lavoro non fatto.
    for lang in LANGS:
        blocco = _blocchi(lang)
        for k in CHIAVI_PERSONA:
            m = re.search(r'%s\s*:\s*"([^"]*)"' % re.escape(k), blocco)
            if m:
                assert m.group(1).strip(), f"{lang}.{k} vuota"
                assert m.group(1) != k.replace("persona_", "").replace("_", "-")


def test_la_traduzione_ricade_e_non_si_rompe():
    # §5.2: dizionario -> stringhe del catalogo -> chiave. Un carattere nuovo
    # non deve richiedere un rilascio.
    i = JS.find("function _voxcpmPersonaLabel")
    assert i != -1
    corpo = JS[i:i + 800]
    assert "persona_" in corpo
    assert "persona_role" in corpo   # l'anello di mezzo
    assert "return" in corpo


def test_gli_accenti_si_traducono_senza_elenchi():
    # 38 varianti oggi, ignote domani: l'etichetta viene dal browser, non da
    # 38 righe per lingua.
    i = JS.find("function _voxcpmLocaleLabel")
    assert i != -1
    corpo = JS[i:i + 600]
    assert "Intl.DisplayNames" in corpo
    assert "catch" in corpo          # ricaduta sul codice grezzo
    assert "_voxcpmLocaleLabel(" in JS.split("function _voxcpmLocaleLabel")[0] \
        or "_voxcpmLocaleLabel(loc)" in JS


def test_il_dizionario_dei_caratteri_non_e_in_app_js():
    # D10: le chiavi stanno nelle traduzioni, l'elenco di cosa esiste sta nel
    # catalogo. app.js non deve contenere ne' l'uno ne' l'altro.
    for cablato in ("warm-young", "audiobook-slow", "elder-sage"):
        assert cablato not in JS
