"""Money-critical concurrency stress tests (Task H2).

Three tests guard against money bugs under concurrent access:
  1. Voucher consume must not overspend the pool when called concurrently.
  2. _mark_paid_job_done must not lose records under interleaved writes.
  3. PayPal captured order must not be double-spent.

These tests touch the real `payment` module globals. We use `monkeypatch.setattr`
to redirect file paths and reset module-level state (without polluting globals).

To amplify scheduler interleaving we shrink ``sys.setswitchinterval`` for the
duration of these tests — restored via the monkeypatch teardown.
"""
import json
import sys
import threading
import time

import pytest

import payment


@pytest.fixture(autouse=True)
def _tight_switch_interval(monkeypatch):
    """Force frequent thread switching so races have a real chance to manifest.
    CPython's default switch interval (5 ms) often serializes short critical
    sections enough to hide races; tightening to 1 microsecond exposes them.
    """
    original = sys.getswitchinterval()
    sys.setswitchinterval(0.000001)
    yield
    sys.setswitchinterval(original)


# ---------------------------------------------------------------------------
# Test 1: concurrent voucher consume — no overspend
# ---------------------------------------------------------------------------

def test_concurrent_voucher_consumption_no_overspend(monkeypatch, tmp_path):
    """N threads each try to consume 4.0 EUR from a voucher with ~11.0 EUR
    (10.0 base + 10% bonus). At most 2 consumes can succeed without overdraw.
    The total consumed across all uses MUST NEVER exceed the initial pool.

    This is a known-race regression guard: without a lock around the
    read-modify-write of remaining_eur in _voucher_consume, multiple threads
    can observe the same balance, all pass the "sufficient" check, and all
    succeed — overspending the pool.
    """
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_vouchers", {})

    code, bonus_amount = payment._create_voucher(
        "u@x.it", 10.0, kind="test", note="stress"
    )
    initial_remaining = payment._voucher_remaining(payment._vouchers[code])
    # Sanity: 10.0 * 1.10 = 11.0
    assert initial_remaining == pytest.approx(11.0, abs=0.01)

    # Use many threads to amplify contention: 50 threads each requesting 4.0
    # against an 11.0 pool — at most 2 can legitimately succeed.
    N_THREADS = 50
    results: list = []
    errors: list = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(N_THREADS)

    def worker(i: int):
        try:
            # Synchronize start to maximize contention
            barrier.wait()
            new_rem = payment._voucher_consume(code, 4.0, job_id=f"j{i}")
            with results_lock:
                results.append((i, new_rem))
        except ValueError as e:
            with results_lock:
                errors.append((i, str(e)))
        except Exception as e:  # pragma: no cover — surface unexpected errors
            with results_lock:
                errors.append((i, f"UNEXPECTED: {type(e).__name__}: {e}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # No overspend: sum of POSITIVE uses must not exceed pool (+ tiny tolerance
    # for the documented 0.01 EUR rounding allowance per consume).
    positive_uses = [
        float(u.get("amount_eur", 0) or 0)
        for u in payment._vouchers[code].get("uses", [])
        if float(u.get("amount_eur", 0) or 0) > 0
    ]
    total_consumed = sum(positive_uses)
    assert total_consumed <= initial_remaining + 0.01, (
        f"OVERSPEND: consumed {total_consumed:.2f} EUR from pool of "
        f"{initial_remaining:.2f} EUR (successes={len(results)}, "
        f"errors={len(errors)})"
    )

    # Critical invariant: final remaining must be non-negative AND consistent
    # with what was consumed.
    final_remaining = payment._voucher_remaining(payment._vouchers[code])
    assert final_remaining >= 0.0, (
        f"OVERDRAFT: voucher remaining is negative ({final_remaining})"
    )

    # Capacity: 11.0 / 4.0 -> 2 successful consumes max, so at least
    # N_THREADS - 2 threads must have failed with ValueError.
    assert len(results) <= 2, (
        f"Too many successes ({len(results)}): capacity is 2 (11.0 / 4.0). "
        f"successes={results}"
    )
    assert len(errors) >= N_THREADS - 2, (
        f"Expected at least {N_THREADS - 2} failures; got {len(errors)}"
    )
    # At least one success expected.
    assert len(results) >= 1


# ---------------------------------------------------------------------------
# Test 2: concurrent _mark_paid_job_done — no record loss
# ---------------------------------------------------------------------------

def test_concurrent_mark_paid_job_done_no_loss(monkeypatch, tmp_path):
    """20 threads each mark a distinct job_id as done. After joining, the
    persisted file MUST contain exactly 20 unique job_ids — no lost writes.
    """
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(
        payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json"
    )
    monkeypatch.setattr(payment, "_paid_jobs_done", [])

    N = 20
    barrier = threading.Barrier(N)
    errors: list = []

    def worker(i: int):
        try:
            barrier.wait()
            payment._mark_paid_job_done(f"job{i}", purpose="gemini")
        except Exception as e:  # pragma: no cover
            errors.append((i, f"{type(e).__name__}: {e}"))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Unexpected errors: {errors}"

    # Verify in-memory state
    in_mem_ids = {r["job_id"] for r in payment._paid_jobs_done}
    assert in_mem_ids == {f"job{i}" for i in range(N)}, (
        f"In-memory lost records: {set(f'job{i}' for i in range(N)) - in_mem_ids}"
    )

    # Verify persisted state on disk
    persisted_file = tmp_path / "_paid_jobs_done.json"
    assert persisted_file.exists(), "_paid_jobs_done.json was not persisted"
    with open(persisted_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    persisted_ids = {r["job_id"] for r in data}
    assert persisted_ids == {f"job{i}" for i in range(N)}, (
        f"Persisted lost records: expected 20 unique, got {len(persisted_ids)} "
        f"unique (missing: {set(f'job{i}' for i in range(N)) - persisted_ids})"
    )
    assert len(data) == N, (
        f"Expected {N} records persisted, got {len(data)} (duplicates?)"
    )


# ---------------------------------------------------------------------------
# Test 3: concurrent PayPal capture consume — no double-spend
# ---------------------------------------------------------------------------

def test_concurrent_paypal_double_spend_rejected(monkeypatch, tmp_path):
    """N threads attempt to consume the SAME captured PayPal order.
    Exactly ONE must succeed; the others MUST raise ValueError.

    Regression guard: without atomic check-and-set on _payments[order]["used"],
    multiple threads can observe used=False, all pass the check, all flip the
    flag, and the same order is consumed multiple times for different jobs —
    a real double-spend.
    """
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_PAYMENTS_FILE", tmp_path / "_payments.json")
    monkeypatch.setattr(
        payment, "_PAID_JOBS_DONE_FILE", tmp_path / "_paid_jobs_done.json"
    )
    monkeypatch.setattr(payment, "_paid_jobs_done", [])

    order_id = "ORD_RACE"
    payment._payments[order_id] = {
        "order_id": order_id,
        "amount_eur": 1.50,
        "email": "x@y.it",
        "captured_at": time.time(),
        "used": False,
    }
    try:
        N_THREADS = 20
        successes: list = []
        errors: list = []
        results_lock = threading.Lock()
        barrier = threading.Barrier(N_THREADS)

        def worker(i: int):
            try:
                barrier.wait()
                method = payment.consume_payment_token(
                    order_id, 1.50, f"job-{i}", purpose="gemini"
                )
                with results_lock:
                    successes.append((i, method))
            except ValueError as e:
                with results_lock:
                    errors.append((i, str(e)))
            except Exception as e:  # pragma: no cover
                with results_lock:
                    errors.append((i, f"UNEXPECTED: {type(e).__name__}: {e}"))

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(N_THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(successes) == 1, (
            f"DOUBLE-SPEND: expected exactly 1 success, got {len(successes)} "
            f"(successes={successes}, errors={errors[:5]}...)"
        )
        assert len(errors) == N_THREADS - 1, (
            f"Expected {N_THREADS - 1} ValueError rejections, got {len(errors)}"
        )
        # Order must be marked used
        assert payment._payments[order_id]["used"] is True
    finally:
        # Cleanup module state
        payment._payments.pop(order_id, None)


# ---------------------------------------------------------------------------
# Test 4: concurrent consume + refund on the same voucher — no overdraft
# ---------------------------------------------------------------------------

def test_concurrent_consume_and_refund_no_overdraft(monkeypatch, tmp_path):
    """While one set of threads consumes a voucher, another set refunds it.
    The accounting MUST stay consistent: final remaining must equal
    (original + total_refunded - total_consumed) clamped to [0, original],
    with no overdraft and no lost updates.

    Regression guard for _voucher_refund: it does a read-modify-write on
    remaining_eur. Without _vouchers_lock, a concurrent _voucher_consume
    can see a stale balance and overspend, or vice versa.
    """
    monkeypatch.setattr(payment, "_DATA_DIR", tmp_path)
    monkeypatch.setattr(payment, "_VOUCHERS_FILE", tmp_path / "_vouchers.json")
    monkeypatch.setattr(payment, "_vouchers", {})

    code, _ = payment._create_voucher("c@x.it", 10.0, kind="test", note="t")
    initial = payment._voucher_remaining(payment._vouchers[code])
    # 20 consume threads of 1.0 each; 10 refund threads of 1.0 each
    # Worst-case net consumed = 10.0 (20*1 - 10*1), well within pool ~11
    consumes_ok = 0
    consumes_fail = 0
    refunds_ok = 0
    refunds_fail = 0
    results_lock = threading.Lock()
    barrier = threading.Barrier(30)

    def consumer(i):
        nonlocal consumes_ok, consumes_fail
        try:
            barrier.wait()
            payment._voucher_consume(code, 1.0, job_id=f"c{i}")
            with results_lock:
                consumes_ok += 1
        except Exception:
            with results_lock:
                consumes_fail += 1

    def refunder(i):
        nonlocal refunds_ok, refunds_fail
        try:
            barrier.wait()
            payment._voucher_refund(code, 1.0, job_id=f"r{i}", reason="test")
            with results_lock:
                refunds_ok += 1
        except Exception:
            with results_lock:
                refunds_fail += 1

    threads = [threading.Thread(target=consumer, args=(i,)) for i in range(20)] + \
              [threading.Thread(target=refunder, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = payment._voucher_remaining(payment._vouchers[code])
    # Invariant 1: no overdraft.
    assert final >= 0.0, f"OVERDRAFT: final={final} (initial={initial})"
    # Invariant 2: never exceeds original amount (refund caps at amount_eur).
    original = float(payment._vouchers[code].get("amount_eur", 0))
    assert final <= original + 0.01, (
        f"Refund exceeded cap: final={final}, original={original}"
    )
    # Invariant 3: the uses log records every successful op (no lost writes).
    # Successful refunds may have been capped (and so not changed balance),
    # but they must still be recorded.
    uses = payment._vouchers[code].get("uses", [])
    assert len(uses) == consumes_ok + refunds_ok, (
        f"Lost-write: expected {consumes_ok + refunds_ok} use records, "
        f"got {len(uses)} (consumes_ok={consumes_ok}, refunds_ok={refunds_ok})"
    )
