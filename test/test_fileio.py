"""fileio: primitive di persistenza condivise (blocco B2)."""
import json

import fileio


def test_data_dir_reads_env_each_call(monkeypatch, tmp_path):
    monkeypatch.delenv("ABM_DATA_DIR", raising=False)
    assert str(fileio.data_dir()) == str(fileio.Path(fileio.DEFAULT_DATA_DIR))
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    assert fileio.data_dir() == tmp_path
    assert fileio.data_path("x.json") == tmp_path / "x.json"
    monkeypatch.setenv("ABM_DATA_DIR", "   ")
    assert str(fileio.data_dir()) == str(fileio.Path(fileio.DEFAULT_DATA_DIR))


def test_atomic_write_json_creates_parents_and_leaves_no_tmp(tmp_path):
    p = tmp_path / "a" / "b" / "s.json"
    fileio.atomic_write_json(p, {"k": "è"}, indent=2)
    assert json.loads(p.read_text(encoding="utf-8")) == {"k": "è"}
    assert not list(p.parent.glob("*.tmp"))
    fileio.atomic_write_json(p, {"k": 2}, fsync=False)
    assert json.loads(p.read_text(encoding="utf-8")) == {"k": 2}


def test_atomic_write_text_removes_tmp_on_failure(tmp_path, monkeypatch):
    p = tmp_path / "t.txt"
    import os as _os
    real = _os.replace

    def boom(a, b):
        raise OSError("disk full")
    monkeypatch.setattr(fileio.os, "replace", boom)
    try:
        fileio.atomic_write_text(p, "x")
        assert False, "doveva sollevare"
    except OSError:
        pass
    monkeypatch.setattr(fileio.os, "replace", real)
    assert not p.exists() and not list(tmp_path.glob("*.tmp"))


def test_write_json_safe_never_raises(tmp_path):
    errors = []
    ok = fileio.write_json_safe(tmp_path / "ok.json", [1, 2])
    assert ok and json.loads((tmp_path / "ok.json").read_text()) == [1, 2]
    bad = tmp_path / "file_not_dir"
    bad.write_text("x")
    assert fileio.write_json_safe(bad / "x.json", {}, on_error=errors.append) is False
    assert errors and isinstance(errors[0], Exception)


def test_load_json_defaults_type_check_and_hook(tmp_path):
    missing = tmp_path / "nope.json"
    assert fileio.load_json(missing) == {}
    assert fileio.load_json(missing, None) is None
    assert fileio.load_json(missing, list) == []
    p = tmp_path / "x.json"
    p.write_text("{not json", encoding="utf-8")
    seen = []
    assert fileio.load_json(p, {"d": 1}, on_error=seen.append) == {"d": 1}
    assert len(seen) == 1
    p.write_text("[1, 2]", encoding="utf-8")
    assert fileio.load_json(p, {}, on_error=seen.append) == {}      # tipo sbagliato
    assert len(seen) == 2
    assert fileio.load_json(p, expect=list) == [1, 2]
    assert fileio.load_json(p, expect=None) == [1, 2]
    p.write_text('{"a": 1}', encoding="utf-8")
    assert fileio.load_json(p) == {"a": 1}


def test_write_json_verified_detects_mismatch(tmp_path, monkeypatch):
    p = tmp_path / "v.json"
    ok, err = fileio.write_json_verified(p, {"on": True}, attempts=2, backoff=0)
    assert ok and err is None
    calls = {"n": 0}
    real = fileio.atomic_write_json

    def corrupt(path, data, **kw):
        calls["n"] += 1
        real(path, {"on": False}, **kw)
    monkeypatch.setattr(fileio, "atomic_write_json", corrupt)
    ok, err = fileio.write_json_verified(p, {"on": True}, attempts=2, backoff=0)
    assert ok is False and calls["n"] == 2 and "non combacia" in str(err)


def test_community_store_reexports_the_same_function():
    import community_store
    assert community_store.atomic_write_json is fileio.atomic_write_json


def test_fileio_is_a_leaf():
    import ast, pathlib
    src = pathlib.Path(fileio.__file__).read_text(encoding="utf-8")
    mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert mods <= {"json", "os", "threading", "time", "pathlib", "env_utils"}
