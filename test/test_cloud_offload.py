"""Test del hook _offload_to_cloud: carica solo i file offloadable e scrive marker."""
import importlib
import types


def test_offload_uploads_outputs_and_marks(monkeypatch, tmp_path):
    import storage_backend, storage_tiering, generation_engine
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    importlib.reload(storage_tiering)

    out = tmp_path / "job1" / "output_1"
    out.mkdir(parents=True)
    (out / "book.m4b").write_bytes(b"audio")
    (out / "cover.jpg").write_bytes(b"img")   # non offloadable

    uploaded = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: uploaded.append(k))
    # Semantica realistica: l'oggetto NON esiste su cold prima dell'upload e
    # risulta presente solo dopo (l'offload pre-controlla per essere idempotente
    # quando richiamato dal pass di riconciliazione).
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: k in uploaded)

    generation_engine._offload_to_cloud("job1", str(out), when=1234.0)

    assert "job1/output_1/book.m4b" in uploaded
    assert all("cover.jpg" not in k for k in uploaded)
    assert storage_tiering.cloud_uploaded_at(out) == 1234.0


def test_offload_noop_when_disabled(monkeypatch, tmp_path):
    import storage_backend, storage_tiering, generation_engine
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    importlib.reload(storage_tiering)
    out = tmp_path / "job2" / "output_1"
    out.mkdir(parents=True)
    (out / "book.mp3").write_bytes(b"x")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: False)
    generation_engine._offload_to_cloud("job2", str(out), when=1.0)
    assert storage_tiering.cloud_uploaded_at(out) is None


def test_offload_no_marker_when_exists_returns_false(monkeypatch, tmp_path):
    import storage_backend, storage_tiering, generation_engine
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    importlib.reload(storage_tiering)
    out = tmp_path / "job3" / "output_1"
    out.mkdir(parents=True)
    (out / "book.mp3").write_bytes(b"x")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: None)
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: False)  # remote non confermato
    generation_engine._offload_to_cloud("job3", str(out), when=1.0)
    assert storage_tiering.cloud_uploaded_at(out) is None  # invariante: nessun marker


def test_offload_no_marker_when_upload_raises(monkeypatch, tmp_path):
    import storage_backend, storage_tiering, generation_engine
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    importlib.reload(storage_tiering)
    out = tmp_path / "job4" / "output_1"
    out.mkdir(parents=True)
    (out / "book.mp3").write_bytes(b"x")
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: (_ for _ in ()).throw(OSError("network")))
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: False)
    generation_engine._offload_to_cloud("job4", str(out), when=1.0)
    assert storage_tiering.cloud_uploaded_at(out) is None
