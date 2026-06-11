import pytest
import translation_core as tc


def test_usage_tracker_estimates_when_no_usage_obj():
    u = tc.UsageTracker()
    u.track("sys", "user content", "output text")
    r = u.report()
    assert r["calls"] == 1
    assert r["estimated"] is True
    assert r["prompt_tokens"] == int((len("sys") + len("user content")) / tc.EST_CHARS_PER_TOKEN)
    assert r["completion_tokens"] == int(len("output text") / tc.EST_CHARS_PER_TOKEN)


def test_usage_tracker_uses_real_usage_when_complete():
    class U:
        prompt_tokens = 100
        completion_tokens = 50
    u = tc.UsageTracker()
    u.track("s", "u", "o", usage_obj=U())
    r = u.report()
    assert r["estimated"] is False
    assert r["prompt_tokens"] == 100
    assert r["completion_tokens"] == 50


def test_usage_tracker_isolated_instances():
    a, b = tc.UsageTracker(), tc.UsageTracker()
    a.track("s", "u", "o")
    assert b.report()["calls"] == 0


def test_split_chunks_respects_paragraphs():
    text = "para uno.\n\npara due.\n\npara tre."
    chunks = tc.split_text_into_chunks(text, 22)
    assert all(len(c) <= 22 for c in chunks)
    assert "".join(chunks).replace("\n\n", "") == text.replace("\n\n", "")


def test_split_chunks_splits_giant_paragraph_on_sentences():
    text = "Frase uno. " * 50  # un solo paragrafo > max
    chunks = tc.split_text_into_chunks(text.strip(), 100)
    assert len(chunks) > 1
    assert all(len(c) <= 100 for c in chunks)


def test_strip_fences():
    assert tc._strip_fences("```text\nciao\n```") == "ciao"
    assert tc._strip_fences("ciao") == "ciao"


def test_build_system_prompt_mentions_langs():
    p = tc.build_system_prompt("it", "en", optimize=False)
    assert "'it'" in p and "'en'" in p
    assert "TTS OPTIMIZATION RULES" not in p


def test_build_system_prompt_optimize_appends_tts_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(tc, "PROMPT_DIR", tmp_path)
    (tmp_path / "prompt_tts_en.md").write_text("RULE-X", encoding="utf-8")
    p = tc.build_system_prompt("it", "en", optimize=True)
    assert "TTS OPTIMIZATION RULES" in p and "RULE-X" in p


# ── Layer LLM ──────────────────────────────────────────────────────────

class _FakeDelta:
    def __init__(self, content):
        self.content = content

class _FakeChoice:
    def __init__(self, content):
        self.delta = _FakeDelta(content)

class _FakeEvent:
    def __init__(self, content=None, usage=None):
        self.choices = [_FakeChoice(content)] if content is not None else []
        self.usage = usage

class _FakeStream:
    def __init__(self, parts):
        self._parts = parts
    def __iter__(self):
        return iter(self._parts)

class _FakeCompletions:
    def __init__(self, parts, fail_times=0, exc=None):
        self.parts = parts
        self.fail_times = fail_times
        self.exc = exc or RuntimeError("boom")
        self.calls = 0
    def create(self, **kwargs):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise self.exc
        return _FakeStream(self.parts)

class _FakeClient:
    def __init__(self, completions):
        self.chat = type("C", (), {"completions": completions})()


def _provider_for(parts, fail_times=0, exc=None):
    comp = _FakeCompletions(parts, fail_times, exc)
    client = _FakeClient(comp)
    return (lambda: client), comp


