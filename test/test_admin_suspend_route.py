# test/test_admin_suspend_route.py
"""`/api/admin/suspend` condivide lo stato con i check di audiobook_app.

Caso d'origine (journal di produzione, 12/10/2026): dopo lo spostamento della
rotta nel blueprint `routes_admin_jobs` (762ef72) GET e POST fallivano con
`NameError: name '_suspend_new_jobs' is not defined`, perche' il flag era
rimasto in `audiobook_app`. La rotta deve leggere/scrivere quel flag, e un
job nuovo (`/api/analyze`) deve essere rifiutato con 503 quando sospeso.
"""
import pytest

import audiobook_app

ADMIN = "tok-admin-test"


@pytest.fixture
def client(monkeypatch):
    audiobook_app.app.config["TESTING"] = True
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", ADMIN)
    monkeypatch.setattr(audiobook_app, "_suspend_new_jobs", False)
    monkeypatch.setattr(audiobook_app, "_ip_rl_check", lambda *a, **k: (True, 0))
    return audiobook_app.app.test_client()


def _hdr():
    return {"X-Admin-Token": ADMIN}


def test_get_reports_app_state(client, monkeypatch):
    r = client.get("/api/admin/suspend")
    assert r.status_code == 200
    assert r.get_json() == {"suspended": False}
    monkeypatch.setattr(audiobook_app, "_suspend_new_jobs", True)
    assert client.get("/api/admin/suspend").get_json() == {"suspended": True}


def test_post_requires_admin_token(client):
    r = client.post("/api/admin/suspend", json={"suspend": True})
    assert r.status_code == 401
    assert audiobook_app._suspend_new_jobs is False
    r = client.post("/api/admin/suspend", json={"suspend": True},
                    headers={"X-Admin-Token": "wrong"})
    assert r.status_code == 401
    assert audiobook_app._suspend_new_jobs is False


def test_post_toggles_and_new_job_refused(client):
    r = client.post("/api/admin/suspend", json={"suspend": True}, headers=_hdr())
    assert r.status_code == 200
    assert r.get_json() == {"suspended": True}
    assert audiobook_app._suspend_new_jobs is True
    assert client.get("/api/admin/suspend").get_json() == {"suspended": True}

    # Job nuovo rifiutato mentre sospeso (guardia prima del controllo file).
    r = client.post("/api/analyze", data={})
    assert r.status_code == 503
    assert "maintenance" in r.get_json()["error"].lower()

    r = client.post("/api/admin/suspend", json={"suspend": False}, headers=_hdr())
    assert r.status_code == 200
    assert r.get_json() == {"suspended": False}
    assert audiobook_app._suspend_new_jobs is False

    # Riattivato: la guardia non scatta piu' (400 per file mancante).
    r = client.post("/api/analyze", data={})
    assert r.status_code == 400
