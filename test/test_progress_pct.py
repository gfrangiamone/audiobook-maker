"""Test del helper _progress_pct(job)."""
from generation_engine import _progress_pct


def test_progress_pct_zero_when_total_missing():
    assert _progress_pct({}) == 0
    assert _progress_pct({"progress_current": 10}) == 0
    assert _progress_pct({"progress_total": 0}) == 0


def test_progress_pct_basic():
    assert _progress_pct({"progress_current": 50, "progress_total": 100}) == 50
    assert _progress_pct({"progress_current": 71, "progress_total": 100}) == 71


def test_progress_pct_clamped_high():
    assert _progress_pct({"progress_current": 200, "progress_total": 100}) == 100


def test_progress_pct_clamped_negative():
    assert _progress_pct({"progress_current": -5, "progress_total": 100}) == 0


def test_progress_pct_rounded():
    out = _progress_pct({"progress_current": 18, "progress_total": 63})
    assert out in (28, 29)
