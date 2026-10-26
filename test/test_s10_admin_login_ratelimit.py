"""S10 (2026-10-12): /admin/login rispondeva 401 subito e senza limiti, mentre
`admin_required` aspetta 0,5 s: il token admin si poteva provare alla
velocita' della rete. Ora: 5 tentativi al minuto e 20 all'ora per IP (429 con
Retry-After) e la stessa pausa sul fallimento."""
import audiobook_app

IP = "198.51.100.77"


def _client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def test_failed_login_sleeps_and_is_rate_limited(monkeypatch, sleeps):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-s10")
    audiobook_app._ip_rl_buckets.pop("admin_login", None)
    c = _client()
    codes = []
    for _ in range(7):
        r = c.post("/admin/login", json={"token": "wrong"}, environ_base={"REMOTE_ADDR": IP})
        codes.append(r.status_code)
    assert codes[:5] == [401] * 5 and codes[5:] == [429, 429]
    assert len(sleeps) == 5 and all(s >= 0.5 for s in sleeps)
    assert int(r.headers["Retry-After"]) >= 1
    # anche il token giusto resta bloccato finche' la finestra non scade
    r = c.post("/admin/login", json={"token": "tok-s10"}, environ_base={"REMOTE_ADDR": IP})
    assert r.status_code == 429
    audiobook_app._ip_rl_buckets.pop("admin_login", None)


def test_valid_login_still_works_and_counts_per_ip(monkeypatch):
    monkeypatch.setattr(audiobook_app, "ADMIN_TOKEN", "tok-s10")
    monkeypatch.setattr(audiobook_app.time, "sleep", lambda s: None)
    audiobook_app._ip_rl_buckets.pop("admin_login", None)
    c = _client()
    r = c.post("/admin/login", json={"token": "tok-s10"}, environ_base={"REMOTE_ADDR": "198.51.100.78"})
    assert r.status_code == 200 and "abm_admin_session" in r.headers.get("Set-Cookie", "")
    audiobook_app._ip_rl_buckets.pop("admin_login", None)
