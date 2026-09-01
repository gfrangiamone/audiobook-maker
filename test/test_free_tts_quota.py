"""Quota mensile di caratteri per client sulle voci STANDARD (free_tts_quota.py)."""
import json

import pytest

import free_tts_quota as ftq

CID = "cid-ftq-unit"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", raising=False)
    yield


def test_limit_default_and_env_parsing(monkeypatch):
    assert ftq.limit_chars() == ftq.DEFAULT_LIMIT_CHARS == 10_000_000
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "2_500_000")
    assert ftq.limit_chars() == 2_500_000
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "0")
    assert ftq.limit_chars() == 0
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "garbage")
    assert ftq.limit_chars() == ftq.DEFAULT_LIMIT_CHARS


def test_decision_allows_within_limit_and_blocks_beyond(monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "1000")
    d = ftq.decision(CID, 600, "j1")
    assert d["allowed"] and not d["exhausted"] and d["remaining_chars"] == 1000
    assert ftq.consume(CID, 600, "j1") == 600
    d = ftq.decision(CID, 500, "j2")
    assert not d["allowed"] and d["exhausted"]
    assert d["used_chars"] == 600 and d["limit_chars"] == 1000 and d["chars"] == 500
    # Esattamente al limite: consentito.
    assert ftq.decision(CID, 400, "j3")["allowed"]


def test_decision_same_job_retry_stays_allowed(monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "1000")
    ftq.consume(CID, 900, "j1")
    assert not ftq.decision(CID, 900, "j-other")["allowed"]
    assert ftq.decision(CID, 900, "j1")["allowed"], "retry dello stesso job gia' addebitato"


def test_consume_is_idempotent_per_job_and_refund_reverts():
    assert ftq.consume(CID, 100, "j1") == 100
    assert ftq.consume(CID, 100, "j1") == 100, "doppio consume dello stesso job non raddoppia"
    assert ftq.consume(CID, 50, "j2") == 150
    assert ftq.refund(CID, "j1") == 100
    assert ftq.used_chars(CID) == 50
    assert ftq.refund(CID, "j1") == 0, "refund ripetuto e' no-op"
    assert ftq.refund(CID, "mai-visto") == 0


def test_gated_counter_and_month_table():
    ftq.consume(CID, 100, "j1")
    ftq.consume(CID, 200, "j2", gated=True)
    ftq.consume("altro", 5, "j3")
    tbl = ftq.month_table()
    assert tbl[CID] == {"chars": 300, "jobs": 2, "gated": 1}
    assert tbl["altro"] == {"chars": 5, "jobs": 1, "gated": 0}


def test_feature_off_never_blocks(monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "0")
    ftq.consume(CID, 10**9, "j1")
    d = ftq.decision(CID, 10**9, "j2")
    assert d["allowed"] and not d["exhausted"] and d["limit_chars"] == 0
    assert ftq.snapshot(CID)["exhausted"] is False


def test_anonymous_client_shares_one_bucket():
    ftq.consume("", 10, "j1")
    ftq.consume(None, 20, "j2")
    assert ftq.used_chars("") == 30 and ftq.used_chars(None) == 30


def test_corrupt_file_is_tolerated(tmp_path):
    (tmp_path / "_free_tts_quota.json").write_text("{not json", encoding="utf-8")
    assert ftq.used_chars(CID) == 0
    assert ftq.consume(CID, 7, "j1") == 7
    data = json.loads((tmp_path / "_free_tts_quota.json").read_text(encoding="utf-8"))
    assert ftq._month() in data
