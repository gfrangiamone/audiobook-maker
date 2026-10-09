"""D2b: retry_util (retry_call, backoff, status transitori, Retry-After)."""
import asyncio
import ast
import pathlib
import types

import pytest

import retry_util as ru


def test_backoff_and_transient_status():
    assert [ru.backoff(a) for a in range(4)] == [1.0, 2.0, 4.0, 8.0]
    assert [ru.backoff(a, base=2, cap=60) for a in range(7)] == [2, 4, 8, 16, 32, 60, 60]
    assert ru.backoff(3, base=20) == 160.0
    for s in (429, 500, 502, 503, 504, 599):
        assert ru.is_transient_http(s)
    for s in (200, 400, 401, 403, 404, "x"):
        assert not ru.is_transient_http(s)
    assert ru.is_transient_http(None) and not ru.is_transient_http(None, none_is_transient=False)


def test_parse_retry_after_values_and_messages():
    assert ru.parse_retry_after(None) is None and ru.parse_retry_after("") is None
    assert ru.parse_retry_after("12") == 12.0 and ru.parse_retry_after(2.5) == 2.5
    assert ru.parse_retry_after("-3") == 0.0
    assert ru.parse_retry_after("429 ... retryDelay: 22371s") == 22371.0
    assert ru.parse_retry_after("quota exceeded, retry in 6h12m51.7s") == 6 * 3600 + 12 * 60 + 51.7
    assert ru.parse_retry_after("please retry in 5s") == 5.0
    assert ru.parse_retry_after("Wed, 21 Oct 2026 07:28:00 GMT") is None


def test_retry_after_from_error_details():
    err = types.SimpleNamespace(details=[{"retryDelay": "30s"}])
    assert ru.retry_after_from_error(err) == 30.0
    err = types.SimpleNamespace(details=[types.SimpleNamespace(retry_delay=types.SimpleNamespace(seconds=7))])
    assert ru.retry_after_from_error(err) == 7.0
    assert ru.retry_after_from_error(RuntimeError("429 retry in 3s")) == 3.0
    assert ru.retry_after_from_error(RuntimeError("boom")) is None
    assert ru.retry_after_from_error(types.SimpleNamespace(details=5)) is None


def test_retry_call_counts_waits_and_predicate():
    calls, waits, seen = [], [], []

    def fn(attempt):
        calls.append(attempt)
        if attempt < 2:
            raise ConnectionError(f"net {attempt}")
        return "ok"

    out = ru.retry_call(fn, attempts=4, wait=1.0, sleep=waits.append,
                        on_retry=lambda a, e, s: seen.append((a, str(e), s)))
    assert out == "ok" and calls == [0, 1, 2] and waits == [1.0, 2.0]
    assert seen == [(0, "net 0", 1.0), (1, "net 1", 2.0)]

    calls.clear(); waits.clear()
    with pytest.raises(ConnectionError):
        ru.retry_call(lambda a: (_ for _ in ()).throw(ConnectionError("x")), attempts=3, sleep=waits.append)
    assert waits == [1.0, 2.0]                                   # 3 tentativi, 2 attese

    class Fatal(Exception):
        pass

    calls.clear(); waits.clear()

    def fatal(attempt):
        calls.append(attempt)
        raise Fatal("no")

    with pytest.raises(Fatal):
        ru.retry_call(fatal, attempts=5, is_retryable=lambda e: not isinstance(e, Fatal), sleep=waits.append)
    assert calls == [0] and waits == []
    with pytest.raises(ru.GiveUp):
        ru.retry_call(lambda a: (_ for _ in ()).throw(ru.GiveUp()), attempts=5, sleep=waits.append)
    assert waits == []
    assert ru.retry_call(lambda a: a, attempts=0) == 0                  # almeno un tentativo


def test_retry_call_custom_wait_and_no_sleep_on_zero():
    waits = []
    with pytest.raises(ValueError):
        ru.retry_call(lambda a: (_ for _ in ()).throw(ValueError()), attempts=3,
                      wait=lambda a, e: [0, 7][a], sleep=waits.append)
    assert waits == [7]                                            # 0 secondi: nessuna sleep


def test_retry_call_async():
    calls, waits = [], []

    async def fn(attempt):
        calls.append(attempt)
        if attempt == 0:
            raise TimeoutError()
        return "done"

    async def sleep(s):
        waits.append(s)

    out = asyncio.run(ru.retry_call_async(fn, attempts=3, wait=2.0, sleep=sleep))
    assert out == "done" and calls == [0, 1] and waits == [2.0]

    async def always(attempt):
        raise TimeoutError("t")

    with pytest.raises(TimeoutError):
        asyncio.run(ru.retry_call_async(always, attempts=2, sleep=sleep))
    assert waits == [2.0, 1.0]


def test_retry_util_is_a_leaf():
    src = pathlib.Path(ru.__file__).read_text(encoding="utf-8")
    mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert mods <= {"asyncio", "re", "time"}
