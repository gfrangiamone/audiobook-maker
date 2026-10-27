# test/test_account_archive.py
"""Archivio dei lavori: quota del piano (gratuito con consenso), ingresso dei job
in archivio entro quota, protezione da retention e cleanup, area personale."""
import json
import pathlib
import re
import shutil
import subprocess
from html import escape
from urllib.parse import parse_qsl, urlsplit

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
                  "items": 0, "state": "active", "grace_until": None, "fill_pct": 58.6}
    out = accounts.admin_list(now=T0 + 60)
    r = out["records"][0]
    assert r["plan"] == "free"
    assert r["archive_bytes"] == 300 * accounts.MIB and "archive_jobs" not in r
    assert r["archive_quota_bytes"] == 512 * accounts.MIB
    assert r["archive_fill_pct"] == 58.6                     # 300 / 512 MiB
    assert out["plans"] == ["free", "sub_5", "sub_10"]


def test_admin_list_sorts_by_archive_fill(acct_env):
    """sort=fill: piu' piena prima su tutte le righe filtrate, poi la pagina; un archivio senza
    quota sta in cima, nessun archivio senza quota in fondo; a parita' vale la registrazione."""
    def acct(email, created, consent, mib):
        a = _login(email, now=created)
        if consent:
            _consent(a)
        if mib:
            _done_job(a, email, created)
            accounts.mark_archived(email, mib * accounts.MIB)
        return email
    half = acct("half@b.it", T0 + 5, True, 300)
    full = acct("full@b.it", T0 + 1, True, 450)
    lost = acct("lost@b.it", T0 + 2, False, 10)               # archivio rimasto senza quota
    empty = acct("empty@b.it", T0 + 3, True, 0)
    zero = acct("zero@b.it", T0 + 4, True, 0)
    none = acct("none@b.it", T0 + 6, False, 0)

    def emails(**kw):
        return [r["email"] for r in accounts.admin_list(now=T0 + 60, **kw)["records"]]
    assert emails() == [none, half, zero, empty, lost, full]
    assert emails(sort="fill") == [lost, full, half, zero, empty, none]
    assert emails(sort="fill", limit=2, offset=1) == [full, half]
    assert emails(sort="boh") == emails()
    out = accounts.admin_list(now=T0 + 60, sort="fill", limit=1)
    assert out["count"] == 6 and out["records"][0]["archive_fill_pct"] is None
    pct = {r["email"]: r["archive_fill_pct"] for r in accounts.admin_list(now=T0 + 60)["records"]}
    assert (pct[full], pct[half], pct[empty], pct[none]) == (87.9, 58.6, 0.0, None)


def test_accounts_audit_api_passes_sort(acct_env, monkeypatch):
    seen = {}
    monkeypatch.setattr(accounts, "admin_list", lambda **kw: seen.update(kw) or {"records": []})
    client = _admin(monkeypatch)
    h = {"X-Admin-Token": "secret"}
    client.get("/admin/api/accounts_audit?sort=%20FILL%20", headers=h)
    assert seen["sort"] == "fill"
    client.get("/admin/api/accounts_audit", headers=h)
    assert seen["sort"] == ""


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


