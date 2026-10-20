# test/test_account_archive.py
"""Archivio dei lavori: quota del piano (gratuito con consenso), ingresso dei job
in archivio entro quota, protezione da retention e cleanup, area personale."""
import re
from html import escape

import pytest

import accounts
import cleanup
import db
import storage_backend
import token_store as _tkstore
from test.test_account_plans import _consent
from test.test_admin_accounts_audit import _admin


T0 = 1_800_000_000
GIB = accounts.GIB


@pytest.fixture
def acct_env(tmp_path, monkeypatch):
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(accounts, "_payments_path", None)
    monkeypatch.setattr(accounts, "_voice_ids_for_email", None)
    monkeypatch.setattr(accounts, "_link_voice", None)
    monkeypatch.setattr(accounts, "_unlink_voice", None)
    accounts._archive_cache_clear()
    yield tmp_path
    accounts._archive_cache_clear()
    db.close()


def _login(email, now=T0):
    token, code = accounts.request_code(email, "login", "it", now=now)
    status, acct = accounts.verify(token=token, code=code, purpose="login", now=now)
    assert status == "ok"
    return acct


def _done_job(acct, job_id, created=T0):
    accounts.record_job(acct["id"], job_id, kind="generate", status="done", created_at=created)


# ------------------------------------------------------------ accounts.py

def test_candidates_only_done_visible_with_consent(acct_env):
    sub, free = _login("s@b.it"), _login("f@b.it")
    _consent(sub, at=T0)
    _done_job(sub, "old", T0)
    _done_job(sub, "new", T0 + 10)
    accounts.record_job(sub["id"], "run", kind="generate", status="running")
    _done_job(sub, "hid", T0 + 5)
    accounts.hide_job(sub["id"], "hid")
    _done_job(free, "fj")
    cands = accounts.archive_candidates(now=T0 + 20)
    assert [c["job_id"] for c in cands] == ["new", "old"]
    assert {c["account_id"] for c in cands} == {sub["id"]}
    assert all(c["quota_bytes"] == 512 * accounts.MIB for c in cands)
    assert accounts.mark_archived("new", 100, now=T0)
    assert not accounts.mark_archived("new", 200, now=T0)  # gia' archiviato
    assert [c["job_id"] for c in accounts.archive_candidates(now=T0 + 20)] == ["old"]
    assert accounts.archive_usage(sub["id"]) == (100, 1)


def test_hide_and_delete_release_archive(acct_env):
    acct = _login("a@b.it")
    _consent(acct)
    _done_job(acct, "j1")
    _done_job(acct, "j2")
    accounts.mark_archived("j1", 10)
    accounts.mark_archived("j2", 20)
    assert accounts.hide_job(acct["id"], "j1") == "ok"
    assert not accounts.archive_protects("j1")
    assert accounts.archive_usage(acct["id"]) == (20, 1)
    accounts.delete_account(acct["id"])
    assert not accounts.archive_protects("j2")


def test_archive_status_and_admin_list(acct_env):
    acct = _login("a@b.it")
    assert accounts.archive_status(acct) is None
    _consent(acct)
    _done_job(acct, "j1")
    accounts.mark_archived("j1", 300 * accounts.MIB)
    st = accounts.archive_status(accounts.get(acct["id"]))
    assert st == {"plan": "free", "plan_source": "", "plan_until": None, "free_active": True,
                  "quota_bytes": 512 * accounts.MIB, "used_bytes": 300 * accounts.MIB, "jobs": 1,
                  "items": 0, "state": "active", "grace_until": None}
    out = accounts.admin_list(now=T0 + 60)
    r = out["records"][0]
    assert r["plan"] == "free"
    assert r["archive_bytes"] == 300 * accounts.MIB and r["archive_jobs"] == 1
    assert r["archive_quota_bytes"] == 512 * accounts.MIB
    assert out["plans"] == ["free", "sub_5", "sub_10"]


# ------------------------------------------------------------ cleanup.py

@pytest.fixture
def sweep_env(acct_env, monkeypatch):
    import audiobook_app  # noqa: F401  configura cleanup (lock, cartelle, policy)
    monkeypatch.setattr(cleanup, "_upload_dir", lambda: acct_env)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(_tkstore, "download_tokens", {})
    monkeypatch.setattr(cleanup, "_archive_over_quota", {})
    return acct_env


