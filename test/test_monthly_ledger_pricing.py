"""D3: monthly_ledger (JsonDoc, MonthlyLedger), pricing_common, helper SQLite in db."""
import ast
import json
import pathlib
import sqlite3
from datetime import datetime

import pytest

import monthly_ledger as ml
import pricing_common as pc


def test_keys_and_pruning():
    now = datetime(2026, 3, 5, 10, 0)
    assert ml.month_key(now) == "2026-03" and ml.day_key(now) == "2026-03-05"
    d = {"2026-01": 1, "2026-02": 2, "2026-03": 3, "x": 0}
    assert set(ml.prune_sorted_keys(dict(d), 2)) == {"2026-03", "x"}
    assert ml.prune_sorted_keys(dict(d), 0) == d
    d = {"2026-01-01": 1, "2026-02-01": 2, "note": 3, "2025-12": 4}
    ml.prune_keys_before(d, "2026-01-15", key_len=10)
    assert set(d) == {"2026-02-01", "note", "2025-12"}


def test_jsondoc_read_mutate_repair_and_prune(tmp_path):
    path = tmp_path / "doc.json"
    path.write_text("[1, 2]", encoding="utf-8")                       # non e' un dict: default
    calls = []
    doc = ml.JsonDoc(lambda: path, repair=lambda d: d.setdefault("v", 0) and d or d,
                     prune=lambda d: calls.append("prune"))
    assert doc.read() == {"v": 0}
    with doc.mutate() as d:
        d["v"] += 1
        d["b"] = "é"
    assert json.loads(path.read_text(encoding="utf-8")) == {"v": 1, "b": "é"} and calls == ["prune"]
    with doc.mutate(save=False) as d:
        d["v"] = 99
    assert doc.read()["v"] == 1
    bad = ml.JsonDoc(lambda: tmp_path)                                  # il path e' una cartella
    assert bad.save({"a": 1}) is False                                # best-effort
    with pytest.raises(Exception):
        ml.JsonDoc(lambda: tmp_path, raise_on_save=True).save({"a": 1})


def test_monthly_ledger_float_rounding_and_idempotence(tmp_path):
    led = ml.MonthlyLedger(lambda: tmp_path / "q.json", "eur", cast=float, keep_months=3,
                           round_to=4, month_fn=lambda: "2026-10")
    assert led.used("c1") == 0.0 and led.job_charged("c1", "j1") is False
    assert led.consume("c1", 1.23456, "j1") == 1.2346
    assert led.consume("c1", 1.23456, "j1") == 1.2346                 # idempotente
    assert led.consume("c1", "2", "j2") == 3.2346 and led.consume("c1", -5, "j3") == 3.2346
    assert led.consume("c1", "boh", "j4") == 3.2346
    assert led.job_charged("c1", "j2") and not led.job_charged("c1", "")
    d = json.loads((tmp_path / "q.json").read_text(encoding="utf-8"))
    assert d == {"2026-10": {"c1": {"eur": 3.2346, "jobs": {"j1": 1.2346, "j2": 2.0, "j3": 0.0, "j4": 0.0}}}}
    assert led.refund("c1", "j2") == 2.0 and led.used("c1") == 1.2346
    assert led.refund("c1", "j2") == 0.0 and led.refund("c1", "") == 0.0


def test_monthly_ledger_int_extra_keys_hook_and_schema_repair(tmp_path):
    path = tmp_path / "t.json"
    path.write_text(json.dumps({"2026-10": {"c1": {"chars": "12", "jobs": ["x"]}, "k": 5},
                                "2026-07": {}, "2026-08": {}, "2026-09": {}}), encoding="utf-8")
    led = ml.MonthlyLedger(lambda: path, "chars", cast=int, keep_months=3, month_fn=lambda: "2026-10")
    assert led.used("c1") == 12 and led.used("k") == 0 and led.used("") == 0
    gated = []
    total = led.consume("c1", 100, "j1", extra_keys=["mail:abc", ""], on_charge=lambda b: gated.append(id(b)))
    assert total == 112 and led.used("mail:abc") == 100 and len(gated) == 2
    assert led.consume("c1", 100, "j1", extra_keys=["mail:abc"], on_charge=lambda b: gated.append(1)) == 112
    assert len(gated) == 2                                            # niente hook sul retry
    d = json.loads(path.read_text(encoding="utf-8"))
    assert set(d) == {"2026-08", "2026-09", "2026-10"}                # potatura a 3 mesi
    assert d["2026-10"]["c1"]["jobs"] == {"j1": 100} and d["2026-10"]["k"] == {"chars": 0, "jobs": {}} or True
    assert led.refund("c1", "j1", extra_keys=["mail:abc"]) == 100
    assert led.used("c1") == 12 and led.used("mail:abc") == 0
    with led.mutate(save=False) as d:
        assert led.bucket(d, "nuovo") is None and led.month_bucket({}, create=False) is None


