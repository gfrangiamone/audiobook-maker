# test/test_account_page.py
"""Pagina /account, API storico e cancellazione self-service."""
import json
import re
import time
from pathlib import Path

import pytest

import accounts
import audiobook_app
import db
import email_service
import voice_clone as vc
import community_store

T0 = 1_800_000_000


@pytest.fixture
def env(tmp_path, monkeypatch):
    db.close()
    db.init(tmp_path)
    accounts.init_schema()
    community_store.init(tmp_path)
    vc.init(tmp_path)
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(audiobook_app, "BASE_URL", "https://abm.test")
    monkeypatch.setattr(audiobook_app, "_smtp_available", lambda: True)
    monkeypatch.setattr(audiobook_app, "_download_tokens", {})
    monkeypatch.setattr(audiobook_app, "_save_tokens", lambda: None)
    monkeypatch.setattr(audiobook_app, "_file_available", lambda p: True)
    audiobook_app._ip_rl_buckets.pop("auth_request", None)
    box = {"codes": [], "deleted": []}
    monkeypatch.setattr(email_service, "send_account_code",
                        lambda email, lang, **kw: box["codes"].append((email, kw)) or True)
    monkeypatch.setattr(email_service, "send_account_deleted",
                        lambda email, lang: box["deleted"].append(email) or True)
    audiobook_app.app.config["TESTING"] = True
    yield box
    db.close()


@pytest.fixture
def logged(env):
    c = audiobook_app.app.test_client()
    c.post("/api/auth/request", json={"email": "a@b.it", "lang": "it"})
    code = env["codes"][-1][1]["code"]
    r = c.post("/api/auth/verify", json={"email": "a@b.it", "code": code})
    assert r.status_code == 200
    acct = accounts.account_for_email("a@b.it")
    return c, acct


def _token(job_id, dl_type="audio", created_at=None, **extra):
    info = {"job_id": job_id, "created_at": created_at if created_at is not None else time.time(),
            "download_type": dl_type, "base_url": "https://abm.test", "book_title": "B"}
    info.update(extra)
    tok = "tok-" + job_id
    audiobook_app._download_tokens[tok] = info
    return tok


def test_i18n_complete():
    d = json.loads((Path(audiobook_app.SCRIPT_DIR) / "i18n" / "account_pages.json").read_text(encoding="utf-8"))
    assert set(d) == {"en", "it", "fr", "es", "de", "zh", "hi"}
    for lang, t in d.items():
        assert set(t) == set(d["en"]), lang
        assert "..." not in t, lang


def test_account_page_redirects_without_session(env):
    c = audiobook_app.app.test_client()
    r = c.get("/account")
    assert r.status_code == 302 and r.headers["Location"].endswith("/?login=1")


def test_account_page_disabled_404(env, monkeypatch):
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert audiobook_app.app.test_client().get("/account").status_code == 404


def test_account_page_lists_jobs_with_downloads(logged, monkeypatch):
    c, acct = logged
    accounts.record_job(acct["id"], "j1", kind="generate", book_title="Il Gattopardo <b>",
                        output_format="m4b", voice="Alice <i>", status="done", created_at=T0)
    accounts.record_job(acct["id"], "j2", kind="translate", book_title="Old", status="done",
                        created_at=T0 - 86400 * 400)
    _token("j1", "audio", output_m4b="/x/a.m4b")
    accounts.set_download_token("j1", "tok-j1")
    _token("j2", "translated", created_at=T0 - 86400 * 400)
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 3600.0)
    r = c.get("/account", headers={"Accept-Language": "it"})
    assert r.status_code == 200
    html = r.data.decode()
    assert "Il Gattopardo &lt;b&gt;" in html and "<b>" not in html.split("Gattopardo")[1][:10]
    assert "M4B" in html and "Alice &lt;i&gt;" in html
    assert "<i>" not in html.split("Alice")[1][:20]
    assert "/dl/tok-j1" in html and "/dl/tok-j1/m4b" in html
    assert "/dl/tok-j2" not in html and "scaduto" in html
    assert "Connesso come" in html and "a@b.it" in html
    assert "no-store" in r.headers.get("Cache-Control", "")