def _live_tokens(monkeypatch, *job_ids, created=T0):
    """Un download token per ciascun job_id: sono i job con i file ancora vivi."""
    monkeypatch.setattr(_tkstore, "download_tokens",
                        {"tok-" + j: {"job_id": j, "created_at": created} for j in job_ids})


def _output(root, job_id, nbytes, name="book.m4b"):
    od = root / job_id / "output_1"
    od.mkdir(parents=True, exist_ok=True)
    (od / name).write_bytes(b"x" * nbytes)
    return od


def test_job_archive_bytes_counts_local_and_cold(sweep_env, monkeypatch):
    od = _output(sweep_env, "j1", 7)
    (od / "chunk.wav").write_bytes(b"y" * 100)   # non offloadable: non conta
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    keys = ["j1/output_1/book.m4b", "j1/output_1/book.abm", "j1/input/src.epub"]
    monkeypatch.setattr(storage_backend, "list_prefix", lambda p: keys)
    monkeypatch.setattr(cleanup.storage_tiering, "key_for_path",
                        lambda p: "j1/output_1/" + p.replace("\\", "/").rsplit("/", 1)[-1])
    monkeypatch.setattr(storage_backend, "object_size", lambda k: 1000)
    # m4b locale (7) + abm solo su cold (1000); input/ escluso
    assert cleanup._job_archive_bytes("j1") == 1007


