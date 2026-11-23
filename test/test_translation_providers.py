"""Registro dei provider di traduzione (translation_core.resolve_provider).

Primario e ripiego con lo stesso schema di env, thinking sempre spento con
l'opt-out proprio di ogni canale, ripiego scartato se coincide col primario.
"""
import pytest

import llm_client
import translation_core as tc

_ROLE_ENVS = [
    f"ABM_TRANSLATE_{pfx}{x}"
    for pfx in ("", "FALLBACK_")
    for x in ("BACKEND", "MODEL", "MAX_TOKENS", "API_KEY", "API_BASE", "OPENROUTER_ORDER")
] + ["ABM_LLM_API_KEY", "ABM_LLM_API_BASE", "ABM_LLM_MODEL",
     "ABM_GCP_PROJECT_ID", "ABM_GOOGLE_CREDENTIALS_FILE"]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ROLE_ENVS:
        monkeypatch.delenv(k, raising=False)


def _prod_deepseek(monkeypatch):
    """Configurazione di destinazione: primario DeepSeek diretto, ripiego
    DeepSeek via OpenRouter."""
    monkeypatch.setenv("ABM_LLM_API_KEY", "ds-key")
    monkeypatch.setenv("ABM_LLM_API_BASE", "https://api.deepseek.com")
    monkeypatch.setenv("ABM_LLM_MODEL", "deepseek-flash")
    monkeypatch.setenv("ABM_TRANSLATE_BACKEND", "llm")
    monkeypatch.setenv("ABM_TRANSLATE_MODEL", "deepseek-flash")
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_BACKEND", "openai")
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_API_KEY", "or-key")
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_API_BASE", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_MODEL", "deepseek/deepseek-v4.1-flash")


# ── Primario ───────────────────────────────────────────────────────────

def test_no_config_raises():
    with pytest.raises(tc.TranslationConfigError):
        tc.resolve_provider()


