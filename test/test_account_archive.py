# test/test_account_archive.py
"""Abbonamento di archivio: piano attribuito dall'admin, ingresso dei job in
archivio entro quota, protezione da retention e cleanup, area personale."""
import time

import pytest

import accounts
import cleanup
import db
import storage_backend
import token_store as _tkstore


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

def test_set_plan_validates_and_revokes_with_plan_until(acct_env):
    acct = _login("a@b.it")
    with pytest.raises(ValueError):
        accounts.set_plan(acct["id"], "archive_99")
    assert accounts.set_plan("missing", "archive_10") is None
    out = accounts.set_plan(acct["id"], "archive_20", now=T0)
    assert out["plan"] == "archive_20" and out["plan_until"] is None
    assert accounts.archive_quota_bytes("archive_20") == 20 * GIB
    out = accounts.set_plan(acct["id"], "free", now=T0 + 5)
    assert out["plan"] == "free" and out["plan_until"] == T0 + 5
    # free -> free non sposta la data di revoca
    assert accounts.set_plan(acct["id"], "free", now=T0 + 99)["plan_until"] == T0 + 5


def test_set_plan_refuses_deleted_account(acct_env):
    acct = _login("a@b.it")
    accounts.delete_account(acct["id"], now=T0)
    assert accounts.set_plan(acct["id"], "archive_10") is None


def test_candidates_only_done_visible_of_subscribers(acct_env):
    sub, free = _login("s@b.it"), _login("f@b.it")
    accounts.set_plan(sub["id"], "archive_10")
    _done_job(sub, "old", T0)
    _done_job(sub, "new", T0 + 10)
    accounts.record_job(sub["id"], "run", kind="generate", status="running")
    _done_job(sub, "hid", T0 + 5)
    accounts.hide_job(sub["id"], "hid")
    _done_job(free, "fj")
    assert [c["job_id"] for c in accounts.archive_candidates()] == ["new", "old"]
    assert accounts.mark_archived("new", 100, now=T0)
    assert not accounts.mark_archived("new", 200, now=T0)  # gia' archiviato
    assert [c["job_id"] for c in accounts.archive_candidates()] == ["old"]
    assert accounts.archive_usage(sub["id"]) == (100, 1)


def test_protection_follows_plan_and_grace(acct_env, monkeypatch):
    acct = _login("a@b.it")
    accounts.set_plan(acct["id"], "archive_10")
    _done_job(acct, "j1")
    accounts.mark_archived("j1", 10)
    assert accounts.archive_protects("j1")
    assert not accounts.archive_protects("other")
    now = int(time.time())
    accounts.set_plan(acct["id"], "free", now=now)
    assert accounts.archive_protects("j1")          # grazia
    assert accounts.archive_candidates() == []        # niente nuovi ingressi
    monkeypatch.setenv("ABM_ARCHIVE_GRACE_DAYS", "0")
    accounts._archive_cache_clear()
    assert not accounts.archive_protects("j1")


def test_hide_and_delete_release_archive(acct_env):
    acct = _login("a@b.it")
    accounts.set_plan(acct["id"], "archive_10")
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
    accounts.set_plan(acct["id"], "archive_50")
    _done_job(acct, "j1")
    accounts.mark_archived("j1", 3 * GIB)
    st = accounts.archive_status(accounts.get(acct["id"]))
    assert st == {"plan": "archive_50", "quota_bytes": 50 * GIB, "used_bytes": 3 * GIB, "jobs": 1}
    out = accounts.admin_list(now=T0 + 60)
    r = out["records"][0]
    assert r["plan"] == "archive_50"
    assert r["archive_bytes"] == 3 * GIB and r["archive_jobs"] == 1
    assert r["archive_quota_bytes"] == 50 * GIB
    assert out["aggregates"]["subscribed"] == 1
    assert out["plans"] == ["free", "archive_10", "archive_20", "archive_50"]


# ------------------------------------------------------------ cleanup.py

