"""load_metrics.purge: retention dei file mensili."""
import pytest

import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def _touch(tmp_path, month):
    (tmp_path / f"load_metrics_{month}.jsonl").write_text("{}\n", encoding="utf-8")


def test_purge_removes_only_files_older_than_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(lm, "RETENTION_MONTHS", 4)
    for m in ("2026-01", "2026-02", "2026-03", "2026-04", "2026-05",
              "2026-06", "2026-07", "2026-08"):
        _touch(tmp_path, m)
    # now = 2026-08-24
    removed = lm.purge(now=1787529600.0)
    left = sorted(p.name for p in tmp_path.glob("load_metrics_*.jsonl"))
    assert left == ["load_metrics_2026-05.jsonl", "load_metrics_2026-06.jsonl",
                    "load_metrics_2026-07.jsonl", "load_metrics_2026-08.jsonl"]
    assert removed == 4


def test_purge_ignores_unrelated_files(tmp_path):
    (tmp_path / "activity_2020-01.log").write_text("x", encoding="utf-8")
    lm.purge(now=1787529600.0)
    assert (tmp_path / "activity_2020-01.log").exists()


def test_purge_never_raises_without_data_dir(monkeypatch):
    monkeypatch.setattr(lm, "_data_dir", None)
    assert lm.purge(now=1787529600.0) == 0


def _rows(path):
    import json
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_voxcpm_gauges_older_than_28_days_are_stripped(tmp_path, monkeypatch):
    import json
    monkeypatch.setattr(lm, "VOXCPM_RETENTION_DAYS", 28)
    now = 1787529600.0                       # 2026-08-24
    old_t, new_t = int(now - 29 * 86400), int(now - 27 * 86400)
    g = {"gen": [0, 1, 0.5, 10], "vx_busy": [0, 1, 0.5, 10], "vx_run": [0, 2, 1.0, 10]}
    for t in (old_t, new_t):
        p = tmp_path / f"load_metrics_{lm._month_of(t)}.jsonl"
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"t": t, "n": 10, "g": dict(g), "c": {}, "h": {}}) + "\n")
    lm.purge(now=now)
    rows = {r["t"]: r for p in tmp_path.glob("load_metrics_*.jsonl") for r in _rows(p)}
    assert set(rows[old_t]["g"]) == {"gen"}          # il resto della riga resta
    assert "vx_busy" in rows[new_t]["g"] and "vx_run" in rows[new_t]["g"]
    assert not list(tmp_path.glob("*.tmp"))


def test_voxcpm_strip_leaves_untouched_files_and_bad_lines(tmp_path):
    p = tmp_path / "load_metrics_2026-07.jsonl"
    p.write_text('{"t": 1, "n": 1, "g": {"gen": [0, 0, 0, 1]}}\nnon-json\n',
                 encoding="utf-8")
    before = p.stat().st_mtime_ns
    lm.purge(now=1787529600.0)
    assert p.read_text(encoding="utf-8").endswith("non-json\n")
    assert p.stat().st_mtime_ns == before
