"""Cablaggio del pannello «Impostazioni audio»: markup, id e stringhe.

La cascata lingua -> modello -> accento -> voce vive in tre file diversi
(app.js legge il DOM, html_head.html lo definisce, i18n_data.js lo scrive).
Le rotture piu' probabili non sono di logica ma di collegamento: un id
rinominato, una chiave mancante in un locale, un blocco di markup spostato
nel posto sbagliato. Sono quelle che questi test difendono.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
I18N = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")

LOCALI = ("it", "en", "fr", "es", "de", "zh", "hi")


def _blocco_elemento(html, id_elemento):
    """Testo interno dell'elemento con quell'id, per bilanciamento dei tag.

    Non un `in` sul sorgente intero: risale davvero l'annidamento, contando
    le aperture e le chiusure di <div> a partire dal tag che porta l'id.
    Cosi' un blocco che rientra dentro un altro fa fallire l'assert, mentre
    una ricerca a sottostringa lo lascerebbe passare.
    """
    m = re.search(r"<(\w+)([^>]*\bid=\"%s\")" % re.escape(id_elemento), html)
    assert m, "elemento #%s non trovato" % id_elemento
    tag = m.group(1)
    apertura = html.index(">", m.end())
    profondita = 1
    i = apertura + 1
    apre = re.compile(r"<%s\b" % re.escape(tag))
    chiude = re.compile(r"</%s\s*>" % re.escape(tag))
    while i < len(html):
        ma = apre.search(html, i)
        mc = chiude.search(html, i)
        assert mc, "tag <%s> di #%s non chiuso" % (tag, id_elemento)
        if ma and ma.start() < mc.start():
            profondita += 1
            i = ma.end()
            continue
        profondita -= 1
        if profondita == 0:
            return html[apertura + 1:mc.start()]
        i = mc.end()
    raise AssertionError("annidamento non bilanciato per #%s" % id_elemento)


# ── F1: il motivo dello spegnimento premium deve essere visibile ──

def test_avviso_premium_spento_fuori_dal_pannello_premium():
    """#premiumOffRow non deve stare dentro #tabPremium.

    applyBookLanguage() disabilita il tab PREMIUM e riporta l'utente su
    Standard nello stesso istante in cui mostra questo avviso: dentro
    #tabPremium (che switchAudioTab() tiene `hidden` finche' il tab non e'
    attivo) l'avviso non raggiungerebbe mai lo schermo, e l'utente vedrebbe
    solo un tab che non risponde.
    """
    dentro_premium = _blocco_elemento(HTML, "tabPremium")
    assert 'id="premiumOffRow"' not in dentro_premium, \
        "#premiumOffRow e' tornato dentro #tabPremium: l'avviso non sarebbe mai visibile"
    assert 'id="premiumOffMsg"' not in dentro_premium, \
        "#premiumOffMsg e' tornato dentro #tabPremium"
    # E deve comunque esistere, nel pannello 3, con il messaggio dentro.
    assert 'id="premiumOffRow"' in HTML
    assert 'id="premiumOffMsg"' in _blocco_elemento(HTML, "premiumOffRow")


def test_il_tab_spento_si_vede_che_e_spento():
    """`btn.disabled` senza una regola CSS e' un tab identico a uno attivo."""
    css = (ROOT / "static/css/style.css").read_text(encoding="utf-8")
    m = re.search(r"\.tab-bar\s+\.tab:disabled\s*\{([^}]*)\}", css)
    assert m, "manca la regola .tab-bar .tab:disabled"
    regola = m.group(1)
    assert "opacity" in regola
    assert "not-allowed" in regola


# ── F2: nessun nome di fornitore nelle etichette dei modelli ──

PAROLE_VIETATE = ("gemini", "google", "speechify", "simba",
                  "microsoft", "edge", "azure")


def _valori_lbl_model():
    """(chiave, valore) di ogni `lbl_model_*:"..."` del file i18n."""
    return re.findall(r'(lbl_model_\w+)\s*:\s*"([^"]*)"', I18N)


def test_nessun_nome_di_fornitore_nelle_etichette_dei_modelli():
    """Il selettore #vmPremium mostra questi valori all'utente.

    Il ripiego neutro scritto in _modelLabel() non entra mai in funzione,
    perche' t() ritorna al peggio la chiave e mai un valore falsy: l'unico
    posto dove la violazione si corregge e' il VALORE della chiave.
    """
    trovati = _valori_lbl_model()
    assert trovati, "nessuna chiave lbl_model_* trovata"
    for chiave, valore in trovati:
        basso = valore.lower()
        for parola in PAROLE_VIETATE:
            assert parola not in basso, \
                "%s espone il nome di un fornitore all'utente: %r" % (chiave, valore)


def test_le_etichette_dei_modelli_esistono_in_tutti_i_locali():
    for chiave in ("lbl_model_flash25", "lbl_model_flash31",
                   "lbl_model_simba", "lbl_model_voxcpm"):
        n = len(re.findall(r'\b%s\s*:' % chiave, I18N))
        assert n == len(LOCALI), \
            "%s definita in %d locali su %d" % (chiave, n, len(LOCALI))


# ── F4: le due classi di rottura piu' probabili del pannello ──

CHIAVI_PANNELLO_AUDIO = (
    "lang_src_assumed", "lang_src_detected", "lang_src_forced",
    "lang_src_metadata", "lbl_accent_std", "lbl_book_lang",
    "note_accent_reset", "note_lang_set", "note_model_reset",
    "note_voice_reset", "premium_no_lang", "tip_force_lang",
)


def test_chiavi_i18n_del_pannello_audio_in_tutti_e_sette_i_locali():
    """Una chiave che manca in un locale non rompe niente: ripiega
    sull'inglese, in silenzio, e l'utente legge una frase nella lingua
    sbagliata in mezzo alle altre."""
    for chiave in CHIAVI_PANNELLO_AUDIO:
        n = len(re.findall(r'\b%s\s*:' % chiave, I18N))
        assert n == len(LOCALI), \
            "%s definita %d volte, attese %d (una per locale)" % (chiave, n, len(LOCALI))


ID_PANNELLO_AUDIO = (
    "bookLangRow", "bookLangName", "bookLangSrc", "forceLangBtn",
    "cascadeNote", "stdAccentRow", "stdAccent", "premiumOffRow",
    "premiumOffMsg", "vv", "vmPremium",
)


def test_gli_id_del_pannello_audio_esistono_nel_markup():
    """Un id rinominato nel markup passa in silenzio: getElementById ritorna
    null, il codice difensivo (`if(!el)return`) esce e il controllo semplicemente
    non funziona piu', senza un solo errore in console."""
    for id_elemento in ID_PANNELLO_AUDIO:
        assert 'id="%s"' % id_elemento in HTML, \
            "id #%s letto dal pannello audio ma assente da html_head.html" % id_elemento


def test_gli_id_letti_da_app_js_sono_quelli_del_markup():
    """Contraltare del test sopra: gli id che app.js cerca davvero devono
    essere gli stessi, non un elenco che invecchia da solo."""
    letti = [i for i in ID_PANNELLO_AUDIO
             if "getElementById('%s')" % i in APP_JS]
    # bookLangRow e forceLangBtn sono letti solo da CSS e dal modale di
    # forzatura (Task 8): gli altri nove li legge applyBookLanguage() e c.
    assert len(letti) == 9, \
        "app.js legge %d dei %d id attesi: %s" % (len(letti), 9, letti)
