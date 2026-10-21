# test/test_app_js_account.py
"""La SPA espone login/logout via magic link + codice e, da loggata, vincola
le notifiche all'email dell'account. Test statici sul sorgente JS/HTML,
piu' `node --check` se node e' disponibile."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

APP = Path("static/js/app.js").read_text(encoding="utf-8")
HEAD = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")

ACCT_KEYS = [
    "acct_login", "acct_logout", "acct_history", "acct_modal_title", "acct_modal_intro",
    "acct_email_ph", "acct_send_code", "acct_code_ph", "acct_code_intro", "acct_verify",
    "acct_err_wrong", "acct_err_expired", "acct_err_locked", "acct_err_none",
    "acct_err_rate", "acct_err_generic", "acct_forced_notice", "acct_signed_in_as",
    "acct_logged_out", "acct_nudge",
]


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


def test_markup_has_button_menu_and_modal():
    assert 'id="acctBtn"' in HEAD and 'id="acctMenu"' in HEAD
    assert 'id="loginModal"' in HEAD and 'id="acctEmail"' in HEAD and 'id="acctCode"' in HEAD
    assert 'id="acctForcedNotice"' in HEAD
    # il bottone sta nella toolbar, prima del separatore del tema
    assert HEAD.index('id="acctBtn"') < HEAD.index('<div class="theme-sep"></div>')
    # nascosto finche' /api/auth/me non conferma la feature
    m = re.search(r'<button[^>]*id="acctBtn"[^>]*>', HEAD)
    assert m and "display:none" in m.group(0)


def test_boot_queries_me_and_handles_login_param():
    fn = _extract_fn("_acctBoot")
    assert "/api/auth/me" in fn
    assert "login=1" in fn
    # non solo il commento: la logica che legge davvero il parametro deve
    # esserci (altrimenti la riga sopra sopravvive alla cancellazione del
    # codice che gestisce ?login=1, vedi review M-7).
    assert "get('login')" in fn
    assert "_acctApplyForcedEmail()" in fn or "_acctRender()" in fn


def test_boot_is_called_at_dom_ready():
    i = APP.index("_restoreActiveJob();")
    assert "_acctBoot()" in APP[i:i + 400]


def test_request_and_verify_hit_auth_endpoints():
    assert "'/api/auth/request'" in _extract_fn("_acctRequest")
    v = _extract_fn("_acctVerify")
    assert "'/api/auth/verify'" in v
    for code in ("wrong", "expired", "locked", "none"):
        assert "acct_err_" + code in v
    assert "_acctAfterLogin" in v
    assert "location.href='/account'" in _extract_fn("_acctBoot")


def test_logout_hits_endpoint_and_rerenders():
    fn = _extract_fn("_acctLogout")
    assert "'/api/auth/logout'" in fn and "_acctRender()" in fn


def test_forced_email_hides_manual_inputs():
    fn = _extract_fn("_acctApplyForcedEmail")
    for el in ("emailLateArea", "emailLateAreaTr", "payEmailNotice", "acctForcedNotice"):
        assert el in fn, el


@pytest.mark.parametrize("fn_name", ["submitEmailLate", "submitEmailLateTr"])
def test_register_email_handles_forced_conflict(fn_name):
    fn = _extract_fn(fn_name)
    assert "logged_in_email_forced" in fn
    # il conflitto non deve finire nell'alert generico
    assert fn.index("logged_in_email_forced") < fn.index("alert(d.error)")


def test_auto_batch_notice_uses_account_wording_when_logged_in():
    fn = _extract_fn("_showAutoBatchNotice")
    assert "_acctLoggedIn()" in fn and "acct_forced_notice" in fn
    lock = _extract_fn("_lockEmailLateBoxAutoBatch")
    assert "_acctLoggedIn()" in lock  # niente link "cambia indirizzo"


def test_login_and_logout_give_feedback_toast():
    # Icona piena + pallino (CSS) da soli si notano poco: al login e al
    # logout parte anche un toast con l'email / "Disconnesso".
    v = _extract_fn("_acctVerify")
    assert "_acctToast(t('acct_signed_in_as'" in v
    assert v.index("closeLoginModal()") < v.index("_acctToast(") < v.index("if(after){after();return}")
    lo = _extract_fn("_acctLogout")
    assert "_acctToast(t('acct_logged_out'))" in lo
    toast = _extract_fn("_acctToast")
    assert "textContent=text" in toast and "innerHTML" not in toast
    css = Path("static/css/style.css").read_text(encoding="utf-8")
    assert ".acct-btn.on{background:var(--ac" in css and ".acct-btn.on::after" in css


@pytest.mark.parametrize("key", ACCT_KEYS)
def test_i18n_key_in_all_seven_languages(key):
    assert len(re.findall(r"\b%s:" % key, I18N)) == 7, key


def test_i18n_no_provider_names_in_account_strings():
    # Ogni blocco lingua e' una singola riga lunghissima con tutte le chiavi
    # della SPA: un controllo per riga intera darebbe falsi positivi su testi
    # preesistenti non collegati (es. FAQ). Isoliamo i soli valori acct_*.
    n = 0
    for m in re.finditer(r'acct_\w+:"((?:[^"\\]|\\.)*)"', I18N):
        n += 1
        assert not re.search(r"DeepSeek|Gemini|Speechify|VoxCPM", m.group(1))
    # Senza questo conteggio un rename silenzioso della chiave svuoterebbe
    # l'iterazione e il test passerebbe comunque (review M-7).
    assert n == 7 * len(ACCT_KEYS)


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_js_syntax():
    for f in ("static/js/app.js", "templates/_fragments/i18n_data.js"):
        subprocess.run(["node", "--check", f], check=True)


# ─────────────────────── Fix round 1 (review findings) ───────────────────────

def test_verify_registers_email_on_mid_job_login():
    """C-1: un login a meta' lavorazione deve vincolare il job in corso
    (altrimenti il banner promette una consegna che il server non ha armato
    e il beacon di chiusura pagina uccide comunque il lavoro)."""
    fn = _extract_fn("_acctVerify")
    assert "generating" in fn and "emailRegistered" in fn
    # round 2: la traduzione partita anonima e vincolata a meta' lavoro deve
    # ricevere lo stesso trattamento della generazione audio (stesso
    # onBeforeUnload, stesso endpoint gia' usato da submitEmailLateTr).
    assert "'translated'" in fn
    assert "trEmailRegistered" in fn
    # round 3: il vincolo vero e proprio vive nell'helper condiviso, usato
    # anche dai due conflitti 409 (niente divergenza fra i tre chiamanti).
    assert "_acctBindCurrentJob" in fn
    helper = _extract_fn("_acctBindCurrentJob")
    assert "/api/register_email" in helper
    assert "_updateGenNoticeWarning" in helper


def test_translation_flow_applies_forced_email_state():
    """I-1: avviare una traduzione da loggati deve riflettere subito il
    vincolo di consegna gia' armato lato server (_apply_account_to_job)."""
    assert 'id="acctForcedNoticeTr"' in HEAD
    fn = _extract_fn("_submitTranslation")
    assert "_acctApplyForcedEmail()" in fn


