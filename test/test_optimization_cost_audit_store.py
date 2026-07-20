import importlib


def _fresh_module(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    import optimization_cost_audit
    importlib.reload(optimization_cost_audit)
    return optimization_cost_audit


def test_append_and_iter(tmp_path, monkeypatch):
    m = _fresh_module(tmp_path, monkeypatch)
    m.append_record({"job_id": "A", "language": "it", "outcome": "completed"})
    m.append_record({"job_id": "B", "language": "en", "outcome": "failed_refunded"})
    recs = list(m.iter_records())
    assert {r["job_id"] for r in recs} == {"A", "B"}
    assert all("ts" in r for r in recs)  # ts auto-aggiunto


def test_iter_filters(tmp_path, monkeypatch):
    m = _fresh_module(tmp_path, monkeypatch)
    m.append_record({"job_id": "A", "language": "it", "outcome": "completed"})
    m.append_record({"job_id": "B", "language": "en", "outcome": "completed"})
    assert [r["job_id"] for r in m.iter_records(language="it")] == ["A"]
    assert [r["job_id"] for r in m.iter_records(outcome="completed")] == ["A", "B"]
    assert list(m.iter_records(language="fr")) == []


def test_iter_date_filter(tmp_path, monkeypatch):
    m = _fresh_module(tmp_path, monkeypatch)
    m.append_record({"job_id": "A", "ts": "2026-01-05T10:00:00+00:00"})
    m.append_record({"job_id": "B", "ts": "2026-07-20T10:00:00+00:00"})
    got = [r["job_id"] for r in m.iter_records(date_from="2026-06-01")]
    assert got == ["B"]
