"""D1 retention (2026-10-09): 48 mesi per gli audit di costo, 6 per judge, leak
LLM, code tagliate e metriche di carico; purge_all() giornaliera nel
campionatore del carico."""
import inspect
from datetime import datetime, timezone

import pytest

import jsonl_audit
from jsonl_audit import MonthlyJsonl


@pytest.fixture
def registry(monkeypatch):
    saved = list(jsonl_audit._STORES)
    yield jsonl_audit._STORES
    jsonl_audit._STORES[:] = saved


def _touch(d, prefix, months):
    for ym in months:
        (d / f"{prefix}_{ym}.jsonl").write_text("{}\n", encoding="utf-8")


def test_keep_months_registers_and_purge_all_respects_each_retention(tmp_path, registry):
    jsonl_audit._STORES[:] = []
    cost = MonthlyJsonl("c", lambda: tmp_path, keep_months=lambda: 3)
    judge = MonthlyJsonl("j", lambda: tmp_path, keep_months=1)
    reader = MonthlyJsonl("c", lambda: tmp_path)                       # lettore: non registrato
    broken = MonthlyJsonl("b", lambda: None, keep_months=2)            # cartella non configurata
    assert registry == [cost, judge, broken] and reader not in registry
    again = MonthlyJsonl("j", lambda: tmp_path, keep_months=1)         # reload: sostituisce, non duplica
    assert registry == [cost, broken, again]
    jsonl_audit._STORES[:] = [cost, judge, broken]
    _touch(tmp_path, "c", ("2025-09", "2025-10", "2025-11", "2026-01"))
    _touch(tmp_path, "j", ("2025-12", "2026-01"))
    now = datetime(2026, 1, 15, tzinfo=timezone.utc)
    gone = jsonl_audit.purge_all(now=now)
    assert {k: sorted(p.name for p in v) for k, v in gone.items()} == {
        "c": ["c_2025-09.jsonl", "c_2025-10.jsonl"], "j": ["j_2025-12.jsonl"]}
    assert sorted(p.name for p in tmp_path.glob("*.jsonl")) == ["c_2025-11.jsonl", "c_2026-01.jsonl", "j_2026-01.jsonl"]
    assert jsonl_audit.purge_all(now=now) == {}


def test_defaults_from_env(monkeypatch):
    monkeypatch.delenv("ABM_COST_AUDIT_KEEP_MONTHS", raising=False)
    monkeypatch.delenv("ABM_AUDIT_KEEP_MONTHS", raising=False)
    assert jsonl_audit.cost_keep_months() == 48 and jsonl_audit.audit_keep_months() == 6
    monkeypatch.setenv("ABM_COST_AUDIT_KEEP_MONTHS", "0")
    monkeypatch.setenv("ABM_AUDIT_KEEP_MONTHS", "-3")
    assert jsonl_audit.cost_keep_months() == 0 and jsonl_audit.audit_keep_months() == 0   # 0 = mai purgare
    import load_metrics
    assert inspect.getsource(load_metrics).count('"ABM_LOAD_METRICS_RETENTION_MONTHS", "6"') == 1


def test_every_writer_is_registered_with_the_right_policy():
    import gemini_cost_audit, translation_cost_audit, optimization_cost_audit
    import semantic_judge, generation_engine, gemini_tts, voxcpm_digest
    for mod in (gemini_cost_audit, translation_cost_audit, optimization_cost_audit):
        assert mod._store.keep_months is jsonl_audit.cost_keep_months and mod._store in jsonl_audit._STORES
    for p in semantic_judge.AUDIT_PREFIXES:
        st = semantic_judge._audit_stores[p]
        assert st in jsonl_audit._STORES and st.keep_months is semantic_judge._audit_keep
    for st in (generation_engine._llm_leak_audit, generation_engine._code_tagliate_store):
        assert st in jsonl_audit._STORES and st.keep_months is jsonl_audit.audit_keep_months
    # Lettori secondari sullo stesso prefisso: non registrati (niente doppia purge).
    assert gemini_tts._cost_audit not in jsonl_audit._STORES
    assert voxcpm_digest._code_tagliate not in jsonl_audit._STORES
    assert len({st.prefix for st in jsonl_audit._STORES}) == len(jsonl_audit._STORES)


def test_judge_retention_is_off_without_data_dir(monkeypatch, tmp_path):
    import semantic_judge
    monkeypatch.delenv("ABM_DATA_DIR", raising=False)
    assert semantic_judge._audit_keep() == 0
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_AUDIT_KEEP_MONTHS", "2")
    assert semantic_judge._audit_keep() == 2
    _touch(tmp_path, "section_judge_audit", ("2025-01", "2026-01"))
    gone = jsonl_audit.purge_all(now=datetime(2026, 1, 15, tzinfo=timezone.utc))
    assert [p.name for p in gone["section_judge_audit"]] == ["section_judge_audit_2025-01.jsonl"]


def test_sampler_runs_purge_all_daily():
    import audiobook_app as app
    src = inspect.getsource(app._load_metrics_sampler)
    assert "load_metrics.purge()" in src and "jsonl_audit.purge_all()" in src
    assert src.index("load_metrics.purge()") < src.index("jsonl_audit.purge_all()")
