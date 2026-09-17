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


VC = VC_PATH.read_text(encoding="utf-8")
CSS = (ROOT / "static/css/style.css").read_text(encoding="utf-8")

TASK2_KEYS = ["vc_btn_start", "vc_btn_mine", "vc_btn_resume", "vc_btn_tip", "vc_resume_banner",
              "vc_resume_btn", "vc_title", "vc_p1_intro", "vc_p1_t1", "vc_p1_t2", "vc_p1_t3",
              "vc_p1_t4", "vc_p1_t5", "vc_p1_price_lbl", "vc_price", "vc_price_free", "vc_consent",
              "vc_next", "vc_cancel", "vc_back", "vc_close", "vc_err_generic",
              "vc_err_rate_limited", "vc_err_voice_clone_disabled"]


def test_script_voice_clone_prima_di_app():
    assert 'src="/static/js/voice_clone.js?v=__APP_VERSION__"' in TAIL
    assert TAIL.index("voice_clone.js") < TAIL.index("/static/js/app.js")


def test_markup_bottone_e_modal():
    for i in ("vcBtnRow", "vcOpenBtn", "vcResumeBanner", "vcResumeBtn", "vcModal", "vcClose",
              "vcErr", "vcP1", "vcConsent", "vcP1Next", "vcP1Cancel", "vcP2", "vcP3", "vcP4", "vcPMine"):
        assert f'id="{i}"' in HTML, i
    # Il microfono e il banner di ripresa vivono DENTRO #tabPremium, subito
    # dopo la combo delle voci: sulla scheda Standard non esistono proprio.
    # (`voxcpmSampleRow` non fa piu' da estremo: il box d'ascolto e' sceso
    # accanto alla stima costo, fuori dal pannello, e li' deve restare.)
    assert (HTML.index('id="tabPremium"') < HTML.index('id="vvPremium"')
            < HTML.index('id="vcOpenBtn"') < HTML.index('id="vcBtnRow"')
            < HTML.index('id="advOptions"'))
    assert 'data-t-title="vc_btn_tip"' in HTML
    # Bottone a sola icona: un data-t sovrascriverebbe l'SVG del microfono.
    bottone = HTML[HTML.index('id="vcOpenBtn"'):HTML.index('id="vcOpenBtn"') + 400]
    assert 'data-t=' not in bottone.split('</button>')[0]
    assert '<svg' in bottone.split('</button>')[0]
    assert HTML.index('id="geminiPayModal"') < HTML.index('id="vcModal"')


def test_nucleo_puro_esportato_e_senza_dom():
    testa = VC[:VC.index("/* ---------- ramo DOM")]
    assert "document." not in testa and "window." not in testa.replace("typeof window", "")
    assert "module.exports = VcCore" in VC
    for f in ("vcPanelFor", "vcGateKey", "vcPending", "vcHasReadyFor", "vcButtonKey", "vcVisible",
              "vcUploadCheck", "vcRecordExt"):
        assert f"function {f}(" in VC


def test_app_sincronizza_il_bottone():
    for fn in ("_onPremiumModelChanged", "switchAudioTab", "updVoicesPremium"):
        assert "vcSyncButton()" in _estrai_funzione(JS, fn), fn


def test_css_vc():
    for c in (".vc-btn-row", ".vc-modal", ".vc-consent", ".vc-prompt", ".vc-code", ".vc-mine-item",
              ".vc-voice-row", ".vc-mic-btn", ".vc-cap", ".vc-up", ".vc-up-btn", ".vc-local"):
        assert c in CSS, c
    # display:inline-flex d'autore batte la regola UA [hidden]{display:none}
    assert ".vc-mic-btn[hidden]{display:none}" in CSS


def test_hidden_batte_il_display_dautore():
    """Ogni classe del wizard che imposta un display d'autore deve riaffermare
    [hidden]{display:none}: la regola UA perde comunque, e senza questa riga
    bottone, banner e spinner restano a schermo quando il JS li nasconde."""
    for c in (".btn", ".vc-btn-row", ".vc-resume", ".vc-rec-dot", ".vc-wait",
              ".vc-claim-row", ".vc-mic-btn", ".vc-mic-pick", ".vc-local", ".vc-actions"):
        atteso = re.escape(c) + r"\[hidden\]\s*\{\s*display:\s*none\s*\}"
        assert re.search(r"(?m)^" + atteso, CSS), c


def test_wizard_modale_non_si_chiude_cliccando_fuori():
    corpo = _estrai_funzione(VC, "vcInit")
    assert "vcClose" in corpo, "la X deve chiudere"
    assert "ev.target === modal" not in corpo and "addEventListener('click'" not in corpo


def test_accento_nascosto_se_la_lingua_ne_ha_uno_solo():
    assert 'id="vcLocaleWrap"' in HTML
    corpo = _estrai_funzione(VC, "vcFillLocales")
    assert "vcLocaleWrap" in corpo and "list.length < 2" in corpo
    # label{display:block} e' d'autore e batte [hidden]{display:none} della UA:
    # senza la guardia la combo restava a schermo anche per l'italiano.
    assert re.search(r"(?m)^#vcLocaleWrap\[hidden\]\s*\{\s*display:\s*none\s*\}", CSS)


def test_chiavi_task2_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK2_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"


def test_nessun_nome_di_fornitore_nelle_chiavi_vc():
    for blocco in re.findall(r"Object\.assign\(L\.[a-z]+,\{(.*?)\}\);", I18N, re.S):
        for k, v in re.findall(r"(vc_[a-z_0-9]+)\s*:\s*\"((?:[^\"\\]|\\.)*)\"", blocco):
            for brand in ("VoxCPM", "DeepSeek", "Gemini", "RunPod", "Google", "Microsoft"):
                assert brand.lower() not in v.lower(), f"{k}: {brand}"


def test_hindi_in_devanagari():
    chiavi_hi = re.findall(r"Object\.assign\(L\.hi,\{(.*?)\}\);", I18N, re.S)
    testo = "".join(b for b in chiavi_hi if "vc_" in b)
    assert re.search(r"[ऀ-ॿ]", testo), "le stringhe vc_ in hindi devono essere in devanagari"


TASK3_KEYS = ["vc_lang", "vc_locale", "vc_gender", "vc_gender_f", "vc_gender_m", "vc_p2_read",
              "vc_setup_t", "vc_setup_intro", "vc_name", "vc_name_ph", "vc_name_hint", "vc_rename", "vc_save",
              "vc_rec_start", "vc_rec_stop", "vc_rec_cancel", "vc_or", "vc_up_offer", "vc_up_pick", "vc_up_hint",
              "vc_mic", "vc_mic_default", "vc_local_listen", "vc_checking", "vc_sample_listen",
              "vc_sample_ok", "vc_sample_redo", "vc_err_no_mic", "vc_err_too_large",
              "vc_gate_short", "vc_gate_long", "vc_gate_noise", "vc_gate_pauses", "vc_gate_nopause",
              "vc_gate_band", "vc_gate_clip", "vc_gate_transcript", "vc_gate_format", "vc_gate_asr",
              "vc_gate_generic", "vc_gate_heard", "vc_err_asr_unavailable", "vc_err_sample_rejected"]


