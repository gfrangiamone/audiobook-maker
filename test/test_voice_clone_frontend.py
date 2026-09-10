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
    assert HTML.index('id="voxcpmSampleRow"') < HTML.index('id="vcBtnRow"') < HTML.index('id="advOptions"')
    assert 'data-t-title="vc_btn_tip"' in HTML
    assert HTML.index('id="geminiPayModal"') < HTML.index('id="vcModal"')


def test_nucleo_puro_esportato_e_senza_dom():
    testa = VC[:VC.index("/* ---------- ramo DOM")]
    assert "document." not in testa and "window." not in testa.replace("typeof window", "")
    assert "module.exports = VcCore" in VC
    for f in ("vcPanelFor", "vcGateKey", "vcPending", "vcHasReadyFor", "vcButtonKey", "vcVisible",
              "vcUploadCheck", "vcRecordExt", "vcRegenAllowed"):
        assert f"function {f}(" in VC


def test_app_sincronizza_il_bottone():
    for fn in ("_onPremiumModelChanged", "switchAudioTab", "updVoicesPremium"):
        assert "vcSyncButton()" in _estrai_funzione(JS, fn), fn


def test_css_vc():
    for c in (".vc-btn-row", ".vc-modal", ".vc-consent", ".vc-prompt", ".vc-code", ".vc-mine-item"):
        assert c in CSS, c


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
              "vc_rec_start", "vc_rec_stop", "vc_or_upload", "vc_checking", "vc_sample_listen",
              "vc_sample_ok", "vc_sample_redo", "vc_err_no_mic", "vc_err_too_large",
              "vc_gate_short", "vc_gate_long", "vc_gate_noise", "vc_gate_pauses", "vc_gate_nopause",
              "vc_gate_band", "vc_gate_clip", "vc_gate_transcript", "vc_gate_format", "vc_gate_asr",
              "vc_gate_generic", "vc_err_asr_unavailable", "vc_err_sample_rejected"]


def test_markup_pannello_2():
    p2 = HTML[HTML.index('id="vcP2"'):HTML.index('id="vcP3"')]
    for i in ("vcLang", "vcLocale", "vcGender", "vcPromptText", "vcRecBtn", "vcLevel", "vcTimer",
              "vcFile", "vcSampleBlock", "vcSampleAudio", "vcSampleRedo", "vcSampleNext", "vcP2Back"):
        assert f'id="{i}"' in p2, i
    assert 'accept=".wav,.mp3,.webm,.opus,.ogg,.m4a,.mp4' in p2


def test_registratore_senza_filtri_e_con_stop_automatico():
    assert "echoCancellation: false" in VC
    assert "noiseSuppression: false" in VC
    assert "autoGainControl: false" in VC
    assert "REC_MAX_MS = 25000" in VC
    assert "/api/voice_clone/sample" in VC
    assert "vcUploadCheck(f.name, f.size" in VC


def test_upload_campione_ha_guardia_anti_doppio_invio():
    corpo = _estrai_funzione(VC, "vcUploadSample")
    assert "vcSetBusy(true)" in corpo
    assert "vcSetBusy(false)" in corpo


def test_onstop_pulisce_solo_se_e_ancora_il_proprietario_di_s_media():
    corpo = _estrai_funzione(VC, "vcStartRecording")
    assert "S.media && S.media.rec === rec" in corpo


def test_chiavi_task3_in_tutte_le_lingue():
    for lang in LANGS:
        chiavi = _chiavi_i18n(lang)
        mancanti = [k for k in TASK3_KEYS if k not in chiavi]
        assert not mancanti, f"{lang}: {mancanti}"


TASK4_KEYS = ["vc_p3_intro", "vc_email", "vc_email2", "vc_p3_extra", "vc_pay_btn", "vc_pay_btn_free",
              "vc_pay_title", "vc_pay_line", "vc_pay_notice", "vc_err_email_bad", "vc_err_email_mismatch",
              "vc_err_email_has_voice", "vc_err_payment_invalid", "vc_err_voice_not_found",
              "vc_err_voice_gone", "vc_err_not_authorized", "vc_err_bad_request"]


