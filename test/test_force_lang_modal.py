"""Modale di forzatura della lingua del libro (Task 8).

Gli step 5 e 6 del brief sono verifiche manuali nel browser (caricare un
EPUB, cliccare, guardare la nota) e non si eseguono qui: confluiscono nel
collaudo manuale del Task 9. Questo file resta la copertura automatica al
loro posto, statica sul sorgente come il resto del repository — nessun
DOM reale, nessun import da altri file di test.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
I18N = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")

LOCALI = ("it", "en", "fr", "es", "de", "zh", "hi")

NUOVE_CHIAVI = (
    "force_lang_title", "force_lang_hint", "force_lang_premium_yes",
    "force_lang_ok", "force_lang_cancel",
)


def _estrai_funzione(src, nome):
    """Corpo di `function nome(...)`, per bilanciamento di graffe.

    Copia locale della stessa utility usata altrove nel repository (ogni
    file di test e' autonomo, nessun modulo condiviso oltre a conftest.py).
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


def _tag_con_id(html, id_elemento):
    """Il tag di apertura completo (fino a '>') dell'elemento con quell'id."""
    m = re.search(r"<(\w+)([^>]*\bid=\"%s\"[^>]*)>" % re.escape(id_elemento), html)
    assert m, "elemento #%s non trovato" % id_elemento
    return m.group(0)


# ── Le cinque chiavi i18n, in tutti e sette i locali ──

def test_le_chiavi_del_modale_sono_in_tutti_i_locali():
    for chiave in NUOVE_CHIAVI:
        n = len(re.findall(r'\b%s\s*:' % chiave, I18N))
        assert n == len(LOCALI), \
            "%s definita %d volte, attese %d (una per locale)" % (chiave, n, len(LOCALI))


def test_nessun_nome_di_fornitore_nelle_chiavi_del_modale():
    parole_vietate = ("gemini", "google", "speechify", "simba",
                       "microsoft", "edge", "azure")
    for chiave, valore in re.findall(r'(force_lang_\w+)\s*:\s*"([^"]*)"', I18N):
        basso = valore.lower()
        for parola in parole_vietate:
            assert parola not in basso, \
                "%s espone il nome di un fornitore: %r" % (chiave, valore)


# ── Il pulsante non e' piu' nascosto ──

def test_forceLangBtn_non_ha_piu_hidden():
    tag = _tag_con_id(HTML, "forceLangBtn")
    assert "hidden" not in tag, "#forceLangBtn e' ancora hidden: %r" % tag
    assert 'onclick="openForceLangModal()"' in tag


# ── Gli id che le tre funzioni nuove cercano esistono davvero ──

ID_MODALE = ("forceLangModal", "forceLangSelect", "forceLangTitle")


def test_gli_id_del_modale_esistono_nel_markup():
    for id_elemento in ID_MODALE:
        assert 'id="%s"' % id_elemento in HTML, \
            "id #%s assente da html_head.html" % id_elemento


def test_le_tre_funzioni_esistono_in_app_js():
    for nome in ("openForceLangModal", "closeForceLangModal", "confirmForceLang"):
        assert re.search(r"function\s+%s\s*\(" % re.escape(nome), APP_JS), \
            "manca function %s" % nome


# ── apri/chiudi agiscono sull'OVERLAY, non su un elemento interno ──

def test_openForceLangModal_apre_lOVERLAY_forceLangModal():
    corpo = _estrai_funzione(APP_JS, "openForceLangModal")
    assert "getElementById('forceLangModal')" in corpo
    assert re.search(
        r"getElementById\('forceLangModal'\)\s*\.classList\.add\('open'\)", corpo
    ), "openForceLangModal non aggiunge 'open' direttamente sull'overlay #forceLangModal"


def test_closeForceLangModal_chiude_lOVERLAY_forceLangModal():
    corpo = _estrai_funzione(APP_JS, "closeForceLangModal")
    assert re.search(
        r"getElementById\('forceLangModal'\)\s*\.classList\.remove\('open'\)", corpo
    ), "closeForceLangModal non toglie 'open' direttamente dall'overlay #forceLangModal"


def test_loverlay_si_chiude_cliccando_lo_sfondo():
    tag = _tag_con_id(HTML, "forceLangModal")
    assert 'onclick="if(event.target===this)closeForceLangModal()"' in tag, \
        "manca la chiusura al click sullo sfondo, come #langWarnModal"


# ── L'elenco marca le lingue con voci a pagamento ──

def test_openForceLangModal_marca_le_lingue_con_voci_a_pagamento():
    corpo = _estrai_funzione(APP_JS, "openForceLangModal")
    assert "resolveAudioSelection(" in corpo, \
        "la marcatura premium deve venire dalla cascata pura, non da un elenco a mano"
    assert "premiumEnabled" in corpo
    assert "force_lang_premium_yes" in corpo


# ── confirmForceLang: guardia e scrittura dello stato ──

def test_confirmForceLang_esce_se_la_scelta_e_vuota_o_invariata():
    corpo = _estrai_funzione(APP_JS, "confirmForceLang")
    assert re.search(
        r"if\(\s*!scelta\s*\|\|\s*scelta\s*===\s*bookLangState\.code\s*\)\s*return;", corpo
    ), "manca (o e' cambiata) la guardia su scelta vuota / invariata"


def test_confirmForceLang_scrive_source_forced_e_propaga():
    corpo = _estrai_funzione(APP_JS, "confirmForceLang")
    assert re.search(r"bookLangState\s*=\s*\{code:\s*scelta\s*,\s*source:\s*'forced'\s*\}", corpo), \
        "confirmForceLang non scrive piu' source:'forced'"
    assert "_rememberLastLang(scelta)" in corpo, \
        "confirmForceLang non ricorda piu' l'ultima lingua scelta"
    assert "applyBookLanguage()" in corpo, \
        "confirmForceLang non richiama piu' la cascata: la nota non si aggiornerebbe"