def test_account_page_voices_tab(logged, monkeypatch):
    c, acct = logged
    monkeypatch.setattr(audiobook_app, "_account_voices_for",
                        lambda a: [{"name": "Nonna <b>", "url": "https://abm.test/vc/mt1/devices", "state": "ready"},
                                   {"name": "Zio", "url": "https://abm.test/vc/mt2/devices", "state": "paid"}])
    r = c.get("/account", headers={"Accept-Language": "it"})
    assert r.status_code == 200
    html = r.data.decode()
    assert 'href="https://abm.test/vc/mt1/devices"' in html
    assert "Nonna &lt;b&gt;" in html and "<b>" not in html.split("Nonna")[1][:10]
    assert "Voci campionate (2)" in html
    assert ">pronta<" in html and ">in preparazione<" in html
    # tab libri selezionato di default, voci nascosto
    assert 'data-tab="books" aria-selected="true"' in html
    assert 'id="tab-voices" hidden' in html
    r = c.get("/account?tab=voices", headers={"Accept-Language": "it"})
    html = r.data.decode()
    assert 'data-tab="voices" aria-selected="true"' in html
    assert 'id="tab-books" hidden' in html and 'id="tab-voices">' in html


def test_account_page_voices_empty(logged):
    c, acct = logged
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    assert "Nessuna voce campionata" in html
    assert "Voci campionate</button>" in html


def test_account_page_voices_avvio_campionamento(logged, monkeypatch):
    """Dal pannello voci si parte a campionare: il link riapre l'app sul
    wizard, e la nota dice subito che la voce serve solo col modello PREMIUM
    (altrove non compare e la si crede sparita)."""
    c, acct = logged
    monkeypatch.setattr(audiobook_app, "_vc_gate", lambda: None)
    html = c.get("/account?tab=voices", headers={"Accept-Language": "it"}).data.decode()
    assert 'href="/?vc=new"' in html
    assert "Campiona la tua voce" in html
    assert "VOXCPM2" in html and "PREMIUM" in html


def test_account_page_voices_senza_feature_niente_bottone(logged, monkeypatch):
    """Feature spenta o motore premium assente: il bottone porterebbe a un
    wizard che non si apre. La nota sul modello resta, la voce campionata
    gia' presente si gestisce lo stesso."""
    c, acct = logged
    monkeypatch.setattr(audiobook_app, "_vc_gate", lambda: ("off", 404))
    html = c.get("/account?tab=voices", headers={"Accept-Language": "it"}).data.decode()
    assert "?vc=new" not in html
    assert "Campiona la tua voce" not in html
    assert "VOXCPM2" in html


def test_account_page_title_brand_and_no_hint(logged):
    c, acct = logged
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    assert "La tua area personale su Audiobook Maker" in html
    assert '<a class="brand" href="/"><svg' in html
    assert "codice di conferma" not in html
    assert 'id="acctLogout"' in html and 'id="acctDelete"' in html


def test_account_page_devices_dialog(logged):
    c, acct = logged
    other = accounts.open_session(acct["id"], device_name="Mozilla/5.0 (X11; Linux x86_64) Firefox/120.0")
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    assert 'id="acctDevices"' in html and '<span class="cnt">2</span>' in html
    assert '<dialog id="acctDevicesDlg">' in html
    assert "questo dispositivo" in html
    assert "Firefox · Linux" in html
    # id: hash intero nel data-sid, otto caratteri a video; mai il token
    sids = re.findall(r'data-sid="([0-9a-f]{64})"', html)
    assert len(sids) == 2 and other not in html
    assert all(f"<code>{sid[:8]}</code>" in html for sid in sids)
    assert 'id="acctLogoutAll"' in html.split("acctDevicesDlg")[1]