def test_apply_i18n_rerenders_account_ui():
    """I-3: cambiare lingua non deve lasciare bottone/menu/banner account
    nella lingua precedente."""
    fn = _extract_fn("applyI18n")
    assert "_acctRender()" in fn


@pytest.mark.parametrize("fn_name", ["submitEmailLate", "submitEmailLateTr"])
def test_forced_conflict_refreshes_account_cache(fn_name):
    """I-4: un 409 logged_in_email_forced significa che la cache locale di
    _acctMe e' stale (il client si credeva anonimo) e va allineata subito."""
    fn = _extract_fn(fn_name)
    conflict = fn[fn.index("logged_in_email_forced"):]
    assert "/api/auth/me" in conflict


# ─────────────────────── Fix round 3 (re-review findings) ───────────────────────

def test_translation_response_syncs_forced_email_flags():
    """N-2 (regressione di I-1): round 2 calcolava canForceTr con
    trEmailRegistered sempre falso all'avvio traduzione, ririnverdendo I-1.
    /api/translate forza batch sull'email dell'account quando c'e' una
    sessione: d.batch e' il segnale che la consegna e' gia' armata, e va
    allineato PRIMA di _acctApplyForcedEmail() perche' il guard lo legga."""
    fn = _extract_fn("_submitTranslation")
    assert "d.batch" in fn
    assert "trEmailRegistered=true" in fn
    assert "emailRegistered=true" in fn
    assert fn.index("trEmailRegistered=true") < fn.index("_acctApplyForcedEmail()")


