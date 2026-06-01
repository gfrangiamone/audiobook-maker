"""Test /admin/audit-tts page exists and has Gemini Audit tab structure."""
import os
import pytest
import audiobook_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


def test_admin_logs_page_exists_and_requires_auth(client):
    r = client.get("/admin/audit-tts")
    # Without token -> admin gate page (200 with gate HTML) or 401
    assert r.status_code in (200, 401)
    if r.status_code == 200:
        body = r.get_data(as_text=True)
        # Must contain admin gate form when unauthorized
        assert "X-Admin-Token" in body or "password" in body.lower() or "admin" in body.lower()
        # CRITICAL: real admin token must NOT leak into unauthenticated response
        assert "test-admin-token" not in body


def test_admin_logs_page_renders_with_token(client):
    r = client.get("/admin/audit-tts", headers={"X-Admin-Token": "test-admin-token"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert 'data-tab="gemini_audit"' in body
    # Filter selects must be present
    assert 'id="auditModelFilter"' in body
    assert 'id="auditLangFilter"' in body
    assert 'id="auditOutcomeFilter"' in body
    # Aggregates panel
    assert 'id="auditAggregates"' in body
    # Records table
    assert 'id="auditRecordsBody"' in body
    # Spec requires auto-fetch on page load
    assert "fetchAudit()" in body


def test_admin_logs_page_disabled_without_admin_token(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "")
    r = client.get("/admin/audit-tts")
    assert r.status_code == 404