def test_markup_pannello_2():
    p2 = HTML[HTML.index('id="vcP2"'):HTML.index('id="vcP3"')]
    for i in ("vcPromptText", "vcMic", "vcMicWrap", "vcRecBtn",
              "vcRecCancel", "vcLevel", "vcTimer", "vcFile", "vcUpName", "vcUpMb", "vcLocalBlock",
              "vcLocalAudio", "vcErr2", "vcSampleBlock", "vcSampleAudio", "vcSampleRedo",
              "vcSampleNext", "vcP2Back", "vcSampleActions"):
        assert f'id="{i}"' in p2, i
    assert 'accept=".wav,.mp3,.webm,.opus,.ogg,.m4a,.mp4' in p2
    for altrove in ("vcLang", "vcLocale", "vcGender"):
        assert altrove not in p2, altrove + ": le scelte stanno nel passo che viene prima"


def test_markup_pannello_delle_scelte():
    """Lingua, accento e voce sono un passo a se': sopra il brano erano tre
    combo di servizio, e invece decidono proprio il testo da leggere."""
    ps = HTML[HTML.index('id="vcPSetup"'):HTML.index('id="vcP2"')]
    for i in ("vcLang", "vcLocaleWrap", "vcLocale", "vcGender",
              "vcGenderIcoF", "vcGenderIcoM", "vcSetupBack", "vcSetupNext"):
        assert 'id="' + i + '"' in ps, i
    for k in ("vc_setup_t", "vc_setup_intro", "vc_lang", "vc_locale", "vc_gender"):
        assert 'data-t="' + k + '"' in ps, k
    # un'icona per ogni campo (tre combo, il nome e il dispositivo), dentro il campo
    assert ps.count('class="vc-pick-ico"') >= 2 and ps.count("<svg") == 6
    assert ps.index('id="vcPSetup"') < HTML.index('id="vcP2"')
    for c in (".vc-picks", ".vc-pick-ico", ".vc-pick-in select"):
        assert c + "{" in CSS, c
    assert ".vc-pick[hidden]{display:none}" in CSS, "il wrap dell'accento si nasconde davvero"


def test_il_wizard_infila_le_scelte_fra_condizioni_e_brano():
    mostra = _estrai_funzione(VC, "vcShow")
    assert "'vcPSetup'" in mostra and "n === 'setup'" in mostra
    uno = _estrai_funzione(VC, "vcInitPanel1")
    assert "vcShow('setup')" in uno, "dalle condizioni si passa alle scelte"
    due = _estrai_funzione(VC, "vcInitPanel2")
    assert "vcShow('setup')" in due, "«indietro» dal brano torna alle scelte"
    assert "vcFillLangs()" not in due, "le combo le riempie il passo delle scelte"
    setup = _estrai_funzione(VC, "vcInitPanelSetup")
    assert "vcFillLangs()" in setup and "!ls.options.length" in setup,         "ripopolare a ogni ritorno azzererebbe la scelta appena fatta"
    assert "vcShow(2)" in setup and "vcShow(1)" in setup
    assert "S.panelHooks.vcPSetup = vcInitPanelSetup;" in VC


def test_l_icona_della_voce_segue_la_scelta():
    corpo = _estrai_funzione(VC, "vcSyncGenderIcon")
    assert "vcGenderIcoF" in corpo and "vcGenderIcoM" in corpo
    assert "g.value !== 'f'" in corpo and "g.value !== 'm'" in corpo
    setup = _estrai_funzione(VC, "vcInitPanelSetup")
    assert "g.onchange = vcSyncGenderIcon" in setup


def test_il_caricamento_sparisce_mentre_si_registra_e_si_verifica():
    """Registrare e caricare sono strade alternative: il riquadro tratteggiato,
    mentre una delle due e' in corso, ruba la scena all'attesa."""
    p2 = HTML[HTML.index('id="vcP2"'):HTML.index('id="vcP3"')]
    assert 'id="vcUpBlock"' in p2
    # il riquadro e lo spinner si scambiano il posto: stesso punto del pannello
    assert p2.index('id="vcUpBlock"') < p2.index('id="vcUploading"') < p2.index('id="vcLocalBlock"')
    assert "#vcUpBlock[hidden]{display:none}" in CSS

    mostra = _estrai_funzione(VC, "vcSetUploadVisible")
    assert "vcUpBlock" in mostra and "hidden = !on" in mostra
    # sparisce alla partenza della registrazione...
    assert "vcSetUploadVisible(false)" in _estrai_funzione(VC, "vcSetRecording")
    # ...e per tutta la verifica del campione; allo scarto (e all'errore di
    # rete) resta chiuso e torna solo come link sotto il messaggio
    carica = _estrai_funzione(VC, "vcUploadSample")
    assert carica.count("vcSetUploadVisible(false)") == 1
    assert carica.count("vcSetUploadVisible(false, true)") == 2
    assert "vcSetUploadVisible(true)" not in carica
    # un annullo non diventa mai un campione: li' il riquadro torna subito
    assert "vcSetUploadVisible(true)" in _estrai_funzione(VC, "vcAbortMedia")
    assert "vcSetUploadVisible(true)" in _estrai_funzione(VC, "vcInitPanel2")


def test_errore_sotto_registrazione_e_caricamento():
    """L'utente guarda i comandi, non la testata del modal: il messaggio di
    scarto deve comparire sotto la cattura, non sopra il pannello."""
    p2 = HTML[HTML.index('id="vcP2"'):HTML.index('id="vcP3"')]
    assert p2.index('id="vcRecBtn"') < p2.index('id="vcErr2"')
    assert p2.index('class="vc-up"') < p2.index('id="vcErr2"')
    corpo = _estrai_funzione(VC, "vcErr")
    assert "vcErr2" in corpo and "vcP2" in corpo


def test_microfono_in_uso_esplicito():
    corpo = _estrai_funzione(VC, "vcFillMics")
    assert "enumerateDevices" in corpo and "audioinput" in corpo
    assert "vc_mic_default" in corpo
    rec = _estrai_funzione(VC, "vcStartRecording")
    # il microfono scelto viaggia nei vincoli e la lista si rifa' con i nomi
    # leggibili solo dopo che il permesso e' stato concesso
    assert "deviceId = {exact: voluto}" in rec
    assert "vcFillMics(conf.deviceId || voluto)" in rec
    assert "vcFillMics()" in _estrai_funzione(VC, "vcInitPanel2")


def test_registrazione_annullabile_in_corsa():
    """Chi si accorge di aver letto male butta via il tentativo senza
    aspettare il verdetto: il bottone esiste solo mentre si registra."""
    corpo = _estrai_funzione(VC, "vcCancelRecording")
    assert "vcAbortMedia()" in corpo
    assert "ann.hidden = !on" in _estrai_funzione(VC, "vcSetRecording")
    assert "$('vcRecCancel').onclick = vcCancelRecording" in _estrai_funzione(VC, "vcInitPanel2")


def test_registrazione_riascoltabile_anche_se_scartata():
    corpo = _estrai_funzione(VC, "vcSetLocalAudio")
    assert "createObjectURL" in corpo and "revokeObjectURL" in corpo
    up = _estrai_funzione(VC, "vcUploadSample")
    assert "vcSetLocalAudio(blob)" in up, "la copia locale nasce prima dell'invio"
    assert "vcSetLocalAudio(null)" in up, "accettato il campione, resta un solo lettore"
    assert "vcSetLocalAudio(null)" in _estrai_funzione(VC, "vcClose")


