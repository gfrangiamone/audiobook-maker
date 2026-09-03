"""abuse_watch: dossier a due livelli, segnali S1-S4, verdetti e blocco."""
import json
import time

import pytest

import abuse_watch as aw


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "admin@example.com")
    for k in ("ABM_ABUSE_LLM_CONFIDENCE", "ABM_ABUSE_KEEP_HOURS", "ABM_ABUSE_GATE_DAILY",
              "ABM_ABUSE_CHARS_DAILY", "ABM_ABUSE_VERDICT_TTL_DAYS"):
        monkeypatch.delenv(k, raising=False)
    return tmp_path


def _gen(group, cid, chars=1000, voice="zh-CN-XiaoxiaoNeural", fn="book.epub", lang="zh"):
    aw.record_event(group, cid, "generate",
                    {"chars": chars, "voice": voice, "filename": fn, "lang": lang})


def test_group_key_hashes_the_slash24(env):
    a = aw.group_key("1.2.3.4", "c1")
    assert a.startswith("net:") and len(a) == 4 + 16
    assert a == aw.group_key("1.2.3.250", "c2")
    assert a != aw.group_key("1.2.4.4", "c1")
    assert "1.2.3" not in a
    assert aw.group_key("", "cidX") == "cid:cidX"
    assert aw.group_key("not-an-ip", "cidY") == "cid:cidY"
    assert aw.group_key("2001:db8:1:2:3:4:5:6", "c") == aw.group_key("2001:db8:1:2:ffff::1", "c")


def test_record_event_two_levels_and_hashed_identifiers(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a", chars=100, fn="Secret Title.epub")
    _gen(g, "b", chars=50, fn="Other.epub")
    aw.record_event(g, "a", "email", {"email": "Someone@Example.com"})
    aw.record_event(g, "a", "quota_block", {"chars": 100})
    d = aw.dossier(g)
    assert d["all"]["generate"] == 2 and d["all"]["chars"] == 150
    assert d["all"]["quota_block"] == 1 and d["all"]["email"] == 1
    assert set(d["cids"]) == {"a", "b"}
    assert d["cids"]["a"]["chars"] == 100 and d["cids"]["b"]["generate"] == 1
    assert len(d["all"]["files"]) == 2 and len(d["all"]["emails"]) == 1
    assert d["all"]["voices"] == {"zh-CN-XiaoxiaoNeural": 2}
    assert d["all"]["langs"] == {"zh": 2}
    raw = (env / "_abuse_dossiers.json").read_text(encoding="utf-8")
    assert "Secret Title" not in raw and "example.com" not in raw.lower()


def test_unknown_kind_and_corrupt_file_are_fail_open(env):
    (env / "_abuse_dossiers.json").write_text("{not json", encoding="utf-8")
    g = aw.group_key("9.9.9.9", "a")
    aw.record_event(g, "a", "bogus", {})
    assert aw.dossier(g) is None
    _gen(g, "a")
    assert aw.dossier(g)["all"]["generate"] == 1
    assert aw.dossier("net:missing") is None


def test_retention_prunes_old_groups(env, monkeypatch):
    g_old = aw.group_key("1.1.1.1", "a")
    _gen(g_old, "a")
    real_time = time.time
    monkeypatch.setattr(aw.time, "time", lambda: real_time() + 61 * 86400)
    g_new = aw.group_key("2.2.2.2", "b")
    _gen(g_new, "b")
    assert aw.dossier(g_old) is None and aw.dossier(g_new) is not None


def test_write_failure_is_fail_open(env, monkeypatch):
    """Verify that persist errors never escape record_event()."""
    monkeypatch.setattr(aw, "atomic_write_json", lambda path, data: (_ for _ in ()).throw(OSError("disk full")))
    g = aw.group_key("3.3.3.3", "a")
    # Must not raise despite write failure
    aw.record_event(g, "a", "generate", {"chars": 100})
