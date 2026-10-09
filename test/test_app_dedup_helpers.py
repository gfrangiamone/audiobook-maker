"""E2(c): helper di audiobook_app al posto delle copie (X-Fallback, ADMIN_CANCEL, ZIP podcast)."""
import inspect
import types
import zipfile
from pathlib import Path

import audiobook_app as app


def test_with_mp3_fallback_header():
    with app.app.test_request_context("/"):
        resp = app.app.response_class(b"x")
        out = app._with_mp3_fallback_header(resp)
        assert out is resp and resp.headers["X-Fallback"] == "mp3"
        assert resp.headers["Access-Control-Expose-Headers"] == "X-Fallback"
        resp.headers["Access-Control-Expose-Headers"] = "Content-Disposition"
        app._with_mp3_fallback_header(resp)
        assert resp.headers["Access-Control-Expose-Headers"] == "Content-Disposition, X-Fallback"
    assert app._with_mp3_fallback_header(object()) is not None            # mai fatale


def test_log_admin_cancel(monkeypatch):
    calls = []
    monkeypatch.setattr(app, "_log_activity", lambda *a, **k: calls.append(a))
    app._log_admin_cancel("J", {"original_filename": "l.epub", "client_id": "c1"}, "it-IT-ElsaNeural")
    app._log_admin_cancel("J", {}, "")
    assert calls == [("J", "l.epub", "ADMIN_CANCEL", "c1", "", "it-IT-ElsaNeural", ""),
                     ("J", "", "ADMIN_CANCEL", "", "", "", "")]
    src = inspect.getsource(app)
    for fn in (app.api_cancel, app.api_cancel_optimize, app.api_translate_cancel):
        assert "_log_admin_cancel(" in inspect.getsource(fn) and '"ADMIN_CANCEL"' not in inspect.getsource(fn)


def test_build_podcast_zip_generated_cover(tmp_path, monkeypatch):
    mp3 = tmp_path / "001_cap.mp3"
    mp3.write_bytes(b"\xff\xfb" + b"\x00" * 100)
    monkeypatch.setattr(app, "_generate_podcast_rss", lambda info, files, path, **k: Path(path).write_text("<rss/>", encoding="utf-8"))
    monkeypatch.setattr(app, "_generate_podcast_index_html", lambda d, *a, **k: (Path(d) / "index.html").write_text("<p>i</p>", encoding="utf-8"))
    monkeypatch.setattr(app, "_generate_fallback_cover", lambda path, title="", author="": Path(path).write_bytes(b"\xff\xd8cover"))
    info = types.SimpleNamespace(title="Libro", author="A", language="it", chapters=[])
    zip_path = app._build_podcast_zip("J", tmp_path / "pod_tmp", [str(mp3)], "", info, "libro",
                                      "https://x", "it", tmp_path / "libro_podcast")
    assert zip_path.endswith("libro_podcast.zip") and not (tmp_path / "pod_tmp").exists()
    names = set(zipfile.ZipFile(zip_path).namelist())
    assert names == {"001_cap.mp3", "cover.jpg", "libro_podcast.xml", "index.html"}
    for fn in (app.api_download_podcast, app._serve_podcast_download):
        s = inspect.getsource(fn)
        assert "_build_podcast_zip(" in s and "_generate_podcast_rss(" not in s and "make_archive" not in s
