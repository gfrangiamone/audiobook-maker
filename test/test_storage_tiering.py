"""Unit test per storage_tiering: derivazione chiave, finestra calda, marker."""
import importlib
import os


def _reload(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_HOT_WINDOW_SEC", "7200")
    monkeypatch.setenv("ABM_HOT_WINDOW_GEMINI_SEC", "14400")
    import storage_tiering
    importlib.reload(storage_tiering)
    return storage_tiering


def test_key_for_path_relative_posix(monkeypatch, tmp_path):
    st = _reload(monkeypatch, tmp_path)
    p = tmp_path / "jobid" / "output_123" / "book.m4b"
    assert st.key_for_path(str(p)) == "jobid/output_123/book.m4b"


def test_key_for_path_outside_datadir_returns_none(monkeypatch, tmp_path):
    st = _reload(monkeypatch, tmp_path)
    assert st.key_for_path("/etc/passwd") is None


def test_hot_window_standard_vs_gemini(monkeypatch, tmp_path):
    st = _reload(monkeypatch, tmp_path)
    assert st.hot_window_sec({"voice": "it-IT-IsabellaNeural"}) == 7200
    assert st.hot_window_sec({"voice": "gemini:flash25:Zephyr"}) == 14400
    assert st.hot_window_sec({"opt_voice": "gemini:flash25:Zephyr"}) == 14400


def test_marker_write_and_read(monkeypatch, tmp_path):
    st = _reload(monkeypatch, tmp_path)
    d = tmp_path / "jobid" / "output_1"
    d.mkdir(parents=True)
    assert st.cloud_uploaded_at(d) is None
    st.mark_cloud_uploaded(d, when=1000.0)
    assert st.cloud_uploaded_at(d) == 1000.0


def test_is_cloud_audio_file(monkeypatch, tmp_path):
    st = _reload(monkeypatch, tmp_path)
    assert st.is_offloadable("book.m4b") is True
    assert st.is_offloadable("book.mp3") is True
    assert st.is_offloadable("chapters.zip") is True
    assert st.is_offloadable("project.abm") is True
    assert st.is_offloadable(".cloud_uploaded") is False
    assert st.is_offloadable("cover.jpg") is False


def test_metadata_txt_not_offloadable(monkeypatch, tmp_path):
    st = _reload(monkeypatch, tmp_path)
    assert st.is_offloadable("book.m4b.metadata.txt") is False
    assert st.is_offloadable("book.txt") is True


def test_hot_window_defaults_match_today(monkeypatch, tmp_path):
    import importlib, os
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ABM_HOT_WINDOW_SEC", raising=False)
    monkeypatch.delenv("ABM_HOT_WINDOW_GEMINI_SEC", raising=False)
    import storage_tiering
    importlib.reload(storage_tiering)
    assert storage_tiering.hot_window_sec({"voice": "it-IT-IsabellaNeural"}) == 64800
    assert storage_tiering.hot_window_sec({"voice": "gemini:flash25:Zephyr"}) == 172800