def test_limite_mb_scritto_non_promesso():
    """`data-t` applica t() senza sostituzioni: un {mb} nella frase resterebbe
    a video tale e quale, com'era in vc_or_upload."""
    p2 = HTML[HTML.index('id="vcP2"'):HTML.index('id="vcP3"')]
    assert 'id="vcUpMb"' in p2
    assert "{mb}" not in p2
    corpo = _estrai_funzione(VC, "vcInitPanel2")
    assert "mb.textContent" in corpo and "max_upload_mb" in corpo
    for lang in LANGS:
        for blocco in re.findall(r"Object\.assign\(L\." + lang + r",\{(.*?)\}\);", I18N, re.S):
            for _k, v in re.findall(r'(vc_up_hint|vc_or|vc_up_pick):"([^"]*)"', blocco):
                assert "{" not in v, f"{lang}: segnaposto in una chiave applicata con data-t"


def test_registratore_senza_filtri_e_con_stop_automatico():
    assert "echoCancellation: false" in VC
    assert "noiseSuppression: false" in VC
    assert "autoGainControl: false" in VC
    # Il tetto della cattura deve stare SOPRA la finestra del gate: se si
    # spegnesse prima, la registrazione verrebbe troncata a meta' dell'ultima
    # frase e poi scartata come «troppo corta» per colpa nostra.
    import voice_clone_audio
    m = re.search(r"REC_MAX_MS = (\d+)", VC)
    assert m, "tetto di registrazione assente"
    assert int(m.group(1)) / 1000.0 > voice_clone_audio.Gate().max_sec
    assert "/api/voice_clone/sample" in VC
    assert "vcUploadCheck(f.name, f.size" in VC


def test_upload_campione_ha_guardia_anti_doppio_invio():
    corpo = _estrai_funzione(VC, "vcUploadSample")
    assert "vcSetBusy(true)" in corpo
    assert "vcSetBusy(false)" in corpo


def test_onstop_pulisce_solo_se_e_ancora_il_proprietario_di_s_media():
    corpo = _estrai_funzione(VC, "vcStartRecording")
    assert "S.media && S.media.rec === rec" in corpo


def test_registrazione_annullata_non_carica_il_campione():
    """I2: chiudere il modal o tornare indietro dal pannello 2 deve annullare
    la registrazione in corso PRIMA di fermarla, cosi' rec.onstop non invia
    nulla al server. Lo stop manuale (bottone) e quello automatico a 25s
    restano conferme: caricano come sempre, passando da vcStopMedia()."""
    corpo_start = _estrai_funzione(VC, "vcStartRecording")
    assert "aborted" in corpo_start, "la sessione deve tracciare un flag aborted"
    onstop_idx = corpo_start.index("rec.onstop")
    onstop = corpo_start[onstop_idx:]
    assert re.search(r"if\s*\(session\.aborted\)\s*return;", onstop), \
        "onstop deve saltare l'upload quando la sessione e' stata annullata"
    assert onstop.index("session.aborted") < onstop.index("vcUploadSample("), \
        "il controllo aborted deve precedere l'upload"

    corpo_abort = _estrai_funzione(VC, "vcAbortMedia")
    assert "aborted = true" in corpo_abort
    assert "vcStopMedia()" in corpo_abort
    assert corpo_abort.index("aborted = true") < corpo_abort.index("vcStopMedia()"), \
        "il flag va marcato PRIMA di fermare la registrazione"

    chiusura = _estrai_funzione(VC, "vcClose")
    assert "S.abortMedia" in chiusura, "vcClose deve annullare, non solo fermare, la registrazione"

    corpo_p2 = _estrai_funzione(VC, "vcInitPanel2")
    assert "vcAbortMedia()" in corpo_p2, "il tasto Indietro del pannello 2 deve annullare la registrazione"


def test_motivo_di_scarto_col_prefisso_del_server():
    """Il server risponde `reason: "vc_gate_short"`, non `"short"`: senza
    normalizzare il prefisso ogni scarto finiva su vc_gate_generic e l'utente
    leggeva sempre e solo «Campione non accettato»."""
    corpo = _estrai_funzione(VC, "vcGateKey")
    assert "replace(/^vc_gate_/, '')" in corpo


def test_messaggio_di_scarto_esplicativo():
    """Tutti i motivi (non solo il primo), i secondi misurati, la finestra
    ammessa presa dalla config e, sul testo, quello che l'ASR ha capito."""
    chiavi = _estrai_funzione(VC, "vcGateKeys")
    assert "metrics" in chiavi and "reasons" in chiavi
    msg = _estrai_funzione(VC, "vcRejectMsg")
    for atteso in ("vcGateKeys(d)", "mt.duration", "cfg.min_sec", "cfg.max_sec",
                   "vc_gate_heard", "join(' ')"):
        assert atteso in msg, atteso
    assert "vcRejectMsg(d)" in _estrai_funzione(VC, "vcApiErrMsg")


def test_durata_e_limiti_nei_messaggi_di_durata():
    """I secondi misurati e la finestra ammessa entrano nel testo: le soglie
    stanno nella config (env), non possono restare cablate nella frase."""
    segnaposto = {"vc_gate_short": ("{got}", "{min}"),
                  "vc_gate_long": ("{got}", "{max}"),
                  "vc_gate_heard": ("{heard}",)}
    for lang in LANGS:
        for blocco in re.findall(r"Object\.assign\(L\." + lang + r",\{(.*?)\}\);", I18N, re.S):
            for k, v in re.findall(r'(vc_gate_short|vc_gate_long|vc_gate_heard):"([^"]*)"', blocco):
                for p in segnaposto[k]:
                    assert p in v, f"{lang}/{k}: manca {p}"


def test_chiavi_task3_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK3_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"


TASK4_KEYS = ["vc_p3_intro", "vc_email", "vc_email2", "vc_p3_sample_ok", "vc_p3_redo",
              "vc_p3_discard", "vc_p3_discard_ask", "vc_p3_demos_t", "vc_p3_email_warn",
              "vc_pay_btn", "vc_pay_btn_free",
              "vc_pay_title", "vc_pay_line", "vc_pay_notice", "vc_err_email_bad", "vc_err_email_mismatch",
              "vc_err_email_has_voice", "vc_resend_manage", "vc_resend_manage_ok",
              "vc_err_payment_invalid", "vc_err_voice_not_found",
              "vc_err_voice_gone", "vc_err_not_authorized", "vc_err_bad_request"]


def test_markup_pannello_3():
    p3 = HTML[HTML.index('id="vcP3"'):HTML.index('id="vcP4"')]
    for i in ("vcP3Sample", "vcP3Redo", "vcP3Discard", "vcP3DiscardAsk", "vcP3DiscardYes",
              "vcP3DiscardNo", "vcEmail", "vcEmail2",
              "vcPrice", "vcP3Back", "vcPayBtn"):
        assert f'id="{i}"' in p3, i
    assert "vcExtraSel" not in p3, "il secondo brano lo sceglie il server, non l'utente"


