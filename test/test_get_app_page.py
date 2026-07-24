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


def test_ua_is_mobile_detects_iphone():
    with audiobook_app.app.test_request_context(
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari"}):
        assert audiobook_app._ua_is_mobile() is True


def test_ua_is_mobile_desktop_false():
    with audiobook_app.app.test_request_context(
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome"}):
        assert audiobook_app._ua_is_mobile() is False


def test_dl_page_mobile_renders_deeplink_button_not_qr():
    html = audiobook_app._render_dl_page(
        "TOK", "Il mio libro", "1h", "m4b", lang="it",
        transfer_qr="data:image/png;base64,AAAA",
        transfer_url="https://example.com/t/abc123",
        is_mobile=True,
    )
    # bottone verso il deep link /t/, non l'immagine QR
    assert 'href="https://example.com/t/abc123"' in html
    assert "Scarica su AudioBook Maker &amp; Player" in html
    assert "data:image/png;base64,AAAA" not in html


def test_dl_page_desktop_still_renders_qr():
    html = audiobook_app._render_dl_page(
        "TOK", "Il mio libro", "1h", "m4b", lang="it",
        transfer_qr="data:image/png;base64,AAAA",
        transfer_url="https://example.com/t/abc123",
        is_mobile=False,
    )
    assert "data:image/png;base64,AAAA" in html
    assert 'href="https://example.com/t/abc123"' not in html


def test_ua_is_android_true_false():
    with audiobook_app.app.test_request_context(
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel) Chrome"}):
        assert audiobook_app._ua_is_android() is True
    with audiobook_app.app.test_request_context(
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari"}):
        assert audiobook_app._ua_is_android() is False


def test_android_intent_url_format():
    intent = audiobook_app._android_intent_url("https://audiobook-maker.com/t/abc123")
    # bypassa la soppressione same-origin: intent:// (scheme=abm) + package + fallback https
    assert intent.startswith("intent://audiobook-maker.com/t/abc123#Intent;")
    assert f"scheme={audiobook_app._APP_SCHEME};" in intent
    assert "scheme=abm;" in intent
    assert f"package={audiobook_app._APP_PACKAGE};" in intent
    # il fallback è l'https url-encoded, e termina con ;end
    assert "S.browser_fallback_url=https%3A%2F%2Faudiobook-maker.com%2Ft%2Fabc123" in intent
    assert intent.endswith(";end")


def test_app_scheme_url_format():
    url = audiobook_app._app_scheme_url("https://audiobook-maker.com/t/abc123")
    assert url == "abm://audiobook-maker.com/t/abc123"


def test_ua_is_ios_true_false():
    with audiobook_app.app.test_request_context(
            headers={"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari"}):
        assert audiobook_app._ua_is_ios() is True
    with audiobook_app.app.test_request_context(
            headers={"User-Agent": "Mozilla/5.0 (Linux; Android 14; Pixel) Chrome"}):
        assert audiobook_app._ua_is_ios() is False


def test_dl_page_mobile_ios_single_scheme_button():
    html = audiobook_app._render_dl_page(
        "TOK", "Il mio libro", "1h", "m4b", lang="it",
        transfer_qr="data:image/png;base64,AAAA",
        transfer_url="https://example.com/t/abc123",
        is_mobile=True, is_android=False, is_ios=True,
    )
    # iOS: bottone UNICO col custom scheme abm://, label "Apri nell'app".
    # Nessuna CTA https, nessun intent://, nessun QR.
    assert 'href="abm://example.com/t/abc123"' in html
    assert "Apri nell" in html  # label "Apri nell'app"
    assert 'href="https://example.com/t/abc123"' not in html
    assert "intent://" not in html
    assert "data:image/png;base64,AAAA" not in html


def test_dl_page_mobile_android_uses_intent_url():
    html = audiobook_app._render_dl_page(
        "TOK", "Il mio libro", "1h", "m4b", lang="it",
        transfer_qr="data:image/png;base64,AAAA",
        transfer_url="https://example.com/t/abc123",
        is_mobile=True, is_android=True,
    )
    # Android: href è l'intent:// (escapato), non l'https diretto né il QR
    assert "href=\"intent://example.com/t/abc123#Intent;" in html
    assert f"package={audiobook_app._APP_PACKAGE}" in html
    assert "data:image/png;base64,AAAA" not in html


def test_dl_page_mobile_ios_uses_https_not_intent():
    html = audiobook_app._render_dl_page(
        "TOK", "Il mio libro", "1h", "m4b", lang="it",
        transfer_qr="data:image/png;base64,AAAA",
        transfer_url="https://example.com/t/abc123",
        is_mobile=True, is_android=False,
    )
    # iOS/altro: https diretto, nessun intent://
    assert 'href="https://example.com/t/abc123"' in html
    assert "intent://" not in html