def test_markup_pannello_3():
    p3 = HTML[HTML.index('id="vcP3"'):HTML.index('id="vcP4"')]
    for i in ("vcEmail", "vcEmail2", "vcExtraSel", "vcPrice", "vcP3Back", "vcPayBtn"):
        assert f'id="{i}"' in p3, i


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


def test_vcloadextratexts_non_ricarica_se_gia_popolato():
    corpo = _estrai_funzione(VC, "vcLoadExtraTexts")
    assert "S.extraLoadedFor" in corpo
    assert re.search(r"if\s*\(S\.extraLoadedFor\s*===\s*key.*\)\s*return;", corpo), \
        "deve saltare il reload quando la selezione e' gia' per lo stesso clone_id/locale"


TASK5_KEYS = ["vc_code_intro", "vc_code_note", "vc_wait", "vc_demos_intro", "vc_demo_common", "vc_demo_extra",
              "vc_approve", "vc_regen", "vc_regen_left", "vc_reject", "vc_reject_sure", "vc_yes", "vc_no",
              "vc_demo_failed", "vc_retry", "vc_done", "vc_refunded", "vc_err_regen_exhausted", "vc_err_bad_state"]


def test_markup_pannello_4():
    p4 = HTML[HTML.index('id="vcP4"'):HTML.index('id="vcPMine"')]
    for i in ("vcCodeBox", "vcCode", "vcWait", "vcDemos", "vcDemoCommon", "vcDemoExtra", "vcApprove",
              "vcRegenSel", "vcRegen", "vcRegenLeft", "vcReject", "vcRejectConfirm", "vcRejectYes",
              "vcRejectNo", "vcFailed", "vcReject2", "vcRetry", "vcDone", "vcDoneClose", "vcRefunded"):
        assert f'id="{i}"' in p4, i


def test_avanzamento_via_sse_e_decisioni():
    assert "new EventSource('/api/voice_clone/progress/'" in VC
    for a in ("'approve'", "'regenerate'", "'retry'", "'reject'"):
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
    for i in ("vcApprove", "vcRegen", "vcReject", "vcRetry"):
        assert i in corpo, i


def test_vcaction_usa_la_guardia_anti_doppio_invio():
    corpo = _estrai_funzione(VC, "vcAction")
    assert "if (S.busy) return" in corpo
    assert "vcSetBusy(true)" in corpo


# ---------- fix round 1 (review Task 5: F1-F4) ----------

def test_regola_small_esiste_in_css():
    """F1: .vc-code-note e .vcRegenLeft usano la classe .small, prima assente."""
    assert re.search(r"\.small\s*\{[^}]*\}", CSS), ".small non definita in style.css"


def test_vcrenderp4_mette_in_pausa_le_prove_quando_nascoste():
    """F2: cambiando stato (regenerate/retry) le due prove audio non devono
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


def test_vcinitpanel4_non_ricarica_le_frasi_extra_se_gia_popolate():
    """F4: come vcLoadExtraTexts sul pannello 3, rientrare piu' volte nel
    pannello 4 non deve ripetere la fetch ne' scartare una risposta tardiva
    di un clone_id ormai abbandonato."""
    corpo = _estrai_funzione(VC, "vcInitPanel4")
    assert "S.regenLoadedFor" in corpo
    assert re.search(r"if\s*\(S\.regenLoadedFor\s*===\s*regenKey.*\)\s*return;", corpo), \
        "deve saltare il reload quando la selezione e' gia' per lo stesso clone_id/locale"
    assert re.search(r"if\s*\(!S\.cur\s*\|\|\s*S\.cur\.clone_id\s*!==\s*cloneId\)\s*return;", corpo), \
        "la risposta della fetch deve essere scartata se nel frattempo e' cambiato il clone corrente"
