# test/test_app_js_translation_done_panel.py
"""Regressione: schermata di fine traduzione senza download ne' adopt.

Difetto osservato in produzione (test con ABM_TRANSLATE_MODEL=gemini-3.5-flash-lite):
il pannello 5 mostrava "Traduzione completata!" ma nessun bottone -> vicolo cieco
(niente download del libro tradotto, niente passaggio al TTS), pur essendo il job
completo e l'email di consegna gia' partita.

Causa: `#dlA` (contenitore dei bottoni di download) viene messo a display:none da
`resetAll()` ("Carica altro libro") e da `goBackToChapters()`. Nel flusso audio lo
riabilita il done-handler di `listenProgress()`; `_showTranslationDone()` non lo
faceva, quindi mostrava btnD/btnTrAdopt dentro un contenitore invisibile.

Il pannello 5 e' condiviso audio/traduzione: il test copre anche il ripristino di
titolo e descrizione quando dopo una traduzione si genera l'audio (adopt).
"""
import re
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")
HEAD = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")


def _fn_body(marker):
    start = APP.find(marker)
    assert start >= 0, f"{marker} non trovato"
    rest = APP[start + len(marker):]
    m = re.search(r"\n(?:async function |function )", rest)
    return rest[:m.start()] if m else rest


def test_translation_done_reveals_download_container():
    """Senza questo, btnD e btnTrAdopt restano dentro un #dlA nascosto."""
    fn = _fn_body("function _showTranslationDone")
    assert "getElementById('dlA')" in fn
    assert re.search(r"dlA\s*\)\s*dlA\.style\.display=''", fn), \
        "_showTranslationDone deve rendere visibile #dlA"


def test_translation_done_shows_both_buttons():
    fn = _fn_body("function _showTranslationDone")
    # download della traduzione
    assert "/api/download_translation/" in fn
    # passaggio al TTS
    assert "getElementById('btnTrAdopt')" in fn
    assert "btnAdopt.style.display=''" in fn


def test_panel5_desc_has_id():
    assert 'id="panel5Desc"' in HEAD


def test_translation_done_sets_translation_desc():
    fn = _fn_body("function _showTranslationDone")
    assert "_setPanel5Desc('tr_done_desc'" in fn


def test_desc_helper_updates_data_t_key():
    """Cambiare solo il testo non basta: al cambio lingua applyI18n()
    rimetterebbe la stringa dell'altro flusso."""
    fn = _fn_body("function _setPanel5Desc")
    assert "setAttribute('data-t',key)" in fn


def test_audio_done_restores_panel5_audio_texts():
    """Traduzione -> adopt -> generazione audio: il pannello 5 non deve
    restare con titolo/descrizione della traduzione."""
    fn = _fn_body("function listenProgress")
    assert "_setPanel5Desc('p5_desc'" in fn
    assert "t('p5_title')" in fn


def test_reset_restores_desc_key():
    fn = _fn_body("function resetAll")
    assert "_p5d.setAttribute('data-t','p5_desc')" in fn
