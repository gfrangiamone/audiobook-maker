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
    "acct_sent", "acct_err_wrong", "acct_err_expired", "acct_err_locked", "acct_err_none",
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
    for m in re.finditer(r'acct_\w+:"((?:[^"\\]|\\.)*)"', I18N):
        assert not re.search(r"DeepSeek|Gemini|Speechify|VoxCPM", m.group(1))


@pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")
def test_js_syntax():
    for f in ("static/js/app.js", "templates/_fragments/i18n_data.js"):
        subprocess.run(["node", "--check", f], check=True)
