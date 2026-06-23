"""Test pagina /get-app + bottoni store + didascalia QR cliccabile."""
import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def test_install_buttons_active_when_env_set(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_PLAY_STORE_URL", "https://play/x")
    monkeypatch.setattr(audiobook_app, "_APP_STORE_URL", "https://apple/x")
    html = audiobook_app._install_buttons_html("it")
    assert 'href="https://play/x"' in html
    assert 'href="https://apple/x"' in html
    assert "btn-disabled" not in html


def test_install_buttons_disabled_when_env_missing(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_PLAY_STORE_URL", "")
    monkeypatch.setattr(audiobook_app, "_APP_STORE_URL", "")
    html = audiobook_app._install_buttons_html("it")
    assert html.count("btn-disabled") == 2
    assert "href=" not in html
    # entrambe le etichette comunque presenti
    assert "Google Play" in html and "App Store" in html


def test_install_buttons_mixed(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_PLAY_STORE_URL", "https://play/x")
    monkeypatch.setattr(audiobook_app, "_APP_STORE_URL", "")
    html = audiobook_app._install_buttons_html("en")
    assert 'href="https://play/x"' in html
    assert "btn-disabled" in html  # apple disabilitato
    assert "Download on the App Store" in html
