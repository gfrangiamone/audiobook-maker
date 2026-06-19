"""Filtri/bottoni stats in /admin/log-activity:
- rimosso il filtro "Email inviate"
- aggiunto il filtro "Traduzioni" a sinistra di "PREMIUM"
- "GEN. GEMINI" rinominato "PREMIUM"
- aggiunto filtro "Da mobile" (platform=android|ios) e "Spostati su mobile" (TRANSFER)
"""
import pathlib
import tempfile
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


# ---------------------------------------------------------------------------
# Nuovi test: filtri "Da mobile" e "Spostati su mobile"
# ---------------------------------------------------------------------------

def _page_with_log(monkeypatch, log_lines):
    """Scrive un log temporaneo, esegue GET /admin/log-activity e ritorna l'HTML."""
    import datetime
    ym = datetime.datetime.now().strftime("%Y-%m")
    tmpdir = pathlib.Path(tempfile.mkdtemp())
    log_path = tmpdir / f"activity_{ym}.log"
    log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    monkeypatch.setattr(audiobook_app, "SCRIPT_DIR", tmpdir)
    with patch.object(audiobook_app, "ADMIN_TOKEN", "tok-test"), \
         patch("audiobook_app._admin_auth_ok", return_value=True):
        r = audiobook_app.app.test_client().get(f"/admin/log-activity?{ym}")
    assert r.status_code == 200
    return r.get_data(as_text=True)


def test_mobile_platform_card_attr(monkeypatch):
    """Una sessione con platform=android deve produrre data-platform="android" e data-transferred="0"."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_ANDROID # {ts} # "book.epub" # GENERATE # cid1 # 1.2.3.4 # en-US-JennyNeural # en # android',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert 'data-platform="android"' in html
    assert 'data-transferred="0"' in html


def test_transferred_card_attr(monkeypatch):
    """Una sessione con evento TRANSFER deve produrre data-transferred="1"."""
    import datetime
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f'SID_WEB # {ts} # "book.epub" # GENERATE # cid2 # 1.2.3.5 # en-US-JennyNeural # en # ',
        f'SID_WEB # {ts} # "book.epub" # TRANSFER # cid2 # 1.2.3.5 # # en # ',
    ]
    html = _page_with_log(monkeypatch, lines)
    assert 'data-transferred="1"' in html


def test_mobile_and_transferred_filter_labels_in_html(monkeypatch):
    """L'HTML deve contenere i due nuovi stat-box con data-filter="mobile" e data-filter="transferred"."""
    html = _page_with_log(monkeypatch, [])
    assert 'data-filter="mobile"' in html
    assert 'data-filter="transferred"' in html
    assert "Da mobile" in html
    assert "Spostati su mobile" in html


def test_mobile_filter_js_logic(monkeypatch):
    """Il JS filterCards deve gestire i nuovi filtri mobile e transferred."""
    html = _page_with_log(monkeypatch, [])
    assert "card.dataset.platform" in html
    assert "card.dataset.transferred" in html
