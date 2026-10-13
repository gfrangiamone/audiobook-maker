"""S12 (2026-10-13): /api/share/create non aveva rate limit: con un cid
inventato si creavano presigned PUT su R2 senza limite (la dimensione si
controlla solo in finalize). Ora 10 al minuto e 60 all'ora per IP, 429 con
Retry-After, prima di qualunque lettura del body."""
import audiobook_app

CID = "cid_s12_test"


def test_share_create_is_rate_limited_per_ip(monkeypatch):
    seen = []
    monkeypatch.setattr(audiobook_app, "_ip_rl_check",
                        lambda bucket, ip, m, h: (seen.append((bucket, ip, m, h)) or (False, 7)))
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        c.set_cookie("abm_cid", CID)
        r = c.post("/api/share/create", json={"filename": "x.m4b", "fingerprint": "f"},
                   environ_base={"REMOTE_ADDR": "203.0.113.5"})
    assert r.status_code == 429 and r.get_json()["error_code"] == "rate_limited"
    assert r.headers["Retry-After"] == "7"
    assert seen == [("share_create", "203.0.113.5", 10, 60)]


def test_without_cid_the_limit_is_not_even_consulted(monkeypatch):
    seen = []
    monkeypatch.setattr(audiobook_app, "_ip_rl_check", lambda *a: seen.append(a) or (True, 0))
    audiobook_app.app.config["TESTING"] = True
    with audiobook_app.app.test_client() as c:
        r = c.post("/api/share/create", json={})
    assert r.status_code == 400 and seen == []
