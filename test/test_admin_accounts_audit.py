# test/test_admin_accounts_audit.py
"""Tab admin "Utenti registrati": elenco account, API e markup."""
from datetime import datetime, timedelta, timezone

import pytest

import accounts
import audiobook_app as app
import db
from test.test_account_plans import _set


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


def test_admin_list_state_active_means_live_session(acct_env):
    """`state=active` = account vivo con una sessione valida, come dice la select."""
    on = _login("on@example.com", T0)
    accounts.open_session(on["id"], now=T0)
    _login("off@example.com", T0)                              # accesso fatto, nessuna sessione
    old = _login("old@example.com", T0)
    accounts.open_session(old["id"], now=T0 - accounts.SESSION_DAYS * 86400)   # scaduta
    gone = _login("gone@example.com", T0)
    accounts.open_session(gone["id"], now=T0)
    accounts.delete_account(gone["id"], now=T0)
    out = accounts.admin_list(state="active", now=T0 + 60)
    assert [r["email"] for r in out["records"]] == ["on@example.com"]
    assert out["count"] == out["aggregates"]["with_session"] == 1
    assert accounts.admin_list(state="dormant", now=T0 + 60)["count"] == 2


# Casella degli aggregati -> filtro che applica al clic.
AGG_FILTERS = {
    "total": {},
    "with_session": {"state": "active"},
    "never_logged": {"state": "never"},
    "deleted": {"state": "deleted"},
    "paid": {"origin": "paid"},
    "gift": {"origin": "gift"},
    "free_active": {"origin": "free"},
    "in_tolerance": {"tolerance": True},
}


def test_admin_aggregates_match_their_filters(acct_env):
    """Il numero di ogni casella e' il `count` del filtro che la casella applica,
    anche con dati sporchi sugli account cancellati."""
    now = T0 + 40 * 86400
    online = _login("online@example.com", now - 86400)
    accounts.open_session(online["id"], now=now - 86400)
    never = _login("never@example.com", T0)
    _set(never, last_login_at=None)
    paid = _login("paid@example.com", T0)
    _set(paid, plan="sub_5", plan_source="paid", plan_until=now + 1000)
    gift = _login("gift@example.com", now - 3600)
    accounts.gift_plan(gift["id"], "sub_10", now + 1000, now=now)
    free = _login("free@example.com", T0)
    accounts.free_plan_action(free["id"], "activate", "account", now=T0)
    _set(free, archive_over_since=now - 10)
    gone = _login("gone@example.com", now - 7200)
    accounts.open_session(gone["id"], now=now)
    accounts.delete_account(gone["id"], now=now)
    _set(gone, plan="sub_5", plan_source="gift", plan_until=now + 1000,
         free_consent_at=T0, archive_over_since=T0, last_login_at=None)
    with db.tx() as c:                                         # sessione viva su un cancellato
        c.execute("UPDATE sessions SET revoked_at=NULL WHERE account_id=?", (gone["id"],))
    out = accounts.admin_list(now=now)
    agg = out["aggregates"]
    for key, kw in AGG_FILTERS.items():
        assert agg[key] == accounts.admin_list(now=now, **kw)["count"], key
    assert (agg["with_session"], agg["never_logged"], agg["deleted"]) == (1, 1, 1)
    assert (agg["paid"], agg["gift"], agg["free_active"], agg["in_tolerance"]) == (1, 1, 1, 1)
    since = (now - 30 * 86400) // 86400 * 86400
    assert agg["last30"] == accounts.admin_list(now=now, date_from=since)["count"] == 3


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


def test_accounts_audit_api_max_date_is_ignored_like_a_bad_date(acct_env, monkeypatch):
    """`date_to=9999-12-31` (il giorno dopo esce dal range) vale come una data malformata:
    ignorata, non un falso "accounts unavailable" (503)."""
    _login("api@example.com", T0)
    c = _admin(monkeypatch)
    h = {"X-Admin-Token": "secret"}
    bad = c.get("/admin/api/accounts_audit?date_to=non-una-data", headers=h)
    r = c.get("/admin/api/accounts_audit?date_to=9999-12-31", headers=h)
    assert r.status_code == bad.status_code == 200
    assert r.get_json()["count"] == 1


def test_accounts_audit_api_filters_by_plan_and_origin(acct_env, monkeypatch):
    gifted = _login("gift@example.com", T0)
    _login("none@example.com", T0)
    # la route legge l'orologio reale: il regalo scade nel 2096
    assert accounts.gift_plan(gifted["id"], "sub_5", 4_000_000_000, now=T0)[0] == "ok"
    c = _admin(monkeypatch)
    h = {"X-Admin-Token": "secret"}

    def emails(query):
        r = c.get("/admin/api/accounts_audit" + query, headers=h)
        assert r.status_code == 200
        return sorted(rec["email"] for rec in r.get_json()["records"])

    assert emails("?origin=gift") == ["gift@example.com"]
    assert emails("?origin=none") == ["none@example.com"]
    assert emails("?origin=paid") == [] and emails("?origin=free") == []
    assert emails("?plan=sub_5") == ["gift@example.com"]
    assert emails("?plan=free") == ["none@example.com"]
    assert emails("?plan=sub_5&origin=none") == []                 # filtri in AND
    assert emails("?plan=sub_5&origin=gift") == ["gift@example.com"]
    assert emails("?origin=%20GIFT%20") == ["gift@example.com"]    # trim + minuscolo
    assert len(emails("?origin=inesistente&plan=boh")) == 2        # valori ignoti: nessun filtro
    d = c.get("/admin/api/accounts_audit?origin=gift", headers=h).get_json()
    assert d["origins"] == ["paid", "gift", "free", "none"]
    rec = d["records"][0]
    assert (rec["origin"], rec["plan_effective"], rec["plan_source"]) == ("gift", "sub_5", "gift")
    agg = d["aggregates"]                                          # aggregati sull'intera anagrafica
    assert (agg["gift"], agg["paid"], agg["free_active"], agg["in_tolerance"], agg["total"]) == (1, 0, 0, 0, 2)
    assert "subscribed" not in agg


def test_accounts_audit_api_tolerance_filter_and_last30_since(acct_env, monkeypatch):
    late = _login("late@example.com", T0)
    _login("ok@example.com", T0)
    _set(late, archive_over_since=T0)
    c = _admin(monkeypatch)
    h = {"X-Admin-Token": "secret"}

    def get(query):
        r = c.get("/admin/api/accounts_audit" + query, headers=h)
        assert r.status_code == 200
        return r.get_json()

    for on in ("?tolerance=1", "?tolerance=true"):
        d = get(on)
        assert [rec["email"] for rec in d["records"]] == ["late@example.com"], on
        assert d["count"] == d["aggregates"]["in_tolerance"] == 1
    for off in ("", "?tolerance=0", "?tolerance=no"):
        assert get(off)["count"] == 2, off
    # la route legge l'orologio reale: last30_since e' la mezzanotte UTC di 30 giorni fa
    day = datetime.strptime(get("")["last30_since"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - day
    assert timedelta(days=30) <= age < timedelta(days=31)


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