def test_account_page_delete_dialog(logged):
    c, acct = logged
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    assert '<dialog id="acctDeleteDlg">' in html
    assert "Cancellare il tuo account?" in html
    assert 'id="acctDeleteConfirm"' in html and "Annulla" in html
    assert "/api/account/delete_request" in html


def test_account_page_close_button_and_dialog(logged):
    c, acct = logged
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    # «X» in alto a destra (dopo i dispositivi) e «Torna all'app» in basso a
    # destra come azione default: entrambi tornano all'app senza popup
    head = html.split("Connesso come")[0]
    assert 'id="acctCloseX" title="Torna all&#x27;app" aria-label="Torna all&#x27;app">' in head
    # sulla riga del marchio, a destra del logo, prima del titolo
    assert '<div class="brandbar"><a class="brand" href="/">' in head
    assert head.index('id="acctCloseX"') < head.index("<h1>")
    assert 'id="acctDevices"' not in head
    # dispositivi: sulla riga «Connesso come», a destra
    riga = html.split('<div class="signed">')[1].split("</div>")[0]
    assert riga.startswith('<p class="meta">Connesso come') and 'class="small" id="acctDevices">' in riga
    foot = html.split("</section>")[-1]
    assert 'class="primary end" id="acctClose" autofocus>Torna all&#x27;app</button>' in foot
    assert foot.index('id="acctDelete"') < foot.index('id="acctClose"')
    assert "['acctClose','acctCloseX'].forEach" in html and "location.href='/'" in html
    assert "acctCloseDlg" not in html
    # il popup di conferma sta sull'uscita: Annulla ha il fuoco, Esci e' danger
    assert '<dialog id="acctLogoutDlg">' in html
    assert "Uscire dall&#x27;account?" in html and "Verrai disconnesso su questo dispositivo" in html
    assert 'class="danger" id="acctLogoutConfirm">Esci</button>' in html
    assert 'class="primary" data-close autofocus>Annulla</button>' in html.split("acctLogoutDlg")[1]
    assert "if(lo)lo.onclick=function(){openDlg(ld);}" in html
    assert "lc.onclick=function(){lc.disabled=true;post('/api/auth/logout')" in html


def test_account_page_theme_and_app_style(logged):
    c, acct = logged
    html = c.get("/account").data.decode()
    # script tema PRIMA del CSS: stessa chiave della SPA, niente lampo chiaro
    assert html.index("localStorage.getItem('abm_th')") < html.index("<style>")
    assert "[data-theme=dark]{" in html
    # variabili con i nomi della SPA; bottoni bianchi col testo accento
    assert "--ac:#c47a2a" in html and "--ac:#f0a050" in html
    assert "background:var(--srf);color:var(--ac)" in html
    assert "#f6f3ee" not in html and "color:#222" not in html


def test_account_page_running_row_polls_progress(logged):
    c, acct = logged
    accounts.record_job(acct["id"], "jrun", kind="generate", book_title="R", status="running")
    accounts.record_job(acct["id"], "jdone", kind="generate", book_title="D", status="done")
    html = c.get("/account", headers={"Accept-Language": "it"}).data.decode()
    assert '<td data-job="jrun"><span class="badge running">In corso<span class="pct"></span></span>' in html
    assert '<span class="prog"><i></i></span>' in html
    assert 'data-job="jdone"' not in html
    assert "/api/account/progress?ids=" in html


def test_api_jobs_pagination_and_shape(logged, monkeypatch):
    c, acct = logged
    for i in range(3):
        accounts.record_job(acct["id"], f"j{i}", kind="generate", status="done", created_at=T0 + i)
    monkeypatch.setattr(audiobook_app, "_ACCT_PER_PAGE", 2)
    r = c.get("/api/account/jobs?p=2")
    assert r.status_code == 200
    d = r.get_json()
    assert d["page"] == 2 and d["total"] == 3 and d["per_page"] == 2 and len(d["jobs"]) == 1
    j = d["jobs"][0]
    assert set(j) >= {"job_id", "created_at", "kind", "book_title", "output_format", "status",
                      "paid_eur", "downloads"}
    assert j["job_id"] == "j0" and j["downloads"] == []