def test_call_llm_streams_and_tracks(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_MAX_RETRIES", "2")
    provider, comp = _provider_for([_FakeEvent("ciao "), _FakeEvent("mondo")])
    usage = tc.UsageTracker()
    received = []
    out = tc.call_llm(provider, "sys", "user", model="m", usage=usage,
                      progress_cb=lambda n: received.append(n))
    assert out == "ciao mondo"
    assert usage.report()["calls"] == 1
    assert received == [5, 10]  # cumulativo caratteri ricevuti


def test_call_llm_retries_then_succeeds(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_MAX_RETRIES", "3")
    monkeypatch.setattr(tc.time, "sleep", lambda s: None)
    provider, comp = _provider_for([_FakeEvent("ok")], fail_times=2)
    out = tc.call_llm(provider, "s", "u", model="m", usage=tc.UsageTracker())
    assert out == "ok"
    assert comp.calls == 3


def test_call_llm_raises_after_max_retries(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_MAX_RETRIES", "2")
    monkeypatch.setattr(tc.time, "sleep", lambda s: None)
    provider, comp = _provider_for([_FakeEvent("ok")], fail_times=99)
    with pytest.raises(tc.TranslationError):
        tc.call_llm(provider, "s", "u", model="m", usage=tc.UsageTracker())
    assert comp.calls == 2


def test_call_llm_cancel_cb_aborts_mid_stream():
    provider, comp = _provider_for([_FakeEvent("a"), _FakeEvent("b")])
    with pytest.raises(tc.TranslationCancelled):
        tc.call_llm(provider, "s", "u", model="m", usage=tc.UsageTracker(),
                    cancel_cb=lambda: True)


def test_call_llm_stream_options_fallback(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_MAX_RETRIES", "1")
    provider, comp = _provider_for([_FakeEvent("ok")],
                                   fail_times=1,
                                   exc=RuntimeError("stream_options not supported"))
    usage = tc.UsageTracker()
    out = tc.call_llm(provider, "s", "u", model="m", usage=usage)
    assert out == "ok"
    assert usage.no_stream_options is True
    assert comp.calls == 2  # il fallback non consuma un retry


def test_translate_titles_valid_json():
    provider, _ = _provider_for([_FakeEvent('["Uno", "Due"]')])
    out = tc.translate_titles(provider, ["One", "Two"], "en", "it",
                              model="m", usage=tc.UsageTracker())
    assert out == ["Uno", "Due"]


def test_translate_titles_invalid_json_keeps_originals():
    provider, _ = _provider_for([_FakeEvent("non-json")])
    out = tc.translate_titles(provider, ["One", "Two"], "en", "it",
                              model="m", usage=tc.UsageTracker())
    assert out == ["One", "Two"]


def test_resolve_backend_no_config_raises(monkeypatch):
    for k in ("ABM_TRANSLATE_API_KEY", "ABM_LLM_API_KEY",
              "ABM_GCP_PROJECT_ID", "ABM_GOOGLE_CREDENTIALS_FILE",
              "ABM_TRANSLATE_BACKEND"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(tc.TranslationConfigError):
        tc.resolve_backend()


def test_resolve_backend_apikey(monkeypatch):
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("ABM_GOOGLE_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("ABM_TRANSLATE_BACKEND", raising=False)
    monkeypatch.setenv("ABM_TRANSLATE_API_KEY", "k")
    assert tc.resolve_backend() == "apikey"


def test_is_available(monkeypatch):
    monkeypatch.delenv("ABM_GCP_PROJECT_ID", raising=False)
    monkeypatch.delenv("ABM_GOOGLE_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("ABM_TRANSLATE_BACKEND", raising=False)
    monkeypatch.setenv("ABM_TRANSLATE_API_KEY", "k")
    # Backend configurato ma SENZA modello di traduzione esplicito -> non
    # disponibile (niente piu' fallback a ABM_LLM_MODEL / default deepseek-chat).
    monkeypatch.delenv("ABM_TRANSLATE_MODEL", raising=False)
    monkeypatch.setenv("ABM_LLM_MODEL", "deepseek-v4-flash")  # non deve bastare
    assert tc.is_available() is False
    # Backend + modello esplicito -> disponibile.
    monkeypatch.setenv("ABM_TRANSLATE_MODEL", "gemini-2.5-flash")
    assert tc.is_available() is True
    # Tolto il backend -> non disponibile anche con modello impostato.
    monkeypatch.delenv("ABM_TRANSLATE_API_KEY")
    monkeypatch.delenv("ABM_LLM_API_KEY", raising=False)
    assert tc.is_available() is False


# ── Writer ─────────────────────────────────────────────────────────────
import json as _json
import zipfile as _zipfile

_CHAPTERS = [
    {"index": 1, "title": "Uno", "text": "Testo capitolo uno.\n\nSecondo para."},
    {"index": 2, "title": "Due", "text": "Testo capitolo due."},
]
_MANIFEST_SRC = {"title": "Il Libro", "author": "Autore", "original_filename": "libro.epub"}


def test_write_abm_roundtrip(tmp_path):
    out = tmp_path / "out.abm"
    tc.write_abm(out, _MANIFEST_SRC, _CHAPTERS, None, "it", "en", optimize=True)
    with _zipfile.ZipFile(out) as zf:
        m = _json.loads(zf.read("manifest.json"))
        assert m["format"] == "audiobook-maker-project"
        assert m["language"] == "en"
        assert m["translated_from"] == "it"
        assert m["ai_optimized"] is True
        assert len(m["chapters"]) == 2
        ch1 = zf.read("chapters/" + m["chapters"][0]["filename"]).decode("utf-8")
        assert "capitolo uno" in ch1


def test_write_epub_creates_valid_zip(tmp_path):
    out = tmp_path / "out.epub"
    tc.write_epub(out, _MANIFEST_SRC, _CHAPTERS, None, "it", "en", optimize=False)
    assert _zipfile.is_zipfile(out)


def test_write_txt(tmp_path):
    out = tmp_path / "out.txt"
    tc.write_txt(out, _MANIFEST_SRC, _CHAPTERS, None, "it", "en", optimize=False)
    body = out.read_text(encoding="utf-8")
    assert "Il Libro" in body
    assert "Uno" in body and "Due" in body
    assert "Testo capitolo uno." in body
    assert body.index("Uno") < body.index("Testo capitolo uno.")


def test_writer_for_format():
    assert tc.writer_for_format("abm") is tc.write_abm
    assert tc.writer_for_format("epub") is tc.write_epub
    assert tc.writer_for_format("txt") is tc.write_txt
    with pytest.raises(ValueError):
        tc.writer_for_format("pdf")


def test_call_llm_empty_stream_retries_then_raises(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_MAX_RETRIES", "2")
    monkeypatch.setattr(tc.time, "sleep", lambda s: None)
    provider, comp = _provider_for([_FakeEvent("")])  # stream con solo delta vuoti
    with pytest.raises(tc.TranslationError):
        tc.call_llm(provider, "s", "u", model="m", usage=tc.UsageTracker())
    assert comp.calls == 2  # ha ritentato, poi errore definitivo


def test_env_num_malformed_falls_back(monkeypatch, capsys):
    monkeypatch.setenv("ABM_TRANSLATE_MAX_RETRIES", "4x")
    assert tc.max_retries() == 4
    monkeypatch.setenv("ABM_TRANSLATE_TEMPERATURE", "abc")
    assert tc.temperature() == 0.3


def test_env_num_comma_decimal(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_TEMPERATURE", "0,7")
    assert tc.temperature() == 0.7