def test_il_campione_gia_accettato_si_riascolta_dal_pagamento():
    """Chi chiude la finestra dopo che il campione e' passato non sa che la
    bozza vive sul server: riaprendo si trovava davanti al pagamento senza
    sapere che cosa stesse pagando."""
    corpo = _estrai_funzione(VC, "vcInitPanel3")
    assert "/sample.wav" in corpo and "vcP3Sample" in corpo
    assert "vcShow(2)" in corpo, "da qui si deve poter rifare il campione"


def test_bozza_abbandonabile_prima_del_pagamento():
    """Il link di gestione arriva solo con l'email, cioe' dopo il pagamento:
    senza questa via d'uscita la bozza resterebbe in piedi fino alla scadenza
    e il bottone del campionamento direbbe «riprendi» per sempre."""
    corpo = _estrai_funzione(VC, "vcDiscardDraft")
    assert "/discard" in corpo
    assert "vcRefreshMine()" in corpo and "vcShow(1)" in corpo
    init = _estrai_funzione(VC, "vcInitPanel3")
    assert "vcP3DiscardYes" in init and "vcP3DiscardAsk" in init
    assert "window.confirm" not in VC, "la conferma e' in linea, come per il rifiuto delle prove"


def test_il_pannello_del_pagamento_non_cita_i_testi_dei_brani():
    """Del pagamento interessa che cosa succede dopo, non che cosa si leggera':
    i due brani citati per esteso spingevano il prezzo e il bottone sotto la
    piega. Resta la sola riga che spiega il seguito."""
    p3 = HTML[HTML.index('id="vcP3"'):HTML.index('id="vcP4"')]
    assert 'data-t="vc_p3_demos_t"' in p3
    for morto in ("vcCommonText", "vc-quote", "vc_p3_common", "vc_p3_extra_auto"):
        assert morto not in p3, morto
    for morto in ("vcLoadCommonText", "S.extraLoadedFor", "demo_texts",
                  "vcExtraSel", "vcExtraText", "S.extraTexts", "vcShowExtraText"):
        assert morto not in VC, morto
    assert "vc_p3_common" not in I18N and "vc_p3_extra_auto" not in I18N


def test_il_secondo_brano_lo_sorteggia_il_server():
    """La combo prima del pagamento faceva scegliere fra brani equivalenti:
    una decisione senza conseguenze piazzata nel punto piu' delicato."""
    corpo = _estrai_funzione(VC, "vcCommit")
    assert "extra_id" not in corpo


def test_email_verificata_subito_non_dopo_il_pagamento():
    """Il conflitto «questa email ha gia' una voce» si scopriva dentro commit,
    cioe' a pagamento avvenuto: il peggior momento possibile."""
    corpo = _estrai_funzione(VC, "vcCheckEmailTaken")
    assert "/api/voice_clone/check_email" in corpo
    assert "vc_err_email_has_voice" in corpo
    assert "pb.disabled = true" in corpo, "finche' e' occupata non si paga"
    init = _estrai_funzione(VC, "vcInitPanel3")
    assert init.count("vcCheckEmailTaken") >= 2, "vanno agganciati entrambi i campi"
    assert "S.emailTaken" in _estrai_funzione(VC, "vcEmailsOk"),         "anche il click su «paga» deve rispettare l'esito del controllo"


def test_avviso_sull_email_sotto_i_campi():
    p3 = HTML[HTML.index('id="vcP3"'):HTML.index('id="vcP4"')]
    assert 'data-t="vc_p3_email_warn"' in p3
    assert p3.index('id="vcEmail2"') < p3.index('data-t="vc_p3_email_warn"') < p3.index('vc_p3_demos_t')
    assert ".vc-warn{" in CSS


def test_errore_email_sotto_i_campi():
    """In cima al modal il messaggio finiva fuori dallo sguardo di chi stava
    battendo l'indirizzo: va letto dove si e' scritto."""
    p3 = HTML[HTML.index('id="vcP3"'):HTML.index('id="vcP4"')]
    assert p3.index('id="vcEmail2"') < p3.index('id="vcErr3"') < p3.index('vc_p3_email_warn')
    corpo = _estrai_funzione(VC, "vcErr")
    assert "vcErr3" in corpo and "vcP3" in corpo
    # le caselle vecchie vanno comunque svuotate, o il messaggio resta doppio
    assert corpo.count("vcErr3") >= 2


def test_bottone_per_farsi_rimandare_il_link_di_gestione():
    """L'indirizzo si libera solo cancellando la vecchia voce dal link di
    gestione: se quell'email e' persa, senza questo bottone non se ne esce."""
    p3 = HTML[HTML.index('id="vcP3"'):HTML.index('id="vcP4"')]
    assert p3.index('id="vcErr3"') < p3.index('id="vcResendManage"')
    assert 'data-t="vc_resend_manage"' in p3
    assert "#vcResendManageWrap" in HTML or ".vc-resend-manage[hidden]{display:none}" in CSS
    corpo = _estrai_funzione(VC, "vcResendManage")
    assert "/api/voice_clone/resend_manage" in corpo
    assert "vc_resend_manage_ok" in corpo
    # compare solo quando l'indirizzo risulta occupato
    chk = _estrai_funzione(VC, "vcCheckEmailTaken")
    assert "vcResendManageWrap" in chk and "!S.emailTaken" in chk
    init = _estrai_funzione(VC, "vcInitPanel3")
    assert "vcResendManage" in init and "w.hidden = true" in init


def test_le_conferme_non_escono_in_rosso():
    """Le caselle dei messaggi sono le stesse degli errori: una conferma in
    rosso si legge come un guaio."""
    corpo = _estrai_funzione(VC, "vcErr")
    assert "al al-ok" in corpo and "al al-e" in corpo
    assert ".al-ok{" in CSS


def test_il_conflitto_email_si_ricontrolla_al_rientro():
    """Chi va a cancellare la vecchia voce dal link dell'email lo fa in
    un'altra scheda: al ritorno il divieto deve cadere da solo."""
    corpo = _estrai_funzione(VC, "vcRicontrollaEmailAlRitorno")
    assert "document.hidden" in corpo and "vcModal" in corpo and "vcP3" in corpo
    assert "vcCheckEmailTaken()" in corpo
    init = _estrai_funzione(VC, "vcInit")
    assert "visibilitychange" in init and "vcRicontrollaEmailAlRitorno" in init
    # e anche chi rientra nel pannello con i campi gia' pieni
    assert "vcCheckEmailTaken();" in _estrai_funzione(VC, "vcInitPanel3")


def test_dopo_il_pagamento_si_parte_senza_conferma():
    """Il countdown di cinque secondi ha senso dove resta qualcosa da
    decidere; qui il pagamento e' l'ultimo passo e l'elaborazione parte."""
    assert "autoConfirm: true" in _estrai_funzione(VC, "vcPay")
    dopo = _estrai_funzione(JS, "_payAfterPaid")
    assert "_payCtx.autoConfirm" in dopo and "onPayConfirm()" in dopo
    # PayPal e buoni: due strade, stessa regola.
    assert "if(!_payAfterPaid())_armPayConfirm();" in JS
    assert "_payAfterPaid();" in _estrai_funzione(JS, "validateVoucherForPayment")


