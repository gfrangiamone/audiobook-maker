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


# ---------------------------------------------------------------------------
# Identita' di quota legata all'installazione (app mobile): l'identificativo
# client dell'app si rigenera a ogni pulizia dei dati, il token push no.
# ---------------------------------------------------------------------------

def test_canonical_of_unknown_cid_is_itself():
    assert ftq.canonical("cid-sconosciuto") == "cid-sconosciuto"
    assert ftq.canonical("") == ftq._ANON


def test_link_device_first_registration_keeps_cid_canonical():
    assert ftq.link_device("hash-dev-1", "cid-primo") == "cid-primo"
    assert ftq.canonical("cid-primo") == "cid-primo"


def test_link_device_binds_quota_across_cid_rotation(monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "1000")
    ftq.link_device("hash-dev-1", "cid-vecchio")
    ftq.consume("cid-vecchio", 900, "j1")
    # Stessa installazione, identificativo nuovo: il contatore non riparte da zero.
    assert ftq.link_device("hash-dev-1", "cid-nuovo") == "cid-vecchio"
    assert ftq.canonical("cid-nuovo") == "cid-vecchio"
    assert ftq.used_chars("cid-nuovo") == 900
    assert not ftq.decision("cid-nuovo", 500, "j2")["allowed"]


def test_link_device_merges_chars_already_spent_by_the_new_cid(monkeypatch):
    monkeypatch.setenv("ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH", "1000")
    ftq.link_device("hash-dev-2", "cid-a")
    ftq.consume("cid-a", 300, "ja")
    ftq.consume("cid-b", 200, "jb")  # cid-b ha consumato prima del legame
    assert ftq.link_device("hash-dev-2", "cid-b") == "cid-a"
    assert ftq.used_chars("cid-b") == 500 and ftq.used_chars("cid-a") == 500
    assert ftq.job_charged("cid-b", "jb") and ftq.job_charged("cid-b", "ja")


def test_link_device_is_idempotent():
    assert ftq.link_device("hash-dev-3", "cid-x") == "cid-x"
    assert ftq.link_device("hash-dev-3", "cid-x") == "cid-x"
    ftq.consume("cid-x", 100, "j")
    assert ftq.link_device("hash-dev-3", "cid-x") == "cid-x"
    assert ftq.used_chars("cid-x") == 100


def test_alias_chain_stays_depth_one():
    """Il secondo device registrato dall'alias resta legato al canonico."""
    ftq.link_device("hash-d1", "cid-1")
    ftq.link_device("hash-d1", "cid-2")          # cid-2 -> alias di cid-1
    assert ftq.link_device("hash-d2", "cid-2") == "cid-1"
    ftq.link_device("hash-d2", "cid-3")          # cid-3 -> alias di cid-1
    assert ftq.canonical("cid-3") == "cid-1"


def test_consume_and_refund_follow_the_canonical_bucket():
    ftq.link_device("hash-dev-4", "cid-old")
    ftq.link_device("hash-dev-4", "cid-new")
    assert ftq.consume("cid-new", 400, "jx") == 400
    assert ftq.used_chars("cid-old") == 400
    assert ftq.refund("cid-old", "jx") == 400
    assert ftq.used_chars("cid-new") == 0


def test_link_device_never_raises_on_broken_state(monkeypatch, tmp_path):
    (tmp_path / "_free_tts_quota_ids.json").write_text("{not json", encoding="utf-8")
    assert ftq.link_device("hash-dev-5", "cid-q") == "cid-q"
    assert ftq.link_device("", "cid-q") == "cid-q"
    assert ftq.link_device("hash-dev-5", "") == ftq._ANON