@pytest.mark.parametrize("fn_name", ["submitEmailLate", "submitEmailLateTr"])
def test_forced_conflict_binds_current_job_before_confirming(fn_name):
    """N-1: il conflitto 409 non deve promettere una consegna che nessuna
    chiamata ha armato (e non deve distruggere il form se il tentativo di
    binding fallisce) — usa lo stesso helper condiviso di _acctVerify."""
    fn = _extract_fn(fn_name)
    conflict = fn[fn.index("logged_in_email_forced"):]
    assert "_acctBindCurrentJob(" in conflict
    assert "bind.ok" in conflict
    assert conflict.index("bind.ok") < conflict.index("_setEmailLateConfirm")


def test_generate_success_paths_reapply_forced_email():
    """N-3: canForceGen/canForceTr sono affidabili solo dopo che generating/
    emailRegistered sono definitivi per il job; senza ricalcolo qui resta
    quello (potenzialmente sbagliato) calcolato al boot."""
    for fn_name in ("startCombinedGeneration", "startGen"):
        fn = _extract_fn(fn_name)
        auto_idx = fn.index("auto_batch_email")
        apply_idx = fn.index("_acctApplyForcedEmail()", auto_idx)
        assert apply_idx > auto_idx


def test_optimize_path_reapplies_forced_email():
    """Da loggati /api/optimize arma gia' la consegna sull'account: il ramo
    ottimizzazione deve allineare emailRegistered e ricalcolare lo stato
    forzato, altrimenti il box email manuale resta visibile."""
    fn = _extract_fn("startCombinedGeneration")
    opt = fn[fn.index("/api/optimize"):fn.index("_listenOptProgressWiz()")]
    assert "d.email_registered" in opt
    assert opt.index("emailRegistered=true") < opt.index("_acctApplyForcedEmail()")


def test_generate_paths_read_email_registered():
    for fn_name in ("startCombinedGeneration", "startGen"):
        fn = _extract_fn(fn_name)
        reg_idx = fn.index("email_registered){emailRegistered=true")
        assert reg_idx < fn.index("_acctApplyForcedEmail()", reg_idx)


def test_restore_path_reapplies_forced_email():
    """N-3: _restoreActiveJob() e _acctBoot() partono in parallelo — il
    ricalcolo va fatto dopo che lo stato del job ripristinato e' definitivo,
    non lasciato a quello (sbagliato) calcolato al boot."""
    fn = _extract_fn("_restoreActiveJob")
    assert "_acctApplyForcedEmail()" in fn


# ── Lingua dell'app condivisa con le pagine server-side (/account, /auth) ──

def test_set_lang_posa_il_cookie_abm_lang_per_le_pagine_server():
    """/account e /auth/<token> sono rese dal server: senza il cookie
    seguirebbero Accept-Language e non la lingua scelta nell'app."""
    fn = _extract_fn("_setLangCookie")
    assert "abm_lang=" in fn and "path=/" in fn and "SameSite=Lax" in fn
    assert "_setLangCookie(l)" in _extract_fn("setLang")


def test_il_cookie_della_lingua_e_posato_anche_al_boot():
    boot = APP[APP.index("cl=detectLang();"):]
    boot = boot[:boot.index("\n")]
    assert "_setLangCookie(cl)" in boot


def test_nudge_shown_once_per_day_only_to_guests():
    assert 'id="acctNudge"' in HEAD and 'data-t="acct_nudge"' in HEAD
    fn = _extract_fn("_acctNudgeMaybe")
    assert "_acctLoggedIn()" in fn and "_acctMe.enabled" in fn
    assert "localStorage.getItem(_ACCT_NUDGE_KEY)===today" in fn
    assert "localStorage.setItem(_ACCT_NUDGE_KEY,today)" in fn
    # non compare quando ?login=1 apre gia' la modale, e si chiude all'apertura
    boot = _extract_fn("_acctBoot")
    assert boot.index("openLoginModal();\n    return;") < boot.index("_acctNudgeMaybe()")
    assert "_acctNudgeHide()" in _extract_fn("openLoginModal")


