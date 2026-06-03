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
    # F1: l'offload procede solo se la generazione è marcata conclusa.
    storage_tiering.mark_generation_complete(out, 1234.0)

    uploaded = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: uploaded.append(k))
    # Semantica realistica: l'oggetto NON esiste su cold prima dell'upload e
    # risulta presente solo dopo. F2 usa object_size per l'idempotenza-per-contenuto.
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: k in uploaded)
    monkeypatch.setattr(storage_backend, "object_size", lambda k: 5 if k in uploaded else None)

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
    storage_tiering.mark_generation_complete(out, 1.0)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: None)
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: False)  # remote non confermato
    monkeypatch.setattr(storage_backend, "object_size", lambda k: None)     # mai su cold
    generation_engine._offload_to_cloud("job3", str(out), when=1.0)
    assert storage_tiering.cloud_uploaded_at(out) is None  # invariante: nessun marker


def test_offload_no_marker_when_upload_raises(monkeypatch, tmp_path):
    import storage_backend, storage_tiering, generation_engine
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    importlib.reload(storage_tiering)
    out = tmp_path / "job4" / "output_1"
    out.mkdir(parents=True)
    (out / "book.mp3").write_bytes(b"x")
    storage_tiering.mark_generation_complete(out, 1.0)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: (_ for _ in ()).throw(OSError("network")))
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: False)
    monkeypatch.setattr(storage_backend, "object_size", lambda k: None)
    generation_engine._offload_to_cloud("job4", str(out), when=1.0)
    assert storage_tiering.cloud_uploaded_at(out) is None


def test_offload_reuploads_on_cold_size_mismatch(monkeypatch, tmp_path):
    """F2: se il cold ESISTE ma con dimensione diversa (es. m4b troncato), NON
    si salta per sola presenza del nome — si RI-carica il locale completo."""
    import os, storage_backend, storage_tiering, generation_engine
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    importlib.reload(storage_tiering)
    out = tmp_path / "job7" / "output_1"; out.mkdir(parents=True)
    (out / "book.m4b").write_bytes(b"complete-audio-bytes")  # 20 byte
    storage_tiering.mark_generation_complete(out, 1.0)

    uploaded = []
    state = {"size": 3}  # cold troncato (3 byte) presente da prima
    def _upload(p, k):
        uploaded.append(k); state["size"] = os.path.getsize(p)
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", _upload)
    monkeypatch.setattr(storage_backend, "object_size", lambda k: state["size"])
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: k in uploaded)
    generation_engine._offload_to_cloud("job7", str(out), when=1.0)
    assert uploaded, "un cold troncato deve essere ri-caricato (F2)"
    assert storage_tiering.cloud_uploaded_at(out) == 1.0


def test_offload_skips_when_generation_incomplete(monkeypatch, tmp_path):
    """F1: senza marker .generation_complete e con file appena scritti
    (conversione in corso), l'offload NON deve caricare nulla — questo previene
    la copia su cold di un .m4b mid-write (atom moov non ancora scritto)."""
    import storage_backend, storage_tiering, generation_engine
    import time as _t
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    importlib.reload(storage_tiering)
    out = tmp_path / "job6" / "output_1"
    out.mkdir(parents=True)
    (out / "book.m4b").write_bytes(b"partial-mid-write")  # nessun marker, mtime fresco

    uploaded = []
    monkeypatch.setattr(storage_backend, "is_enabled", lambda: True)
    monkeypatch.setattr(storage_backend, "upload_file", lambda p, k: uploaded.append(k))
    monkeypatch.setattr(storage_backend, "object_exists", lambda k: k in uploaded)

    # when = adesso → il file è stato scritto "ora" → quiet < soglia → SKIP
    generation_engine._offload_to_cloud("job6", str(out), when=_t.time())
    assert uploaded == [], "non deve offloadare un output mid-conversione"
    assert storage_tiering.cloud_uploaded_at(out) is None
