"""Test /admin/audit-tts: dopo l'unificazione (Task 7) e' un redirect 302
verso la pagina unificata /admin/audit-premium#tab-tts."""
import os
import pytest
import audiobook_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


def test_admin_logs_page_redirects_to_premium(client):
    # Il vecchio URL non renderizza piu': reindirizza alla pagina unificata.
    r = client.get("/admin/audit-tts")
    assert r.status_code == 302
    assert "/admin/audit-premium" in r.headers["Location"]
    # Nessun token deve trapelare nella risposta di redirect.
    assert "test-admin-token" not in r.get_data(as_text=True)


def test_admin_logs_page_redirect_targets_tts_tab(client):
    r = client.get("/admin/audit-tts", headers={"X-Admin-Token": "test-admin-token"})
    assert r.status_code == 302
    assert r.headers["Location"] == "/admin/audit-premium#tab-tts"


def test_admin_premium_page_renders_with_token(client):
    # La pagina unificata (bersaglio del redirect) mantiene la struttura audit TTS.
    r = client.get("/admin/audit-premium", headers={"X-Admin-Token": "test-admin-token"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'data-tab="tts"' in body
    assert 'id="tts_auditModelFilter"' in body
    assert 'id="tts_auditLangFilter"' in body
    assert 'id="tts_auditOutcomeFilter"' in body
    assert 'id="tts_auditAggregates"' in body
    assert 'id="tts_auditRecordsBody"' in body
    # Auto-fetch della tab TTS al caricamento pagina.
    assert "ttsFetch" in body


def test_admin_premium_page_disabled_without_admin_token(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "")
    r = client.get("/admin/audit-premium")
    assert r.status_code == 404