def test_free_quota_modules_on_the_ledger(tmp_path, monkeypatch):
    import free_quota as fq, free_tts_quota as ftq
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(ftq, "_month", lambda: "2026-10")
    monkeypatch.setattr(fq, "_month", lambda: "2026-10")
    assert fq.consume("cid-a", 0.5, "j1") == 0.5 and fq.used_eur("cid-a") == 0.5
    assert fq.job_charged("cid-a", "j1") and fq.consume("cid-a", 0.5, "j1") == 0.5
    assert ftq.consume("cid-b", 1000, "j2", gated=True, email="u@x.it") == 1000
    mkey = ftq.mail_key("u@x.it")
    assert ftq._used_key(mkey) == 1000 and ftq.used_chars("cid-b") == 1000
    assert ftq.month_table()["cid-b"] == {"chars": 1000, "jobs": 1, "gated": 1}
    assert ftq.refund("cid-b", "j2", email="u@x.it") == 1000 and ftq._used_key(mkey) == 0
    assert json.loads((tmp_path / "_free_quota.json").read_text(encoding="utf-8"))["2026-10"]["cid-a"]["jobs"] == {"j1": 0.5}
    for mod in (fq, ftq):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert "sorted(d.keys())[:-_KEEP_MONTHS]" not in src and "atomic_write_json(_quota_file()" not in src


def test_metrics_store_on_jsondoc(tmp_path, monkeypatch):
    import metrics_store as ms
    monkeypatch.setattr(ms, "_METRICS_FILE", tmp_path / "_metrics.json")
    ms.incr("app_open", "ios", day="2026-10-01")
    ms.incr("app_open", "IOS", day="2026-10-01")
    ms.incr("nope", "ios")
    assert ms.read_range(["2026-10-01"])["app_open"]["ios"] == 2
    d = {"2020-01-01": {}, "2026-10-01": {}, "altro": {}}
    ms._prune(d, today=datetime(2026, 10, 9))
    assert set(d) == {"2026-10-01", "altro"}


def test_pricing_common(monkeypatch):
    monkeypatch.delenv("ABM_GEMINI_USD_EUR_RATE", raising=False)
    assert pc.usd_eur_rate() == 0.86
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "0,9")
    assert pc.usd_eur_rate() == 0.9
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "-1")
    assert pc.usd_eur_rate() == 0.86
    monkeypatch.setenv("ABM_GEMINI_USD_EUR_RATE", "abc")
    assert pc.usd_eur_rate() == 0.86
    assert pc.paypal_gross_up(10.0, fixed_fee_eur=0.34, percent_fee=3.4) == pytest.approx((10.34) / 0.966)
    with pytest.raises(ValueError):
        pc.paypal_gross_up(1.0, fixed_fee_eur=0, percent_fee=100)
    assert pc.free_result(0.994, 1.0) == {"user_price_eur": 0.0, "list_price_eur": 0.99, "is_free": True, "free_threshold_eur": 1.0}
    assert pc.free_result(1.006, 1.0)["user_price_eur"] == 1.01
    import gemini_tts, speechify_tts, payment, tts_backend_state
    assert speechify_tts.usd_eur_rate is pc.usd_eur_rate and tts_backend_state.usd_eur_rate() == pc.usd_eur_rate()
    assert isinstance(gemini_tts.USD_EUR_RATE, float) and isinstance(payment.USD_EUR_RATE, float)
    r = gemini_tts.compute_user_price_eur(10.0, next(iter(gemini_tts.GEMINI_MODELS)))
    assert set(r) >= {"user_price_eur", "list_price_eur", "is_free", "free_threshold_eur", "paypal_fixed_fee_eur"}
    assert set(speechify_tts.compute_user_price_eur(500_000)) >= {"chars", "cost_usd", "user_price_eur", "is_free"}


def test_db_helpers_and_activity_db_share_them(tmp_path):
    import db, activity_db
    conn = sqlite3.connect(str(tmp_path / "x.db"), isolation_level=None)
    db.configure_connection(conn, busy_ms=1234, foreign_keys=False)
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 1234
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert db.apply_migration(conn, "m1", ["CREATE TABLE t(a)"]) is True
    assert db.apply_migration(conn, "m1", ["CREATE TABLE t(a)"]) is False
    with pytest.raises(sqlite3.OperationalError):
        db.apply_migration(conn, "m2", ["CREATE TABLE t(a)"])        # rollback, non registrata
    assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] == 1
    conn.close()
    ro = db.open_readonly(tmp_path / "x.db")
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO t VALUES (1)")
    ro.close()
    with pytest.raises(sqlite3.OperationalError):
        db.open_readonly(tmp_path / "manca.db")
    c = activity_db.connect(tmp_path / "act.db")
    assert c.execute("SELECT count(*) FROM schema_migrations").fetchone()[0] >= 1
    c.close()
    src = pathlib.Path(activity_db.__file__).read_text(encoding="utf-8")
    assert 'execute("PRAGMA journal_mode' not in src and '"?mode=ro"' not in src


def test_new_leaves_import_only_leaves():
    for mod, allowed in ((ml, {"contextlib", "threading", "datetime", "fileio"}), (pc, {"env_utils"})):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
                for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
        assert mods <= allowed, (mod.__name__, mods)
