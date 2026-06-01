"""La rimozione definitiva di una job dir cancella anche il prefisso su cold."""
import importlib


def test_delete_cold_prefix_called(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import storage_backend, audiobook_app
    importlib.reload(audiobook_app)
    deleted = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: deleted.append(p))
    audiobook_app._delete_cold_for_job("jobZ")
    assert deleted == ["jobZ/"]


def test_delete_cold_noop_when_disabled(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import storage_backend, audiobook_app
    importlib.reload(audiobook_app)
    called = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: called.append(p))
    audiobook_app._delete_cold_for_job("jobZ")
    assert called == []
