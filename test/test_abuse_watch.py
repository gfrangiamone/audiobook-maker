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


def test_signals_s1_to_s4(env, monkeypatch):
    monkeypatch.setenv("ABM_ABUSE_GATE_DAILY", "3")
    monkeypatch.setenv("ABM_ABUSE_CHARS_DAILY", "5000")
    g = aw.group_key("9.9.9.9", "a")
    assert aw.signals_for(g) == {"S1": False, "S2": False, "S3": False, "S4": False}
    _gen(g, "a", chars=1000)
    assert not any(aw.signals_for(g).values())
    aw.record_event(g, "a", "quota_block", {"chars": 1000})
    assert aw.signals_for(g)["S1"] is True
    _gen(g, "b", chars=1000)
    assert aw.signals_for(g)["S2"] is True
    for _ in range(3):
        aw.record_event(g, "b", "quota_gate", {"chars": 1000})
    assert aw.signals_for(g)["S3"] is True
    assert aw.signals_for(g)["S4"] is False
    _gen(g, "b", chars=3000)
    assert aw.signals_for(g)["S4"] is True


def test_needs_judgement_from_second_signal(env):
    g = aw.group_key("9.9.9.9", "a")
    aw.record_event(g, "a", "quota_block", {"chars": 10})
    assert aw.needs_judgement(g, "a") is False          # solo S1
    _gen(g, "b", chars=10)
    assert aw.needs_judgement(g, "b") is True           # S1 + S2
    aw.set_verdict(g, {"verdict": "clean", "confidence": 0.8, "scope": "cids",
                       "cids": ["a", "b"], "reason": "shared network"})
    assert aw.needs_judgement(g, "a") is False          # clean valido
    _gen(g, "c", chars=10)
    assert aw.needs_judgement(g, "c") is False          # nessun segnale nuovo
    for _ in range(5):
        aw.record_event(g, "c", "quota_gate", {"chars": 10})
    assert aw.needs_judgement(g, "c") is True           # S3 e' nuovo rispetto al verdetto


def test_verdict_scope_cids_vs_group_and_new_cid(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a"); _gen(g, "b")
    v = aw.set_verdict(g, {"verdict": "abuse", "confidence": "0.95", "scope": "cids",
                           "cids": ["a", "ghost"], "reason": "bot"})
    assert v["cids"] == ["a"] and v["confidence"] == 0.95
    assert aw.is_blocked(g, "a") is True and aw.is_blocked(g, "b") is False
    assert aw.needs_judgement(g, "a") is False
    assert aw.needs_judgement(g, "b") is True           # cid fuori scope -> rigiudizio
    v = aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.99, "scope": "group",
                           "cids": [], "reason": "same actor"})
    assert sorted(v["cids"]) == ["a", "b"]
    assert aw.is_blocked(g, "b") is True
    _gen(g, "c")
    assert aw.is_blocked(g, "c") is False and aw.needs_judgement(g, "c") is True


def test_low_confidence_or_inconclusive_never_blocks(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.7, "scope": "cids", "cids": ["a"]})
    assert aw.is_blocked(g, "a") is False
    aw.set_verdict(g, {"verdict": "inconclusive", "confidence": 1.0, "scope": "group", "cids": []})
    assert aw.is_blocked(g, "a") is False
    aw.set_verdict(g, {"verdict": "nonsense", "confidence": 1.0, "scope": "group"})
    assert aw.verdict_for(g)["verdict"] == "inconclusive"


def test_verdict_ttl_and_growth_reevaluation(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    for _ in range(4):
        _gen(g, "a")
    aw.record_event(g, "a", "quota_block", {})
    _gen(g, "b")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.95, "scope": "group", "cids": []})
    assert aw.needs_judgement(g, "a") is False
    for _ in range(2):
        _gen(g, "a")                                    # +25% eventi (6 -> 8)
    assert aw.needs_judgement(g, "a") is True
    real_time = time.time
    monkeypatch.setattr(aw.time, "time", lambda: real_time() + 15 * 86400)
    assert aw.verdict_for(g) is None and aw.is_blocked(g, "a") is False


def test_kill_switch_and_admin_email_gate(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": []})
    assert aw.is_blocked(g, "a") is True
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    assert aw.kill_enabled() is False and aw.is_blocked(g, "a") is False
    assert aw.verdict_ttl_sec() == 86400                # osservazione: TTL 1 giorno
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "")
    assert aw.kill_enabled() is False and aw.is_blocked(g, "a") is False


def test_clear_verdict_and_arm_on_startup(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": []})
    assert aw.clear_verdict(g) is True and aw.verdict_for(g) is None
    assert aw.clear_verdict(g) is False
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "0")
    assert aw.arm_on_startup() == 0
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": []})
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    assert aw.arm_on_startup() == 1                     # primo avvio con kill: azzera
    assert aw.verdict_for(g) is None
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 1.0, "scope": "group", "cids": []})
    assert aw.arm_on_startup() == 0                     # gia' armato: non tocca
    assert aw.verdict_for(g) is not None