# ── Proposta una tantum del piano gratuito e invito al cloud ──

FP_KEYS = ["fp_title", "fp_body", "fp_activate", "fp_decline", "fp_on_toast",
           "cloud_invite", "cloud_invite_btn"]


@pytest.mark.parametrize("key", FP_KEYS)
def test_free_offer_key_in_all_seven_languages(key):
    assert len(re.findall(r"\b%s:" % key, I18N)) == 7, key
    matches = list(re.finditer(r'\b%s:"((?:[^"\\]|\\.)*)"' % key, I18N))
    # senza questo conteggio un valore non letto dalla regex salterebbe il
    # controllo sui nomi di provider senza far fallire nulla
    assert len(matches) == 7, key
    for m in matches:
        assert m.group(1).strip(), key
        assert not re.search(r"DeepSeek|Gemini|Speechify|VoxCPM", m.group(1))


def test_free_offer_flow_wiring():
    offer = _extract_fn("_acctFreeOffer")
    assert "/api/account/free_plan" in offer and "'prompt'" in offer
    assert "decline" in offer and "activate" in offer and "innerHTML" not in offer
    assert "_acctFreeOffer" in _extract_fn("_acctBoot")
    verify = _extract_fn("_acctVerify")
    assert verify.index("_acctFreeOffer") < verify.index("after()")
    assert verify.index("_acctFreeOffer") < verify.index("/api/auth/me")
    invite = _extract_fn("_acctCloudInviteRender")
    assert "_acctLoggedIn()" in invite and "openLoginModal" in invite
    assert "innerHTML" not in invite


def test_free_offer_markup_has_no_preselection():
    start = HEAD.index('id="freePlanModal"')
    m = HEAD[start:HEAD.index('id="fpDecline"', start) + 200]
    assert 'id="fpActivate"' in m and "autofocus" not in m and "checked" not in m
    assert 'id="cloudInvite"' in HEAD and 'id="cloudInviteBtn"' in HEAD
    # stesso peso visivo: i due pulsanti hanno la stessa classe
    cls = [re.search(r'class="([^"]*)"', re.search(r'<button[^>]*id="%s"[^>]*>' % i, HEAD).group(0)).group(1)
           for i in ("fpActivate", "fpDecline")]
    assert cls[0] == cls[1]


def test_free_offer_boot_replaces_nudge_and_invite_follows_generation():
    boot = _extract_fn("_acctBoot")
    assert boot.index("_acctFreeOffer(") < boot.index("_acctNudgeMaybe()")
    # l'invito compare a fine generazione, dopo aver popolato il pannello 5
    done = APP[APP.index("if(d.status==='done'||d.status==='partial'){"):]
    done = done[:done.index("// Heartbeat")]
    assert done.index("Populate panel 5 download buttons") < done.index("_acctCloudInviteRender()") < done.index("goToStep(5)")
    assert "_acctCloudInviteRender()" in _extract_fn("_acctRender")


def test_free_offer_closing_the_modal_is_a_decline():
    offer = _extract_fn("_acctFreeOffer")
    # X, clic sullo sfondo ed Esc valgono "Non ora"
    assert offer.count("choose('decline')") >= 3
    assert "Escape" in offer


def test_fmt_bytes_follows_server_rule():
    fn = _extract_fn("_acctFmtBytes")
    assert "MB" in fn and "GB" in fn and "toFixed(2)" in fn


# ── Fix round: quota dal server, timeout, guardie del modale ──

def test_free_quota_for_invite_comes_from_server_not_a_second_copy():
    # la quota degli anonimi arriva da /api/auth/me e sopravvive al logout:
    # la costante resta solo come ripiego se il campo manca
    logout = _extract_fn("_acctLogout")
    assert "free_quota_bytes" in logout and "_acctMe.free_quota_bytes" in logout
    quota = _extract_fn("_acctFreeQuota")
    assert "free_quota_bytes" in quota and "_ACCT_FREE_QUOTA_DEFAULT" in quota
    assert "typeof" in quota  # 0 dal server e' un valore, non un campo mancante
    assert "_acctFreeQuota(" in _extract_fn("_acctCloudInviteRender")
    assert "_acctFreeQuota(" in _extract_fn("_acctFreeOffer")
    # il server manda sempre tolerance_days con la proposta: niente seconda copia
    assert "_ACCT_TOLERANCE_DAYS_DEFAULT" not in APP


