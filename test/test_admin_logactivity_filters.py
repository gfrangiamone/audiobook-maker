"""Filtri/bottoni stats in /admin/log-activity:
- rimosso il filtro "Email inviate"
- aggiunto il filtro "Traduzioni" a sinistra di "PREMIUM"
- "GEN. GEMINI" rinominato "PREMIUM"
"""
from unittest.mock import patch

import pytest

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def _page():
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get("/admin/log-activity")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_email_filter_removed():
    html = _page()
    assert 'data-filter="email"' not in html
    assert "filterCards('email'" not in html


def test_translation_filter_added():
    html = _page()
    assert 'data-filter="translation"' in html
    assert "filterCards('translation'" in html
    # La logica JS deve gestire il nuovo filtro
    assert "card.dataset.translation" in html


def test_premium_label_replaces_gemini():
    html = _page()
    assert "PREMIUM" in html
    # Il vecchio testo del bottone non deve comparire
    assert "Gen. Gemini" not in html
    assert "Gemini runs" not in html


def test_translation_stat_left_of_premium():
    html = _page()
    tr_idx = html.index('data-filter="translation"')
    gem_idx = html.index('data-filter="gemini"')
    assert tr_idx < gem_idx