def test_form_email_allineato():
    """Le due email erano label d'autore (display:block, maiuscolo) con dentro
    un input inline a larghezza di default: etichette e campi disallineati."""
    p3 = HTML[HTML.index('id="vcP3"'):HTML.index('id="vcP4"')]
    assert p3.count('class="vc-fld"') >= 2
    assert re.search(r"(?m)^\.vc-fld input,\.vc-fld select\{width:100%", CSS)
    for c in (".vc-form", ".vc-card", ".vc-demos-t", ".vc-warn"):
        assert c + "{" in CSS, c


def test_pagamento_passa_dal_modal_esistente():
    assert "_openPayModalCtx({" in VC
    assert "voucherPurpose: 'voice_clone'" in VC
    assert "endpoint: '/api/paypal_create_order_voice_clone'" in VC
    assert "captureJobId: 'vc:' + S.cur.clone_id" in VC
    assert "geminiAmount: 0" in VC
    assert "/api/voice_clone/commit" in VC


def test_capture_paypal_usa_capture_job_id():
    corpo = _estrai_funzione(JS, "renderPaypalGeminiButtons")
    assert "captureJobId" in corpo
    corpo2 = _estrai_funzione(JS, "_openPayModalCtx")
    assert "titleKey" in corpo2 and "noticeKey" in corpo2


def test_chiavi_task4_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK4_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"


def test_vcsetbusy_blocca_anche_i_controlli_del_pannello_3():
    corpo = _estrai_funzione(VC, "vcSetBusy")
    assert "vcP3Back" in corpo
    assert "vcPayBtn" in corpo


def test_vccommit_usa_la_guardia_anti_doppio_invio():
    corpo = _estrai_funzione(VC, "vcCommit")
    assert "vcSetBusy(true)" in corpo
    assert corpo.count("vcSetBusy(false)") >= 2, "serve su successo, errore applicativo ed errore di rete"
    assert "btn.disabled" not in corpo, "il bottone va gestito solo via vcSetBusy, non a mano"


def test_vcp3back_rispetta_lo_stato_busy():
    corpo = _estrai_funzione(VC, "vcInitPanel3")
    m = re.search(r"vcP3Back'\)\.onclick\s*=\s*function\s*\(\)\s*\{([^}]*)\}", corpo)
    assert m, "onclick di vcP3Back non trovato"
    assert "if (S.busy) return;" in m.group(1)


def test_il_caricamento_sparisce_col_campione_accettato():
    """Registrare e caricare sono alternative: a campione accettato il riquadro
    «scegli un file» invita a rifare quel che e' gia' fatto. Torna con «rifai»."""
    corpo = _estrai_funzione(VC, "vcUploadSample")
    assert "if (!r.ok) { vcSetUploadVisible(false, true);" in corpo, \
        "solo lo scarto offre il caricamento, come link sotto il messaggio"
    dopo = corpo[corpo.index("if (!r.ok)"):]
    dopo = dopo[dopo.index("return;"):]
    dopo = dopo[:dopo.index(".catch(")]  # la rete caduta e' un altro caso: li' torna
    assert "vcSetUploadVisible(true)" not in dopo and "vcSetUploadVisible(false, true)" not in dopo, \
        "dopo l'accettazione il riquadro non deve tornare"
    redo = _estrai_funzione(VC, "vcInitPanel2")
    m = re.search(r"vcSampleRedo'\)\.onclick\s*=\s*function\s*\(\)\s*\{([^}]*)\}", redo)
    assert m and "vcSetUploadVisible(true)" in m.group(1), \
        "«rifai il campione» deve rimettere a disposizione il caricamento"


TASK5_KEYS = ["vc_code_intro", "vc_code_note", "vc_wait", "vc_demos_intro", "vc_demo_common", "vc_demo_extra",
              "vc_approve", "vc_reject", "vc_reject_sure", "vc_yes", "vc_no",
              "vc_demo_failed", "vc_retry", "vc_done", "vc_refunded", "vc_err_bad_state"]


def test_markup_pannello_4():
    p4 = HTML[HTML.index('id="vcP4"'):HTML.index('id="vcPMine"')]
    for i in ("vcCodeBox", "vcCode", "vcWait", "vcDemos", "vcDemoCommon", "vcDemoExtra", "vcApprove",
              "vcReject", "vcRejectConfirm", "vcRejectYes",
              "vcRejectNo", "vcFailed", "vcReject2", "vcRetry", "vcDone", "vcDoneClose", "vcRefunded"):
        assert f'id="{i}"' in p4, i


def test_avanzamento_via_sse_e_decisioni():
    assert "new EventSource('/api/voice_clone/progress/'" in VC
    for a in ("'approve'", "'retry'", "'reject'"):
        assert f"vcAction({a}" in VC, a
    assert "window._vcJustCreated = view.voice_id" in VC
    assert "confirm(" not in VC.replace("vcRejectConfirm", "").replace("vcConfirm", "").replace("confirm_code", ""), "mai confirm() del browser"


def test_chiavi_task5_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK5_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"


def test_vcsetbusy_blocca_anche_i_controlli_del_pannello_4():
    corpo = _estrai_funzione(VC, "vcSetBusy")
    for i in ("vcApprove", "vcReject", "vcRetry"):
        assert i in corpo, i


def test_vcaction_usa_la_guardia_anti_doppio_invio():
    corpo = _estrai_funzione(VC, "vcAction")
    assert "if (S.busy) return" in corpo
    assert "vcSetBusy(true)" in corpo


# ---------- fix round 1 (review Task 5: F1-F4) ----------

def test_regola_small_esiste_in_css():
    """F1/M7: .vc-code-note usa la classe .vc-small (rinominata
    da .small, generica, per non collidere con classi omonime future fuori dal
    wizard voci campionate)."""
    assert re.search(r"\.vc-small\s*\{[^}]*\}", CSS), ".vc-small non definita in style.css"
    assert not re.search(r"(?<![.\w-])\.small\b", CSS), ".small non deve piu' comparire in style.css"
    assert "'small'" not in VC and 'class="small"' not in HTML, \
        "nessun uso residuo della vecchia classe .small"


def test_css_vc_niente_token_non_definiti():
    """I3: .vc-prompt/.vc-code/.vc-mine-item usavano --bg-soft/--border, mai
    definiti su :root in questo file (solo il fallback CSS li rendeva
    innocui). Devono usare i token effettivi del tema (--srf2/--brd)."""
    blocco_vc = CSS[CSS.index("/* Voci campionate */"):]
    fine = blocco_vc.find("\n\n")
    if fine != -1:
        blocco_vc = blocco_vc[:fine]
    assert "--bg-soft" not in blocco_vc
    assert "--border" not in blocco_vc
    assert "--srf2" in blocco_vc
    assert "--brd" in blocco_vc


def test_vcrenderp4_mette_in_pausa_le_prove_quando_nascoste():
    """F2: cambiando stato (retry/esito) le due prove audio non devono
    restare a suonare in sottofondo dietro lo spinner o l'esito."""
    corpo = _estrai_funzione(VC, "vcRenderP4")
    assert "vcDemoCommon" in corpo and "vcDemoExtra" in corpo
    assert ".pause()" in corpo
    assert re.search(r"if\s*\(!demosOn\)", corpo), "la pausa deve scattare solo quando i demo non sono mostrati"


