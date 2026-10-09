"""D1: jsonl_audit.MonthlyJsonl, wrapper *_cost_audit, helper dei judge in semantic_judge."""
import ast
import json
import pathlib
from datetime import datetime, timezone

import pytest

import jsonl_audit
from jsonl_audit import MonthlyJsonl


def test_append_iter_filters_and_dates(tmp_path):
    st = MonthlyJsonl("t_audit", lambda: tmp_path)
    st.append({"job_id": "A", "outcome": "completed", "model_key": "m1", "ts": "2026-07-10T10:00:00+00:00"})
    st.append({"job_id": "B", "outcome": "failed", "model_key": "m2", "ts": "2026-07-12T10:00:00+00:00"})
    st.append({"job_id": "C", "outcome": "completed", "model_key": "m2"})      # ts aggiunto adesso
    fp = st.path()
    assert fp.name == f"t_audit_{jsonl_audit.month_now()}.jsonl" and fp.exists()
    lines = fp.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3 and '"job_id":"A"' in lines[0]                      # compact
    assert json.loads(lines[2])["ts"][:4] == str(datetime.now(timezone.utc).year)
    ids = lambda **kw: [r["job_id"] for r in st.iter(**kw)]
    assert ids() == ["A", "B", "C"]
    assert ids(outcome="completed") == ["A", "C"]
    assert ids(filters={"model_key": "m2"}) == ["B", "C"]
    assert ids(filters={"model_key": None, "language": ""}) == ["A", "B", "C"]   # falsy ignorati
    assert ids(date_from="2026-07-12", date_to="2026-07-12") == ["B"]
    assert ids(date_to="2026-07-10") == ["A"]
    assert ids(month="1999-01") == [] and ids(month=jsonl_audit.month_now()) == ["A", "B", "C"]


def test_iter_skips_garbage_and_missing_dir(tmp_path):
    st = MonthlyJsonl("g", lambda: tmp_path / "manca")
    assert list(st.iter()) == []
    st = MonthlyJsonl("g", lambda: tmp_path)
    (tmp_path / "g_2026-01.jsonl").write_text('\n{"a":1}\nnope\n[1,2]\n\n{"a":2}\n', encoding="utf-8")
    assert [r["a"] for r in st.iter()] == [1, 2]


def test_append_many_non_compact_ascii_and_require_dir(tmp_path):
    st = MonthlyJsonl("j", lambda: tmp_path / "sub", compact=False, require_dir=True)
    assert st.append({"x": "é"}) is False and not (tmp_path / "sub").exists()
    (tmp_path / "sub").mkdir()
    assert st.append_many([{"x": "é"}, {"x": 2}], add_ts=False) is True
    txt = (tmp_path / "sub" / f"j_{jsonl_audit.month_now()}.jsonl").read_text(encoding="utf-8")
    assert txt == '{"x": "é"}\n{"x": 2}\n'
    st2 = MonthlyJsonl("k", lambda: tmp_path, ascii=True)
    st2.append({"x": "é"}, month="2025-03", add_ts=False)
    assert (tmp_path / "k_2025-03.jsonl").read_text(encoding="utf-8") == '{"x":"\\u00e9"}\n'
    assert st2.append_many([]) is True


def test_purge_keeps_recent_months(tmp_path):
    st = MonthlyJsonl("p", lambda: tmp_path)
    for ym in ("2025-01", "2025-11", "2025-12", "2026-01", "junk"):
        (tmp_path / f"p_{ym}.jsonl").write_text("{}\n", encoding="utf-8")
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    assert st.purge(0, now=now) == []
    removed = {p.name for p in st.purge(2, now=now)}
    assert removed == {"p_2025-01.jsonl", "p_2025-11.jsonl"}
    assert sorted(p.name for p in tmp_path.glob("p_*.jsonl")) == ["p_2025-12.jsonl", "p_2026-01.jsonl", "p_junk.jsonl"]


