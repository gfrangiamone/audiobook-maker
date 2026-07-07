"""Test statici: i toggle 'leggi testo tra parentesi' sono cablati end-to-end
nel frontend (checkbox nel template, flag nei payload generate/estimate/preview,
inclusione nella cache-key della stima, i18n in tutte le lingue)."""
from pathlib import Path
import re

APP = Path("static/js/app.js").read_text(encoding="utf-8")
HEAD = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")

LANGS = ["it", "en", "fr", "es", "de", "zh", "hi"]
NEW_KEYS = ["adv_options_title", "adv_read_round", "adv_read_square", "adv_paren_hint"]


def test_checkboxes_in_template():
    assert 'id="readRoundParens"' in HEAD
    assert 'id="readSquareBrackets"' in HEAD
    assert 'id="advOptions"' in HEAD


def test_getparenflags_helper_present():
    assert "function getParenFlags" in APP
    assert "read_round_parens" in APP
    assert "read_square_brackets" in APP


def test_generate_payload_includes_flags():
    # Entrambe le costruzioni del payload di generazione includono i flag.
    assert APP.count("...getParenFlags()") >= 3  # 2 generate + 1 estimate


def test_optimize_payload_includes_flags():
    # Il flusso wizard (optimize + auto-generate) deve inoltrare i flag parentesi,
    # altrimenti l'auto-generazione post-LLM userebbe il default (rimozione).
    assert "Object.assign(payload,getParenFlags())" in APP


def test_estimate_cache_key_includes_paren_flags():
    m = re.search(r"function getEstimateCacheKey\(\)\s*\{(.*?)^\}", APP, re.MULTILINE | re.DOTALL)
    assert m, "getEstimateCacheKey not found"
    assert "getParenFlags()" in m.group(1)


def test_preview_url_passes_flags():
    assert "read_round_parens=1" in APP
    assert "read_square_brackets=1" in APP


def test_toggle_retriggers_estimate():
    assert "readRoundParens" in APP and "requestCombinedEstimate" in APP
    # il listener sul cambio checkbox deve esistere
    assert re.search(r"readRoundParens['\"]\)\?\.addEventListener\(['\"]change['\"]\s*,\s*requestCombinedEstimate", APP)


def test_i18n_keys_all_langs():
    def block(lang):
        m = re.search(rf'(?:^|[,\s{{]){lang}\s*:\s*\{{', I18N, re.MULTILINE)
        assert m, f"lang block {lang} not found"
        brace = I18N.rfind("{", m.start(), m.end())
        depth = 0
        for i in range(brace, len(I18N)):
            if I18N[i] == "{":
                depth += 1
            elif I18N[i] == "}":
                depth -= 1
                if depth == 0:
                    return I18N[brace:i]
        return ""

    missing = []
    for lang in LANGS:
        b = block(lang)
        for k in NEW_KEYS:
            if f"{k}:" not in b:
                missing.append(f"{lang}.{k}")
    assert not missing, f"missing i18n keys: {missing}"