def test_vcwatch_onerror_riprova_con_backoff():
    """F3: alla caduta della rete l'SSE non deve arrendersi in silenzio ne'
    ritentare a raffica: deve riarmarsi con un setTimeout crescente finche'
    lo stato resta di attesa e il pannello 4 e' ancora quello mostrato."""
    corpo = _estrai_funzione(VC, "vcWatch")
    assert "onerror" in corpo
    ramo_errore = corpo[corpo.index("onerror"):]
    assert "setTimeout(" in ramo_errore, "deve riarmarsi via setTimeout, non in loop stretto"
    assert "S.esTimer" in ramo_errore
    assert "vcWatch(" in ramo_errore, "il riarmo deve richiamare vcWatch"
    assert re.search(r"p4\s*&&\s*!p4\.hidden", ramo_errore), "il riarmo deve controllare che il pannello 4 sia ancora visibile"


def test_vcwatch_e_vcclose_ripuliscono_il_timer_di_retry():
    """F3: nessun riarmo zombie dopo la chiusura del modal o una vcWatch nuova."""
    chiusura = _estrai_funzione(VC, "vcClose")
    assert "S.esTimer" in chiusura and "clearTimeout" in chiusura
    corpo = _estrai_funzione(VC, "vcWatch")
    inizio = corpo[:corpo.index("es.onmessage")]
    assert "S.esTimer" in inizio and "clearTimeout" in inizio, \
        "vcWatch deve azzerare un retry precedente prima di aprire un nuovo EventSource"


def test_niente_rigenerazione_nel_pannello_4():
    """La rigenerazione delle prove e' stata tolta (lenta e poco utile): via il
    bottone, la combo delle frasi, il contatore e le chiavi che li scrivevano.
    Restano solo rifiuto e approvazione, sulla stessa riga."""
    assert "vcRegen" not in VC and "regen_left" not in VC
    assert "vcRegen" not in HTML and "vc_regen" not in HTML
    assert "vc_regen" not in I18N
    p4 = HTML[HTML.index('id="vcP4"'):HTML.index('id="vcPMine"')]
    demos = p4[p4.index('id="vcDemos"'):p4.index('id="vcFailed"')]
    riga = demos[demos.index('class="vc-footer"'):]
    riga = riga[:riga.index("</div>")]
    assert 'id="vcReject"' in riga and 'id="vcApprove"' in riga,         "rifiuto e approvazione devono stare nella stessa riga di chiusura"
    # la conferma inline resta sotto, e sparendo non deve lasciare un vuoto
    assert 'id="vcRejectConfirm" class="vc-confirm"' in demos
    assert ".vc-confirm[hidden]{display:none}" in CSS


def _return_a_livello_zero(frammento):
    """True se `frammento` contiene un `return;` FUORI da qualunque graffa
    annidata (quindi appartiene al corpo diretto della funzione esaminata, non
    a una callback/onclick interna: `function () { if (x) return; ... }` non
    deve far scattare il controllo, un `if (x) return;` nudo si')."""
    profondita = 0
    for i, c in enumerate(frammento):
        if c == '{':
            profondita += 1
        elif c == '}':
            profondita -= 1
        elif profondita == 0 and frammento[i:i + len('return;')] == 'return;':
            return True
    return False


def test_vcinitpanel4_cablaggio_sempre_eseguito():
    """I1: vcInitPanel4 non deve mai poter uscire prima di aver cablato i
    bottoni e chiamato vcRenderP4/vcWatch. Il guard di memoizzazione vive
    solo nel cablaggio delle prove, qui si controlla che vcInitPanel4 stesso non
    contenga alcun `return;` A LIVELLO ZERO (fuori da callback/onclick interne)
    che possa saltare quella coda."""
    corpo = _estrai_funzione(VC, "vcInitPanel4")
    assert "vcRenderP4(" in corpo
    prima_di_render = corpo[:corpo.index("vcRenderP4(")]
    assert not _return_a_livello_zero(prima_di_render), \
        "vcInitPanel4 non deve uscire in anticipo prima di vcRenderP4 (era il bug F4 riaperto)"


# ---------- Task 6: ripresa, pannello «Le tue voci», errori di generazione ----------

TASK6_KEYS = ["vc_mine_empty", "vc_state_ready", "vc_state_sample_ok", "vc_state_generating",
              "vc_state_demos_ready", "vc_state_demo_failed", "vc_forget", "vc_resend", "vc_resend_ok",
              "vc_claim_title", "vc_claim_intro", "vc_claim_ph", "vc_claim_btn", "vc_confirm_intro",
              "vc_confirm_ph", "vc_confirm_btn", "vc_new_voice", "vc_err_code_unknown", "vc_err_code_locked",
              "vc_err_confirm_wrong", "vc_err_confirm_expired", "vc_err_confirm_none",
              "vc_err_voice_not_authorized", "vc_err_voice_lang_mismatch",
              "vc_p1_have_code", "vc_mine_sample"]


def test_markup_pannello_mine():
    pm = HTML[HTML.index('id="vcPMine"'):]
    pm = pm[:pm.index("</section>")]
    for i in ("vcMineList", "vcClaimCode", "vcClaimBtn", "vcConfirmRow", "vcConfirmCode", "vcConfirmBtn",
              "vcMineClose", "vcNewVoice"):
        assert f'id="{i}"' in pm, i


def test_la_scheda_voce_fa_sentire_il_campione_non_la_prova():
    """Il player della scheda suonava `demo_urls.common`, cioe' una frase
    sintetizzata: chi lo apriva non riconosceva la propria voce. Ora suona il
    campione registrato, che il backend espone in `mine()`."""
    corpo = _estrai_funzione(VC, "vcRenderMine")
    assert "m.sample_url" in corpo
    assert "demo_urls" not in corpo, "la scheda non deve piu' suonare la prova generata"
    assert "vc_mine_sample" in corpo, "il player va detto cosa fa sentire"
    assert 'pub["sample_url"]' in (ROOT / "voice_clone.py").read_text(encoding="utf-8")


def test_rimanda_email_e_una_icona_accanto_al_player():
    """M: il bottone a tutta larghezza sotto la scheda diventa un'icona a
    destra del player, con la scritta solo nel tooltip."""
    corpo = _estrai_funzione(VC, "vcRenderMine")
    assert "vc-sample-row" in corpo and "vc-icon-btn" in corpo
    assert "rb.title = tt('vc_resend')" in corpo
    assert "setAttribute('aria-label', tt('vc_resend'))" in corpo, "il tooltip non basta da solo"
    assert "<svg" in corpo, "serve l'icona della busta"
    assert "mk('vc_resend'" not in corpo, "niente piu' bottone con la scritta"
    for regola in (".vc-sample-row{", ".vc-icon-btn{"):
        assert regola in CSS, regola


def test_codice_voce_raggiungibile_anche_senza_voce_propria():
    """Chi riceve un codice-voce non deve prima campionare la propria voce per
    poterlo usare: dalle condizioni si salta alla sezione che lo accetta, e
    quella sezione si apre da sola quando non c'e' nessuna voce."""
    p1 = HTML[HTML.index('id="vcP1"'):HTML.index('id="vcP2"')]
    assert 'id="vcP1Claim"' in p1 and 'data-t="vc_p1_have_code"' in p1
    assert "vcShow('mine')" in _estrai_funzione(VC, "vcInitPanel1")
    corpo = _estrai_funzione(VC, "vcInitPanelMine")
    assert "vcClaimBox" in corpo and "!S.mine.length" in corpo


