"""Regressione: il pulsante 'Sospendi nuovi processi' su /admin/log-activity
deve autenticare il POST via header X-Admin-Token (come tutte le altre azioni
admin), NON via `?token=` in query string — che `_admin_auth_from_request`
ignora di proposito (sicurezza: niente token nei log nginx/Referer).

Bug: il JS usava `fetch('/api/admin/suspend?token='+ADMIN_TOKEN)` senza header
X-Admin-Token, quindi il POST autenticava solo se per caso era presente il
cookie abm_admin_session; in caso contrario -> 401 -> nessun cambiamento
visibile del pulsante (sintomo riportato: "a volte non funziona").
"""
import pytest

TOKEN = "test-admin-token-123"


@pytest.fixture
def app_mod(monkeypatch):
    # NB: niente importlib.reload qui — ricaricare audiobook_app lascerebbe stale
    # l'istanza `app`/stato condivisi e inquinerebbe i test successivi. Settiamo
    # solo il global ADMIN_TOKEN (auto-revert via monkeypatch); _admin_auth_ok e
    # la route /admin/log-activity lo leggono a runtime.
    import audiobook_app
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", TOKEN)
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app


def test_log_activity_page_does_not_use_query_token_for_suspend(app_mod):
    """La pagina renderizzata non deve più passare il token in query string al
    suspend, e deve referenziare l'endpoint via header."""
    client = app_mod.app.test_client()
    resp = client.get("/admin/log-activity", headers={"X-Admin-Token": TOKEN})
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    # Pattern buggy: token in query string sul suspend
    assert "/api/admin/suspend?token=" not in html
    # L'endpoint resta referenziato (senza query token)
    assert "/api/admin/suspend" in html
    # L'auth admin del suspend passa per l'header X-Admin-Token
    assert "X-Admin-Token" in html


def test_suspend_post_rejects_query_token_only(app_mod):
    """Il server ignora `?token=`: un POST con solo query token (niente header,
    niente cookie) deve essere 401 (premessa del bug)."""
    client = app_mod.app.test_client()
    resp = client.post(f"/api/admin/suspend?token={TOKEN}", json={"suspend": True})
    assert resp.status_code == 401


def test_suspend_post_accepts_header_token(app_mod):
    """Il POST autentica correttamente via header X-Admin-Token."""
    client = app_mod.app.test_client()
    resp = client.post("/api/admin/suspend",
                        headers={"X-Admin-Token": TOKEN},
                        json={"suspend": True})
    assert resp.status_code == 200
    assert resp.get_json().get("suspended") is True
    # ripristina
    client.post("/api/admin/suspend", headers={"X-Admin-Token": TOKEN},
                json={"suspend": False})
