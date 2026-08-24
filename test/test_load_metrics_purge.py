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
