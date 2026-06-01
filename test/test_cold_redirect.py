"""Il serving fa redirect 302 al presigned URL quando il locale è assente
ma l'oggetto esiste su cold storage."""
import importlib
import pytest


@pytest.fixture
def app_client(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import audiobook_app
    importlib.reload(audiobook_app)
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app, audiobook_app.app.test_client()


def test_redirect_to_presigned_when_local_missing(app_client, monkeypatch, tmp_path):
    audiobook_app, client = app_client
    import storage_backend, storage_tiering
    missing = tmp_path / "jobX" / "output_1" / "book.m4b"

    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: k == "jobX/output_1/book.m4b")
    monkeypatch.setattr(storage_backend, "presigned_get_url",
                        lambda k, download_name=None, ttl=None: f"https://cold/{k}")
    monkeypatch.setattr(storage_tiering, "key_for_path",
                        lambda p: "jobX/output_1/book.m4b")

    with audiobook_app.app.test_request_context("/"):
        resp = audiobook_app._send_file_throttled(str(missing), download_name="book.m4b")
    assert resp.status_code == 302
    assert resp.headers["Location"] == "https://cold/jobX/output_1/book.m4b"


def test_no_redirect_when_local_exists(app_client, monkeypatch, tmp_path):
    audiobook_app, client = app_client
    f = tmp_path / "book.mp3"
    f.write_bytes(b"data")
    with audiobook_app.app.test_request_context("/"):
        resp = audiobook_app._send_file_throttled(str(f), download_name="book.mp3", bypass_throttle=True)
    assert resp.status_code == 200


def test_cold_cap_keeps_deleted_state_without_deleting_object(app_client, monkeypatch, tmp_path):
    """Al raggiungimento del cap per-worker, _check_cold_throttle ritorna
    'deleted' e MANTIENE il record (richieste successive restano 'deleted'),
    ma NON cancella mai l'oggetto cold condiviso: in multi-worker Gunicorn il
    counter è per-processo e cancellerebbe lo stato durevole sotto gli altri."""
    audiobook_app, client = app_client
    import storage_backend
    audiobook_app._download_tracking.clear()
    # record già al massimo
    audiobook_app._download_tracking["k1"] = {
        "count": audiobook_app._DL_MAX_DOWNLOADS,
        "last_download": 0,
    }
    called = {"delete": False}
    monkeypatch.setattr(storage_backend, "delete_object",
                        lambda k: called.__setitem__("delete", True))
    s1, _ = audiobook_app._check_cold_throttle("k1")
    s2, _ = audiobook_app._check_cold_throttle("k1")
    assert s1 == "deleted"
    assert s2 == "deleted"  # record mantenuto: cap per-worker persistente
    assert "k1" in audiobook_app._download_tracking
    assert called["delete"] is False  # l'oggetto cold condiviso NON viene toccato