@pytest.fixture
def sweep_env(acct_env, monkeypatch):
    import audiobook_app  # noqa: F401  configura cleanup (lock, cartelle, policy)
    monkeypatch.setattr(cleanup, "_upload_dir", lambda: acct_env)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(_tkstore, "has_active_download_tokens", lambda jid, now=None: True)
    monkeypatch.setattr(cleanup, "_archive_over_quota", {})
    return acct_env


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
    monkeypatch.setitem(accounts.ARCHIVE_PLANS, "archive_10", 1)  # quota 1 GiB
    acct = _login("a@b.it")
    accounts.set_plan(acct["id"], "archive_10")
    _done_job(acct, "old", T0)
    _done_job(acct, "new", T0 + 10)
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
    accounts.set_plan(acct["id"], "archive_10")
    _done_job(acct, "gone")
    _done_job(acct, "empty")
    monkeypatch.setattr(_tkstore, "has_active_download_tokens", lambda jid, now=None: jid != "gone")
    assert cleanup._archive_sweep(T0, force=True) == 0  # "empty" non ha output
    assert accounts.archive_usage(acct["id"]) == (0, 0)


def test_sweep_rate_limited(sweep_env, monkeypatch):
    monkeypatch.setitem(cleanup._archive_sweep_state, "at", T0)
    assert cleanup._archive_sweep(T0 + 10) == 0
    assert cleanup._archive_sweep_state["at"] == T0


def test_delete_cold_refused_for_archived(sweep_env, monkeypatch):
    acct = _login("a@b.it")
    accounts.set_plan(acct["id"], "archive_10")
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
    accounts.set_plan(acct["id"], "archive_10")
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
    accounts.set_plan(acct["id"], "archive_10")
    _done_job(acct, "j1")
    base = app._effective_retention_for_token_info({"job_id": "j1", "is_gemini": True})
    accounts.mark_archived("j1", 10)
    assert app._effective_retention_for_token_info({"job_id": "j1"}) == accounts.ARCHIVE_RETENTION_SEC
    assert base < accounts.ARCHIVE_RETENTION_SEC
    assert app._effective_retention_for_token_info({"job_id": "j2"}) < accounts.ARCHIVE_RETENTION_SEC


def _admin(monkeypatch):
    import audiobook_app as app
    monkeypatch.setattr(app, "ADMIN_TOKEN", "secret", raising=False)
    monkeypatch.setattr(app, "_admin_auth_ok", lambda tok: tok == "secret")
    app.app.config["TESTING"] = True
    return app.app.test_client()


def test_admin_plan_route(acct_env, monkeypatch):
    client = _admin(monkeypatch)
    acct = _login("a@b.it")
    url = "/admin/api/accounts/plan"
    assert client.post(url, json={"account_id": acct["id"], "plan": "archive_10"}).status_code == 401
    h = {"X-Admin-Token": "secret"}
    r = client.post(url, json={"account_id": acct["id"], "plan": "archive_20"}, headers=h)
    assert r.status_code == 200
    assert r.get_json()["plan"] == "archive_20"
    assert r.get_json()["archive_quota_bytes"] == 20 * GIB
    assert accounts.get(acct["id"])["plan"] == "archive_20"
    assert client.post(url, json={"account_id": acct["id"], "plan": "gold"}, headers=h).status_code == 400
    assert client.post(url, json={"account_id": "nope", "plan": "free"}, headers=h).status_code == 404
    assert client.post(url, json={"plan": "free"}, headers=h).status_code == 400


def test_admin_template_has_plan_selector():
    import pathlib
    html = pathlib.Path(__file__).resolve().parent.parent.joinpath(
        "templates", "pages", "admin_audit_premium.html").read_text(encoding="utf-8")
    assert "/admin/api/accounts/plan" in html
    for label in ("Nessun abbonamento", "10 GB di archivio", "20 GB di archivio", "50 GB di archivio"):
        assert label in html


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
        now=T0, archive={"plan": "archive_10", "quota_bytes": 10 * GIB, "used_bytes": GIB, "jobs": 1})
    assert t["dl_archived"] in html
    assert "1.00 GB" in html and "10 GB" in html
    assert 'data-dl="2"' in html
    assert "acctJobDelPArch" in html


def test_i18n_keys_in_all_languages():
    import i18n
    data = i18n.load("account_pages")
    for lang in i18n.LANGS:
        for k in ("dl_archived", "archive_line", "archive_line_ended", "job_delete_archived_p"):
            assert data[lang].get(k), (lang, k)