def test_free_offer_failed_activation_is_toasted_and_failed_decline_is_silent():
    offer = _extract_fn("_acctFreeOffer")
    assert "acct_err_generic" in offer
    # l'errore si mostra solo per l'attivazione, mai per un "Non ora" andato a vuoto
    assert re.search(r"else if\(action==='activate'\)\{[^}]*acct_err_generic", offer)


def test_free_offer_post_has_a_timeout_that_unblocks_the_modal():
    offer = _extract_fn("_acctFreeOffer")
    assert "new AbortController()" in offer and "signal" in offer
    assert "abort()" in offer and "setTimeout(" in offer
    # il timer si ferma comunque (finally) e il modale si chiude dopo l'errore
    assert "finally" in offer and "clearTimeout(" in offer
    assert re.search(r"_ACCT_FP_TIMEOUT_MS\s*=\s*1[0-9]{4}(?!\d)", APP)
    assert "_ACCT_FP_TIMEOUT_MS" in offer


def test_free_offer_overlay_click_needs_mousedown_on_overlay_too():
    # una selezione di testo che parte dal riquadro e finisce sullo sfondo non
    # e' un "clic fuori": non deve registrare un rifiuto persistente
    offer = _extract_fn("_acctFreeOffer")
    assert "onmousedown" in offer
    click = offer[offer.index("m.onclick=function"):]
    click = click.splitlines()[0]
    assert "ev.target===m" in click and "choose('decline')" in click
    assert "downOnOverlay" in click
    down = offer[offer.index("m.onmousedown=function"):]
    down = down.splitlines()[0]
    assert "ev.target===m" in down and "downOnOverlay" in down
    # anche il rilascio deve cadere sullo sfondo: dallo sfondo al riquadro il
    # click nasce comunque sullo sfondo (antenato comune) e non e' un rifiuto
    assert "onmouseup" in offer and "upOnOverlay" in click
    up = offer[offer.index("m.onmouseup=function"):].splitlines()[0]
    assert "ev.target===m" in up and "upOnOverlay" in up
    assert "m.onmouseup=null" in offer       # finish() scollega anche questo


def test_free_offer_traps_focus_but_never_focuses_a_button():
    offer = _extract_fn("_acctFreeOffer")
    assert "_trapFocusIn(m)" in offer
    assert offer.index("panel.focus()") < offer.index("_trapFocusIn(m)")
    # l'unico focus e' sul riquadro: nessuna scelta suggerita
    receivers = re.findall(r"([A-Za-z_]\w*)\.focus\(", offer)
    assert receivers == ["prev", "panel"], receivers     # prev = chi l'aveva prima dell'apertura
    assert offer.count(".focus(") == len(receivers)
    for btn in ("bAct", "bDec", "bX"):
        assert btn + ".focus" not in offer
    assert "autofocus" not in offer and ".click()" not in offer
    # Maiusc+Tab dal riquadro (focus sul contenitore) non esce dal dialogo
    trap = _extract_fn("_trapFocusIn")
    assert "indexOf" in trap or "includes" in trap


# ---- proposta del gratuito: eventi del mouse e focus alla chiusura (comportamento) ----

_FP_HARNESS = r"""
let _fpPending=null;
const _ACCT_FP_TIMEOUT_MS=15000;
const t=function(k){return k};
const _acctFmtBytes=function(n){return String(n)};
const _acctFreeQuota=function(){return 1};
const _acctToast=function(){};
const _trapFocusIn=function(){};
const getComputedStyle=function(el){return{visibility:el.visibility||'visible'}};
const state={active:null};
const body={id:'body'};
state.active=body;
function mk(id){
  return{id:id,rects:1,isConnected:true,visibility:'visible',textContent:'',disabled:false,
    classList:{s:new Set(),add(c){this.s.add(c)},remove(c){this.s.delete(c)},contains(c){return this.s.has(c)}},
    getClientRects(){return{length:this.rects}},
    focus(){if(this.rects&&this.isConnected)state.active=this}};
}
const els={};
['freePlanModal','fpBody','fpActivate','fpDecline','fpClose','fpPanel'].forEach(function(i){els[i]=mk(i)});
const document={body:body,
  getElementById:function(i){return els[i]||null},
  addEventListener(){},removeEventListener(){},
  get activeElement(){return state.active}};
const calls=[];
const fetch=async function(url,opt){calls.push(JSON.parse(opt.body).action);
  return{ok:true,json:async function(){return{ok:true}}}};
"""

