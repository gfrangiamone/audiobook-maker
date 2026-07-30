import importlib
import json
from datetime import datetime

import pytest


@pytest.fixture()
def fq(tmp_path, monkeypatch):
    """free_quota isolato: data dir temporanea, quota e floor deterministici."""
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "2.00")
    monkeypatch.setenv("ABM_PREMIUM_MIN_COST_EUR", "0.50")
    monkeypatch.setenv("ABM_GEMINI_FREE_THRESHOLD_EUR", "0.20")
    monkeypatch.setenv("ABM_SPEECHIFY_FREE_THRESHOLD_EUR", "0.30")
    import free_quota
    importlib.reload(free_quota)
    return free_quota


def test_consume_accumulates(fq):
    assert fq.consume("cid1", 0.30, "job1") == pytest.approx(0.30)
    assert fq.consume("cid1", 0.20, "job2") == pytest.approx(0.50)
    assert fq.used_eur("cid1") == pytest.approx(0.50)


def test_consume_is_idempotent_per_job(fq):
    fq.consume("cid1", 0.30, "job1")
    fq.consume("cid1", 0.30, "job1")
    assert fq.used_eur("cid1") == pytest.approx(0.30)


def test_clients_are_isolated(fq):
    fq.consume("cid1", 0.30, "job1")
    assert fq.used_eur("cid2") == pytest.approx(0.0)


def test_empty_client_id_uses_shared_bucket(fq):
    fq.consume("", 0.30, "job1")
    assert fq.used_eur("") == pytest.approx(0.30)


def test_used_eur_survives_missing_and_corrupt_file(fq, tmp_path):
    assert fq.used_eur("cid1") == pytest.approx(0.0)
    (tmp_path / "_free_quota.json").write_text("{not json", encoding="utf-8")
    assert fq.used_eur("cid1") == pytest.approx(0.0)


def test_used_eur_survives_schema_corruption_month_is_string(fq, tmp_path):
    path = tmp_path / "_free_quota.json"
    # Mese corrente è mappato a string invece di dict
    month = datetime.now().strftime("%Y-%m")
    path.write_text(json.dumps({month: "corrupted_value"}), encoding="utf-8")
    assert fq.used_eur("cid1") == pytest.approx(0.0)


def test_consume_repairs_schema_corruption_and_works(fq, tmp_path):
    path = tmp_path / "_free_quota.json"
    # Mese corrente è mappato a string (schema corrotto)
    month = datetime.now().strftime("%Y-%m")
    path.write_text(json.dumps({month: "corrupted_value"}), encoding="utf-8")
    # consume() deve riparare e funzionare correttamente
    total = fq.consume("cid1", 0.25, "job1")
    assert total == pytest.approx(0.25)
    assert fq.used_eur("cid1") == pytest.approx(0.25)


def test_prune_keeps_last_three_months(fq, tmp_path):
    path = tmp_path / "_free_quota.json"
    old = {m: {"cid1": {"eur": 1.0, "jobs": {}}}
           for m in ("2026-01", "2026-02", "2026-03", "2026-04")}
    path.write_text(json.dumps(old), encoding="utf-8")
    fq.consume("cid1", 0.10, "jobX")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert len(saved) == 3
    assert "2026-01" not in saved


def test_snapshot_reports_remaining(fq):
    fq.consume("cid1", 1.50, "job1")
    snap = fq.snapshot("cid1")
    assert snap["used_eur"] == pytest.approx(1.50)
    assert snap["limit_eur"] == pytest.approx(2.00)
    assert snap["remaining_eur"] == pytest.approx(0.50)
    assert snap["exhausted"] is False


def test_decision_above_threshold_is_untouched(fq):
    d = fq.decision("cid1", "gemini:flash31:Laomedeia", 1.20)
    assert d["due_eur"] == pytest.approx(1.20)
    assert d["is_free"] is False
    assert d["quota_exhausted"] is False
    assert fq.used_eur("cid1") == pytest.approx(0.0)   # decision non consuma


def test_decision_below_threshold_within_quota_is_free(fq):
    d = fq.decision("cid1", "gemini:flash31:Laomedeia", 0.15)
    assert d["due_eur"] == pytest.approx(0.0)
    assert d["is_free"] is True
    assert d["quota_exhausted"] is False


def test_decision_below_threshold_over_quota_charges_floor(fq):
    fq.consume("cid1", 1.95, "job1")
    d = fq.decision("cid1", "gemini:flash31:Laomedeia", 0.15)
    assert d["due_eur"] == pytest.approx(0.50)
    assert d["is_free"] is False
    assert d["quota_exhausted"] is True
    assert d["quota_used_eur"] == pytest.approx(1.95)
    assert d["quota_limit_eur"] == pytest.approx(2.00)


def test_decision_uses_speechify_threshold_for_speechify_voice(fq):
    voice = "speechify:simba-3.2:harper_32"
    assert fq.decision("cid1", voice, 0.25)["is_free"] is True      # 0.25 <= 0.30
    assert fq.decision("cid1", "gemini:flash31:X", 0.25)["is_free"] is False  # 0.25 > 0.20


def test_limit_zero_disables_quota(fq, monkeypatch):
    monkeypatch.setenv("ABM_FREE_QUOTA_EUR_PER_MONTH", "0")
    fq.consume("cid1", 5.00, "job1")
    d = fq.decision("cid1", "gemini:flash31:Laomedeia", 0.15)
    assert d["due_eur"] == pytest.approx(0.0)
    assert d["is_free"] is True
    assert d["quota_exhausted"] is False
