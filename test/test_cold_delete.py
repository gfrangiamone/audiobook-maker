"""La rimozione definitiva di una job dir cancella anche il prefisso su cold."""
import cleanup


def test_delete_cold_prefix_called(fresh_app, monkeypatch, tmp_path):
    import storage_backend
    fresh_app(env={"ABM_DATA_DIR": str(tmp_path)})
    deleted = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: deleted.append(p))
    cleanup._delete_cold_for_job("jobZ")
    assert deleted == ["jobZ/"]


def test_delete_cold_noop_when_disabled(fresh_app, monkeypatch, tmp_path):
    import storage_backend
    fresh_app(env={"ABM_DATA_DIR": str(tmp_path)})
    called = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: called.append(p))
    cleanup._delete_cold_for_job("jobZ")
    assert called == []


def test_no_cold_delete_when_forensic_protected(fresh_app, monkeypatch, tmp_path):
    """Job sotto retention forense: i file locali sono preservati, quindi anche
    gli oggetti cold NON devono essere cancellati."""
    import storage_backend
    fresh_app(env={"ABM_DATA_DIR": str(tmp_path)})
    # crea la work dir del job così work_dir.exists() è True
    (tmp_path / "jobF").mkdir()
    deleted = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "delete_prefix", lambda p: deleted.append(p))
    # forza la protezione forense
    monkeypatch.setattr(cleanup, "_forensic_marker_protects", lambda *a, **k: True)
    cleanup._cleanup_job("jobF", "test")
    assert deleted == []   # nessun delete cold sotto hold forense
