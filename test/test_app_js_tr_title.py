# test/test_app_js_tr_title.py
"""Test statici su app.js: proposta nome file tradotto
(spec 2026-06-06-translated-title-filename)."""
import re
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")


def _fn_body(marker):
    """Estrae il corpo di una funzione a partire dal suo marcatore di
    definizione fino alla successiva dichiarazione di funzione top-level.
    Robusto alla lunghezza del corpo (niente finestre a caratteri fissi)."""
    start = APP.find(marker)
    assert start >= 0, f"{marker} non trovato"
    rest = APP[start + len(marker):]
    m = re.search(r"\n(?:async function |function )", rest)
    return rest[:m.start()] if m else rest


def test_has_fetch_translated_name():
    assert "function _trFetchTranslatedName" in APP


def test_uses_translate_title_endpoint():
    assert "/api/translate_title/" in APP


def test_guard_user_edits():
    # Aggiorna il campo solo se contiene ancora il valore auto-impostato
    assert "el.value===trAutoOutName" in APP


def test_state_var_reset():
    assert "trAutoOutName=''" in APP


def test_prefill_records_auto_value():
    assert "trAutoOutName=base" in APP


def test_fetch_triggered_from_panel_and_change():
    # definizione + chiamata in goToTranslate + chiamata nel listener change
    assert APP.count("_trFetchTranslatedName(") >= 3


def test_timeout_abort_present():
    assert "function _trFetchTranslatedName" in APP
    fn = _fn_body("function _trFetchTranslatedName")
    assert "AbortController" in fn
    assert "signal:ctrl.signal" in fn


def test_stale_response_guard():
    # Una risposta lenta per una lingua non piu' selezionata non deve applicarsi
    fn = _fn_body("function _trFetchTranslatedName")
    assert "requestedTarget" in fn
    assert "cur.value===requestedTarget" in fn


def test_loading_animation_on_title_fetch():
    """Durante la traduzione del titolo il campo nome mostra uno spinner."""
    assert "function _trNameLoading" in APP
    assert "trOutNameWrap" in APP
    fn = _fn_body("function _trFetchTranslatedName")
    assert "_trNameLoading(true)" in fn
    assert "_trNameLoading(false)" in fn


def test_title_fetch_concurrency_token():
    """Solo la richiesta piu' recente aggiorna campo/spinner (token di sequenza)."""
    assert "_trTitleReqSeq" in APP
    fn = _fn_body("function _trFetchTranslatedName")
    assert "++_trTitleReqSeq" in fn
    assert "myReq===_trTitleReqSeq" in fn


def test_title_fetch_timeout_covers_llm_latency():
    """Timeout client alzato: la prima richiesta (non in cache) deve poter
    completare lato client, non abortire mentre il server traduce e cachea."""
    fn = _fn_body("function _trFetchTranslatedName")
    assert ",12000)" not in fn
    assert ",30000)" in fn
