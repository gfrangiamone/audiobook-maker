# test/test_app_js_account.py
"""La SPA espone login/logout via magic link + codice e, da loggata, vincola
le notifiche all'email dell'account. Test statici sul sorgente JS/HTML,
piu' `node --check` se node e' disponibile."""
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


def test_restore_path_reapplies_forced_email():
    """N-3: _restoreActiveJob() e _acctBoot() partono in parallelo — il
    ricalcolo va fatto dopo che lo stato del job ripristinato e' definitivo,
    non lasciato a quello (sbagliato) calcolato al boot."""
    fn = _extract_fn("_restoreActiveJob")
    assert "_acctApplyForcedEmail()" in fn
