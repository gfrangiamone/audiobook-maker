import pytest


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("ABM_SPEECHIFY_API_KEY", "sk_test")
    import audiobook_app
    audiobook_app._invalidate_voices_cache()
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


def test_voices_include_speechify_when_available(client):
    r = client.get("/api/voices")
    assert r.status_code == 200
    data = r.get_json()
    en_voices = data["en"]["voices"]
    ids = [v["id"] for v in en_voices]
    assert any(i.startswith("speechify:simba-3.2:") for i in ids)


def test_voices_exclude_speechify_without_key(monkeypatch):
    monkeypatch.delenv("ABM_SPEECHIFY_API_KEY", raising=False)
    import importlib
    import audiobook_app
    importlib.reload(audiobook_app)
    audiobook_app._invalidate_voices_cache()
    audiobook_app.app.config["TESTING"] = True
    c = audiobook_app.app.test_client()
    r = c.get("/api/voices")
    assert r.status_code == 200
    data = r.get_json()
    en_voices = data["en"]["voices"]
    ids = [v["id"] for v in en_voices]
    assert not any(i.startswith("speechify:") for i in ids)
