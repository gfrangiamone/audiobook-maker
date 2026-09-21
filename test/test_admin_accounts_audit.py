# test/test_admin_accounts_audit.py
"""Tab admin "Utenti registrati": elenco account, API e markup."""
import pytest

import accounts
import audiobook_app as app
import db


T0 = 1_800_000_000


@pytest.fixture
def acct_env(tmp_path, monkeypatch):
    db.init(tmp_path)
    accounts.init_schema()
    monkeypatch.setattr(accounts, "ENABLE", True)
    monkeypatch.setattr(accounts, "_payments_path", None)
    monkeypatch.setattr(accounts, "_voice_ids_for_email", None)
    monkeypatch.setattr(accounts, "_link_voice", None)
    monkeypatch.setattr(accounts, "_unlink_voice", None)
    yield tmp_path
    db.close()


def _login(email, now):
    token, code = accounts.request_code(email, "login", "it", now=now)
    status, acct = accounts.verify(token=token, code=code, purpose="login", now=now)
    assert status == "ok"
    return acct


def _admin(monkeypatch):
    monkeypatch.setattr(app, "ADMIN_TOKEN", "secret", raising=False)
    monkeypatch.setattr(app, "_admin_auth_ok", lambda tok: tok == "secret")
    app.app.config["TESTING"] = True
    return app.app.test_client()


def test_admin_list_reports_registration_and_sessions(acct_env):
    acct = _login("Mario@Example.com", T0)
    accounts.open_session(acct["id"], device_name="pc", now=T0)
    out = accounts.admin_list(now=T0 + 60)
    assert out["count"] == 1
    r = out["records"][0]
    assert r["email"] == "mario@example.com"
    assert r["created_at"] == T0
    assert r["last_login_at"] == T0
    assert r["sessions_active"] == 1
    assert r["deleted_at"] is None
    assert r["state"] == "active"
    agg = out["aggregates"]
    assert agg["total"] == 1 and agg["deleted"] == 0 and agg["with_session"] == 1


def test_admin_list_marks_deleted_account(acct_env):
    acct = _login("anna@example.com", T0)
    assert accounts.delete_account(acct["id"], now=T0 + 100)
    out = accounts.admin_list(now=T0 + 200)
    r = out["records"][0]
    assert r["state"] == "deleted"
    assert r["deleted_at"] == T0 + 100
    # l'indirizzo e' gia' stato sostituito da un segnaposto: non si espone
    assert r["email"] == ""
    assert out["aggregates"]["deleted"] == 1
    # filtro per stato
    assert accounts.admin_list(state="active", now=T0 + 200)["count"] == 0
    assert accounts.admin_list(state="deleted", now=T0 + 200)["count"] == 1


def test_admin_list_states_never_and_dormant(acct_env):
    # accesso completato ma sessione scaduta -> dormant
    acct = _login("dorme@example.com", T0)
    accounts.open_session(acct["id"], now=T0)
    later = T0 + accounts.SESSION_DAYS * 86400 + 10
    recs = {r["id"]: r for r in accounts.admin_list(now=later)["records"]}
    assert recs[acct["id"]]["state"] == "dormant"
    assert accounts.admin_list(state="dormant", now=later)["count"] == 1
    # codice richiesto ma mai verificato: nessun account, quindi nessuna riga
    accounts.request_code("mai@example.com", "login", "it", now=T0)
    assert accounts.admin_list(now=later)["count"] == 1


def test_admin_list_filters_by_query_and_date(acct_env):
    _login("uno@example.com", T0)
    _login("due@other.com", T0 + 10 * 86400)
    now = T0 + 20 * 86400
    assert accounts.admin_list(q="other", now=now)["count"] == 1
    assert accounts.admin_list(q="EXAMPLE.COM", now=now)["count"] == 1
    out = accounts.admin_list(date_from=T0 + 5 * 86400, now=now)
    assert [r["email"] for r in out["records"]] == ["due@other.com"]


def test_accounts_audit_api(acct_env, monkeypatch):
    acct = _login("api@example.com", T0)
    accounts.open_session(acct["id"], now=T0)
    c = _admin(monkeypatch)
    r = c.get("/admin/api/accounts_audit", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    d = r.get_json()
    assert d["count"] == 1
    assert d["records"][0]["email"] == "api@example.com"
    assert d["aggregates"]["total"] == 1


def test_accounts_audit_api_requires_admin(acct_env, monkeypatch):
    c = _admin(monkeypatch)
    r = c.get("/admin/api/accounts_audit")
    assert r.status_code == 401


def test_accounts_audit_api_bad_date_is_ignored(acct_env, monkeypatch):
    _login("api@example.com", T0)
    c = _admin(monkeypatch)
    r = c.get("/admin/api/accounts_audit?date_from=non-una-data",
              headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    assert r.get_json()["count"] == 1


def test_premium_page_has_accounts_tab(monkeypatch):
    c = _admin(monkeypatch)
    body = c.get("/admin/audit-premium",
                 headers={"X-Admin-Token": "secret"}).get_data(as_text=True)
    assert 'data-tab="accounts"' in body
    assert "Utenti registrati" in body
    assert 'id="tab_accounts"' in body
    assert 'id="accRecordsBody"' in body
    assert "/admin/api/accounts_audit" in body
    # colonne chiave della tab
    for col in ("Registrato", "Ultimo accesso", "Cancellato"):
        assert col in body
    # caricamento pigro + deep link
    assert "window._accLoaded" in body
    assert '#tab-accounts' in body
