"""Riuso dell'output di una generazione identica (output_reuse.py)."""
import os

import pytest

import output_reuse as orx
from epub_to_tts import Chapter

CID = "cid-reuse-unit"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ABM_OUTPUT_REUSE", raising=False)
    yield


def _chapters(*texts):
    return [Chapter(index=i, title=f"C{i}", text=t) for i, t in enumerate(texts)]


def _src_job(tmp_path, name="src", status="done", failed=0, client=CID, files=("a.mp3", "b.mp3")):
    out = tmp_path / name / "output_0"
    out.mkdir(parents=True)
    paths = []
    for f in files:
        p = out / f
        p.write_bytes(b"ID3" + f.encode())
        paths.append(str(p))
    (out / "book.abm").write_bytes(b"PK")
    m4b = out / "book.m4b"
    m4b.write_bytes(b"m4b")
    return {
        "status": status, "client_id": client, "failed_chunks": failed,
        "output_dir": str(out), "output_files": paths, "output_m4b": str(m4b),
        "output_name": "book", "bytes_generated": 123, "total_chunks": 4,
        "total_chars": 999, "m4b_failed": False,
    }


def test_enabled_switch(monkeypatch):
    assert orx.enabled()
    monkeypatch.setenv("ABM_OUTPUT_REUSE", "0")
    assert not orx.enabled()
    monkeypatch.setenv("ABM_OUTPUT_REUSE", "off")
    assert not orx.enabled()


def test_compute_key_deterministic_and_sensitive():
    ch = _chapters("uno", "due")
    k1 = orx.compute_key(ch, "en-US-AriaNeural", "+0%", "m4b", True)
    assert k1 == orx.compute_key(_chapters("uno", "due"), "en-US-AriaNeural", "+0%", "m4b", True)
    assert k1 != orx.compute_key(_chapters("uno", "due!"), "en-US-AriaNeural", "+0%", "m4b", True)
    assert k1 != orx.compute_key(ch, "en-US-GuyNeural", "+0%", "m4b", True)
    assert k1 != orx.compute_key(ch, "en-US-AriaNeural", "+10%", "m4b", True)
    assert k1 != orx.compute_key(ch, "en-US-AriaNeural", "+0%", "zip", False)
    assert k1 != orx.compute_key(ch, "en-US-AriaNeural", "+0%", "m4b", True, strip_round=False)
    # Ordine dei capitoli conta (selezione diversa = output diverso).
    assert k1 != orx.compute_key(_chapters("due", "uno"), "en-US-AriaNeural", "+0%", "m4b", True)


def test_record_lookup_forget_scoped_by_client(tmp_path):
    assert orx.record("k1", CID, "job-a", str(tmp_path)) is True
    assert orx.lookup("k1", CID)["job_id"] == "job-a"
    assert orx.lookup("k1", "altro-client") is None, "mai riuso fra client diversi"
    assert orx.lookup("manca", CID) is None
    orx.forget("k1")
    assert orx.lookup("k1", CID) is None
    assert orx.record("", CID, "job-a", "") is False


def test_source_is_reusable_conditions(tmp_path):
    ok = _src_job(tmp_path)
    assert orx.source_is_reusable(ok, CID)
    assert not orx.source_is_reusable(ok, "altro")
    assert not orx.source_is_reusable(_src_job(tmp_path, "p", status="partial"), CID)
    assert not orx.source_is_reusable(_src_job(tmp_path, "f", failed=1), CID)
    assert not orx.source_is_reusable(None, CID)
    evicted = _src_job(tmp_path, "e")
    os.remove(evicted["output_files"][0])  # hot->cold eviction
    assert not orx.source_is_reusable(evicted, CID)
    outside = _src_job(tmp_path, "o")
    outside["output_m4b"] = str(tmp_path / "elsewhere.m4b")
    assert not orx.source_is_reusable(outside, CID)


def test_materialize_copies_and_rebases(tmp_path):
    src = _src_job(tmp_path)
    dst = tmp_path / "dst" / "output_1"
    fields = orx.materialize(src, dst)
    assert fields is not None
    assert all(p.startswith(str(dst)) for p in fields["output_files"])
    assert fields["output_m4b"] == str(dst / "book.m4b")
    assert all(os.path.isfile(p) for p in fields["output_files"])
    assert (dst / "a.mp3").read_bytes() == b"ID3a.mp3"
    assert not (dst / "book.abm").exists(), "lo snapshot .abm non si copia"
    for f in ("output_name", "bytes_generated", "total_chunks", "total_chars", "m4b_failed"):
        assert fields[f] == src[f]
    assert "status" not in fields and "client_id" not in fields


def test_materialize_returns_none_when_source_incomplete(tmp_path):
    src = _src_job(tmp_path)
    os.remove(src["output_m4b"])
    assert orx.materialize(src, tmp_path / "dst") is None
    assert orx.materialize({"output_dir": str(tmp_path / "nope")}, tmp_path / "dst2") is None


def test_prune_by_age(monkeypatch, tmp_path):
    orx.record("old", CID, "j-old", str(tmp_path))
    d = orx._load()
    d["old"]["ts"] -= orx._MAX_AGE_SEC + 10
    from community_store import atomic_write_json
    atomic_write_json(orx._index_file(), d)
    orx.record("new", CID, "j-new", str(tmp_path))  # record prunes
    assert orx.lookup("old", CID) is None
    assert orx.lookup("new", CID)["job_id"] == "j-new"
