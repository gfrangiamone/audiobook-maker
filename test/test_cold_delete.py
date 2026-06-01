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


def test_no_cold_delete_when_forensic_protected(monkeypatch, tmp_path):
    """Job sotto retention forense: i file locali sono preservati, quindi anche
    gli oggetti cold NON devono essere cancellati."""
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import storage_backend, audiobook_app
    importlib.reload(audiobook_app)
    # crea la work dir del job così work_dir.exists() è True
    (tmp_path / "jobF").mkdir()
    deleted = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: deleted.append(p))
    # forza la protezione forense
    monkeypatch.setattr(audiobook_app, "_forensic_marker_protects", lambda *a, **k: True)
    audiobook_app._cleanup_job("jobF", "test")
    assert deleted == []   # nessun delete cold sotto hold forense
