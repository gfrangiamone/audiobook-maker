# test/test_app_js_preview_premium_promo.py
"""Fumetto PREMIUM mostrato mentre si ascolta l'anteprima con voci Standard.

Il fumetto e' l'unico invito alle voci a pagamento che arriva nel momento in
cui l'utente sta davvero valutando il timbro della lettura. Vive dentro
#previewAudioWrap, esce sull'evento 'play' del player e al click porta sulla
tab PREMIUM. I gate (tab Standard attiva, tab PREMIUM disponibile, mai dopo la
scoperta, una volta al giorno) sono quello che lo separa da un banner
pubblicitario: se cadono, va rimesso il test, non tolto.
"""
import re
from pathlib import Path

APP = Path("static/js/app.js").read_text(encoding="utf-8")
HEAD = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
CSS = Path("static/css/style.css").read_text(encoding="utf-8")

LANGS = ("it", "en", "fr", "es", "de", "zh", "hi")


def _extract_fn(name):
    marker = "function %s(" % name
    start = APP.find(marker)
    assert start >= 0, "%s non trovata" % name
    depth = 0
    i = APP.index("{", start)
    for j in range(i, len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError("parentesi non bilanciate in %s" % name)


def test_bolla_dentro_il_wrapper_del_player():
    # Fuori dal wrapper resterebbe visibile anche senza anteprima caricata.
    wrap = HEAD[HEAD.index('id="previewAudioWrap"'):]
    wrap = wrap[:wrap.index('<audio id="previewAudioWiz"')]
    assert 'id="previewPremiumCoach"' in wrap
    assert 'class="prem-coach preview-coach"' in wrap
    assert 'data-t="preview_premium_promo"' in wrap
    assert '_previewPromoGo()' in wrap
    assert '_dismissPreviewPromo()' in wrap


def test_testo_tradotto_in_tutte_le_lingue():
    found = re.findall(r'preview_premium_promo:"([^"]+)"', I18N)
    assert len(found) == len(LANGS), found
    assert len(set(found)) == len(LANGS), "traduzioni duplicate: %r" % (found,)


def test_la_bolla_esce_solo_sul_play_dell_anteprima():
    assert "_prevAudioEl.addEventListener('play',_maybeShowPreviewPromo)" in APP
    assert "_prevAudioEl.addEventListener('ended',_dismissPreviewPromo)" in APP


def test_gate_di_eleggibilita():
    fn = _extract_fn("_previewPromoEligible")
    # Solo con voci gratuite: sulla tab PREMIUM l'invito non ha senso.
    assert "wizardState.audioTab!=='standard'" in fn
    # Mai verso una tab che non si apre (lingua senza voci a pagamento, manutenzione).
    assert "_premiumTabAvailable()" in fn
    # Mai a chi le voci PREMIUM le ha gia' viste.
    assert "discovered" in fn
    # Una volta al giorno.
    assert "_PREVIEW_PROMO_KEY" in fn and "_premiumHintToday()" in fn


def test_click_porta_sulla_tab_premium():
    fn = _extract_fn("_previewPromoGo")
    assert "switchAudioTab('premium')" in fn
    assert "_dismissPreviewPromo()" in fn


def test_la_bolla_non_sopravvive_al_cambio_di_contesto():
    for name in ("previewStop", "_resetPreviewState", "_onPreviewParamsChanged",
                 "switchAudioTab"):
        assert "_dismissPreviewPromo()" in _extract_fn(name), name


def test_bolla_in_flusso_e_non_sovrapposta_al_player():
    # .prem-coach e' absolute (ancorata alla tab-bar): qui deve stare in flusso,
    # altrimenti copre i comandi di riproduzione invece di indicarli.
    assert ".prem-coach.preview-coach" in CSS
    rule = CSS[CSS.index(".prem-coach.preview-coach"):]
    rule = rule[:rule.index("}") + 1]
    assert "position:relative" in rule
