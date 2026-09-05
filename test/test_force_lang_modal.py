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


# ── Il ritorno alla lingua dichiarata dal libro ──

# Richiesta dell'utente del 05/09/2026: dire «riportata al valore
# predefinito» non basta, il ritorno dev'essere una cosa su cui si clicca,
# e dev'essere li' per tutto il tempo in cui la lingua resta forzata.

def test_le_chiavi_del_ritorno_sono_in_tutti_i_locali():
    for chiave in ("restore_lang_btn", "tip_restore_lang"):
        n = len(re.findall(r'\b%s\s*:' % chiave, I18N))
        assert n == len(LOCALI), \
            "%s definita %d volte, attese %d (una per locale)" % (chiave, n, len(LOCALI))


def test_l_etichetta_del_ritorno_nomina_la_lingua():
    """«Riporta a Francese» dice dove si va; «Riporta» da solo no."""
    valori = re.findall(r'\brestore_lang_btn\s*:\s*"([^"]*)"', I18N)
    assert len(valori) == len(LOCALI)
    for valore in valori:
        assert "{lang}" in valore, \
            "restore_lang_btn non nomina piu' la lingua: %r" % valore


def test_il_bottone_di_ritorno_nasce_nascosto_e_chiama_restoreBookLang():
    """L'etichetta la scrive applyBookLanguage(), perche' contiene il nome
    della lingua: un `data-t` la riscriverebbe a ogni cambio di lingua
    dell'interfaccia, segnaposto compreso."""
    tag = _tag_con_id(HTML, "restoreLangBtn")
    assert re.search(r"\bhidden\b", tag), \
        "#restoreLangBtn non nasce nascosto: comparirebbe su ogni libro"
    assert 'onclick="restoreBookLang()"' in tag, "#restoreLangBtn non e' cliccabile"
    assert 'data-t-title="tip_restore_lang"' in tag
    assert "data-t=" not in tag, \
        "l'etichetta di #restoreLangBtn viene riscritta da i18n: perderebbe il nome della lingua"


def test_restoreBookLang_torna_alla_lingua_del_libro_non_alla_precedente():
    """Non e' un «annulla»: dopo tre forzature di fila riporta comunque a
    quella che il libro dichiara, con la provenienza che aveva."""
    corpo = _estrai_funzione(APP_JS, "restoreBookLang")
    assert re.search(
        r"bookLangState=\{code:_langDalLibro\.code,source:_langDalLibro\.source\}",
        corpo.replace(" ", "")
    ), "restoreBookLang non ripristina piu' codice E provenienza del libro"
    assert "_rememberLastLang(_langDalLibro.code)" in corpo, \
        "restoreBookLang non ricorda la lingua ripristinata: il ricaricamento la riperderebbe"
    assert "applyBookLanguage()" in corpo, \
        "restoreBookLang non richiama la cascata: voce e modello resterebbero quelli della lingua forzata"


def test_restoreBookLang_esce_se_non_c_e_niente_a_cui_tornare():
    corpo = _estrai_funzione(APP_JS, "restoreBookLang").replace(" ", "")
    assert re.search(
        r"if\(!_langDalLibro\|\|_langDalLibro\.code===bookLangState\.code\)return;",
        corpo
    ), "manca (o e' cambiata) la guardia su «nessun valore del libro / gia' quello»"


def test_una_lingua_indovinata_non_e_un_posto_dove_tornare():
    """Il bottone promette la lingua «del libro»: offrirlo quando la lingua
    l'ha tirata a indovinare l'app, o quando arriva da una forzatura
    precedente, sarebbe una promessa falsa."""
    corpo = _estrai_funzione(APP_JS, "initBookLanguage").replace(" ", "")
    assert re.search(r"source:'assumed'\};\s*_langDalLibro=null;", corpo), \
        "il ramo «lingua indovinata» non azzera piu' _langDalLibro"
    assert re.search(r"_langDalLibro=\(src==='forced'\)\?null:", corpo), \
        "una provenienza 'forced' viene offerta come lingua del libro"


def test_una_traduzione_adottata_cancella_il_ritorno():
    """Dopo l'adozione il testo E' nell'altra lingua: tornare alla lingua di
    partenza darebbe voci giuste per un testo che non c'e' piu'."""
    corpo = _estrai_funzione(APP_JS, "adoptTranslation").replace(" ", "")
    assert re.search(r"_langDalLibro=null;\s*applyBookLanguage\(\);", corpo), \
        "adoptTranslation non cancella _langDalLibro prima di far girare la cascata"


def test_il_bottone_si_mostra_solo_quando_c_e_una_lingua_del_libro_diversa():
    """La visibilita' si ricalcola nella cascata, non al click del modale: la
    lingua cambia anche dall'adozione di una traduzione e dal caricamento di
    un altro libro."""
    corpo = _estrai_funzione(APP_JS, "applyBookLanguage").replace(" ", "")
    assert re.search(
        r"rb\.hidden=!daRipristinare",
        corpo
    ), "applyBookLanguage non decide piu' la visibilita' di #restoreLangBtn"
    assert re.search(
        r"daRipristinare=!!\(_langDalLibro\s*&&_langDalLibro\.code!==bookLangState\.code\)",
        corpo
    ), "la condizione di visibilita' del ritorno non e' piu' «il libro ne dichiara una diversa»"
    assert "replace('{lang}',_langLabel(_langDalLibro.code))" in corpo, \
        "l'etichetta del ritorno non nomina piu' la lingua del libro"