def test_api_jobs_requires_session(env):
    c = audiobook_app.app.test_client()
    assert c.get("/api/account/jobs").status_code == 401


def test_downloads_for_handles_types_and_expiry(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 100.0)
    now = time.time()
    _token("ja", "audio", created_at=now - 10, output_m4b="")
    _token("jb", "optimized_abm", created_at=now - 10)
    _token("jc", "translated", created_at=now - 10)
    _token("jd", "audio", created_at=now - 500)
    f = audiobook_app._account_downloads_for
    assert [d["kind"] for d in f({"job_id": "ja", "download_token": ""}, now)] == ["page"]
    assert [d["kind"] for d in f({"job_id": "jb", "download_token": "tok-jb"}, now)] == ["page", "abm"]
    kinds = [d["kind"] for d in f({"job_id": "jc", "download_token": ""}, now)]
    assert kinds == ["page", "translated"]
    assert f({"job_id": "jd", "download_token": "tok-jd"}, now) == []
    assert f({"job_id": "nope", "download_token": ""}, now) == []
    d = f({"job_id": "ja", "download_token": ""}, now)[0]
    assert d["url"] == "https://abm.test/dl/tok-ja" and abs(d["expires_at"] - (now + 90)) < 2


def test_downloads_for_skips_missing_files(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 100.0)
    monkeypatch.setattr(audiobook_app, "_file_available", lambda p: False)
    now = time.time()
    _token("ja", "audio", created_at=now - 10, output_m4b="/x/a.m4b")
    _token("jb", "optimized_abm", created_at=now - 10, optimized_abm_path="/x/b.abm")
    _token("jc", "translated", created_at=now - 10, translated_path="/x/c.txt")
    f = audiobook_app._account_downloads_for
    assert [d["kind"] for d in f({"job_id": "ja", "download_token": ""}, now)] == ["page"]
    assert [d["kind"] for d in f({"job_id": "jb", "download_token": "tok-jb"}, now)] == ["page"]
    assert [d["kind"] for d in f({"job_id": "jc", "download_token": ""}, now)] == ["page"]


def test_downloads_for_job_id_fallback_picks_newest_token(env, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 100.0)
    now = time.time()
    # Inserito per primo (vincerebbe con un semplice "primo match" in ordine
    # di dict) ma ormai scaduto: la scelta corretta e' il token piu' recente.
    audiobook_app._download_tokens["tok-old"] = {
        "job_id": "je", "created_at": now - 5000, "download_type": "audio", "output_m4b": ""}
    audiobook_app._download_tokens["tok-new"] = {
        "job_id": "je", "created_at": now - 1, "download_type": "audio", "output_m4b": ""}
    f = audiobook_app._account_downloads_for
    out = f({"job_id": "je", "download_token": ""}, now)
    assert out and out[0]["url"] == "https://abm.test/dl/tok-new"
    assert abs(out[0]["expires_at"] - (now + 99)) < 2


class _SpyTokens(dict):
    """Registra ogni `items()` e se il lock era preso.

    _download_tokens e' mutato dai thread di generazione e dal cleanup:
    scorrerlo senza snapshot e' la `RuntimeError: dictionary changed size
    during iteration` che aveva gia' ucciso il _cleanup_loop. Qui la
    scansione deve avvenire una volta sola per richiesta e sotto _tokens_lock.
    """

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.calls = []

    def items(self):
        self.calls.append(audiobook_app._tokens_lock.locked())
        return super().items()


class _NoScanTokens(dict):
    def items(self):
        raise AssertionError("_download_tokens scorso senza snapshot/indice")