def test_sezione_codice_voce_ha_uno_stile_suo():
    """La sezione era una `details` nuda con l'input di default del browser
    accanto a un bottone dell'app: bordi e altezze diversi."""
    campi = ".vc-claim-row input,.vc-claim-row textarea{"
    for regola in (".vc-claim{", ".vc-claim>summary{", campi, ".vc-linkbtn{"):
        assert regola in CSS, regola
    assert "border-radius:var(--rs)" in CSS[CSS.index(campi):CSS.index(campi) + 400]

    # il marcatore e' il triangolo vero, non un escape CSS: scritto come
    # "\25B8" era arrivato nel foglio come carattere di controllo e a video
    # si leggeva «B8» al posto della freccia.
    marcatore = CSS[CSS.index(".vc-claim>summary::before{"):]
    marcatore = marcatore[:marcatore.index("}")]
    assert "▸" in marcatore, marcatore


def test_il_foglio_di_stile_non_ha_caratteri_di_controllo():
    r"""Guardia sugli escape scritti a mano: un `content:"\25B8"` passato per
    una shell diventa il byte 0x15 e il glifo sparisce dalla pagina."""
    ammessi = (chr(10), chr(13), chr(9))
    sporchi = sorted({hex(ord(c)) for c in CSS if ord(c) < 32 and c not in ammessi})
    assert not sporchi, sporchi


def test_ripresa_e_gestione():
    assert "S.resumeId" in VC
    assert "/api/voice_clone/claim" in VC and "/api/voice_clone/confirm" in VC
    assert "'forget'" in VC and "'resend'" in VC
    assert "history.replaceState" in VC


def test_il_codice_voce_non_finisce_in_console():
    assert "console.log" not in VC


def test_app_gestisce_gli_errori_di_generazione_delle_voci_personali():
    corpo = _estrai_funzione(JS, "_handleVcGenerateError")
    for c in ("voice_gone", "voice_not_authorized", "voice_lang_mismatch"):
        assert c in corpo
    assert "t('vc_err_'+code)" in corpo
    # Nei due punti di /api/generate in app.js la variabile della risposta si
    # chiama rispettivamente `gd` (startCombinedGeneration) e `d` (startGen):
    # la funzione va richiamata in entrambi, una sola volta ciascuno.
    chiamate = JS.count("_handleVcGenerateError(gd)") + JS.count("_handleVcGenerateError(d)")
    assert chiamate >= 2, "va chiamata in entrambi i punti di errore di /api/generate"


def test_chiavi_task6_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK6_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"


def test_app_non_legge_privati_di_voice_clone():
    app_src = (ROOT / "audiobook_app.py").read_text(encoding="utf-8")
    assert "voice_clone._ACCEPTED_EXT" not in app_src
    assert "voice_clone.accepted_ext()" in app_src
    import voice_clone
    assert voice_clone.accepted_ext() == frozenset(voice_clone._ACCEPTED_EXT)
    js_ext = re.search(r"ACCEPTED_EXT = \[([^\]]+)\]", VC).group(1)
    assert set(re.findall(r"'(\w+)'", js_ext)) == set(voice_clone.accepted_ext())


def test_scarto_con_riascolto_e_messaggio_in_alto():
    """Col campione scartato il riquadro di caricamento spingeva in fondo il
    riascolto e il motivo dello scarto: resta chiuso, e sotto il messaggio un
    link lo riapre per chi preferisce passare a un file."""
    p2 = HTML[HTML.index('id="vcP2"'):HTML.index('id="vcP3"')]
    assert 'id="vcUpOffer"' in p2 and 'id="vcUpOfferBtn"' in p2
    assert 'data-t="vc_up_offer"' in p2
    assert p2.index('id="vcErr2"') < p2.index('id="vcUpOffer"') < p2.index('id="vcSampleBlock"')
    assert "#vcUpOffer[hidden]{display:none}" in CSS
    mostra = _estrai_funzione(VC, "vcSetUploadVisible")
    # riquadro aperto o registrazione in corso: il link non ha ragione d'esistere
    assert "off.hidden = !!on || !offer" in mostra
    init = _estrai_funzione(VC, "vcInitPanel2")
    assert "vcUpOfferBtn" in init and "vcSetUploadVisible(true)" in init


def test_pannello_2_layout_razionalizzato():
    """Microfono come icona e combo larga quanto la barra del livello;
    riascolto in riga con l'etichetta; «Indietro» a sinistra nella stessa riga
    delle conferme del campione."""
    p2 = HTML[HTML.index('id="vcP2"'):HTML.index('id="vcP3"')]
    mic = p2[p2.index('id="vcMicWrap"'):p2.index('</label>', p2.index('id="vcMicWrap"'))]
    assert 'class="vc-mic-ico"' in mic and 'data-t="vc_mic"' not in mic
    assert 'data-t-title="vc_mic"' in mic and 'aria-label=' in mic
    assert "grid-template-columns:subgrid" in CSS
    assert ".vc-mic-pick select{grid-column:2" in CSS
    assert ".vc-cap .vc-rec-row meter{grid-column:2" in CSS
    campione = p2[p2.index('id="vcSampleBlock"'):]
    campione = campione[:campione.index('</div>')]
    assert 'class="vc-local"' in campione and "vcSampleRedo" not in campione
    riga = p2[p2.index('class="vc-footer vc-footer-split"'):]
    assert riga.index('id="vcP2Back"') < riga.index('id="vcSampleActions"') < riga.index('id="vcSampleNext"')
    assert p2.count('class="vc-footer') == 1
    mostra = _estrai_funzione(VC, "vcSetSampleVisible")
    assert "vcSampleBlock" in mostra and "vcSampleActions" in mostra
    assert "blk.hidden" not in _estrai_funzione(VC, "vcUploadSample")
    assert "vcSetSampleVisible(false)" in _estrai_funzione(VC, "vcInitPanel2")


def test_brano_senza_passare_dalle_scelte():
    """Ripresa di una bozza accettata -> pagamento -> «Indietro»: il pannello del
    brano si apriva con lingua e voce vuote, il brano non arrivava e l'invio del
    campione tornava 400 «Dati mancanti o non validi»."""
    corpo = _estrai_funzione(VC, "vcEnsureChoices")
    assert "vcFillLangs()" in corpo and "!ls.options.length" in corpo
    # le scelte della bozza ripresa hanno la precedenza sui default
    assert "v.lang" in corpo and "v.locale" in corpo and "v.gender" in corpo
    init = _estrai_funzione(VC, "vcInitPanel2")
    assert init.index("vcEnsureChoices()") < init.index("vcLoadPrompt()")
    assert "vcShow('setup')" in init