def test_digest_data_only_hashes_and_counts(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a", chars=500, fn="Secret.epub")
    aw.record_event(g, "a", "email", {"email": "who@example.com"})
    assert aw.digest_data() == []                       # nessun giudizio/kill/403
    aw.record_judgement_failed(g, "timeout")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.93, "scope": "cids",
                       "cids": ["a"], "reason": "103 files in 2 days"})
    aw.record_kill(g, "a", "job-1")
    aw.record_block(g, "a")
    rows = aw.digest_data()
    assert len(rows) == 1
    r = rows[0]
    assert r["group"] == g and r["verdict"] == "abuse" and r["scope"] == "cids"
    assert r["kills"] == 1 and r["blocks"] == 1 and r["unjudged"] == 1
    assert r["cids_n"] == 1 and r["generate_24h"] == 1 and r["chars_24h"] == 500
    blob = json.dumps(rows)
    assert "9.9.9" not in blob and "example.com" not in blob and "Secret" not in blob


def test_growth_formula_base_4_events(env):
    """Verify growth trigger at exactly 25% with integer arithmetic (5*4 >= 4*5)."""
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    _gen(g, "a")
    aw.record_event(g, "a", "quota_block", {})
    _gen(g, "b")
    # events_at_verdict = 4 (2 generate + 1 quota_block from "a", 1 generate from "b")
    aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.95, "scope": "group", "cids": []})
    assert aw.needs_judgement(g, "a") is False
    _gen(g, "a")  # +1 event, total = 5; 5*4 >= 4*5 → 20 >= 20 → True
    assert aw.needs_judgement(g, "a") is True


def test_cid_eviction_caps_group_at_max(env, monkeypatch):
    """26 cid -> resta il tetto (default 25): il meno attivo di recente
    (cid-0) e' evictato, il cid appena registrato (cid-25) resta sempre."""
    g = aw.group_key("9.9.9.9", "cid-0")
    real_time = time.time
    t = [real_time()]
    monkeypatch.setattr(aw.time, "time", lambda: t[0])
    for i in range(26):
        aw.record_event(g, f"cid-{i}", "generate", {"chars": 10})
        t[0] += 1
    d = aw.dossier(g)
    assert len(d["cids"]) == 25
    assert "cid-0" not in d["cids"]
    assert "cid-25" in d["cids"]


def test_cid_eviction_floor_and_custom_limit(env, monkeypatch):
    monkeypatch.setenv("ABM_ABUSE_MAX_CIDS_PER_GROUP", "1")   # floor 2
    assert aw._max_cids_per_group() == 2
    g = aw.group_key("9.9.9.9", "x")
    _gen(g, "x")
    _gen(g, "y")
    _gen(g, "z")
    assert len(aw.dossier(g)["cids"]) == 2
    assert "z" in aw.dossier(g)["cids"]                       # l'ultimo mai evictato


def test_verdict_group_scope_restricted_to_active_cids(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    real_time = time.time
    _gen(g, "stale")
    monkeypatch.setattr(aw.time, "time", lambda: real_time() + 8 * 86400)   # oltre 7 giorni
    _gen(g, "fresh")
    v = aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.9, "scope": "group", "cids": []})
    assert v["cids"] == ["fresh"]
    assert aw.is_blocked(g, "fresh") is True
    assert aw.is_blocked(g, "stale") is False


def test_verdict_group_scope_falls_back_to_all_known_if_none_active(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a"); _gen(g, "b")
    real_time = time.time
    monkeypatch.setattr(aw.time, "time", lambda: real_time() + 8 * 86400)   # entrambi ormai stale
    v = aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.9, "scope": "group", "cids": []})
    assert sorted(v["cids"]) == ["a", "b"]                    # nessun attivo -> fallback a tutti i noti


def test_needs_judgement_uses_passed_group_data_without_reload(env, monkeypatch):
    g = aw.group_key("9.9.9.9", "a")
    aw.record_event(g, "a", "quota_block", {"chars": 10})
    group_data = aw.record_event(g, "b", "generate", {"chars": 10})
    assert group_data is not None
    monkeypatch.setattr(aw, "_load", lambda: (_ for _ in ()).throw(AssertionError("must not reload")))
    assert aw.needs_judgement(g, "b", group_data=group_data) is True     # S1 + S2, nessuna rilettura


def test_reason_field_scrubs_pii(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    v = aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.95, "scope": "cids",
                           "cids": ["a"], "reason": "mail bob@example.com from 1.2.3.4 same actor"})
    assert "bob@example.com" not in v["reason"]
    assert "1.2.3.4" not in v["reason"]
    assert "same actor" in v["reason"]
    stored = aw.verdict_for(g)
    assert "bob@example.com" not in stored["reason"]
    assert "1.2.3.4" not in stored["reason"]
    assert "[redacted]" in stored["reason"]


def test_reason_field_scrubs_ipv6(env):
    g = aw.group_key("9.9.9.9", "a")
    _gen(g, "a")
    v = aw.set_verdict(g, {"verdict": "abuse", "confidence": 0.95, "scope": "cids",
                           "cids": ["a"], "reason": "seen from 2001:db8::1 same actor"})
    assert "2001:db8::1" not in v["reason"]
    assert "same actor" in v["reason"]
    assert "[redacted]" in v["reason"]
