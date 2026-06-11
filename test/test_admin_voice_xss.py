"""Difese contro stored XSS / token leak nelle pagine admin.

1. Il parametro `voice` finisce nell'Activity Log e viene renderizzato dalla
   pagina /admin/log-activity. Un id voce forgiato non deve produrre HTML
   eseguibile (stored XSS nel browser admin).
2. /api/generate e /api/optimize devono rifiutare id voce malformati.
3. Il token admin non deve essere inlinato nel sorgente della pagina audit.
"""
import pytest

import audiobook_app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "test-admin-token")
    audiobook_app.app.testing = True
    return audiobook_app.app.test_client()


def test_voice_id_regex_rejects_html():
    assert audiobook_app._VOICE_ID_RE.match("it-IT-IsabellaNeural")
    assert audiobook_app._VOICE_ID_RE.match("gemini:flash25:Zephyr")
    assert audiobook_app._VOICE_ID_RE.match("it-IT-Chirp3-HD-Zephyr")
    # Payload XSS e injection rifiutati
    assert not audiobook_app._VOICE_ID_RE.match("x-y-<img src=x onerror=alert(1)>")
    assert not audiobook_app._VOICE_ID_RE.match("a-b-c # injected")
    assert not audiobook_app._VOICE_ID_RE.match("a-b-c\nNEWLINE")
    assert not audiobook_app._VOICE_ID_RE.match("")


def test_generate_rejects_malformed_voice(client):
    r = client.post("/api/generate", json={
        "job_id": "whatever",
        "voice": "x-y-<script>alert(1)</script>",
    })
    assert r.status_code == 400
    assert r.get_json().get("error_code") == "invalid_voice"


def test_optimize_rejects_malformed_voice(client, monkeypatch):
    monkeypatch.setattr(audiobook_app, "_llm_available", lambda: True)
    r = client.post("/api/optimize", json={
        "job_id": "whatever",
        "voice": "a-b-<img src=x onerror=alert(1)>",
    })
    assert r.status_code == 400
    assert r.get_json().get("error_code") == "invalid_voice"


def test_admin_log_escapes_voice_in_render(client, monkeypatch):
    """Una sessione di log con voice malevola (simulando un log storico
    pre-validazione) deve essere renderizzata con escape, non come HTML."""
    import datetime
    payload = "x-y-<img src=x onerror=alert(1)>"
    fake_session = {
        "filename": "book.epub",
        "events": ["GENERATE", "COMPLETE"],
        "last_op": "COMPLETE",
        "voice": payload,
        "client_id": "",
        "client_ip": "1.2.3.4",
        "first_dt": datetime.datetime(2026, 6, 1, 10, 0, 0),
        "last_dt": datetime.datetime(2026, 6, 1, 10, 5, 0),
    }
    # _parse_log_sessions ritorna (sessions_dict_by_sid, client_session_count)
    monkeypatch.setattr(audiobook_app, "_parse_log_sessions",
                        lambda *a, **k: ({"s1": fake_session}, {}))
    r = client.get("/admin/log-activity", headers={"X-Admin-Token": "test-admin-token"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Il payload raw non deve comparire come tag eseguibile.
    assert "<img src=x onerror=alert(1)>" not in body
    # Deve comparire la versione escaped.
    assert "&lt;img" in body


def test_admin_audit_page_does_not_inline_token(client):
    r = client.get("/admin/audit-tts", headers={"X-Admin-Token": "test-admin-token"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # Il token reale non deve comparire nel sorgente HTML servito.
    assert "test-admin-token" not in body
    # Deve invece usare il pattern session/localStorage.
    assert "getItem('abm_admin_token')" in body
