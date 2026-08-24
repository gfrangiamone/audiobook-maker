"""load_metrics: accumulo in bucket da 5 minuti e persistenza JSONL."""
import json

import pytest

import load_metrics as lm


@pytest.fixture(autouse=True)
def fresh(tmp_path):
    """Ogni test parte da uno stato pulito e da una data dir isolata."""
    lm.configure(tmp_path)
    lm.reset_for_tests()
    yield
    lm.reset_for_tests()


def _read(tmp_path, month):
    p = tmp_path / f"load_metrics_{month}.jsonl"
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines()]


def test_bucket_start_is_aligned():
    assert lm._bucket_start(1756000123.0) % lm.BUCKET_SEC == 0
    assert lm._bucket_start(1756000123.0) <= 1756000123.0


def test_sample_accumulates_min_max_avg_count():
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=2, ram=50.0)
    lm.sample(now=t + 2, gen=4, ram=70.0)
    b = lm._current_bucket()
    assert b["g"]["gen"] == [2, 4, 6, 2]      # min, max, somma, conteggio
    assert b["g"]["ram"] == [50.0, 70.0, 120.0, 2]
    assert b["n"] == 2


def test_gauge_absent_from_a_sample_does_not_skew_count():
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=2, ram=50.0)
    lm.sample(now=t + 2, gen=4)              # niente ram: fuori da Linux
    b = lm._current_bucket()
    assert b["g"]["gen"][3] == 2
    assert b["g"]["ram"][3] == 1
    assert b["g"]["ram"][0] == 50.0          # il minimo non diventa 0


def test_incr_sums_within_bucket():
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    lm.incr("rej_busy", now=t + 2)
    lm.incr("rej_busy", n=3, now=t + 3)
    assert lm._current_bucket()["c"]["rej_busy"] == 4


def test_observe_lands_in_the_right_bin_and_branch():
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    lm.observe("asm_wait", 5, now=t + 2)                    # bin 0: < 10s
    lm.observe("asm_wait", 45, now=t + 3)                   # bin 2: 30-60s
    lm.observe("asm_wait", 5000, now=t + 4)                 # bin 7: overflow
    lm.observe("asm_wait", 5, premium=True, now=t + 5)
    b = lm._current_bucket()
    assert b["h"]["asm_wait"] == [1, 0, 1, 0, 0, 0, 0, 1]
    assert b["h"]["asm_wait_p"] == [1, 0, 0, 0, 0, 0, 0, 0]


def test_flush_writes_only_closed_buckets(tmp_path):
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    assert lm.flush(now=t + 10) == 0                        # bucket ancora aperto
    assert not (tmp_path / f"load_metrics_{lm._month_of(t)}.jsonl").exists()
    lm.sample(now=t + lm.BUCKET_SEC + 1, gen=2)             # apre il bucket dopo
    assert lm.flush(now=t + lm.BUCKET_SEC + 10) == 1
    rows = _read(tmp_path, lm._month_of(t))
    assert len(rows) == 1
    assert rows[0]["t"] == t
    assert rows[0]["g"]["gen"] == [1, 1, 1.0, 1]            # su file: media, non somma


def test_flush_is_idempotent(tmp_path):
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    lm.sample(now=t + lm.BUCKET_SEC + 1, gen=2)
    lm.flush(now=t + lm.BUCKET_SEC + 10)
    assert lm.flush(now=t + lm.BUCKET_SEC + 20) == 0
    assert len(_read(tmp_path, lm._month_of(t))) == 1


def test_never_raises_when_data_dir_is_unwritable(tmp_path):
    lm.configure(tmp_path / "non" / "esiste" / "affatto")
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    lm.incr("boot", now=t + 1)
    lm.observe("job", 30, now=t + 1)
    lm.sample(now=t + lm.BUCKET_SEC + 1, gen=1)
    lm.flush(now=t + lm.BUCKET_SEC + 10)                    # non deve sollevare


def test_disabled_module_is_a_noop(monkeypatch, tmp_path):
    monkeypatch.setattr(lm, "ENABLED", False)
    t = lm._bucket_start(1756000000.0)
    lm.sample(now=t + 1, gen=1)
    assert lm._current_bucket() is None