def test_sweep_archives_within_quota_newest_first(sweep_env, monkeypatch):
    monkeypatch.setattr(accounts, "plan_quota_bytes", lambda plan: GIB)  # quota 1 GiB
    acct = _login("a@b.it")
    _consent(acct)
    _done_job(acct, "old", T0)
    _done_job(acct, "new", T0 + 10)
    _live_tokens(monkeypatch, "old", "new")
    sizes = {"old": GIB // 2, "new": GIB // 2 + 1}
    monkeypatch.setattr(cleanup, "_job_archive_bytes", lambda jid: sizes[jid])
    assert cleanup._archive_sweep(T0, force=True) == 1
    assert accounts.archive_protects("new")
    assert not accounts.archive_protects("old")     # oltre quota
    assert "old" in cleanup._archive_over_quota
    # liberata la quota, rientra solo dopo l'attesa
    accounts.hide_job(acct["id"], "new")
    assert cleanup._archive_sweep(T0 + 60, force=True) == 0
    assert cleanup._archive_sweep(T0 + cleanup.ARCHIVE_OVER_QUOTA_RETRY_SEC + 1, force=True) == 1
    assert accounts.archive_protects("old")


def test_sweep_skips_jobs_without_live_files(sweep_env, monkeypatch):
    acct = _login("a@b.it")
    _consent(acct)
    _done_job(acct, "gone")
    _done_job(acct, "empty")
    _live_tokens(monkeypatch, "empty")                  # "gone": token scaduti, non e' nell'insieme
    assert cleanup._archive_sweep(T0, force=True) == 0  # "empty" non ha output
    assert accounts.archive_usage(acct["id"]) == (0, 0)


def test_sweep_scans_tokens_once_not_per_candidate(sweep_env, monkeypatch):
    acct = _login("a@b.it")
    _consent(acct)
    ids = [f"j{i}" for i in range(6)]
    for i, jid in enumerate(ids):
        _done_job(acct, jid, T0 + i)
    _live_tokens(monkeypatch, *ids[:4])                 # j4 e j5: token scaduti
    real = _tkstore.jobs_with_active_download_tokens
    calls = []
    monkeypatch.setattr(_tkstore, "jobs_with_active_download_tokens",
                        lambda now=None: calls.append(now) or real(now))
    monkeypatch.setattr(_tkstore, "has_active_download_tokens",
                        lambda *a, **k: pytest.fail("scansione dei token per candidato"))
    monkeypatch.setattr(cleanup, "_job_archive_bytes", lambda jid: 1)
    assert cleanup._archive_sweep(T0 + 100, force=True) == 4
    assert calls == [T0 + 100]                          # una sola volta, con 6 candidati
    assert [accounts.archive_protects(j) for j in ids] == [True] * 4 + [False] * 2


def test_sweep_rate_limited(sweep_env, monkeypatch):
    monkeypatch.setitem(cleanup._archive_sweep_state, "at", T0)
    assert cleanup._archive_sweep(T0 + 10) == 0
    assert cleanup._archive_sweep_state["at"] == T0


def test_delete_cold_refused_for_archived(sweep_env, monkeypatch):
    acct = _login("a@b.it")
    _consent(acct)
    _done_job(acct, "j1")
    accounts.mark_archived("j1", 10)
    deleted = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", deleted.append)
    cleanup._delete_cold_for_job("j1")
    cleanup._delete_cold_for_job("j2")
    assert deleted == ["j2/"]


def test_cleanup_job_preserves_archived_dir(sweep_env, monkeypatch):
    acct = _login("a@b.it")
    _consent(acct)
    _done_job(acct, "j1")
    accounts.mark_archived("j1", 10)
    od = _output(sweep_env, "j1", 5)
    monkeypatch.setattr(cleanup, "_reconcile_unused_capture_for_job", lambda *a, **k: None)
    monkeypatch.setattr(_tkstore, "has_active_download_tokens", lambda jid, now=None: False)
    cleanup._cleanup_job("j1", "test")
    assert (od / "book.m4b").exists()


def test_archived_release_due(monkeypatch):
    monkeypatch.setattr(cleanup, "_effective_retention_for_job", lambda job: 100)
    now = T0
    assert cleanup._archived_release_due({"status": "done", "email_sent_at": now - 101}, now)
    assert not cleanup._archived_release_due({"status": "done", "email_sent_at": now - 50}, now)
    assert not cleanup._archived_release_due({"status": "done"}, now)
    assert not cleanup._archived_release_due({"status": "generating", "email_sent_at": 1}, now)
    assert cleanup._archived_release_due({"status": "translated", "translated_at": 1}, now)


# ------------------------------------------------------------ app e route

def test_token_retention_infinite_for_archived(acct_env):
    import audiobook_app as app
    acct = _login("a@b.it")
    _consent(acct)
    _done_job(acct, "j1")
    base = app._effective_retention_for_token_info({"job_id": "j1", "is_gemini": True})
    accounts.mark_archived("j1", 10)
    assert app._effective_retention_for_token_info({"job_id": "j1"}) == accounts.ARCHIVE_RETENTION_SEC
    assert base < accounts.ARCHIVE_RETENTION_SEC
    assert app._effective_retention_for_token_info({"job_id": "j2"}) < accounts.ARCHIVE_RETENTION_SEC


def test_account_page_shows_archive(acct_env):
    import account_page
    import i18n
    t = i18n.pick(i18n.load("account_pages"), "it")
    acct = _login("a@b.it")
    rows = [{"job_id": "j1", "status": "done", "kind": "generate", "created_at": T0,
             "downloads": [{"kind": "page", "url": "https://x/dl/t", "expires_at": T0 + 10 ** 9,
                            "archived": True}]}]
    html = account_page.render_history(
        t, lang="it", account=acct, rows=rows, page=1, per_page=50, total=1, voices_count=0,
        now=T0, archive={"plan": "sub_10", "plan_source": "paid", "plan_until": None,
                         "free_active": False, "quota_bytes": 10 * GIB, "used_bytes": GIB,
                         "jobs": 1, "items": 0, "state": "active", "grace_until": None})
    assert t["dl_archived"] in html
    assert "1 GB" in html and "10 GB" in html and t["plan_name_sub_10"] in html
    assert 'data-dl="2"' in html
    assert "acctJobDelPArch" in html


def _render(t, acct, archive):
    import account_page
    return account_page.render_history(
        t, lang="it", account=acct, rows=[], page=1, per_page=50, total=0, voices_count=0,
        now=T0, archive=archive, free_quota_bytes=512 * accounts.MIB, tolerance_days=15)


def _it():
    import i18n
    return i18n.pick(i18n.load("account_pages"), "it")


def test_plan_header_states(acct_env):
    t = _it()
    acct = _login("a@b.it")
    html = _render(t, acct, None)
    assert t["plan_inactive"] in html and t["free_activate_btn"] in html
    assert "/api/account/free_plan" in html and t["free_deactivate_btn"] not in html
    acct = accounts.free_plan_action(acct["id"], "activate", "account", now=T0)
    st = {"plan": "free", "plan_source": "", "plan_until": None, "free_active": True,
          "quota_bytes": 512 * accounts.MIB, "used_bytes": 380 * accounts.MIB, "jobs": 3,
          "items": 0, "state": "active", "grace_until": None}
    html = _render(t, acct, st)
    assert "380 MB" in html and "512 MB" in html and 'style="width:74%"' in html
    assert t["free_deactivate_btn"] in html
    html = _render(t, acct, {**st, "state": "grace", "grace_until": T0 + 15 * 86400})
    assert "2027-01-30" in html          # T0 = 2027-01-15 08:00 UTC, + 15 giorni
    gift = {**st, "plan": "sub_10", "plan_source": "gift", "plan_until": T0 + 10 * 86400,
            "free_active": False, "quota_bytes": 10 * accounts.GIB}
    html = _render(t, accounts.get(acct["id"]), gift)
    assert t["plan_name_sub_10"] in html and "2027-01-25" in html
    assert 'id="freePlanOn"' not in html and 'id="freePlanOff"' not in html


def test_plan_header_escapes(acct_env):
    import i18n
    t = dict(i18n.pick(i18n.load("account_pages"), "it"))
    t["plan_name_free"] = "<script>x</script>"
    acct = accounts.free_plan_action(_login("a@b.it")["id"], "activate", "account", now=T0)
    html = _render(t, acct, {"plan": "free", "plan_source": "", "plan_until": None,
                             "free_active": True, "quota_bytes": 1, "used_bytes": 0, "jobs": 0,
                             "items": 0, "state": "active", "grace_until": None})
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html


def test_plan_header_inactive_with_content(acct_env):
    """Senza consenso ne' regalo ma con libri ancora nell'archivio (tolleranza dopo
    lo spegnimento del gratuito o la scadenza di un regalo): non e' il piano
    gratuito (quota 0), la barra e' piena, la data limite si vede e il gratuito si
    puo' riattivare."""
    t = _it()
    acct = _login("a@b.it")
    _done_job(acct, "j1")
    accounts.mark_archived("j1", 200 * accounts.MIB)
    accounts.set_archive_tolerance(acct["id"], T0, 1)
    acct = accounts.get(acct["id"])
    st = accounts.archive_status(acct, now=T0)
    assert st["quota_bytes"] == 0 and st["state"] == "grace" and st["used_bytes"] == 200 * accounts.MIB
    html = _render(t, acct, st)
    assert t["plan_inactive"] in html and t["plan_name_free"] not in html
    assert 'style="width:100%"' in html and "200 MB su 0 MB" in html
    assert "2027-01-30" in html and escape(t["archive_tolerance_warn"].split("{date}")[0]) in html
    assert 'id="freePlanOn"' in html and 'id="freePlanOff"' not in html
    assert escape(t["free_deactivate_btn"]) not in html and escape(t["free_deactivate_p"].split("{days}")[0]) not in html
    # con `plan` "none" (nessun piano in vigore) l'esito e' lo stesso
    html = _render(t, acct, {**st, "plan": "none"})
    assert t["plan_inactive"] in html and t["plan_name_free"] not in html
    assert 'style="width:100%"' in html and 'id="freePlanOn"' in html


def test_plan_header_dialogs_and_wiring(acct_env):
    t = _it()
    acct = _login("a@b.it")
    html = _render(t, acct, None)
    # un solo dialog, quello di attivazione, con quota e giorni di tolleranza
    assert html.count('<dialog id="freePlanDlg">') == 1
    assert escape(t["free_info_p"].replace("{quota}", "512 MB").replace("{days}", "15")) in html
    assert t["free_deactivate_title"] not in html and 'data-action="activate"' in html
    assert "'/api/account/free_plan'" in html and "source:'account'" in html
    acct = accounts.free_plan_action(acct["id"], "activate", "account", now=T0)
    html = _render(t, acct, None)
    # consenso dato e archivio non leggibile: piano gratuito e ritiro, senza barra
    assert t["plan_name_free"] in html and 'id="freePlanOff"' in html and 'class="quota"' not in html
    assert escape(t["free_deactivate_p"].replace("{days}", "15")) in html
    assert 'data-action="deactivate"' in html and escape(t["free_info_p"].split("{quota}")[0]) not in html


def test_plan_header_usage_percent():
    import account_page
    assert account_page._usage_pct(0, 0) == 0 and account_page._usage_pct(0, 5) == 0
    assert account_page._usage_pct(5, 0) == 100                  # senza quota non c'e' margine
    assert account_page._usage_pct(1, 2) == 50 and account_page._usage_pct(3, 2) == 100
    assert account_page._usage_pct(995, 1000) == 99               # mai "pieno" se non lo e'


def test_i18n_keys_in_all_languages():
    import i18n
    data = i18n.load("account_pages")
    new = ("plan_title", "plan_name_free", "plan_name_sub_5", "plan_name_sub_10", "plan_gift_until",
           "plan_inactive", "archive_usage", "archive_tolerance_warn", "free_activate_btn",
           "free_activate_title", "free_info_p", "free_confirm_btn", "free_deactivate_btn",
           "free_deactivate_title", "free_deactivate_p", "free_deactivate_confirm")
    for lang in i18n.LANGS:
        for k in ("dl_archived", "job_delete_archived_p", *new):
            assert data[lang].get(k), (lang, k)
        assert "archive_line" not in data[lang] and "archive_line_ended" not in data[lang], lang
    # i segnaposto sono gli stessi in ogni lingua
    for k in new:
        marks = {lang: sorted(re.findall(r"\{\w+\}", data[lang][k])) for lang in i18n.LANGS}
        assert all(m == marks["en"] for m in marks.values()), (k, marks)
    assert sorted(re.findall(r"\{\w+\}", data["en"]["free_info_p"])) == ["{days}", "{quota}"]
    assert re.findall(r"\{\w+\}", data["en"]["free_deactivate_p"]) == ["{days}"]
    # nessun nome di provider nei testi della testata
    for lang in i18n.LANGS:
        for k in new:
            assert not re.search(r"deepseek|gemini|openai|google|speechify|voxcpm", data[lang][k], re.I), (lang, k)


# ------------------------------------------------------------ piani regalati: console admin

def test_admin_gift_routes(acct_env, monkeypatch):
    client = _admin(monkeypatch)
    acct = _login("a@b.it")
    h = {"X-Admin-Token": "secret"}
    url = "/admin/api/accounts/gift"
    body = {"account_id": acct["id"], "plan": "sub_10", "until": "2099-01-31"}
    assert client.post(url, json=body).status_code == 401
    r = client.post(url, json=body, headers=h)
    assert r.status_code == 200 and r.get_json()["plan_source"] == "gift"
    assert r.get_json()["plan_until"] == 4073587200          # 2099-02-01T00:00:00Z
    assert client.post(url, json={**body, "until": "2000-01-01"}, headers=h).status_code == 400
    assert client.post(url, json={**body, "plan": "archive_10"}, headers=h).status_code == 400
    assert client.post(url, json={**body, "account_id": "nope"}, headers=h).status_code == 404
    rv = "/admin/api/accounts/gift_revoke"
    assert client.post(rv, json={"account_id": acct["id"]}, headers=h).status_code == 200
    assert client.post(rv, json={"account_id": acct["id"]}, headers=h).status_code == 409
    assert client.post("/admin/api/accounts/plan", json={}, headers=h).status_code in (404, 405)


def test_admin_gift_route_contract(acct_env, monkeypatch):
    client = _admin(monkeypatch)
    acct = _login("a@b.it")
    h = {"X-Admin-Token": "secret"}
    url = "/admin/api/accounts/gift"
    r = client.post(url, json={"account_id": acct["id"], "plan": "sub_5", "until": "2099-01-31"}, headers=h)
    assert r.get_json() == {"ok": True, "id": acct["id"], "plan": "sub_5", "plan_source": "gift",
                            "plan_until": 4073587200, "archive_quota_bytes": 5 * GIB}
    stored = accounts.get(acct["id"])
    assert (stored["plan"], stored["plan_source"], stored["plan_until"]) == ("sub_5", "gift", 4073587200)
    assert stored["free_consent_at"] is None                 # il regalo non da' consensi
    r = client.post("/admin/api/accounts/gift_revoke", json={"account_id": acct["id"]}, headers=h)
    assert r.get_json() == {"ok": True, "id": acct["id"], "plan": "free"}
    assert accounts.get(acct["id"])["plan_source"] == ""


def test_admin_gift_route_validation(acct_env, monkeypatch):
    client = _admin(monkeypatch)
    acct = _login("a@b.it")
    h = {"X-Admin-Token": "secret"}
    url = "/admin/api/accounts/gift"
    ok = {"account_id": acct["id"], "plan": "sub_5", "until": "2099-01-31"}
    for bad in ({}, {**ok, "account_id": ""}, {"plan": "sub_5", "until": "2099-01-31"},
                {**ok, "plan": ""}, {**ok, "plan": "free"}, {**ok, "plan": ["sub_5"]},
                {**ok, "until": ""}, {**ok, "until": "31/01/2099"}, {**ok, "until": "2099-13-01"},
                {k: v for k, v in ok.items() if k != "until"}, {**ok, "until": 4073587200},
                {**ok, "until": "2000-01-01"}):
        r = client.post(url, json=bad, headers=h)
        assert r.status_code == 400, bad
        assert r.get_json()["error"], bad
    assert client.post(url, data="not json", headers=h).status_code == 400
    assert accounts.get(acct["id"])["plan"] == "free"
    rv = "/admin/api/accounts/gift_revoke"
    assert client.post(rv, json={}, headers=h).status_code == 400
    assert client.post(rv, json={"account_id": "nope"}, headers=h).get_json() == {"error": "not_found"}
    assert client.post(rv, json={"account_id": "nope"}).status_code == 401


def test_admin_gift_route_until_is_end_of_that_utc_day(acct_env, monkeypatch):
    monkeypatch.setattr(accounts, "_now", lambda now: T0 if now is None else int(now))   # 2027-01-15T08:00Z
    client = _admin(monkeypatch)
    acct = _login("a@b.it")
    h = {"X-Admin-Token": "secret"}
    url = "/admin/api/accounts/gift"
    body = {"account_id": acct["id"], "plan": "sub_5"}
    assert client.post(url, json={**body, "until": "2027-01-14"}, headers=h).status_code == 400   # ieri
    r = client.post(url, json={**body, "until": "2027-01-15"}, headers=h)                         # oggi
    assert r.status_code == 200 and r.get_json()["plan_until"] == 1_800_057_600                  # 2027-01-16T00:00Z
    assert accounts.get(acct["id"])["plan_until"] - T0 == 16 * 3600


def test_admin_gift_route_conflicts_and_disabled(acct_env, monkeypatch):
    client = _admin(monkeypatch)
    acct = _login("a@b.it")
    h = {"X-Admin-Token": "secret"}
    url, rv = "/admin/api/accounts/gift", "/admin/api/accounts/gift_revoke"
    body = {"account_id": acct["id"], "plan": "sub_10", "until": "2099-01-31"}
    with db.tx() as c:
        c.execute("UPDATE accounts SET plan='sub_5', plan_source='paid', plan_until=NULL WHERE id=?",
                  (acct["id"],))
    r = client.post(url, json=body, headers=h)
    assert r.status_code == 409 and r.get_json() == {"error": "paid_plan_active"}
    r = client.post(rv, json={"account_id": acct["id"]}, headers=h)
    assert r.status_code == 409 and r.get_json() == {"error": "not_gift"}
    assert accounts.get(acct["id"])["plan_source"] == "paid"
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert client.post(url, json=body, headers=h).status_code == 503
    assert client.post(rv, json={"account_id": acct["id"]}, headers=h).status_code == 503


def test_admin_template_has_gift_controls():
    import pathlib
    html = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "templates", "pages", "admin_audit_premium.html").read_text(encoding="utf-8")
    for s in ("/admin/api/accounts/gift", "/admin/api/accounts/gift_revoke",
              "5 GB (regalo)", "10 GB (regalo)", "Gratuito attivo", "Nessun piano",
              "Pagato", "Regalato", "In tolleranza"):
        assert s in html
    assert "/admin/api/accounts/plan\"" not in html and "archive_20" not in html


def test_admin_template_gift_ui_is_consistent():
    import pathlib
    import re
    html = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "templates", "pages", "admin_audit_premium.html").read_text(encoding="utf-8")
    assert not re.search(r"archive_(10|20|50)|ABM_ARCHIVE_GRACE_DAYS|subscribed", html)
    assert "Revoca regalo" in html and 'origin === "gift"' in html
    assert re.search(r'<input type="date" data-acc-gift-until min="\$\{', html)   # data minima = oggi
    for param in ("plan", "origin"):
        assert f'p.set("{param}"' in html
    for agg in ("Pagati", "Regalati", "Gratuito attivo", "In tolleranza"):
        assert agg in html
    # i valori che arrivano dal server entrano solo escapati
    assert "escAttr(r.id)" in html and "data-acc-gift" in html
