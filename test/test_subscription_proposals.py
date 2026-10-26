# test/test_subscription_proposals.py
"""Momenti di proposta dell'abbonamento (fase 2b, spec §9.3 punti 2-3):
libreria quasi piena o piena nell'Area personale e nel fumetto della SPA, libro
non salvato per spazio esaurito, buono del mese ricordato nel modale di
pagamento. Le condizioni della riga nel modale (solo loggati senza
abbonamento, servizio pagabile col buono, importo entro il tetto, mai a
generazione in corso) sono quello che la separa da un banner: se cadono, va
rimesso il test, non tolto."""
import json
import re
from pathlib import Path

import account_page
import accounts
import i18n

LANGS = ("it", "en", "fr", "es", "de", "zh", "hi")
APP = Path("static/js/app.js").read_text(encoding="utf-8")
HEAD = Path("templates/_fragments/html_head.html").read_text(encoding="utf-8")
I18N = Path("templates/_fragments/i18n_data.js").read_text(encoding="utf-8")
T0 = 1_800_000_000


def _t(lang="it"):
    return i18n.pick(i18n.load("account_pages"), lang)


def _status(sub=None):
    return {"enabled": True, "subscription": sub, "plans": [
        {"plan": "sub_5", "price_eur": 5.0, "voucher_eur": 5.0, "quota_bytes": 5 * accounts.GIB},
        {"plan": "sub_10", "price_eur": 10.0, "voucher_eur": 10.0, "quota_bytes": 10 * accounts.GIB}]}


def _extract_fn(name):
    start = APP.index("function %s(" % name)
    depth = 0
    for j in range(APP.index("{", start), len(APP)):
        if APP[j] == "{":
            depth += 1
        elif APP[j] == "}":
            depth -= 1
            if depth == 0:
                return APP[start:j + 1]
    raise AssertionError("parentesi non bilanciate in %s" % name)


# ------------------------------------------------------------------ Area personale

def test_page_keys_in_every_language():
    with open("i18n/account_pages.json", encoding="utf-8") as f:
        data = json.load(f)
    for lang in LANGS:
        for k in ("sub_archive_near_full", "sub_archive_full", "dl_not_archived"):
            assert data[lang].get(k), f"{lang}.{k} mancante"


def test_block_shows_archive_warning_with_anchor():
    t = _t()
    plain = account_page._subscription_block(t, _status())
    assert 'id="abbonamento"' in plain and '<p class="warn">' not in plain
    for kind in ("near_full", "full"):
        html = account_page._subscription_block(t, _status(), archive_nudge=kind)
        assert f'<p class="warn">{account_page._e(t["sub_archive_" + kind])}</p>' in html
    assert '<p class="warn">' not in account_page._subscription_block(t, _status(), archive_nudge="<x>")


def test_quota_bar_turns_warning_from_80_percent():
    t = _t()
    acct = {"free_consent_at": 1, "email": "a@x.it"}
    st = {"plan": "free", "plan_source": "", "plan_until": None, "free_active": True,
          "quota_bytes": 1000, "state": "active", "grace_until": None}

    def bar(used):
        html = account_page._plan_header(t, acct, {**st, "used_bytes": used}, free_quota_bytes=1000,
                                         tolerance_days=15)
        return re.search(r'<div class="(quota[^"]*)"', html).group(1)
    assert bar(799) == "quota" and bar(800) == "quota near" and bar(1000) == "quota near"


def _row(skipped):
    dl = {"kind": "page", "url": "https://x/dl/t", "expires_at": T0 + 86400, "archived": False}
    return {"job_id": "j1", "status": "done", "kind": "generate", "created_at": T0,
            "downloads": [dl], "archive_skipped_at": skipped}


def _history(t, rows):
    return account_page.render_history(
        t, lang="it", account={"email": "a@x.it", "id": "a1"}, rows=rows, page=1, per_page=50,
        total=len(rows), voices_count=0, now=T0)


def test_row_not_saved_links_to_plans():
    t = _t()
    badge = f'<a class="badge expired" href="#abbonamento">{account_page._e(t["dl_not_archived"])}</a>'
    assert badge in _history(t, [_row(T0)])
    assert t["dl_not_archived"] not in _history(t, [_row(None)])
    archived = dict(_row(T0), downloads=[dict(_row(T0)["downloads"][0], archived=True)])
    assert t["dl_not_archived"] not in _history(t, [archived])         # in libreria: niente avviso


# ------------------------------------------------------------------ SPA

def test_spa_keys_in_every_language():
    for k in ("pay_sub_hint", "acct_archive_nudge_near_full", "acct_archive_nudge_full"):
        for lang in LANGS:
            assert re.search(r"Object\.assign\(L\.%s,\{[^\n]*\b%s:\"[^\"]+\"" % (lang, k), I18N), \
                f"{lang}.{k} mancante"


def test_spa_texts_name_no_provider():
    block = I18N[I18N.index("pay_sub_hint:"):]
    for name in ("PayPal", "Gemini", "DeepSeek", "VoxCPM", "Speechify", "Stripe"):
        assert name not in block


def test_pay_modal_hint_markup_hidden_by_default_and_opens_new_tab():
    tag = re.search(r'<p class="pay-sub-hint" id="paySubHint"[^>]*>\s*<a ([^>]*)>', HEAD)
    assert tag and "hidden" in HEAD[tag.start():tag.end()]
    assert 'href="/account#abbonamento"' in tag.group(1) and 'target="_blank"' in tag.group(1)
    assert 'rel="noopener"' in tag.group(1) and 'data-t="pay_sub_hint"' in tag.group(1)


def test_pay_modal_hint_gates():
    fn = _extract_fn("_paySubHintRender")
    assert "_acctLoggedIn()" in fn and "_acctMe.sub_promo" in fn      # mai agli anonimi
    assert "!sub.subscription" in fn                                    # gia' abbonato: no
    assert "!generating" in fn                                          # mai a generazione in corso
    assert "promo.services" in fn and "promo.max_eur" in fn             # servizi e tetto dal server
    assert "_isVoxcpmVoiceId(ctx.voucherVoice)" in fn                   # voce premium pagabile col buono
    assert "voice_clone" not in fn                                      # "questo libro": non le voci
    assert "el.hidden = !(" in fn                                       # riparte nascosta a ogni apertura
    assert "_paySubHintRender(ctx);" in _extract_fn("_openPayModalCtx")


def test_account_nudge_archive_kind():
    maybe = _extract_fn("_acctNudgeMaybe")
    assert "_acctMe.archive_nudge==='near_full'||_acctMe.archive_nudge==='full'" in maybe
    assert "_ACCT_ARCHIVE_NUDGE_KEY" in maybe and "_ACCT_FREE_NUDGE_DAYS" in maybe
    assert "const _ACCT_ARCHIVE_NUDGE_KEY='abm_archive_nudge_day';" in APP
    # la proposta del piano gratuito ha la precedenza
    assert maybe.index("free_nudge?'free'") < maybe.index("'archive'")
    assert "t('acct_archive_nudge_'+_acctMe.archive_nudge)" in _extract_fn("_acctNudgeFill")
    assert "else if(kind==='archive')location.href='/account#abbonamento';" in APP