def test_sweep_over_quota_marks_the_row_until_archived(sweep_env, monkeypatch):
    """Spec §9.3 punto 2: il libro che non entra per quota resta annotato sulla
    riga (una volta sola) finche' un passaggio successivo non lo archivia."""
    monkeypatch.setattr(accounts, "plan_quota_bytes", lambda plan: GIB)
    acct = _login("a@b.it")
    _consent(acct)
    _done_job(acct, "old", T0)
    _done_job(acct, "new", T0 + 10)
    _live_tokens(monkeypatch, "old", "new")
    sizes = {"old": GIB // 2, "new": GIB // 2 + 1}
    monkeypatch.setattr(cleanup, "_job_archive_bytes", lambda jid: sizes[jid])
    assert cleanup._archive_sweep(T0, force=True) == 1

    def skipped():
        return {r["job_id"]: r["archive_skipped_at"] for r in accounts.list_jobs(acct["id"])[0]}
    assert skipped() == {"old": T0, "new": None}
    assert not accounts.mark_archive_skipped("old", T0 + 5)      # gia' annotato
    assert not accounts.mark_archive_skipped("new", T0 + 5)      # archiviato: non si annota
    accounts.hide_job(acct["id"], "new")
    assert cleanup._archive_sweep(T0 + cleanup.ARCHIVE_OVER_QUOTA_RETRY_SEC + 1, force=True) == 1
    assert skipped() == {"old": None}


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


def test_plan_header_gift_last_day_is_the_day_before_midnight(acct_env):
    """`gift_plan` salva la scadenza a mezzanotte UTC del giorno dopo l'ultimo
    giorno scelto: la testata mostra l'ultimo giorno, non la mezzanotte."""
    t = _it()
    acct = _login("a@b.it")
    until = T0 + 16 * 3600                               # 2027-01-16T00:00Z
    assert accounts.utc_day(until) == "2027-01-16" and accounts.utc_day(until - 1) == "2027-01-15"
    st = {"plan": "sub_5", "plan_source": "gift", "plan_until": until, "free_active": False,
          "quota_bytes": 5 * accounts.GIB, "used_bytes": 0, "jobs": 0, "items": 0,
          "state": "active", "grace_until": None}
    html = _render(t, acct, st)
    assert "2027-01-15" in html and "2027-01-16" not in html


def test_plan_header_quota_bar_is_an_accessible_progressbar(acct_env):
    """La barra della quota non e' solo `width:N%`: ha ruolo e valori numerici per chi non la vede."""
    t = _it()
    acct = accounts.free_plan_action(_login("a@b.it")["id"], "activate", "account", now=T0)
    st = {"plan": "free", "plan_source": "", "plan_until": None, "free_active": True,
          "quota_bytes": 512 * accounts.MIB, "used_bytes": 380 * accounts.MIB, "jobs": 3,
          "items": 0, "state": "active", "grace_until": None}
    html = _render(t, acct, st)
    bar = re.search(r'<div class="quota[^"]*"([^>]*)>', html).group(1)
    assert 'role="progressbar"' in bar
    assert 'aria-valuemin="0"' in bar and 'aria-valuemax="100"' in bar and 'aria-valuenow="74"' in bar
    assert 'aria-valuetext="380 MB' in bar and "512 MB" in bar
    html = _render(t, acct, {**st, "quota_bytes": 0, "used_bytes": 200 * accounts.MIB, "state": "grace",
                             "grace_until": T0 + 15 * 86400})       # senza quota l'archivio non vuoto e' pieno
    assert 'aria-valuenow="100"' in re.search(r'<div class="quota[^"]*"([^>]*)>', html).group(1)
    t = dict(t)
    t["archive_usage"] = '"><script>x</script> {used} {quota}'
    bar = re.search(r'<div class="quota[^"]*"([^>]*)>', _render(t, acct, st)).group(1)
    assert "<script>" not in bar and '"><' not in bar and "&lt;script&gt;" in bar


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


def test_admin_gift_route_until_max_date_is_400_not_500(acct_env, monkeypatch):
    """`9999-12-31` + 1 giorno esce dal range di `datetime`: input non valido (400), mai 500."""
    client = _admin(monkeypatch)
    acct = _login("a@b.it")
    h = {"X-Admin-Token": "secret"}
    body = {"account_id": acct["id"], "plan": "sub_5", "until": "9999-12-31"}
    r = client.post("/admin/api/accounts/gift", json=body, headers=h)
    assert r.status_code == 400 and r.get_json()["error"]
    assert accounts.get(acct["id"])["plan"] == "free"


def test_admin_gift_routes_non_object_json_body_is_400(acct_env, monkeypatch):
    """Un corpo JSON che non e' un oggetto (`[1]`, `"x"`, `1`) vale come `{}`: 400, mai 500."""
    client = _admin(monkeypatch)
    acct = _login("a@b.it")
    h = {"X-Admin-Token": "secret"}
    for url in ("/admin/api/accounts/gift", "/admin/api/accounts/gift_revoke"):
        for body in ([1], "x", 1, [], None):
            r = client.post(url, json=body, headers=h)
            assert r.status_code == 400, (url, body)
            assert r.get_json() == {"error": "account_id required"}, (url, body)
    assert accounts.get(acct["id"])["plan"] == "free"


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
    # regalo attivo: va revocato prima di farne un altro
    with db.tx() as c:
        c.execute("UPDATE accounts SET plan='sub_5', plan_source='gift', plan_until=4073587200 WHERE id=?",
                  (acct["id"],))
    r = client.post(url, json=body, headers=h)
    assert r.status_code == 409 and r.get_json() == {"error": "gift_active"}
    stored = accounts.get(acct["id"])
    assert (stored["plan"], stored["plan_source"], stored["plan_until"]) == ("sub_5", "gift", 4073587200)
    assert client.post(rv, json={"account_id": acct["id"]}, headers=h).status_code == 200
    assert client.post(url, json=body, headers=h).status_code == 200
    monkeypatch.setattr(accounts, "ENABLE", False)
    assert client.post(url, json=body, headers=h).status_code == 503
    assert client.post(rv, json={"account_id": acct["id"]}, headers=h).status_code == 503


ADMIN_HTML = pathlib.Path(__file__).resolve().parent.parent.joinpath(
    "templates", "pages", "admin_audit_premium.html")
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node non disponibile")

# Finto DOM minimo per eseguire in node la sezione "Utenti registrati" della console:
# elementi per id creati al volo, caselle degli aggregati prese dal template (AGG_KEYS),
# fetch/alert/confirm registrati. AUDIT e' la risposta di /admin/api/accounts_audit.
_ADMIN_FAKE_DOM = r"""
const _els = {};
function _el(id){
  const cls = new Set(), on = {};
  const e = {id, value: "", checked: false, hidden: false, disabled: false, innerHTML: "",
    textContent: "", dataset: {},
    classList: {toggle(c, v){ if (v) cls.add(c); else cls.delete(c); }, contains: (c) => cls.has(c)},
    addEventListener(t, f){ (on[t] = on[t] || []).push(f); },
    _fire(t, ev){ (on[t] || []).forEach(f => f(Object.assign({target: e, currentTarget: e, preventDefault(){}}, ev))); },
    querySelector(){ return null; }, focus(){}};
  return e;
}
const $ = (id) => _els[id] || (_els[id] = _el(id));
const _boxes = AGG_KEYS.map(k => {
  const b = _el(), v = _el();
  b.dataset.accAgg = k; b.querySelector = () => v; b._value = v;
  return b;
});
const _box = (k) => _boxes.find(b => b.dataset.accAgg === k);
const document = Object.assign(_el(), {
  querySelectorAll: () => _boxes,
  createElement(){ let v = ""; return {set textContent(s){ v = String(s); },
    get innerHTML(){ return v.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;"); }}; },
});
const ADMIN_TOKEN = "t";
const _fetches = [], _alerts = [];
let _giftReply = {ok: true, status: 200, body: "{}"};
// _holdUrl: le risposte alle URL con questo prefisso restano in _held finche' il test non le rilascia.
let _holdUrl = "";
const _held = [];
function fmtEur(n){ return String(n); }
function auditTruncNote(){ return ""; }
function alert(m){ _alerts.push(String(m)); }
function confirm(){ return true; }
async function fetch(url, opts){
  _fetches.push({url, body: opts && opts.body ? JSON.parse(opts.body) : null});
  let res;
  if (url.startsWith("/admin/api/accounts_audit")) {
    const snap = JSON.parse(JSON.stringify(AUDIT));      // AUDIT com'era alla richiesta
    res = {ok: true, status: 200, json: async () => snap};
  } else {
    const g = _giftReply;
    res = {ok: g.ok, status: g.status, text: async () => g.body};
  }
  return _holdUrl && url.startsWith(_holdUrl) ? new Promise(r => _held.push(() => r(res))) : res;
}
const _tick = () => new Promise(r => setTimeout(r, 0));
"""


def _js_fn(html, name):
    """Sorgente della funzione `name` del template."""
    start = html.index("function %s(" % name)
    depth = 0
    for j in range(html.index("{", start), len(html)):
        depth += {"{": 1, "}": -1}.get(html[j], 0)
        if depth == 0:
            return html[start:j + 1]
    raise AssertionError(name)


def _run_admin_accounts_js(tmp_path, consts, body):
    """Esegue in node la sezione "Utenti registrati" del template sul finto DOM, poi `body` in
    una funzione async; `consts` diventano costanti JS. Ritorna il JSON stampato da `body`."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    section = html[html.index("// ===================== Utenti registrati"):
                   html.index("// ===================== Tab switching")]
    consts = dict({"AUDIT": {}}, **consts, AGG_KEYS=re.findall(r'data-acc-agg="([a-z0-9_]+)"', html))
    script = tmp_path / "admin_accounts.js"
    script.write_text(
        "".join("const %s = %s;\n" % (k, json.dumps(v)) for k, v in consts.items())
        + _ADMIN_FAKE_DOM + _js_fn(html, "esc") + "\n" + section
        + "\n(async () => {\n" + body + "\n})().catch(e => { console.error(e); process.exit(1); });\n",
        encoding="utf-8")
    res = subprocess.run(["node", str(script)], capture_output=True, text=True)
    assert res.returncode == 0, res.stderr
    return json.loads(res.stdout.strip())


def test_admin_template_has_gift_controls():
    html = ADMIN_HTML.read_text(encoding="utf-8")
    for s in ("/admin/api/accounts/gift", "/admin/api/accounts/gift_revoke",
              "5 GB (regalo)", "10 GB (regalo)", "Gratuito attivo", "Nessun piano",
              "Pagato", "Regalato", "In tolleranza", 'id="accGiftModal"', 'id="accTolFilter"',
              '"gift_active":'):
        assert s in html
    assert "/admin/api/accounts/plan\"" not in html and "archive_20" not in html


@needs_node
def test_admin_console_plan_cell_escapes_server_values(tmp_path):
    """Si esegue davvero `accPlanCell` con valori ostili (id, piano, origine): il payload grezzo non
    compare nel markup, ne' esce da un attributo; c'e' solo la forma escapata. Il bottone Regalo e'
    colorato sul regalo attivo, spento sul pagato, assente sul cancellato; niente controlli inline."""
    evil_id = 'x"><script>alert(1)</script>'
    rows = [{"id": evil_id, "origin": "gift", "plan_effective": "<img src=x onerror=alert(1)>",
             "plan_until": 1_800_057_600, "archive_bytes": 1, "archive_quota_bytes": 2,
             "archive_grace_until": 1_800_057_600},
            {"id": evil_id, "origin": "<svg onload=alert(1)>", "plan_effective": "free"},
            {"id": "acc-paid", "origin": "paid", "plan_effective": "sub_5"},
            {"id": "acc-del", "origin": "none", "deleted_at": T0}]
    cells = _run_admin_accounts_js(tmp_path, {"ROWS": rows},
                                   "console.log(JSON.stringify(ROWS.map(accPlanCell)));")
    gift, odd, paid, deleted = cells
    for cell in (gift, odd):
        assert "<script" not in cell and "<img" not in cell and "<svg" not in cell
        assert 'onerror=alert(1)>' not in cell and 'onload=alert(1)>' not in cell
        assert '="x"' not in cell and evil_id not in cell                 # non esce dall'attributo
        assert 'data-acc-gift-open="x&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;"' in cell
    assert "&lt;img src=x onerror=alert(1)&gt;" in gift
    assert "&lt;svg onload=alert(1)&gt;" in odd

    def btn(cell):
        return re.search(r"<button [^>]*data-acc-gift-open[^>]*>", cell).group(0)
    assert "secondary" not in btn(gift) and "secondary" in btn(odd)      # accent solo sul regalo attivo
    assert re.search(r"\bdisabled\b", btn(paid)) and 'title="' in btn(paid)
    assert not re.search(r"\bdisabled\b", btn(gift) + btn(odd))
    assert "data-acc-gift-open" not in deleted
    for cell in cells:
        assert "<select" not in cell and "<input" not in cell and "Revoca" not in cell


@needs_node
def test_admin_plan_cell_shows_archive_fill(tmp_path):
    """La cella mostra l'occupazione della quota del server (rossa oltre l'80%), non il consenso
    al gratuito ne' il numero di job in archivio; senza quota niente percentuale."""
    base = {"origin": "free", "plan_effective": "free", "free_consent_at": T0, "archive_jobs": 7}
    rows = [dict(base, id="a", archive_bytes=GIB // 4, archive_quota_bytes=GIB, archive_fill_pct=25),
            dict(base, id="b", archive_bytes=GIB, archive_quota_bytes=GIB, archive_fill_pct=80),
            dict(base, id="c", archive_bytes=GIB, archive_quota_bytes=GIB, archive_fill_pct=80.1),
            dict(base, id="d", archive_bytes=GIB, archive_quota_bytes=0, archive_fill_pct=None),
            dict(base, id="e", archive_fill_pct='<img src=x onerror=alert(1)>',
                 archive_bytes=1, archive_quota_bytes=1)]
    low, edge, high, lost, odd = _run_admin_accounts_js(
        tmp_path, {"ROWS": rows}, "console.log(JSON.stringify(ROWS.map(accPlanCell)));")
    for cell in (low, edge, high, lost, odd):
        assert "consenso" not in cell and " job" not in cell and "<img" not in cell
    assert "0.25 GB / 1.00 GB &middot; <span>25%</span>" in low
    assert "<span>80%</span>" in edge
    assert '<span class="delta-negative">80.1%</span>' in high
    assert "1.00 GB</small>" in lost and "%" not in lost


@needs_node
def test_admin_accounts_sort_select_reloads_with_sort(tmp_path):
    """L'ordinamento va al server solo se non e' quello di default, rilegge subito al cambio e non
    spegne la casella degli aggregati attiva; il titolo dice quale elenco si sta guardando."""
    out = _run_admin_accounts_js(tmp_path, {"AUDIT": {"records": [], "count": 0}}, r"""
      const q = () => Object.fromEntries(new URLSearchParams(_fetches[_fetches.length - 1].url.split("?")[1]));
      const out = {};
      $("accSort").value = "recent"; await accFetch();
      out.recent = {q: q(), title: $("accListScope").textContent};
      _box("gift")._fire("click"); await _tick();
      $("accSort").value = "fill"; $("accSort")._fire("change"); await _tick();
      out.fill = {q: q(), title: $("accListScope").textContent,
                  marked: _boxes.filter(b => b.classList.contains("agg-active")).map(b => b.dataset.accAgg)};
      console.log(JSON.stringify(out));
    """)
    assert out["recent"]["q"] == {"limit": "500"} and out["recent"]["title"] == "ultimi 500"
    assert out["fill"]["q"] == {"origin": "gift", "sort": "fill", "limit": "500"}
    assert out["fill"]["marked"] == ["gift"] and "piena" in out["fill"]["title"]


@needs_node
def test_admin_gift_popup_opens_filled_and_reports_errors_inside(tmp_path):
    """Il popup si riempie all'apertura con la riga della tabella: taglio e data liberi senza
    regalo, in sola lettura con la revoca sul regalo attivo, valori escapati. Gli errori
    (validazione, 409 del server) restano nel popup senza alert; l'esito ok chiude e rilegge la
    tabella; Esc, clic sull'overlay e X chiudono."""
    evil_id = 'x"><script>alert(1)</script>'
    rows = [{"id": "acc-free", "email": "a@x.it", "origin": "free", "plan_effective": "free"},
            {"id": evil_id, "email": "<img src=x onerror=alert(1)>", "origin": "gift",
             "plan_effective": "sub_10", "plan_until": 1_800_057_600},
            {"id": "acc-paid", "email": "p@x.it", "origin": "paid", "plan_effective": "sub_5"},
            {"id": "acc-del", "origin": "none", "deleted_at": T0}]
    out = _run_admin_accounts_js(tmp_path, {"ROWS": rows, "EVIL": evil_id,
                                            "AUDIT": {"records": rows, "count": 4}}, r"""
      const modal = $("accGiftModal"), err = $("accGiftErr"), out = {today: accToday()};
      const posts = () => _fetches.filter(f => !f.url.startsWith("/admin/api/accounts_audit"));
      const reloads = () => _fetches.length - posts().length;
      accRender(ROWS, ROWS.length);
      out.table = $("accRecordsBody").innerHTML;
      accGiftOpen("acc-free");
      out.free = {hidden: modal.hidden, body: $("accGiftBody").innerHTML};
      $("accGiftPlan").value = "sub_5";
      $("accGiftUntil").value = "";
      await accGift({});
      out.noDate = {err: err.textContent, errHidden: err.hidden, posts: posts().length};
      $("accGiftUntil").value = "2999-12-31";
      // Nel frattempo l'account ha avuto un regalo altrove: il 409 rilegge la tabella e il
      // popup riparte dallo stato nuovo (solo revoca), con l'errore sopra.
      AUDIT.records = [Object.assign({}, ROWS[0], {origin: "gift", plan_effective: "sub_10",
                                                   plan_until: 1_800_057_600}), ...ROWS.slice(1)];
      _giftReply = {ok: false, status: 409, body: '{"error":"gift_active"}'};
      await accGift({}); await _tick();
      out.conflict = {err: err.textContent, errHidden: err.hidden, hidden: modal.hidden,
                      post: posts()[0], body: $("accGiftBody").innerHTML};
      _giftReply = {ok: true, status: 200, body: "{}"};
      const before = reloads();
      await accGift({}); await _tick();
      out.ok = {hidden: modal.hidden, reloaded: reloads() - before, errHidden: err.hidden};
      accGiftOpen(EVIL);
      out.gift = {hidden: modal.hidden, body: $("accGiftBody").innerHTML};
      await accRevoke({}); await _tick();
      out.revoke = posts().pop();
      accGiftOpen("acc-free"); document._fire("keydown", {key: "Escape"});
      out.esc = modal.hidden;
      accGiftOpen("acc-free"); modal._fire("click", {target: modal});
      out.overlay = modal.hidden;
      accGiftOpen("acc-free");
      modal._fire("click", {target: {closest: () => ({dataset: {accGiftAct: "close"}})}});
      out.x = modal.hidden;
      // 404 e la riga sparita dalla tabella riletta: l'azione resta spenta, ritentarla darebbe
      // lo stesso errore; il popup resta aperto con il messaggio.
      accGiftOpen("acc-free");
      AUDIT.records = [];
      _giftReply = {ok: false, status: 404, body: '{"error":"not_found"}'};
      const gone = {disabled: false};
      await accRevoke(gone); await _tick();
      out.gone = {disabled: gone.disabled, hidden: modal.hidden, err: err.textContent};
      out.alerts = _alerts;
      console.log(JSON.stringify(out));
    """)
    assert out["table"].count("data-acc-gift-open=") == 3                # non sulla riga cancellata

    def tag(body, pattern):
        return re.search(pattern, body).group(0)
    free = out["free"]["body"]
    assert out["free"]["hidden"] is False
    assert "disabled" not in tag(free, r"<select [^>]*>")
    date_in = tag(free, r'<input type="date"[^>]*>')
    assert 'min="%s"' % out["today"] in date_in and "disabled" not in date_in
    assert "5 GB (regalo)" in free and "10 GB (regalo)" in free
    assert 'data-acc-gift-act="submit"' in free and 'data-acc-gift-act="close"' in free
    assert "Revoca regalo" not in free

    assert "ultimo giorno" in out["noDate"]["err"]
    assert out["noDate"]["errHidden"] is False and out["noDate"]["posts"] == 0
    assert "revocato prima" in out["conflict"]["err"] and out["conflict"]["errHidden"] is False
    assert out["conflict"]["hidden"] is False
    assert out["conflict"]["post"] == {"url": "/admin/api/accounts/gift", "body": {
        "account_id": "acc-free", "plan": "sub_5", "until": "2999-12-31"}}
    assert 'data-acc-gift-act="revoke"' in out["conflict"]["body"]
    assert 'data-acc-gift-act="submit"' not in out["conflict"]["body"]
    assert out["ok"] == {"hidden": True, "reloaded": 1, "errHidden": True}

    gift = out["gift"]["body"]
    assert out["gift"]["hidden"] is False
    assert "disabled" in tag(gift, r"<select [^>]*>") and '<option value="sub_10" selected>' in gift
    date_in = tag(gift, r'<input type="date"[^>]*>')
    assert "disabled" in date_in and 'value="2027-01-15"' in date_in and "15/01/2027" in gift
    assert 'data-acc-gift-act="revoke"' in gift and "Revoca regalo" in gift
    assert 'data-acc-gift-act="submit"' not in gift
    assert "<img" not in gift and "<script" not in gift
    assert "&lt;img src=x onerror=alert(1)&gt;" in gift and "&lt;script&gt;" in gift
    assert out["revoke"] == {"url": "/admin/api/accounts/gift_revoke", "body": {"account_id": evil_id}}

    assert out["esc"] is out["overlay"] is out["x"] is True
    assert out["gone"] == {"disabled": True, "hidden": False,
                           "err": "Errore 404: Account non trovato (forse e' stato cancellato)."}
    assert out["alerts"] == []


@needs_node
def test_admin_accounts_slow_reply_does_not_overwrite_newer_one(tmp_path):
    """Due clic rapidi su caselle diverse: se la risposta della prima arriva dopo quella della
    seconda, tabella e numeri restano quelli dell'ultima richiesta, cioe' della casella evidenziata."""
    out = _run_admin_accounts_js(tmp_path, {"AUDIT": {"records": [], "count": 1,
                                                      "aggregates": {"gift": 1}}}, r"""
      _holdUrl = "/admin/api/accounts_audit";
      AUDIT.aggregates.gift = 111; AUDIT.records = [{id: "dalla-prima"}];
      _box("gift")._fire("click");
      AUDIT.aggregates.gift = 222; AUDIT.records = [{id: "dalla-seconda"}];
      _box("paid")._fire("click");
      _held[1](); await _tick();
      _held[0](); await _tick();
      console.log(JSON.stringify({gift: String(_box("gift")._value.textContent),
        rows: $("accRecordsBody").innerHTML,
        marked: _boxes.filter(b => b.classList.contains("agg-active")).map(b => b.dataset.accAgg)}));
    """)
    assert out["marked"] == ["paid"]
    assert out["gift"] == "222"
    assert "dalla-seconda" in out["rows"] and "dalla-prima" not in out["rows"]


@needs_node
def test_admin_gift_reply_leaves_alone_a_popup_opened_meanwhile(tmp_path):
    """Regalo inviato, popup chiuso e riaperto su un altro account prima della risposta: ne' l'esito
    ok ne' il 409 (con la sua rilettura) chiudono, riscrivono o sporcano il popup nuovo."""
    rows = [{"id": "acc-free", "email": "a@x.it", "origin": "free", "plan_effective": "free"},
            {"id": "acc-other", "email": "b@x.it", "origin": "free", "plan_effective": "free"}]
    out = _run_admin_accounts_js(tmp_path, {"ROWS": rows, "AUDIT": {"records": rows, "count": 2}}, r"""
      const modal = $("accGiftModal"), err = $("accGiftErr"), out = {};
      accRender(ROWS, ROWS.length);
      const switched = async () => {
        accGiftOpen("acc-free");
        $("accGiftPlan").value = "sub_5"; $("accGiftUntil").value = "2999-12-31";
        const sent = accGift({});
        document._fire("keydown", {key: "Escape"});
        accGiftOpen("acc-other");
        _held.shift()(); await sent; await _tick();
        return {hidden: modal.hidden, id: accGiftId, err: err.textContent,
                other: $("accGiftBody").innerHTML.includes("acc-other")};
      };
      _holdUrl = "/admin/api/accounts/gift";
      out.ok = await switched();
      _giftReply = {ok: false, status: 409, body: '{"error":"gift_active"}'};
      out.conflict = await switched();
      console.log(JSON.stringify(out));
    """)
    expected = {"hidden": False, "id": "acc-other", "err": "", "other": True}
    assert out["ok"] == expected
    assert out["conflict"] == expected


@needs_node
def test_admin_aggregate_boxes_are_quick_filters(tmp_path):
    """Ogni casella degli Aggregati e' un filtro rapido: azzera gli altri filtri e imposta quelli
    con cui il server la conta (`accounts._ADMIN_AGGREGATES`; "Nuovi 30 gg" = `last30_since`).
    Resta evidenziata, il secondo clic azzera tutto, un filtro toccato a mano la spegne."""
    html = ADMIN_HTML.read_text(encoding="utf-8")
    boxes = re.findall(r'<div class="agg-box"[^>]*data-acc-agg="[^"]+"[^>]*>', html)
    # "sub_live" la conta subscriptions.admin_stats (`subscriptions` della risposta), non un aggregato
    expected = dict(accounts._ADMIN_AGGREGATES, last30={"date_from": "2026-09-21"},
                    sub_live={"sub": "live"})
    assert len(boxes) == len(expected)
    for b in boxes:
        assert 'role="button"' in b and 'tabindex="0"' in b
    aggregates = {k: i + 1 for i, k in enumerate(expected) if k != "sub_live"}
    out = _run_admin_accounts_js(tmp_path, {"AUDIT": {
        "records": [], "count": 0, "aggregates": aggregates, "last30_since": "2026-09-21",
        "subscriptions": {"live": 3, "live_sub_5": 2, "live_sub_10": 1}}}, r"""
      const fields = () => Object.fromEntries(Object.entries(ACC_FILTER_DEFAULTS).map(([id, d]) =>
        [id, typeof d === "boolean" ? $(id).checked : $(id).value]));
      const marked = () => _boxes.filter(b => b.classList.contains("agg-active")).map(b => b.dataset.accAgg);
      await accFetch();
      const out = {values: Object.fromEntries(_boxes.map(b => [b.dataset.accAgg, String(b._value.textContent)])),
                   apply: {}};
      for (const b of _boxes) {
        $("accQuery").value = "resto di un filtro a mano";
        b._fire("click"); await _tick();
        out.apply[b.dataset.accAgg] = {fields: fields(), marked: marked(), url: _fetches[_fetches.length - 1].url};
      }
      _box("paid")._fire("keydown", {key: "Enter"}); await _tick();
      out.enter = {fields: fields(), marked: marked()};
      _box("paid")._fire("click"); await _tick();
      out.second = {fields: fields(), marked: marked()};
      _box("gift")._fire("click"); await _tick();
      $("accOriginFilter")._fire("change");
      out.manual = {fields: fields(), marked: marked()};
      console.log(JSON.stringify(out));
    """)
    param = {"accStateFilter": "state", "accQuery": "q", "accDateFrom": "date_from",
             "accDateTo": "date_to", "accPlanFilter": "plan", "accOriginFilter": "origin",
             "accSubFilter": "sub", "accTolFilter": "tolerance"}

    def as_filter(fields):
        return {param[k]: v for k, v in fields.items() if v not in ("", "all", False)}

    assert out["values"] == dict({k: str(v) for k, v in aggregates.items()}, sub_live="3 (2 / 1)")
    for key, kw in expected.items():
        got = out["apply"][key]
        assert as_filter(got["fields"]) == kw, key
        assert got["marked"] == [key], key
        query = dict(parse_qsl(urlsplit(got["url"]).query))
        query.pop("limit")
        assert query == {k: "1" if v is True else v for k, v in kw.items()}, key
    assert as_filter(out["enter"]["fields"]) == {"origin": "paid"} and out["enter"]["marked"] == ["paid"]
    assert as_filter(out["second"]["fields"]) == {} and out["second"]["marked"] == []
    assert as_filter(out["manual"]["fields"]) == {"origin": "gift"} and out["manual"]["marked"] == []


def test_admin_template_gift_ui_is_consistent():
    html = ADMIN_HTML.read_text(encoding="utf-8")
    assert not re.search(r"archive_(10|20|50)|ABM_ARCHIVE_GRACE_DAYS|subscribed", html)
    assert "Revoca regalo" in html and 'origin === "gift"' in html
    assert re.search(r'<input type="date" id="accGiftUntil" min="\$\{', html)   # data minima = oggi
    for param in ("plan", "origin", "tolerance"):
        assert f'p.set("{param}"' in html
    for agg in ("Pagati", "Regalati", "Gratuito attivo", "In tolleranza"):
        assert agg in html
    # i valori che arrivano dal server entrano solo escapati
    assert "escAttr(r.id)" in html and "data-acc-gift-open" in html