def test_cost_audit_modules_read_env_per_call(tmp_path, monkeypatch):
    import gemini_cost_audit as g, translation_cost_audit as t, optimization_cost_audit as o
    for mod in (g, t, o):
        monkeypatch.setattr(mod, "_DATA_DIR", None)
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path / "one"))
    g.append_record({"job_id": "x", "model_key": "m", "language": "it", "outcome": "completed",
                     "user_price_eur_charged": 2, "google_cost_eur_actual": 0.5, "delta_eur": 0.1})
    t.append_record({"job_id": "y", "source_lang": "it", "target_lang": "en"})
    o.append_record({"job_id": "z", "model_key": "deepseek-chat", "language": "fr"})
    assert (tmp_path / "one" / g._current_file().name).exists()
    assert [r["job_id"] for r in g.iter_records(model="m", language="it")] == ["x"]
    assert [r["job_id"] for r in t.iter_records(source_lang="it", target_lang="en")] == ["y"]
    assert [r["job_id"] for r in o.iter_records(model="deepseek-chat")] == ["z"] and list(o.iter_records(model="altro")) == []
    assert g.aggregate(model="m")["count"] == 1 and g.aggregate()["margin_eur"] == 1.5
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path / "two"))
    assert list(g.iter_records()) == []                     # la cartella si rilegge a ogni chiamata
    monkeypatch.setattr(g, "_DATA_DIR", tmp_path / "one")   # override esplicito (fixture dei test)
    assert len(list(g.iter_records())) == 1


def test_semantic_judge_helpers(monkeypatch, tmp_path, capsys):
    import semantic_judge as sj
    monkeypatch.setenv("ABM_X_MODE", "Recover")
    assert sj.mode_from_env("ABM_X_MODE", ("off", "observe", "recover", "on"), "observe") == "recover"
    monkeypatch.setenv("ABM_X_MODE", "typo")
    assert sj.mode_from_env("ABM_X_MODE", ("off", "on"), "observe") == "observe"
    assert sj.clip("abc", 10) == "abc" and sj.clip("  abcdefgh  ", 4) == "abcd [...]"
    assert sj.clip("abcdefgh", 3, marker="…") == "abc…"
    assert sj.clip("abcdefghij", 3, 2) == "abc\n[...]\nij"
    assert sj.probs(None, ["a"]) == {}

    class R:
        nouls = {"a": type("N", (), {"noul": 0.25})(), "b": None}
    assert sj.probs(R(), ["a", "b", "c"]) == {"a": 0.25}
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path / "assente"))
    assert sj.append_monthly_audit("x_audit", {"k": 1}) is False
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    assert sj.append_monthly_audit("x_audit", {"k": "é"}) is True
    txt = (tmp_path / f"x_audit_{jsonl_audit.month_now()}.jsonl").read_text(encoding="utf-8")
    assert txt.startswith('{"k": "é"') and '"ts": "' in txt
    monkeypatch.delenv("ABM_DATA_DIR")
    assert sj.append_monthly_audit("x_audit", {"k": 1}) is False
    assert "audit non scritto" not in capsys.readouterr().out


def test_judges_share_the_skeleton():
    import section_judge, translation_judge, transcript_judge, llm_output_judge, voice_language_guard
    for mod in (section_judge, translation_judge, transcript_judge, llm_output_judge, voice_language_guard):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        assert "_audit_path" not in src and 'open(path, "a"' not in src, mod.__name__
        assert "sj.mode_from_env(" in src and "sj.append_monthly_audit(" in src, mod.__name__
    assert translation_judge._clip("x" * 2000).count("[...]") == 1
    assert transcript_judge._clip("y" * 5000).endswith(" [...]")
    assert section_judge._excerpt("z" * 1000).endswith("…")


def test_jsonl_audit_is_a_leaf():
    src = pathlib.Path(jsonl_audit.__file__).read_text(encoding="utf-8")
    mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
            for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
    assert mods <= {"json", "threading", "datetime", "pathlib", "fileio"}
