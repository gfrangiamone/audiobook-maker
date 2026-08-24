"""load_metrics.query: aggregazione di finestra, percentili, copertura."""
import json

import pytest

import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def _write(tmp_path, t, g=None, c=None, h=None, n=10):
    row = {"t": t, "n": n, "g": g or {}, "c": c or {}, "h": h or {}}
    p = tmp_path / f"load_metrics_{lm._month_of(t)}.jsonl"
    with open(p, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def test_percentile_interpolates_inside_the_bin():
    # 10 osservazioni tutte nel bin 0 (< 10s): il p50 cade a meta' del bin.
    assert lm._percentile([10, 0, 0, 0, 0, 0, 0, 0], 50) == pytest.approx(5.0, abs=0.6)


def test_percentile_picks_the_right_bin():
    # 8 sotto i 10s, 2 fra 30 e 60s: il p95 cade nel terzo bin.
    bins = [8, 0, 2, 0, 0, 0, 0, 0]
    assert 30 <= lm._percentile(bins, 95) <= 60


def test_percentile_of_empty_histogram_is_zero():
    assert lm._percentile([0] * 8, 95) == 0.0


def test_percentile_in_overflow_bin_returns_lower_edge():
    assert lm._percentile([0, 0, 0, 0, 0, 0, 0, 5], 50) == float(lm._BINS[-1])


def test_window_peak_is_the_max_across_buckets(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 600, g={"gen": [0, 2, 1.0, 10]})
    _write(tmp_path, now - 300, g={"gen": [1, 5, 2.0, 10]})
    out = lm.query("24h", now=now)
    assert out["job"]["gen_peak"] == 5


def test_window_average_is_weighted_by_sample_count(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 600, g={"gen": [0, 2, 1.0, 10]})
    _write(tmp_path, now - 300, g={"gen": [4, 4, 4.0, 2]})
    # (1.0*10 + 4.0*2) / 12 = 1.5
    assert lm.query("24h", now=now)["job"]["gen_avg"] == pytest.approx(1.5, abs=0.01)


def test_counters_are_summed_over_the_window(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 600, c={"rej_busy": 2, "rej_busy_p": 1})
    _write(tmp_path, now - 300, c={"rej_busy": 3})
    out = lm.query("24h", now=now)
    assert out["job"]["rejected_free"] == 5
    assert out["job"]["rejected_premium"] == 1


def test_buckets_outside_the_window_are_ignored(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 86400 - 3600, c={"rej_busy": 99})
    _write(tmp_path, now - 300, c={"rej_busy": 1})
    assert lm.query("24h", now=now)["job"]["rejected_free"] == 1


def test_window_spanning_two_monthly_files(tmp_path):
    # 1756598400 = 2025-08-31 00:00 UTC; una finestra di 7 giorni tocca luglio.
    now = lm._bucket_start(1756598400.0)
    _write(tmp_path, now - 3 * 86400, c={"done": 4})
    _write(tmp_path, now - 300, c={"done": 1})
    months = {p.name for p in tmp_path.glob("load_metrics_*.jsonl")}
    assert len(months) >= 1
    assert lm.query("7d", now=now)["quality"]["completed"] == 5


def test_coverage_is_zero_with_no_history(tmp_path):
    now = lm._bucket_start(1756000000.0)
    out = lm.query("28d", now=now)
    assert out["meta"]["coverage_pct"] == 0
    assert out["meta"]["first_sample_ts"] is None
    assert out["job"]["gen_peak"] == 0


def test_timeline_resolution_matches_the_window(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 300, g={"gen": [0, 2, 1.0, 10]})
    assert lm.query("24h", now=now)["meta"]["timeline_step_sec"] == 1800
    assert lm.query("7d", now=now)["meta"]["timeline_step_sec"] == 14400
    assert lm.query("28d", now=now)["meta"]["timeline_step_sec"] == 86400


def test_timeline_point_carries_peaks_and_rejections(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 300,
           g={"gen": [0, 3, 1.0, 10], "gen_p": [0, 1, 0.5, 10], "ram": [40, 80, 60.0, 10]},
           c={"rej_busy": 2})
    pts = [p for p in lm.query("24h", now=now)["timeline"] if p["gen"] > 0]
    assert pts[-1]["gen"] == 3
    assert pts[-1]["gen_p"] == 1
    assert pts[-1]["ram"] == 80
    assert pts[-1]["rej"] == 2


def test_unknown_window_falls_back_to_24h(tmp_path):
    now = lm._bucket_start(1756000000.0)
    assert lm.query("qualunque", now=now)["meta"]["window"] == "24h"


def test_premium_errors_are_counted_and_exposed(tmp_path):
    now = lm._bucket_start(1756000000.0) + lm.BUCKET_SEC
    _write(tmp_path, now - 300, c={"done": 6, "done_p": 2, "err": 1, "err_p": 1})
    q = lm.query("24h", now=now)["quality"]
    assert q["errors"] == 2
    assert q["errors_premium"] == 1
    # 2 errori su 10 job terminati
    assert q["error_pct"] == pytest.approx(20.0, abs=0.1)
