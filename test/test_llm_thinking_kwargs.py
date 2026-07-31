# test/test_llm_thinking_kwargs.py
"""Il thinking del provider LLM deve essere sempre esplicito.

DeepSeek v4 (v4-pro / v4-flash) abilita il ragionamento DI DEFAULT quando la
richiesta non contiene ne' `thinking` ne' `reasoning_effort`: omettere i
parametri non basta a spegnerlo. `reasoning_effort` e `thinking.type` sono
inoltre mutuamente esclusivi.
"""
import types
import pytest

import generation_engine as ge


OFF = {"extra_body": {"thinking": {"type": "disabled"}}}
ON = {"extra_body": {"thinking": {"type": "enabled"}}}


def test_default_config_disables_thinking(monkeypatch):
    monkeypatch.setattr(ge, "LLM_REASONING_EFFORT", "none")
    monkeypatch.setattr(ge, "LLM_THINKING", False)
    assert ge.llm_thinking_kwargs() == OFF


@pytest.mark.parametrize("value", ["none", "None", " NONE ", "off", "false", "0", ""])
def test_off_aliases_disable_thinking(monkeypatch, value):
    monkeypatch.setattr(ge, "LLM_THINKING", False)
    monkeypatch.setattr(ge, "LLM_REASONING_EFFORT", value)
    assert ge.llm_thinking_kwargs() == OFF


def test_thinking_flag_enables_without_effort(monkeypatch):
    monkeypatch.setattr(ge, "LLM_REASONING_EFFORT", "none")
    monkeypatch.setattr(ge, "LLM_THINKING", True)
    assert ge.llm_thinking_kwargs() == ON


@pytest.mark.parametrize("value", ["low", "high", "max"])
def test_valid_effort_passed_through(monkeypatch, value):
    monkeypatch.setattr(ge, "LLM_THINKING", False)
    monkeypatch.setattr(ge, "LLM_REASONING_EFFORT", value)
    kw = ge.llm_thinking_kwargs()
    assert kw == {"reasoning_effort": value}
    # reasoning_effort e thinking.type non convivono nella stessa richiesta
    assert "extra_body" not in kw


def test_medium_degrades_to_high(monkeypatch):
    monkeypatch.setattr(ge, "LLM_THINKING", False)
    monkeypatch.setattr(ge, "LLM_REASONING_EFFORT", "medium")
    assert ge.llm_thinking_kwargs() == {"reasoning_effort": "high"}


def test_invalid_effort_falls_back_to_disabled(monkeypatch):
    monkeypatch.setattr(ge, "LLM_THINKING", False)
    monkeypatch.setattr(ge, "LLM_REASONING_EFFORT", "turbo")
    assert ge.llm_thinking_kwargs() == OFF


def test_thinking_off_body_constant():
    assert ge.THINKING_OFF_BODY == {"thinking": {"type": "disabled"}}


# --- integrazione con _call_llm --------------------------------------------

class _Delta:
    def __init__(self, content=None):
        self.content = content
        self.reasoning_content = None


class _Choice:
    def __init__(self, content=None):
        self.delta = _Delta(content)


class _Chunk:
    def __init__(self, content=None):
        self.choices = [_Choice(content)]
        self.usage = None


class _FakeStream:
    def __iter__(self):
        return iter([_Chunk("out")])

    def close(self):
        pass


class _RecordingCompletions:
    def __init__(self):
        self.seen: dict = {}

    def create(self, **kwargs):
        self.seen = kwargs
        return _FakeStream()


def _patch_client(monkeypatch):
    rec = _RecordingCompletions()
    monkeypatch.setattr(ge, "_llm_client",
                        types.SimpleNamespace(chat=types.SimpleNamespace(completions=rec)))
    monkeypatch.setattr(ge, "_get_llm_prompt", lambda lang: "SYS")
    monkeypatch.setattr(ge, "_sanitize_llm_output", lambda x: x)
    monkeypatch.setattr(ge, "_is_prompt_leak", lambda a, b: False)
    return rec


def test_call_llm_sends_thinking_disabled_by_default(monkeypatch):
    rec = _patch_client(monkeypatch)
    monkeypatch.setattr(ge, "LLM_REASONING_EFFORT", "none")
    monkeypatch.setattr(ge, "LLM_THINKING", False)
    assert ge._call_llm("testo") == "out"
    assert rec.seen["extra_body"] == {"thinking": {"type": "disabled"}}
    assert "reasoning_effort" not in rec.seen


def test_call_llm_sends_reasoning_effort_when_configured(monkeypatch):
    rec = _patch_client(monkeypatch)
    monkeypatch.setattr(ge, "LLM_REASONING_EFFORT", "high")
    monkeypatch.setattr(ge, "LLM_THINKING", False)
    assert ge._call_llm("testo") == "out"
    assert rec.seen["reasoning_effort"] == "high"
    assert "extra_body" not in rec.seen
