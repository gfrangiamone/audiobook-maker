"""La finestra calda evacua i file di output locali se: marker presente,
età oltre la finestra, e oggetto confermato su cold storage."""
import importlib
import pytest


@pytest.fixture
def aa(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_HOT_WINDOW_SEC", "7200")
    import storage_tiering
    importlib.reload(storage_tiering)
    import audiobook_app
    importlib.reload(audiobook_app)
    return audiobook_app, storage_tiering


def test_evicts_local_after_hot_window(aa, monkeypatch, tmp_path):
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "job1" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time() - 10800)

    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: True)
    audiobook_app.jobs["job1"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert not audio.exists()
    assert (out / ".cloud_uploaded").exists()


def test_keeps_local_within_hot_window(aa, monkeypatch, tmp_path):
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "job2" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.mp3"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time())

    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: True)
    audiobook_app.jobs["job2"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert audio.exists()


def test_no_evict_if_object_not_confirmed(aa, monkeypatch, tmp_path):
    audiobook_app, storage_tiering = aa
    import storage_backend
    out = tmp_path / "job3" / "output_1"
    out.mkdir(parents=True)
    audio = out / "book.m4b"
    audio.write_bytes(b"x")
    storage_tiering.mark_cloud_uploaded(out, when=__import__("time").time() - 10800)

    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: False)
    audiobook_app.jobs["job3"] = {"voice": "it-IT-IsabellaNeural"}

    audiobook_app._evict_hot_local()
    assert audio.exists()
