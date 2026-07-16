import importlib
import json


def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import translation_cost_audit
    importlib.reload(translation_cost_audit)
    return translation_cost_audit


def test_append_and_iter_all(tmp_path, monkeypatch):
    m = _fresh(tmp_path, monkeypatch)
    m.append_record({"job_id": "A", "source_lang": "it", "target_lang": "en",
                     "model_key": "gemini-2.5-flash", "outcome": "completed"})
    m.append_record({"job_id": "B", "source_lang": "fr", "target_lang": "de",
                     "model_key": "deepseek-chat", "outcome": "failed_refunded"})
    recs = list(m.iter_records())
    assert {r["job_id"] for r in recs} == {"A", "B"}
    assert all("ts" in r for r in recs)  # ts auto-set


def test_iter_filters(tmp_path, monkeypatch):
    m = _fresh(tmp_path, monkeypatch)
    m.append_record({"job_id": "A", "source_lang": "it", "target_lang": "en",
                     "model_key": "gemini-2.5-flash", "outcome": "completed",
                     "ts": "2026-07-10T00:00:00+00:00"})
    m.append_record({"job_id": "B", "source_lang": "it", "target_lang": "de",
                     "model_key": "deepseek-chat", "outcome": "completed",
                     "ts": "2026-07-15T00:00:00+00:00"})
    assert [r["job_id"] for r in m.iter_records(target_lang="en")] == ["A"]
    assert [r["job_id"] for r in m.iter_records(source_lang="it", model="deepseek-chat")] == ["B"]
    assert [r["job_id"] for r in m.iter_records(date_from="2026-07-12")] == ["B"]
    assert [r["job_id"] for r in m.iter_records(date_to="2026-07-12")] == ["A"]


def test_iter_skips_malformed(tmp_path, monkeypatch):
    m = _fresh(tmp_path, monkeypatch)
    m.append_record({"job_id": "A", "outcome": "completed"})
    fp = next(tmp_path.glob("translation_cost_audit_*.jsonl"))
    with open(fp, "a", encoding="utf-8") as f:
        f.write("{not json}\n\n")
    recs = list(m.iter_records())
    assert [r["job_id"] for r in recs] == ["A"]
