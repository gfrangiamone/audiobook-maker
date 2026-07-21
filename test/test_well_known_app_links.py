"""Tests per i file di verifica dominio deep link (Android + iOS)."""
import json
import pytest
import audiobook_app


@pytest.fixture
def client():
    return audiobook_app.app.test_client()


def test_assetlinks_json(client):
    r = client.get("/.well-known/assetlinks.json")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/json")
    data = json.loads(r.get_data(as_text=True))
    assert data[0]["target"]["package_name"] == audiobook_app._APP_PACKAGE
    assert data[0]["target"]["sha256_cert_fingerprints"]


def test_apple_app_site_association(client):
    # Apple richiede: path senza estensione, 200 diretto (no redirect),
    # Content-Type application/json.
    r = client.get("/.well-known/apple-app-site-association")
    assert r.status_code == 200
    assert r.headers["Content-Type"].startswith("application/json")
    data = json.loads(r.get_data(as_text=True))
    details = data["applinks"]["details"]
    assert len(details) == 1
    assert details[0]["appID"] == audiobook_app._IOS_APP_ID
    assert details[0]["paths"] == ["/t/*", "/s/*"]


def test_apple_app_site_association_no_redirect(client):
    """Nessun redirect: la richiesta deve risolversi in 200 senza Location."""
    r = client.get("/.well-known/apple-app-site-association", follow_redirects=False)
    assert r.status_code == 200
    assert "Location" not in r.headers
