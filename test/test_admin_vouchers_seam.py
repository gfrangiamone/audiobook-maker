"""E3, seam admin parte 3 (2026-10-10): pagina e API dei voucher nel blueprint
`routes_admin_vouchers`; guardia e policy della app risolte a ogni richiesta."""
import inspect
import re

import pytest

import audiobook_app
import payment
import routes_admin_vouchers as rv

ROUTES = ("/admin/vouchers", "/admin/api/vouchers", "/admin/api/vouchers/<code>/revoke", "/admin/api/vouchers/<code>/notify")


def test_routes_live_in_the_blueprint():
    rules = {r.rule: r.endpoint for r in audiobook_app.app.url_map.iter_rules()}
    for route in ROUTES:
        assert rules[route].startswith("admin_vouchers."), route
    src = inspect.getsource(audiobook_app)
    for route in ROUTES:
        assert f'@app.route("{route}"' not in src, route
    assert "def admin_api_vouchers(" not in src and "def admin_api_vouchers(" in inspect.getsource(rv)
    assert "app.register_blueprint(routes_admin_vouchers.bp)" in src
    assert not re.search(r"^\s*(import|from) (audiobook_app|generation_engine)\b", inspect.getsource(rv), flags=re.M)


def test_guard_and_logging_resolve_on_the_app(monkeypatch, tmp_path):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda s: None)
    c = audiobook_app.app.test_client()
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "")
    assert c.get("/admin/api/vouchers").status_code == 404
    assert c.get("/admin/vouchers").status_code == 404
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-seam")
    assert c.get("/admin/api/vouchers").status_code == 401
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: False)
    monkeypatch.setattr(audiobook_app, "_render_admin_gate", lambda title, url: f"GATE:{title}")
    r = c.get("/admin/vouchers")
    assert r.status_code == 200 and r.get_data(as_text=True) == "GATE:Voucher Admin"
    # Creazione: la riga di activity log passa dalla funzione della app.
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: True)
    monkeypatch.setattr(payment, "_vouchers", {}, raising=False)
    monkeypatch.setattr(payment, "_save_vouchers", lambda: None)
    logged = []
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: logged.append(a[2]))
    monkeypatch.setattr(audiobook_app, "client_ip", lambda: "9.9.9.9")
    r = c.post("/admin/api/vouchers", json={"amount_eur": 2.5, "email": "v@x.it"},
               headers={"X-Admin-Token": "tok-seam"})
    assert r.status_code in (200, 201), r.get_data(as_text=True)
    assert logged and logged[-1].startswith("ADMIN_VOUCHER")


def test_notify_is_recorded_on_the_voucher(monkeypatch):
    """L'email inviata dal bottone resta annotata sulla riga (`notified`)."""
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-seam")
    monkeypatch.setattr(audiobook_app, "_admin_auth_ok", lambda provided: True)
    monkeypatch.setattr(audiobook_app, "_log_activity", lambda *a, **k: None)
    monkeypatch.setattr(audiobook_app, "client_ip", lambda: "9.9.9.9")
    monkeypatch.setattr(payment, "_vouchers", {"GIFT-AAAA-BBBB-CCCC": {
        "email": "v@x.it", "amount_eur": 5.0, "created_at": 1.0, "expires_at": 2e9}})
    monkeypatch.setattr(payment, "_save_vouchers", lambda: None)
    monkeypatch.setattr(rv, "_smtp_available", lambda: True)
    monkeypatch.setattr(rv.email_service, "_send_voucher_notification_email", lambda *a, **k: True)
    h = {"X-Admin-Token": "tok-seam"}
    rows = c.get("/admin/api/vouchers", headers=h).get_json()["vouchers"]
    assert rows[0]["notified"] == []
    assert c.post("/admin/api/vouchers/GIFT-AAAA-BBBB-CCCC/notify", headers=h).status_code == 200
    rows = c.get("/admin/api/vouchers", headers=h).get_json()["vouchers"]
    assert [n["email"] for n in rows[0]["notified"]] == ["v@x.it"]
    # Invio fallito: nessuna annotazione.
    monkeypatch.setattr(rv.email_service, "_send_voucher_notification_email", lambda *a, **k: False)
    assert c.post("/admin/api/vouchers/GIFT-AAAA-BBBB-CCCC/notify", headers=h).status_code == 502
    assert len(payment.voucher_info("GIFT-AAAA-BBBB-CCCC")["notified"]) == 1