_FP_MOUSE = r"""
(async function(){
  const m=els.freePlanModal,panel=els.fpPanel,out=[];
  const seqs={
    'sfondo-sfondo':[['down',m],['up',m],['click',m]],
    'sfondo-riquadro':[['down',m],['up',panel],['click',m]],
    'riquadro-sfondo':[['down',panel],['up',m],['click',m]],
    'sfondo-riquadro poi sfondo-sfondo':[['down',m],['up',panel],['click',m],['down',m],['up',m],['click',m]]
  };
  for(const name of Object.keys(seqs)){
    calls.length=0;
    const p=_acctFreeOffer({tolerance_days:15});
    for(const [kind,target] of seqs[name]){
      if(kind==='down')m.onmousedown({target:target});
      else if(kind==='up'){if(m.onmouseup)m.onmouseup({target:target})}
      else m.onclick({target:target});
    }
    out.push([name,calls.length]);
    if(!calls.length)els.fpClose.onclick();     // chiude per passare al caso dopo
    await p;
  }
  console.log(JSON.stringify(out));
})();
"""

_FP_FOCUS = r"""
(async function(){
  const out={};
  async function run(name,setup){
    state.active=body;
    const trigger=mk('trigger');
    trigger.rects=1;trigger.isConnected=true;trigger.visibility='visible';
    setup(trigger);
    const p=_acctFreeOffer({tolerance_days:15});
    out[name+'_open']=state.active.id;                  // il focus e' sul riquadro
    els.fpClose.onclick();
    await p;
    out[name]=state.active.id;
  }
  await run('visibile',function(tr){state.active=tr});
  await run('nascosto',function(tr){tr.rects=0;state.active=tr});
  await run('visibility',function(tr){tr.visibility='hidden';state.active=tr});
  await run('rimosso',function(tr){tr.isConnected=false;state.active=tr});
  await run('nessuno',function(tr){state.active=body});
  console.log(JSON.stringify(out));
})();
"""


def _run_fp(tmp_path, tail):
    script = tmp_path / "fp.js"
    script.write_text(
        _FP_HARNESS + "\n" + _extract_fn("_acctFreeOffer") + "\n" + tail, encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_free_offer_background_decline_needs_press_and_release_on_overlay(tmp_path):
    got = dict(_run_fp(tmp_path, _FP_MOUSE))
    assert got["sfondo-sfondo"] == 1                         # un vero clic fuori vale "Non ora"
    assert got["sfondo-riquadro"] == 0                       # trascinamento verso il riquadro: niente
    assert got["riquadro-sfondo"] == 0                       # trascinamento verso lo sfondo: niente
    assert got["sfondo-riquadro poi sfondo-sfondo"] == 1     # il flag non resta sporco


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_free_offer_gives_focus_back_to_the_opener_only_if_visible(tmp_path):
    got = _run_fp(tmp_path, _FP_FOCUS)
    for case in ("visibile", "nascosto", "visibility", "rimosso", "nessuno"):
        assert got[case + "_open"] == "fpPanel", case        # il focus si sposta sul riquadro
    assert got["visibile"] == "trigger"                      # chiusura: torna a chi l'aveva
    for case in ("nascosto", "visibility", "rimosso"):
        assert got[case] != "trigger", case                  # mai su un elemento nascosto/rimosso
    assert got["nessuno"] != "trigger"                       # senza un chiamante non si inventa nulla


def test_free_offer_reads_the_opener_before_moving_focus():
    offer = _extract_fn("_acctFreeOffer")
    assert offer.index("document.activeElement") < offer.index("m.classList.add('open')")
    assert offer.index("m.classList.add('open')") < offer.index("panel.focus()")
    finish = offer[offer.index("function finish()"):offer.index("async function choose")]
    assert finish.index("m.classList.remove('open')") < finish.index("refocusOpener()")
    assert "isConnected" in offer and "getClientRects" in offer

