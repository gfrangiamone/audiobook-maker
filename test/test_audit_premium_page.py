import pathlib

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


def _default_dates_js(body):
    """Il blocco che valorizza i filtri periodo all'apertura della pagina."""
    i = body.index("(function setDefaultDates(){")
    return body[i:body.index("})();", i)]


def test_periodo_iniziale_segue_il_mese_in_query_string(monkeypatch):
    """La pagina arriva da Activity Log come `?YYYY-MM` (come l'export):
    il filtro deve partire da quel mese, non sempre da quello corrente."""
    c = _setup(monkeypatch)
    body = c.get("/admin/audit-premium?2026-08",
                 headers={"X-Admin-Token": "secret"}).get_data(as_text=True)
    js = _default_dates_js(body)
    assert "location.search" in js and r"^\d{4}-\d{2}$" in js
    # tutte e tre le tab: TTS, Traduzioni, AI Optimization
    for campo in ("tts_auditDateFrom", "tr_auditDateFrom", "optDateFrom",
                  "tts_auditDateTo", "tr_auditDateTo", "optDateTo"):
        assert campo in js
    # su un mese chiuso si fissa anche il "Al", altrimenti si vedrebbe
    # tutto da quel mese a oggi
    assert "lastDay" in js and 'ym === cur' in js
    assert 'id="periodLabel"' in body


def test_ritorno_ad_activity_log_mantiene_il_mese(monkeypatch):
    c = _setup(monkeypatch)
    body = c.get("/admin/audit-premium?2026-08",
                 headers={"X-Admin-Token": "secret"}).get_data(as_text=True)
    assert 'id="backToLog"' in body
    assert '"/admin/log-activity?" + ym' in _default_dates_js(body)


def test_link_da_activity_log_porta_il_mese_selezionato(monkeypatch, tmp_path):
    """Il mese scelto nel pannello Activity Log finisce nel link all'audit."""
    (tmp_path / "activity_2026-08.log").write_text(
        'j1 # 2026-08-01 10:00:00 # "a.epub" # COMPLETE # cidA # 1.1.1.1'
        ' # it-IT-DiegoNeural # it # web\n', encoding="utf-8")
    monkeypatch.setattr(app, "SCRIPT_DIR", pathlib.Path(tmp_path), raising=False)
    c = _setup(monkeypatch)
    body = c.get("/admin/log-activity?2026-08",
                 headers={"X-Admin-Token": "secret"}).get_data(as_text=True)
    assert 'href="/admin/audit-premium?2026-08"' in body
