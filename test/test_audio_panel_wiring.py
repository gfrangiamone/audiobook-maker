"""Cablaggio del pannello «Impostazioni audio»: markup, id e stringhe.

La cascata lingua -> modello -> accento -> voce vive in tre file diversi
(app.js legge il DOM, html_head.html lo definisce, i18n_data.js lo scrive).
Le rotture piu' probabili non sono di logica ma di collegamento: un id
rinominato, una chiave mancante in un locale, un blocco di markup spostato
nel posto sbagliato. Sono quelle che questi test difendono.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "templates/_fragments/html_head.html").read_text(encoding="utf-8")
APP_JS = (ROOT / "static/js/app.js").read_text(encoding="utf-8")
I18N = (ROOT / "templates/_fragments/i18n_data.js").read_text(encoding="utf-8")

LOCALI = ("it", "en", "fr", "es", "de", "zh", "hi")


def _corpo(nome, src=APP_JS):
    """Corpo di `function nome(...)`, per bilanciamento di graffe.

    Gli assert sotto vanno ancorati alla funzione giusta e non a tutto app.js:
    una stringa che compare da qualche altra parte nel file terrebbe verde un
    test su una funzione svuotata.
    """
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(nome) + r"\s*\(", src)
    assert m, "funzione %s non trovata in app.js" % nome
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


def _codice(src):
    """`src` senza commenti e senza spazi: la STRUTTURA, non il testo.

    Serve perche' asserire su una sottostringa del sorgente non morde: una
    mutazione che cancella la guardia o l'effetto ma lascia in vita il nome
    (in un commento, in una definizione vicina) passa indisturbata. Sul
    codice ripulito si puo' invece ritagliare lo *statement* e chiedergli di
    contenere la condizione, non la parola.

    Uno scanner e non una regex: appiattire gli spazi prima di togliere i
    commenti incollerebbe la riga di codice successiva dentro un commento
    `//`, e togliere i commenti con una regex taglierebbe a meta' una stringa
    che contiene `//`.
    """
    fuori = []
    i, n = 0, len(src)
    apice = None
    while i < n:
        c = src[i]
        if apice:
            fuori.append(c)
            if c == "\\" and i + 1 < n:
                fuori.append(src[i + 1])
                i += 2
                continue
            if c == apice:
                apice = None
            i += 1
            continue
        if c in "'\"`":
            apice = c
            fuori.append(c)
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            fine = src.find("*/", i + 2)
            i = n if fine < 0 else fine + 2
            continue
        fuori.append(c)
        i += 1
    return re.sub(r"\s+", "", "".join(fuori))


def _guardia_di(piatto, posizione):
    """Testo che precede `posizione` a partire dall'inizio dello statement.

    Cioe' dall'ultimo `;` (o dall'inizio del corpo): comprende quindi l'`if`
    che protegge l'assegnamento, blocco graffato incluso. E' su questo
    ritaglio che si verifica che una guardia esista DAVVERO, e non solo che
    il nome della variabile guardata compaia da qualche parte nel file.
    """
    taglio = piatto.rfind(";", 0, posizione)
    return piatto[taglio + 1:posizione]


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


# Gli id che app.js legge davvero con getElementById. bookLangRow e
# forceLangBtn restano fuori: li usano solo il CSS e il modale di forzatura.
ID_LETTI_DA_APP_JS = {
    "bookLangName", "bookLangSrc", "cascadeNote", "stdAccentRow", "stdAccent",
    "premiumOffRow", "premiumOffMsg", "vv", "vmPremium",
}


def test_gli_id_letti_da_app_js_sono_quelli_del_markup():
    """Contraltare del test sopra: gli id che app.js cerca davvero devono
    essere gli stessi, non un elenco che invecchia da solo.

    Sull'INSIEME e non sul conteggio: contando, sostituire un id con un altro
    lascia il totale invariato e il test verde su un pannello scollegato.
    """
    letti = {i for i in ID_PANNELLO_AUDIO
             if "getElementById('%s')" % i in APP_JS}
    assert letti == ID_LETTI_DA_APP_JS, (
        "app.js non legge piu' gli id attesi.\n  mancanti: %s\n  in piu': %s"
        % (sorted(ID_LETTI_DA_APP_JS - letti), sorted(letti - ID_LETTI_DA_APP_JS))
    )


# ── B1: la voce PREMIUM scelta dall'utente non si azzera in silenzio ──

def test_il_ramo_gemini_ricorda_la_voce_scelta():
    """Il ramo Gemini di updVoicesPremium() svuota #vvPremium e lo ripopola.

    Senza una memoria fuori dal DOM il browser risceglie la prima <option>, e
    la via applyI18n() -> applyBookLanguage() -> _onPremiumModelChanged()
    passa in mezzo alla sequenza di generazione a PAGAMENTO: l'audiolibro
    esce con una voce che l'utente non ha scelto, e nessuna nota lo dice.
    I rami VoxCPM e Simba quella memoria ce l'hanno gia'.

    Ricordare non basta: la memoria deve TORNARE nel select. Per questo
    l'assert non cerca il nome `_geminiVoiceSel` ma l'assegnamento che
    riapplica la voce ricordata dopo la ricostruzione, e la guardia che lo
    protegge. Cancellare quella riga lasciando in vita la memoria e' la
    regressione piu' naturale, e deve far diventare rosso questo test.
    """
    corpo = _corpo("updVoicesPremium")
    piatto = _codice(corpo[corpo.index("Ramo Gemini"):])
    m = re.search(r"(?:const|let|var)(\w+)=_geminiVoiceSel\|\|sel\.value;", piatto)
    assert m, (
        "il ramo Gemini non legge piu' la memoria della voce in una variabile "
        "prima di ricostruire #vvPremium"
    )
    memoria = m.group(1)
    svuotamento = piatto.index("sel.innerHTML=''")
    assert m.start() < svuotamento, (
        "la memoria viene letta DOPO sel.innerHTML='': il ripiego su sel.value "
        "leggerebbe un select gia' svuotato"
    )
    coda = piatto[svuotamento:]
    ripristino = re.search(r"sel\.value=" + memoria + r"\b", coda)
    assert ripristino, (
        "la voce ricordata non torna MAI nel select dopo la ricostruzione: la "
        "memoria e' scritta e mai riapplicata, e il browser risceglie la prima "
        "<option>"
    )
    guardia = _guardia_di(coda, ripristino.start())
    assert "sel.options" in guardia and memoria in guardia, (
        "il ripristino della voce non e' protetto dal controllo che quella voce "
        "esista ancora fra le option del modello corrente: %r" % guardia
    )
    assert re.search(r"_geminiVoiceSel=sel\.value\b", coda), \
        "la memoria non viene riscritta dopo la ricostruzione"
    assert "_geminiVoiceSel=sel.value" in piatto.split("sel.onchange")[1], \
        "l'onchange dell'utente non aggiorna la memoria della voce Gemini"


def test_apply_book_language_riversa_la_voce_premium():
    """La cascata la voce premium la calcola E la preserva: se il renderer non
    la riversa nel select, il rebuild di _onPremiumModelChanged() vince e la
    scelta dell'utente sparisce.

    Non basta che `esito.premium.voice` compaia nel sorgente: il riversamento
    dev'essere VIVO. Una guardia svuotata (`if(false)`) lascia la riga al suo
    posto e il riversamento inerte, e questo test deve accorgersene.
    """
    piatto = _codice(_corpo("applyBookLanguage"))
    dopo = piatto.index("_onPremiumModelChanged")
    m = re.search(r"(?:const|let|var)(\w+)=esito\.premium\.voice;", piatto)
    assert m, "applyBookLanguage non legge piu' la voce premium preservata dalla cascata"
    assert m.start() > dopo, (
        "la voce premium viene riversata PRIMA del rebuild: "
        "_onPremiumModelChanged() la sovrascriverebbe"
    )
    voce = m.group(1)
    scrittura = re.search(r"(\w+)\.value=" + voce + r"\b", piatto)
    assert scrittura, (
        "la voce premium preservata non viene MAI scritta nel select: il "
        "riversamento e' presente nel sorgente ma inerte"
    )
    select = scrittura.group(1)
    guardia = _guardia_di(piatto, scrittura.start())
    assert voce in guardia and select + ".options" in guardia, (
        "il riversamento non e' protetto dal controllo che quella voce esista "
        "fra le option ricostruite, oppure la guardia e' stata svuotata: %r"
        % guardia
    )
    assert "_allineaMemoriaVocePremium(" + voce + ")" in piatto, (
        "il riversamento scrive il DOM senza riallineare la memoria fuori dal "
        "DOM: il rebuild successivo ripristinerebbe la voce precedente"
    )


# ── I1: la cascata non calpesta manutenzione e istanza non configurata ──

def test_il_tab_premium_non_viene_disabilitato_in_manutenzione():
    """Con il kill-switch admin acceso il tab deve restare CLICCABILE: e' il
    click ad aprire il popup «funzione in manutenzione», e un <button disabled>
    non emette click. Disabilitarlo lo rende irraggiungibile e al suo posto
    l'utente legge che la colpa e' della lingua del suo libro.

    L'assert sta sulla GUARDIA dell'assegnamento, non sulla presenza del nome
    `_premiumMaintenance` nel corpo: togliere `&&!gestitoAltrove` dall'`if`
    lascia in vita sia il nome sia la variabile, e la regressione tornerebbe
    in produzione con la suite verde.
    """
    piatto = _codice(_corpo("applyBookLanguage"))
    m = re.search(r"(?:const|let|var)(\w+)=_premiumMaintenance\|\|", piatto)
    assert m, (
        "applyBookLanguage non ricava piu' da _premiumMaintenance la condizione "
        "«lo spegnimento del tab lo decide qualcun altro»"
    )
    gestito = m.group(1)
    assert piatto.count("btn.disabled=") == 1, (
        "btn.disabled viene scritto %d volte: la guardia va verificata su "
        "ciascuna" % piatto.count("btn.disabled=")
    )
    guardia = _guardia_di(piatto, piatto.index("btn.disabled="))
    assert "!" + gestito in guardia, (
        "btn.disabled viene scritto guardando solo la lingua del libro: in "
        "manutenzione il tab tornerebbe disabled e il popup irraggiungibile. "
        "Guardia trovata: %r" % guardia
    )


def test_l_avviso_di_lingua_non_compare_su_un_tab_che_non_c_e():
    """Su un'istanza senza premium configurato #tabPremiumBtn e' hidden: la
    frase «Le voci PREMIUM non sono disponibili in {lingua}» parlerebbe di un
    tab che non e' sullo schermo."""
    corpo = _corpo("applyBookLanguage")
    riga = [r for r in corpo.splitlines() if "offRow.hidden=" in r]
    assert riga, "applyBookLanguage non decide piu' la visibilita' di #premiumOffRow"
    assert "gestitoAltrove" in riga[0], (
        "#premiumOffRow viene mostrato guardando solo la lingua: comparirebbe "
        "anche quando il tab premium e' nascosto o in manutenzione"
    )


# ── D2/D3: la nota parla del tab che l'utente guarda, e non si ripete ──

def test_la_nota_non_ripete_la_frase_sulla_voce():
    """note_model_reset dice gia' «Modello E VOCE riportati al valore
    predefinito»: con tre `if` indipendenti l'utente legge due volte che la
    voce e' stata reimpostata."""
    corpo = _corpo("_showCascadeNote")
    assert re.search(r"note_model_reset[^;]*;\s*\}\s*else\s+if", corpo), (
        "la frase sulla voce non e' in un ramo `else`: si ripete quando "
        "note_model_reset l'ha gia' detto"
    )


def test_la_nota_parla_del_tab_che_l_utente_guarda():
    """Il reset di una voce che sta nell'altro tab e' l'annuncio di un cambio
    che l'utente non vede: la nota deve filtrare per wizardState.audioTab.

    Definire il filtro non basta: va APPLICATO. Gli assert sotto ritagliano la
    condizione di ciascuno dei due rami filtrabili e pretendono la chiamata al
    predicato dentro quella condizione. Cercare la sottostringa `dove` non
    morderebbe: sopravvive nella definizione del predicato anche quando
    nessuno lo chiama piu'.
    """
    piatto = _codice(_corpo("_showCascadeNote"))
    m_tab = re.search(r"(?:const|let|var)(\w+)=\(wizardState&&wizardState\.audioTab\)", piatto)
    assert m_tab, "_showCascadeNote non guarda piu' quale tab e' attivo"
    tab_visto = m_tab.group(1)
    m_pred = re.search(r"(?:const|let|var)(\w+)=(\w+)=>([^;]+);", piatto)
    assert m_pred, "_showCascadeNote non definisce piu' il predicato «e' il tab che guardo»"
    predicato, parametro, corpo_pred = m_pred.group(1), m_pred.group(2), m_pred.group(3)
    assert parametro + ".dove" in corpo_pred and tab_visto in corpo_pred, (
        "il predicato non confronta piu' il tab di provenienza del cambiamento "
        "con il tab attivo: %r" % corpo_pred
    )
    for chiave in ("note_voice_reset", "note_accent_reset"):
        posizione = piatto.index("t('" + chiave + "')")
        inizio = piatto.rfind("changes.some(", 0, posizione)
        assert inizio != -1, "%s non e' piu' deciso da changes.some(): %s" % (chiave, piatto)
        condizione = piatto[inizio:posizione]
        assert predicato + "(" + parametro + ")" in condizione, (
            "%s viene mostrata senza filtrare sul tab attivo: annuncerebbe il "
            "reset di un controllo che l'utente non ha davanti. Condizione: %r"
            % (chiave, condizione)
        )


# ── M2: i ripieghi delle etichette scattano davvero, e sono in inglese ──

def test_i_ripieghi_delle_etichette_sono_raggiungibili():
    """`t(k)||ripiego` e' codice morto: t() ritorna la CHIAVE quando la
    traduzione manca, e una chiave e' una stringa vera. Se `lbl_model_flash31`
    sparisse dall'i18n, l'utente leggerebbe `lbl_model_flash31` nel selettore
    del modello."""
    corpo = _corpo("_modelLabel")
    assert "||'" not in corpo.replace(" ", ""), (
        "_modelLabel usa ancora `t(k)||ripiego`, che non scatta mai"
    )
    aiuto = _corpo("_tOr")
    assert "!==k" in aiuto.replace(" ", ""), (
        "_tOr non riconosce il caso «t() ha restituito la chiave»: "
        "il ripiego resta irraggiungibile"
    )


def test_i_ripieghi_delle_etichette_sono_in_inglese():
    """Vincolo globale: le stringhe non localizzate vanno in inglese. Un
    ripiego italiano, se scattasse, scatterebbe per tutti."""
    corpo = _corpo("_modelLabel")
    ripieghi = re.findall(r"_tOr\('[^']*',\s*'([^']*)'\)", corpo)
    assert set(ripieghi) == {
        "Audiobook Maker (VOXCPM2)", "Standard", "Advanced",
        "Express (English only)",
    }, "ripieghi di _modelLabel cambiati o tradotti: %s" % sorted(ripieghi)
    # Il divieto sui nomi dei fornitori vale su cio' che l'utente LEGGE: la
    # chiave `lbl_model_simba` e' un identificatore e resta legittima, quindi
    # si guardano i ripieghi uno per uno, non il corpo della funzione.
    for ripiego in ripieghi:
        for parola in PAROLE_VIETATE:
            assert parola not in ripiego.lower(), (
                "ripiego di _modelLabel con un nome di fornitore: %r" % ripiego
            )


# ── M4: 'forced' e' una provenienza accertata quanto le altre due ──

def test_init_book_language_accetta_la_lingua_scelta_dall_utente():
    """Dopo l'adozione di una traduzione il server risponde
    language_source='forced'. Se il client non la riconoscesse, la
    normalizzerebbe a 'unknown' e riproporrebbe il modale di conferma su una
    lingua che l'utente ha scelto lui."""
    corpo = _corpo("initBookLanguage")
    # Sull'ESPRESSIONE, non sulla stringa: 'forced' compare anche nel commento
    # che elenca le provenienze, e un `in corpo` resterebbe verde su un codice
    # che quella provenienza non la riconosce piu'.
    assert "raw==='forced'" in corpo.replace(" ", ""), (
        "initBookLanguage non riconosce language_source='forced': la lingua "
        "adottata tornerebbe 'ipotizzata'"
    )


# ── I3: le due copie della tabella accenti devono coincidere ──

def _accent_catalog_dal_js():
    """{lingua: [codici]} letto da `const _ACCENT_CATALOG={...}` di app.js.

    E' la copia che il dropdown VIVO usa davvero (_updateAccentDropdown): non
    quella nuova della cascata, che l'accento premium non lo calcola nemmeno.
    """
    inizio = APP_JS.index("const _ACCENT_CATALOG=")
    apertura = APP_JS.index("{", inizio)
    profondita = 0
    for i in range(apertura, len(APP_JS)):
        if APP_JS[i] == "{":
            profondita += 1
        elif APP_JS[i] == "}":
            profondita -= 1
            if profondita == 0:
                blocco = APP_JS[apertura:i + 1]
                break
    else:
        raise AssertionError("_ACCENT_CATALOG non bilanciato in app.js")
    # Il blocco e' JSON a meno delle chiavi senza virgolette e degli apici
    # singoli. Convertirlo e' piu' onesto di una regex: sulle liste annidate
    # una regex non greedy si ferma alla prima `]` interna e restituisce liste
    # vuote, che confrontate fra loro passerebbero sempre.
    grezzo = re.sub(r"([A-Za-z_]\w*)\s*:", r'"\1":', blocco).replace("'", '"')
    tabella = json.loads(grezzo)
    return {lingua: [codice for codice, _chiave in varianti]
            for lingua, varianti in tabella.items()}


def test_le_due_tabelle_degli_accenti_coincidono():
    """La fonte di verita' e' gemini_tts.ACCENT_VARIANTS: e' quella che il
    server usa per ancorare l'accento di ogni chunk. app.js ne tiene una copia
    per popolare il dropdown.

    Senza questo confronto, aggiungere una variante da una parte sola resta
    invisibile: la suite passa, i test `node` passano, e l'utente o non vede
    l'accento nuovo (aggiunto solo lato server) o lo sceglie e il server lo
    ignora (aggiunto solo lato client).
    """
    import gemini_tts

    dal_js = _accent_catalog_dal_js()
    assert all(dal_js.values()), (
        "il lettore di _ACCENT_CATALOG ha restituito liste vuote: il confronto "
        "qui sotto passerebbe senza guardare niente"
    )
    dal_server = {lingua: [codice for codice, _descrizione in varianti]
                  for lingua, varianti in gemini_tts.ACCENT_VARIANTS.items()}
    assert set(dal_js) == set(dal_server), (
        "lingue con varianti d'accento diverse fra app.js e gemini_tts:\n"
        "  solo in app.js: %s\n  solo nel server: %s"
        % (sorted(set(dal_js) - set(dal_server)), sorted(set(dal_server) - set(dal_js)))
    )
    for lingua in sorted(dal_server):
        assert set(dal_js[lingua]) == set(dal_server[lingua]), (
            "accenti di %r diversi: app.js=%s, gemini_tts=%s"
            % (lingua, dal_js[lingua], dal_server[lingua])
        )
        assert dal_js[lingua][0] == dal_server[lingua][0], (
            "il PRIMO accento di %r (il default della lingua) non coincide: "
            "app.js=%r, gemini_tts=%r"
            % (lingua, dal_js[lingua][0], dal_server[lingua][0])
        )