def test_nome_della_voce_scelto_al_campionamento():
    """Il nome si sceglie nel passo delle scelte, parte col campione e prende
    il posto dell'etichetta generica nella combo e in «Le tue voci»."""
    setup = HTML[HTML.index('id="vcPSetup"'):HTML.index('id="vcP2"')]
    assert 'id="vcName"' in setup and 'maxlength="40"' in setup and 'data-t-ph="vc_name_ph"' in setup
    up = _estrai_funzione(VC, "vcUploadSample")
    assert "fd.append('name', _val('vcName'))" in up
    assert "name: _val('vcName')" in up
    assert "v.name" in _estrai_funzione(VC, "vcEnsureChoices")
    head = _estrai_funzione(VC, "vcMineHead")
    assert "m.name ||" in head and "vcRenameForm" in head and "if (m.owner)" in head
    assert "textContent = m.name" in head          # mai innerHTML col nome dell'utente
    form = _estrai_funzione(VC, "vcRenameForm")
    assert "/rename'" in form and "vcReloadCombo()" in form
    assert "o.textContent=(v.name||(v.owner?t('vc_voice_own'):t('vc_voice_shared')))" in JS


def test_riascolto_locale_corregge_la_durata_del_webm():
    """MediaRecorder scrive WebM senza Duration: il lettore parte con
    duration Infinity e la barra sembra gia' a fine corsa appena si preme
    play. Senza questo cablaggio la correzione sarebbe codice morto."""
    corpo = _estrai_funzione(VC, "vcSetLocalAudio")
    assert "vcFixDurata(" in corpo, "il lettore locale deve montare la correzione della durata"
    assert "preload = 'metadata'" in corpo, "con preload=none la durata si risolverebbe solo al play"
    assert "S.localFix" in corpo, "al cambio sorgente i listener vanno staccati"


def test_richiesta_email_in_evidenza():
    assert '<p class="vc-intro" data-t="vc_p3_intro"></p>' in HTML
    assert re.search(r"(?m)^\.vc-intro\{[^}]*font-weight:\s*600", CSS)


def test_nome_del_dispositivo_chiesto_a_ogni_autorizzazione():
    """Senza un nome, nella pagina dei dispositivi autorizzati resta solo un
    hash: il nome si chiede nel passo delle scelte (creatore) e, per il
    codice-voce, nella richiesta insieme alla presentazione: il proprietario
    li legge nell'email prima di dare il codice di conferma."""
    setup = HTML[HTML.index('id="vcPSetup"'):HTML.index('id="vcP2"')]
    assert 'id="vcDeviceName"' in setup and 'data-t="vc_device_name"' in setup
    assert 'data-t="vc_device_name_hint"' in setup
    richiesta = HTML[HTML.index('id="vcClaimCode"'):HTML.index('id="vcClaimBtn"')]
    assert 'id="vcClaimDevice"' in richiesta and 'data-t-ph="vc_device_name"' in richiesta
    assert 'id="vcClaimIdentity"' in richiesta and 'maxlength="300"' in richiesta
    assert 'data-t-ph="vc_identity_ph"' in richiesta and 'data-t="vc_identity_hint"' in richiesta
    assert "vcConfirmDevice" not in HTML and "vcConfirmDevice" not in VC
    up = _estrai_funzione(VC, "vcUploadSample")
    assert "fd.append('device_name', _val('vcDeviceName'))" in up
    conf = _estrai_funzione(VC, "vcConfirm")
    assert "device_name" not in conf
    claim = _estrai_funzione(VC, "vcClaim")
    assert "{voice_code: code, device_name: nome, identity: chi}" in claim
    assert "vc_err_device_name_required" in claim and "vc_err_identity_required" in claim
    # partita la richiesta, «Aggiungi» sparisce e i campi si bloccano
    assert 'id="vcClaimSend"' in HTML and HTML.index('id="vcClaimSend"') < HTML.index('id="vcClaimBtn"')
    assert "vcClaimSent(true)" in claim
    inviata = _estrai_funzione(VC, "vcClaimSent")
    assert "$('vcClaimSend')" in inviata and "readOnly" in inviata and "$('vcConfirmRow')" in inviata
    assert "confirm_wrong" in conf and "vcClaimSent(false)" in conf
    assert "vcClaimSent(!!S.claimSent)" in _estrai_funzione(VC, "vcInitPanelMine")
    proposta = _estrai_funzione(VC, "vcDeviceNameDefault")
    assert "device_name" in proposta and "device_name_guess" in proposta
    assert "vcDeviceNameDefault()" in _estrai_funzione(VC, "vcEnsureChoices")
    assert "device_name_guess" not in _estrai_funzione(VC, "vcInitPanelMine")
    for lang in LANGS:
        assert {"vc_device_name", "vc_device_name_hint", "vc_identity_ph", "vc_identity_hint",
                "vc_err_device_name_required", "vc_err_identity_required",
                "vc_err_claim_busy"} <= _chiavi_i18n(lang), lang


def test_rimuovi_da_questo_dispositivo_chiede_conferma():
    corpo = _estrai_funzione(VC, "vcRenderMine")
    assert "vcAskForget(m, act)" in corpo and "'forget'" not in corpo
    ask = _estrai_funzione(VC, "vcAskForget")
    assert "vc_forget_ask" in ask and "vc_forget_yes" in ask and "vc_forget_no" in ask
    assert "vcAction2(m.id, 'forget')" in ask
    for lang in LANGS:
        assert {"vc_forget_ask", "vc_forget_yes", "vc_forget_no"} <= _chiavi_i18n(lang), lang
    # la voce puo' essere arrivata da un altro: la didascalia non dice «che hai registrato»
    assert 'vc_mine_sample:"Il campione vocale registrato:"' in I18N


def test_fumetto_promozionale_delle_voci_campionate():
    # la bolla sta accanto al coachmark Premium e si apre col click sul testo
    assert 'id="vcPromoCoach"' in HTML
    blocco = HTML[HTML.index('id="vcPromoCoach"'):]
    blocco = blocco[:blocco.index("</div>")]
    assert 'onclick="_vcPromoGo()"' in blocco and 'onclick="_dismissVcPromo()"' in blocco
    assert 'data-t="vc_promo_text"' in blocco and 'data-t="vc_promo_cta"' in blocco
    for lang in LANGS:
        assert {"vc_promo_text", "vc_promo_cta"} <= _chiavi_i18n(lang), lang
    # precedenza: il fumetto esce prima del coachmark Premium e ne salta il conteggio
    hint = _estrai_funzione(JS, "maybeShowPremiumHint")
    assert hint.index("_maybeShowVcPromo()") < hint.index("_showPremiumCoach()")
    assert hint.index("if(vcPromo)return;") < hint.index("st.shows++")
    promo = _estrai_funzione(JS, "_maybeShowVcPromo")
    assert "vcPromoEligible()" in promo and "vcPromoShown()" in promo and "_dismissPremiumHint()" in promo
    # click: tab Premium, modello VoxCPM, wizard
    vai = _estrai_funzione(JS, "_vcPromoGo")
    assert vai.index("switchAudioTab('premium')") < vai.index("vm.value='voxcpm'") < vai.index("vcOpen()")
    assert "_dismissVcPromo()" in _estrai_funzione(JS, "switchAudioTab")
    # condizioni: feature attiva per la lingua, nessuna voce sul dispositivo, ogni 7 giorni
    assert "VC_PROMO_EVERY_MS = 7 * 24 * 3600 * 1000" in VC
    idx = VC.index("window.vcPromoEligible")
    elig = VC[idx:VC.index("};", idx)]
    assert "vcVisible(S.cfg" in elig and "S.mine.length" in elig and "vcPromoDue(" in elig
    assert "maybeShowPremiumHint()" in _estrai_funzione(VC, "vcInit")
