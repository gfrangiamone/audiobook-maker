# test/test_call_llm_usage.py
import types
import generation_engine as ge


class _Delta:
    def __init__(self, content=None):
        self.content = content
        self.reasoning_content = None


class _Choice:
    def __init__(self, content=None):
        self.delta = _Delta(content)


class _Chunk:
    """Chunk stile openai: choices con delta, e usage solo nell'ultimo."""
    def __init__(self, content=None, usage=None):
        self.choices = [] if content is None and usage is not None else [_Choice(content)]
        self.usage = usage


class _Usage:
    def __init__(self, p, c):
        self.prompt_tokens = p
        self.completion_tokens = c


class _FakeStream:
    def __init__(self, chunks):
        self._chunks = chunks
    def __iter__(self):
        return iter(self._chunks)
    def close(self):
        pass


class _FakeCompletions:
    def __init__(self, chunks):
        self._chunks = chunks
    def create(self, **kwargs):
        # deve richiedere l'usage nello stream
        assert kwargs.get("stream_options") == {"include_usage": True}
        return _FakeStream(self._chunks)


class _FakeClient:
    def __init__(self, chunks):
        self.chat = types.SimpleNamespace(
            completions=_FakeCompletions(chunks))


def test_call_llm_accumulates_usage(monkeypatch):
    chunks = [
        _Chunk("Ciao "),
        _Chunk("mondo."),
        _Chunk(content=None, usage=_Usage(120, 45)),  # final usage-only chunk
    ]
    monkeypatch.setattr(ge, "_llm_client", _FakeClient(chunks))
    monkeypatch.setattr(ge, "_get_llm_prompt", lambda lang: "SYS")
    monkeypatch.setattr(ge, "_sanitize_llm_output", lambda x: x)
    monkeypatch.setattr(ge, "_is_prompt_leak", lambda a, b: False)
    job = {"opt_usage": {"prompt_tokens": 0, "completion_tokens": 0, "estimated": False}}
    out = ge._call_llm("testo", job=job)
    assert out == "Ciao mondo."
    assert job["opt_usage"]["prompt_tokens"] == 120
    assert job["opt_usage"]["completion_tokens"] == 45


def test_call_llm_usage_missing_marks_estimated(monkeypatch):
    chunks = [_Chunk("Solo testo.")]  # nessun chunk usage
    monkeypatch.setattr(ge, "_llm_client", _FakeClient(chunks))
    monkeypatch.setattr(ge, "_get_llm_prompt", lambda lang: "SYS")
    monkeypatch.setattr(ge, "_sanitize_llm_output", lambda x: x)
    monkeypatch.setattr(ge, "_is_prompt_leak", lambda a, b: False)
    job = {"opt_usage": {"prompt_tokens": 0, "completion_tokens": 0, "estimated": False}}
    out = ge._call_llm("testo", job=job)
    assert out == "Solo testo."
    assert job["opt_usage"]["estimated"] is True
