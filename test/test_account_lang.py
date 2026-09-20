# test/test_account_lang.py
"""Le pagine server-side dell'account seguono la lingua scelta nell'app.

La SPA tiene la lingua scelta solo lato client (localStorage + path /it/):
/account e /auth/<token> sceglievano da Accept-Language o dalla lingua
salvata sull'account, e un utente con browser italiano che usa l'app in
inglese trovava l'area personale in italiano. Ora la SPA posa il cookie
`abm_lang` e le pagine lo onorano; `?lang=` esplicito vince su tutto.
"""
import audiobook_app

from test.test_account_page import env, logged  # noqa: F401  (fixture)


def test_area_personale_segue_il_cookie_della_lingua_app(logged):
    c, acct = logged
    assert acct["lang"] == "it"
    # senza cookie: lingua dell'account (come prima)
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    assert 'lang="it"' in html and "La tua area personale" in html
    # app in inglese su browser e account italiani: la pagina e' in inglese
    c.set_cookie("abm_lang", "en")
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    assert 'lang="en"' in html and "Your personal area" in html and "Esci" not in html
    assert "Sign out" in html


def test_lang_in_query_vince_sul_cookie_e_valore_ignoto_ignorato(logged):
    c, _ = logged
    c.set_cookie("abm_lang", "en")
    html = c.get("/account?lang=de", headers={"Accept-Language": "it"}).data.decode()
    assert 'lang="de"' in html and "Abmelden" in html
    # lingua non tradotta in query o nel cookie: si ripiega sull'ordine normale
    html = c.get("/account?lang=xx", headers={"Accept-Language": "it"}).data.decode()
    assert 'lang="en"' in html
    c.set_cookie("abm_lang", "zz")
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    assert 'lang="it"' in html


def test_paginazione_conserva_la_lingua_esplicita(logged, monkeypatch):
    import accounts
    c, acct = logged
    monkeypatch.setattr(audiobook_app, "_ACCT_PER_PAGE", 1)
    for i in range(2):
        accounts.record_job(acct["id"], f"j{i}", kind="generate", book_title=f"B{i}", status="done")
    html = c.get("/account?lang=fr", headers={"Accept-Language": "it"}).data.decode()
    assert 'lang="fr"' in html
    assert 'href="/account?p=2&amp;lang=fr"' in html


def test_conferma_magic_link_segue_il_cookie_poi_la_lingua_del_codice(env):
    c = audiobook_app.app.test_client()
    c.post("/api/auth/request", json={"email": "a@b.it", "lang": "it"})
    link = env["codes"][-1][1]["link_url"]
    path = link[len("https://abm.test"):]
    # senza cookie: lingua del codice (it), non del browser (de)
    html = c.get(path, headers={"Accept-Language": "de"}).data.decode()
    assert 'lang="it"' in html and "Accedi" in html
    # con il cookie dell'app: la lingua scelta nell'app
    c.set_cookie("abm_lang", "de")
    html = c.get(path, headers={"Accept-Language": "it"}).data.decode()
    assert 'lang="de"' in html and "Anmelden" in html
    # ?lang esplicito vince
    html = c.get(path + "&lang=fr" if "?" in path else path + "?lang=fr",
                 headers={"Accept-Language": "it"}).data.decode()
    assert 'lang="fr"' in html


def test_pagine_voce_campionata_onorano_il_cookie_app():
    """Raggiungibili dal tab «Voci» dell'area personale: stessa lingua."""
    with audiobook_app.app.test_request_context("/vc/x/delete", headers={"Accept-Language": "it"}):
        assert audiobook_app._vc_page_lang() == "it"
    with audiobook_app.app.test_request_context(
            "/vc/x/delete", headers={"Accept-Language": "it", "Cookie": "abm_lang=de"}):
        assert audiobook_app._vc_page_lang() == "de"
    # ?lang= resta ignorato sulle pagine dei link email
    with audiobook_app.app.test_request_context(
            "/vc/x/delete?lang=fr", headers={"Accept-Language": "it", "Cookie": "abm_lang=de"}):
        assert audiobook_app._vc_page_lang() == "de"