def test_unknown_backend_raises(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_BACKEND", "nope")
    monkeypatch.setenv("ABM_TRANSLATE_MODEL", "m")
    with pytest.raises(tc.TranslationConfigError):
        tc.resolve_provider()


def test_missing_model_raises(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_API_KEY", "k")
    with pytest.raises(tc.TranslationConfigError):
        tc.resolve_provider()


def test_llm_backend_reuses_shared_client(monkeypatch):
    _prod_deepseek(monkeypatch)
    shared = object()
    monkeypatch.setattr(llm_client, "client", lambda: shared)
    p = tc.resolve_provider()
    assert p.backend == "llm"
    assert p.model == "deepseek-flash"
    assert p.base_url == "https://api.deepseek.com"
    assert p.client() is shared
    assert p.thinking_kwargs == {"extra_body": {"thinking": {"type": "disabled"}}}
    assert p.request_kwargs["max_tokens"] == 65536
    assert p.request_kwargs["timeout"] == tc.request_timeout()


def test_llm_backend_needs_llm_key(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_BACKEND", "llm")
    monkeypatch.setenv("ABM_TRANSLATE_MODEL", "deepseek-flash")
    with pytest.raises(tc.TranslationConfigError):
        tc.resolve_provider()


def test_apikey_alias_keeps_current_prod_env(monkeypatch):
    """Le env di prod di oggi (apikey + OpenRouter + Gemini) restano valide e
    mandano la stessa richiesta di prima."""
    monkeypatch.setenv("ABM_TRANSLATE_BACKEND", "apikey")
    monkeypatch.setenv("ABM_TRANSLATE_API_KEY", "or-key")
    monkeypatch.setenv("ABM_TRANSLATE_API_BASE", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("ABM_TRANSLATE_MODEL", "google/gemini-3.5-flash-lite")
    p = tc.resolve_provider()
    assert p.backend == "openai"
    assert p.thinking_kwargs == {"reasoning_effort": "minimal"}
    assert "max_tokens" not in p.request_kwargs
    assert "extra_body" not in p.request_kwargs


def test_auto_prefers_apikey_without_vertex(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_API_KEY", "k")
    monkeypatch.setenv("ABM_TRANSLATE_MODEL", "m")
    assert tc.resolve_provider().backend == "openai"


def test_vertex_backend(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "proj")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))
    monkeypatch.setenv("ABM_TRANSLATE_MODEL", "gemini-3.5-flash-lite")
    p = tc.resolve_provider()  # auto -> vertex
    assert p.backend == "vertex"
    assert p.model == "google/gemini-3.5-flash-lite"
    assert "/projects/proj/" in p.base_url
    assert p.thinking_kwargs == {"reasoning_effort": "minimal"}


def test_max_tokens_env(monkeypatch):
    _prod_deepseek(monkeypatch)
    monkeypatch.setenv("ABM_TRANSLATE_MAX_TOKENS", "0")
    assert "max_tokens" not in tc.resolve_provider().request_kwargs
    monkeypatch.setenv("ABM_TRANSLATE_MAX_TOKENS", "32000")
    assert tc.resolve_provider().request_kwargs["max_tokens"] == 32000


# ── Thinking sempre spento ─────────────────────────────────────────────

@pytest.mark.parametrize("base,model,expected", [
    ("https://openrouter.ai/api/v1", "google/gemini-3.5-flash-lite",
     {"reasoning_effort": "minimal"}),
    ("https://openrouter.ai/api/v1", "deepseek/deepseek-v4.1-flash",
     {"extra_body": {"reasoning": {"enabled": False}}}),
    ("https://api.deepseek.com", "deepseek-flash",
     {"extra_body": {"thinking": {"type": "disabled"}}}),
    ("https://example.com/v1", "some-model", {}),
])
def test_openai_thinking_off_per_channel(base, model, expected):
    assert tc._openai_thinking_off(base, model) == expected


@pytest.mark.parametrize("name", ["ABM_TRANSLATE_THINKING", "ABM_TRANSLATE_REASONING",
                                  "ABM_LLM_REASONING_EFFORT", "ABM_LLM_THINKING"])
def test_no_env_turns_thinking_on(monkeypatch, name):
    _prod_deepseek(monkeypatch)
    monkeypatch.setenv(name, "high")
    assert tc.resolve_provider().thinking_kwargs == \
        {"extra_body": {"thinking": {"type": "disabled"}}}
    assert tc.resolve_provider(tc.FALLBACK).thinking_kwargs == \
        {"extra_body": {"reasoning": {"enabled": False}}}


# ── Ripiego ────────────────────────────────────────────────────────────

def test_fallback_deepseek_via_openrouter(monkeypatch):
    _prod_deepseek(monkeypatch)
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_OPENROUTER_ORDER", "deepseek, novita")
    primary = tc.resolve_provider()
    fb = tc.resolve_fallback(primary, log=lambda *_: None)
    assert fb is not None and fb.role == tc.FALLBACK
    assert fb.backend == "openai"
    assert fb.model == "deepseek/deepseek-v4.1-flash"
    assert fb.request_kwargs["extra_body"]["provider"] == {
        "order": ["deepseek", "novita"], "allow_fallbacks": False,
        "data_collection": "deny"}


def test_fallback_default_is_llm_provider(monkeypatch):
    """Senza env di ripiego: l'LLM dell'ottimizzazione, come prima."""
    monkeypatch.setenv("ABM_TRANSLATE_BACKEND", "apikey")
    monkeypatch.setenv("ABM_TRANSLATE_API_KEY", "or-key")
    monkeypatch.setenv("ABM_TRANSLATE_API_BASE", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("ABM_TRANSLATE_MODEL", "google/gemini-3.5-flash-lite")
    monkeypatch.setenv("ABM_LLM_API_KEY", "ds-key")
    monkeypatch.setenv("ABM_LLM_MODEL", "deepseek-flash")
    fb = tc.resolve_fallback(tc.resolve_provider(), log=lambda *_: None)
    assert fb.backend == "llm" and fb.model == "deepseek-flash"
    assert fb.thinking_kwargs == {"extra_body": {"thinking": {"type": "disabled"}}}


def test_fallback_same_channel_is_dropped_with_log(monkeypatch):
    _prod_deepseek(monkeypatch)
    for k in ("BACKEND", "API_KEY", "API_BASE", "MODEL"):
        monkeypatch.delenv(f"ABM_TRANSLATE_FALLBACK_{k}")
    logs = []
    assert tc.resolve_fallback(tc.resolve_provider(), log=logs.append) is None
    assert any("coincide" in m for m in logs)


def test_fallback_off(monkeypatch):
    _prod_deepseek(monkeypatch)
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_MODEL", "off")
    assert tc.resolve_fallback(tc.resolve_provider(), log=lambda *_: None) is None


def test_fallback_incomplete_config_logged(monkeypatch):
    _prod_deepseek(monkeypatch)
    monkeypatch.delenv("ABM_TRANSLATE_FALLBACK_API_KEY")
    logs = []
    assert tc.resolve_fallback(tc.resolve_provider(), log=logs.append) is None
    assert any("API_KEY" in m for m in logs)


def test_is_available_with_llm_backend(monkeypatch):
    _prod_deepseek(monkeypatch)
    assert tc.is_available() is True
    monkeypatch.delenv("ABM_LLM_API_KEY")
    assert tc.is_available() is False


# ── Richiesta effettiva ────────────────────────────────────────────────

class _Rec:
    def __init__(self):
        self.kw = None
        self.chat = type("C", (), {"completions": self})()

    def create(self, **kw):
        self.kw = kw
        ev = type("E", (), {})()
        ch = type("Ch", (), {})()
        ch.delta = type("D", (), {"content": "ok"})()
        ch.finish_reason = "stop"
        ev.choices = [ch]
        ev.usage = None
        return iter([ev])


def test_call_llm_sends_routing_and_thinking_together(monkeypatch):
    _prod_deepseek(monkeypatch)
    monkeypatch.setenv("ABM_TRANSLATE_FALLBACK_OPENROUTER_ORDER", "deepseek")
    fb = tc.resolve_fallback(tc.resolve_provider(), log=lambda *_: None)
    rec = _Rec()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: rec)
    assert tc.call_llm(fb, "s", "u", usage=tc.UsageTracker()) == "ok"
    assert rec.kw["model"] == "deepseek/deepseek-v4.1-flash"
    assert rec.kw["extra_body"] == {
        "provider": {"order": ["deepseek"], "allow_fallbacks": False,
                     "data_collection": "deny"},
        "reasoning": {"enabled": False}}
    assert rec.kw["timeout"] == tc.request_timeout()


def test_call_llm_thinking_rejected_drops_only_thinking(monkeypatch):
    _prod_deepseek(monkeypatch)
    calls = []

    class _Picky(_Rec):
        def create(self, **kw):
            calls.append(kw)
            if "extra_body" in kw:
                raise RuntimeError("400: unknown parameter thinking")
            return super().create(**kw)

    rec = _Picky()
    monkeypatch.setattr(llm_client, "client", lambda: rec)
    usage = tc.UsageTracker()
    assert tc.call_llm(tc.resolve_provider(), "s", "u", usage=usage) == "ok"
    assert usage.no_reasoning_effort is True
    assert len(calls) == 2 and calls[1]["max_tokens"] == 65536