def test_downloads_index_built_once_per_request_under_lock(logged, monkeypatch):
    c, acct = logged
    spy = _SpyTokens()
    monkeypatch.setattr(audiobook_app, "_download_tokens", spy)
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 3600.0)
    now = time.time()
    for i in range(3):
        accounts.record_job(acct["id"], f"jx{i}", kind="generate", status="done",
                            created_at=T0 + i)
        spy[f"tok-jx{i}"] = {"job_id": f"jx{i}", "created_at": now,
                             "download_type": "audio", "output_m4b": ""}
    r = c.get("/account")
    assert r.status_code == 200
    # una sola scansione per l'intera pagina (3 righe), sempre sotto lock
    assert spy.calls == [True]
    html = r.data.decode()
    for i in range(3):
        assert f"/dl/tok-jx{i}" in html
    # stessa garanzia sull'API JSON
    spy.calls.clear()
    assert c.get("/api/account/jobs").status_code == 200
    assert spy.calls == [True]


def test_downloads_for_with_index_never_scans_tokens(env, monkeypatch):
    """Con l'indice passato dal chiamante la funzione non tocca mai
    _download_tokens.items(): niente iterazione non protetta per riga."""
    toks = _NoScanTokens()
    now = time.time()
    toks["tok-jz"] = {"job_id": "jz", "created_at": now - 1, "download_type": "audio",
                      "output_m4b": ""}
    monkeypatch.setattr(audiobook_app, "_download_tokens", toks)
    monkeypatch.setattr(audiobook_app, "_effective_retention_for_token_info", lambda info: 100.0)
    index = {"jz": [("tok-jz", toks["tok-jz"])]}
    out = audiobook_app._account_downloads_for({"job_id": "jz", "download_token": ""}, now, index)
    assert [d["kind"] for d in out] == ["page"]
    assert out[0]["url"] == "https://abm.test/dl/tok-jz"
    # riga senza token noto: nessuna scansione, semplicemente nessun link
    assert audiobook_app._account_downloads_for({"job_id": "nope", "download_token": ""},
                                                now, index) == []


def test_delete_flow_by_code(logged, env):
    c, acct = logged
    accounts.record_job(acct["id"], "j1", kind="generate", status="done")
    r = c.post("/api/account/delete_request")
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    email, kw = env["codes"][-1]
    assert email == "a@b.it" and kw["purpose"] == "delete" and "?p=delete" in kw["link_url"]
    r = c.post("/api/account/delete_confirm", json={"code": kw["code"]})
    assert r.status_code == 200 and r.get_json() == {"ok": True}
    assert env["deleted"] == ["a@b.it"]
    assert accounts.account_for_email("a@b.it") is None
    assert accounts.list_jobs(acct["id"])[1] == 0
    assert c.get("/api/auth/me").get_json()["logged_in"] is False


def test_delete_flow_by_magic_link(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request")
    link = env["codes"][-1][1]["link_url"]
    path = link[len("https://abm.test"):]
    r = c.get(path)
    assert r.status_code == 200 and b"<form" in r.data
    assert accounts.account_for_email("a@b.it") is not None
    # anche il ramo delete passa dal double-submit anti login-CSRF
    csrf = re.search(r'name="csrf" value="([^"]+)"', r.data.decode()).group(1)
    assert c.post(path).status_code == 403
    assert accounts.account_for_email("a@b.it") is not None
    r = c.post(path, data={"csrf": csrf})
    assert r.status_code == 200 and env["deleted"] == ["a@b.it"]
    assert accounts.account_for_email("a@b.it") is None


def test_delete_confirm_wrong_code_401_and_requires_session(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request")
    r = c.post("/api/account/delete_confirm", json={"code": "000000"})
    assert r.status_code == 401 and r.get_json()["error_code"] in ("wrong", "none")
    assert accounts.account_for_email("a@b.it") is not None
    anon = audiobook_app.app.test_client()
    assert anon.post("/api/account/delete_request").status_code == 401
    assert anon.post("/api/account/delete_confirm", json={"code": "1"}).status_code == 401


def test_delete_request_ignores_body_email(logged, env):
    c, acct = logged
    c.post("/api/account/delete_request", json={"email": "victim@x.it"})
    assert env["codes"][-1][0] == "a@b.it"
