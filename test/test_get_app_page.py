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


def test_get_app_page_both_labels(client):
    r = client.get("/get-app")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Google Play" in body and "App Store" in body


def test_get_app_page_active_when_env(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_PLAY_STORE_URL", "https://play/abm")
    body = client.get("/get-app").get_data(as_text=True)
    assert 'href="https://play/abm"' in body


def test_get_app_page_disabled_when_no_env(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_PLAY_STORE_URL", "")
    monkeypatch.setattr(audiobook_app, "_APP_STORE_URL", "")
    body = client.get("/get-app").get_data(as_text=True)
    # CSS definition counts as 1 extra; check both buttons are disabled (>= 2 usages)
    assert body.count("btn-disabled") >= 2


def test_transfer_landing_renders_store_buttons(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_PLAY_STORE_URL", "https://play/abm")
    monkeypatch.setattr(audiobook_app, "_APP_STORE_URL", "")
    body = client.get("/t/sometoken").get_data(as_text=True)
    assert 'href="https://play/abm"' in body   # play attivo
    assert "btn-disabled" in body               # apple disabilitato


def test_install_buttons_render_svg_badges(monkeypatch):
    monkeypatch.setattr(audiobook_app, "_PLAY_STORE_URL", "https://play/x")
    monkeypatch.setattr(audiobook_app, "_APP_STORE_URL", "https://apple/x")
    html = audiobook_app._install_buttons_html("en")
    assert html.count("<svg") == 2
    assert "store-badge" in html


def test_dl_page_caption_links_only_app_name():
    html = audiobook_app._render_dl_page(
        "TOK", "Il mio libro", "1h", "m4b", lang="it",
        transfer_qr="data:image/png;base64,AAAA",
    )
    base = audiobook_app.BASE_URL
    # SOLO "AudioBook Maker & Player" e' il testo del link
    assert (f'href="{base}/get-app" style="color:inherit;text-decoration:underline;">'
            f'AudioBook Maker &amp; Player</a>') in html
    # il testo iniziale della didascalia e' testo piano PRIMA dell'anchor
    assert "Inquadra il QR con l&rsquo;app <a href=" in html
