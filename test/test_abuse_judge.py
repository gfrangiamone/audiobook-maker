"""Giudice LLM: prompt da sole feature, parsing del verdetto, fail-open, worker."""
import json
import queue

import pytest

import abuse_watch as aw
import generation_engine as ge


@pytest.fixture(autouse=True)
def _isolated_queue():
    """Un worker reale puo' essere vivo sul modulo globale (avviato da
    _ensure_background_threads all'import di audiobook_app in altri test file
    della stessa sessione): sgancia ogni gruppo residuo e svuota la coda
    condivisa prima di ciascun test, cosi' nessun consumatore in background
    puo' rubare gli item scriptati per _FakeClient (issue #1)."""
    with aw._lock:
        aw._queued.clear()
    while True:
        try:
            aw._queue.get_nowait()
        except queue.Empty:
            break
    yield


class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _FakeClient:
    """Risponde in sequenza con i testi passati; registra le chiamate."""
    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []
        outer = self

        class _Completions:
            def create(self, **kw):
                outer.calls.append(kw)
                if not outer.answers:
                    raise RuntimeError("no more answers")
                a = outer.answers.pop(0)
                if isinstance(a, Exception):
                    raise a
                return _Resp(a)

        class _Chat:
            completions = _Completions()

        self.chat = _Chat()


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("ABM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ABM_IP_SALT", "salt-test")
    monkeypatch.setenv("ABM_ABUSE_KILL_ENABLE", "1")
    monkeypatch.setenv("ABM_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setattr(ge, "_llm_available", lambda: True)
    monkeypatch.setattr(ge, "LLM_MODEL", "deepseek-chat")
    monkeypatch.setattr(aw.time, "sleep", lambda *_a, **_k: None)
    return tmp_path


def _suspicious_group():
    g = aw.group_key("9.9.9.9", "a")
    for i in range(6):
        aw.record_event(g, "a", "generate", {"chars": 400_000, "voice": "zh-CN-XiaoxiaoNeural",
                                             "filename": f"Secret Book {i}.epub", "lang": "zh"})
    aw.record_event(g, "a", "email", {"email": "first@gmail.com"})
    aw.record_event(g, "a", "quota_block", {"chars": 400_000})
    aw.record_event(g, "b", "email", {"email": "second@outlook.com"})
    for i in range(3):
        aw.record_event(g, "b", "quota_gate", {"chars": 400_000})
        aw.record_event(g, "b", "generate", {"chars": 400_000, "voice": "zh-CN-XiaoxiaoNeural",
                                             "filename": f"Other {i}.epub", "lang": "zh"})
    return g


def test_prompt_contains_only_features(env):
    g = _suspicious_group()
    user, alias = aw.build_prompt(g)
    assert set(alias) == {"cid_1", "cid_2"} and set(alias.values()) == {"a", "b"}
    for secret in ("9.9.9", "gmail", "outlook", "Secret", "Other", "first@", "@"):
        assert secret not in user
    feats = json.loads(user)
    assert feats["signals"]["S1"] and feats["signals"]["S2"]
    assert feats["group"]["distinct_cids"] == 2
    assert feats["group"]["distinct_emails"] == 2 and feats["group"]["distinct_files"] == 9
    assert feats["cids"]["cid_1"]["generate_total"] == 6
    assert feats["cids"]["cid_2"]["quota_gate_total"] == 3
    assert feats["group"]["top_voices"] == [["zh-CN-XiaoxiaoNeural", 9]]
    assert aw.build_prompt("net:unknown") is None


def test_judge_parses_verdict_with_cids_scope(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient(json.dumps({"verdict": "abuse", "confidence": 0.95, "scope": "cids",
                                   "cids": ["cid_1", "cid_9"], "reason": "one voice, many files"}))
    monkeypatch.setattr(ge, "_llm_client", fake)
    v = aw.judge(g)
    assert v["verdict"] == "abuse" and v["confidence"] == 0.95 and v["cids"] == ["a"]
    assert aw.is_blocked(g, "a") is True and aw.is_blocked(g, "b") is False
    call = fake.calls[0]
    assert call["model"] == "deepseek-chat" and call["temperature"] == 0.0
    assert call["extra_body"] == ge.THINKING_OFF_BODY and call["timeout"] == 20.0
    assert call["messages"][0]["role"] == "system" and "inconclusive" in call["messages"][0]["content"]


def test_judge_scope_group_and_json_in_prose(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient('Here is my verdict: {"verdict": "abuse", "confidence": 0.92, '
                       '"scope": "group", "cids": [], "reason": "same actor"} thanks')
    monkeypatch.setattr(ge, "_llm_client", fake)
    v = aw.judge(g)
    assert v["scope"] == "group" and sorted(v["cids"]) == ["a", "b"]


def test_judge_abuse_without_known_cids_becomes_inconclusive(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient(json.dumps({"verdict": "abuse", "confidence": 0.99, "scope": "cids",
                                   "cids": ["cid_42"], "reason": "x"}))
    monkeypatch.setattr(ge, "_llm_client", fake)
    v = aw.judge(g)
    assert v["verdict"] == "inconclusive" and aw.is_blocked(g, "a") is False


def test_judge_fail_open_on_malformed_and_errors(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient("not json at all", RuntimeError("boom"))
    monkeypatch.setattr(ge, "_llm_client", fake)
    assert aw.judge(g) is None
    assert len(fake.calls) == 2                          # 1 retry
    assert aw.verdict_for(g) is None
    rows = aw.digest_data()
    assert rows and rows[0]["unjudged"] == 1


def test_judge_skips_when_llm_unavailable(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient("{}")
    monkeypatch.setattr(ge, "_llm_client", fake)
    monkeypatch.setattr(ge, "_llm_available", lambda: False)
    assert aw.judge(g) is None and fake.calls == []
    assert aw.digest_data()[0]["unjudged"] == 1


def test_worker_process_calls_back_and_dedups_queue(env, monkeypatch):
    """Non passa dalla coda condivisa del modulo (un worker reale altrove nella
    sessione la consumerebbe concorrentemente, issue #1): simula direttamente
    lo stato 'accodato' e verifica il dedup attraverso `_queued`."""
    g = _suspicious_group()
    fake = _FakeClient(json.dumps({"verdict": "abuse", "confidence": 0.95, "scope": "group",
                                   "cids": [], "reason": "r"}))
    monkeypatch.setattr(ge, "_llm_client", fake)
    with aw._lock:
        aw._queued.add(g)
    seen = []
    v = aw._process(g, "a", lambda grp, verdict: seen.append((grp, verdict["verdict"])))
    assert v["verdict"] == "abuse" and seen == [(g, "abuse")]
    with aw._lock:
        assert g not in aw._queued             # sganciato a fine giudizio (issue #6, finally)
    assert aw._process(g, "a", lambda *_: seen.append("again")) is None   # verdetto valido: no rigiudizio
    assert seen == [(g, "abuse")] and len(fake.calls) == 1


def test_worker_process_survives_callback_error(env, monkeypatch):
    g = _suspicious_group()
    fake = _FakeClient(json.dumps({"verdict": "clean", "confidence": 0.9, "scope": "group",
                                   "cids": [], "reason": "shared NAT"}))
    monkeypatch.setattr(ge, "_llm_client", fake)

    def _boom(*_a):
        raise RuntimeError("callback failed")

    v = aw._process(g, "a", _boom)
    assert v["verdict"] == "clean" and aw.verdict_for(g)["verdict"] == "clean"


def test_judge_survives_build_prompt_error(env, monkeypatch):
    g = _suspicious_group()
    monkeypatch.setattr(aw, "build_prompt", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    assert aw.judge(g) is None
    assert aw.dossier(g) is not None


def test_parse_verdict_accepts_markdown_fence(env):
    text = '```json\n{"verdict": "abuse", "confidence": 0.95, "scope": "cids", "cids": ["cid_1"], "reason": "test"}\n```'
    v = aw._parse_verdict(text)
    assert v["verdict"] == "abuse" and v["confidence"] == 0.95
    assert v["scope"] == "cids" and v["cids"] == ["cid_1"]
