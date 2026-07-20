import audiobook_app as app


def _setup(monkeypatch):
    monkeypatch.setattr(app, "ADMIN_TOKEN", "secret", raising=False)
    monkeypatch.setattr(app, "_admin_auth_ok", lambda tok: tok == "secret")
    app.app.config["TESTING"] = True
    return app.app.test_client()


def test_premium_page_renders_three_tabs(monkeypatch):
    c = _setup(monkeypatch)
    r = c.get("/admin/audit-premium", headers={"X-Admin-Token": "secret"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'data-tab="tts"' in body
    assert 'data-tab="translations"' in body
    assert 'data-tab="optimization"' in body
    # niente tab Eventi & Rimborsi
    assert "Eventi" not in body


def test_old_routes_redirect(monkeypatch):
    c = _setup(monkeypatch)
    r1 = c.get("/admin/audit-tts", headers={"X-Admin-Token": "secret"})
    assert r1.status_code == 302
    assert "/admin/audit-premium" in r1.headers["Location"]
    r2 = c.get("/admin/audit-translations", headers={"X-Admin-Token": "secret"})
    assert r2.status_code == 302
    assert "/admin/audit-premium" in r2.headers["Location"]
