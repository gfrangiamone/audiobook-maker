"""D2a: llm_client (client condiviso, thinking, errori transitori, parser, prompt) e gcp_auth."""
import ast
import pathlib
import types

import pytest

import llm_client as lc


class _Resp:
    def __init__(self, content):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]


class _Fake:
    def __init__(self, reply="ok"):
        self.calls = []
        self.reply = reply
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(kw)
        return _Resp(self.reply)


@pytest.fixture
def own(monkeypatch):
    """llm_client senza client registrato: lo costruisce da ABM_LLM_*."""
    monkeypatch.setattr(lc, "_client_fn", None)
    monkeypatch.setattr(lc, "_model_fn", None)
    monkeypatch.setattr(lc, "_available_fn", None)
    lc.reset()
    yield
    lc.reset()


def test_client_from_env_or_registered(own, monkeypatch):
    monkeypatch.delenv("ABM_LLM_API_KEY", raising=False)
    assert lc.client() is None and lc.available() is False
    with pytest.raises(RuntimeError):
        lc.chat_once("s", "u", max_tokens=5, timeout=1)
    built = []
    monkeypatch.setattr(lc, "build_client", lambda key, base, timeout=None: built.append((key, base)) or _Fake("x"))
    monkeypatch.setenv("ABM_LLM_API_KEY", "k1")
    monkeypatch.setenv("ABM_LLM_API_BASE", " https://llm.example ")
    c1 = lc.client()
    assert c1 is lc.client() and built == [("k1", "https://llm.example")]
    monkeypatch.setenv("ABM_LLM_API_KEY", "k2")
    assert lc.client() is not c1 and len(built) == 2            # chiave ruotata
    monkeypatch.setenv("ABM_LLM_MODEL", "m-env")
    assert lc.model() == "m-env" and lc.available() is True
    fake = _Fake("reg")
    lc.configure(client_fn=lambda: fake, model_fn=lambda: "m-reg", available_fn=lambda: False)
    assert lc.client() is fake and lc.model() == "m-reg" and lc.available() is False


def test_chat_once_kwargs(own):
    fake = _Fake("  risposta \n")
    out = lc.chat_once("SYS", "USER", max_tokens=42, timeout=7.5, llm=fake, model_name="m")
    assert out == "risposta"
    call = fake.calls[0]
    assert call["model"] == "m" and call["max_tokens"] == 42 and call["timeout"] == 7.5
    assert call["temperature"] == 0.0 and call["extra_body"] == lc.THINKING_OFF_BODY
    assert call["messages"] == [{"role": "system", "content": "SYS"}, {"role": "user", "content": "USER"}]
    assert "response_format" not in call
    lc.chat_once("S", "U", max_tokens=1, timeout=1, llm=fake, model_name="m", json_mode=True,
                 thinking_off=False, temperature=0.4, extra={"seed": 3})
    call = fake.calls[1]
    assert call["response_format"] == {"type": "json_object"} and "extra_body" not in call
    assert call["temperature"] == 0.4 and call["seed"] == 3
    assert lc.chat_once("S", "U", max_tokens=1, timeout=1, llm=_Fake(None), model_name="m") == ""


def test_thinking_kwargs_and_summary(capsys):
    off = {"extra_body": {"thinking": {"type": "disabled"}}}
    for v in ("none", "None", " NONE ", "off", "false", "0", "", None):
        assert lc.thinking_kwargs(v, False) == off
    assert lc.thinking_kwargs("none", True) == {"extra_body": {"thinking": {"type": "enabled"}}}
    for v in ("low", "high", "max"):
        assert lc.thinking_kwargs(v, False) == {"reasoning_effort": v}
    assert lc.thinking_kwargs("medium", False) == {"reasoning_effort": "high"}
    assert lc.thinking_kwargs("turbo", True) == off and "non valido" in capsys.readouterr().out
    assert lc.thinking_summary({"reasoning_effort": "low"}) == "reasoning_effort=low"
    assert lc.thinking_summary(off) == "thinking=disabled"


def test_transient_and_overload():
    class ReadError(Exception):
        pass

    class Boring(Exception):
        pass

    class Status(Exception):
        def __init__(self, code):
            self.status_code = code

    class Wrapped(Exception):
        response = types.SimpleNamespace(status_code=503)

    assert lc.is_transient(ReadError("x")) and not lc.is_transient(Boring("x"))
    assert lc.is_transient(Status(429)) and lc.is_transient(Status(502)) and not lc.is_transient(Status(400))
    assert lc.is_transient(Wrapped("x")) and lc.status_code(Wrapped("x")) == 503
    assert lc.status_code(Boring("x")) is None
    assert lc.is_overload(Boring("The server is busy, try again later")) and lc.is_transient(Boring("overloaded"))
    assert not lc.is_overload(Boring("bad request"))


def test_strip_fences_and_extract_json_object():
    assert lc.strip_fences("```text\nciao\n```") == "ciao" and lc.strip_fences(" ciao ") == "ciao"
    assert lc.strip_fences("```json\n{\"a\": 1}\n```") == '{"a": 1}'
    assert lc.extract_json_object('{"a": 1}') == {"a": 1}
    assert lc.extract_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert lc.extract_json_object('Sure! Here it is:\n{"a": {"b": "}"}, "c": "\\"{"} thanks') == {"a": {"b": "}"}, "c": '"{'}
    assert lc.extract_json_object("[1, 2]") is None and lc.extract_json_object("") is None
    assert lc.extract_json_object("no json here") is None and lc.extract_json_object("{broken") is None


def test_tts_prompt_cache_and_fallback(tmp_path):
    (tmp_path / "prompt_tts_generic.md").write_text(" G ", encoding="utf-8")
    (tmp_path / "prompt_tts_it.md").write_text("IT", encoding="utf-8")
    lc.reset()
    seen = []
    assert lc.tts_prompt("it", prompt_dir=tmp_path, log=seen.append) == "IT"
    assert lc.tts_prompt("de", prompt_dir=tmp_path, log=seen.append) == "G"
    assert lc.tts_prompt("it", prompt_dir=tmp_path, log=seen.append) == "IT"
    assert seen == ["prompt_tts_it.md", "prompt_tts_generic.md"]            # cache: nessun secondo log
    assert lc.tts_prompt("it", prompt_dir=tmp_path / "manca") == ""
    lc.reset()


def test_engine_registers_itself_and_community_modules_follow(monkeypatch):
    import generation_engine as ge
    import community_moderator as cm, community_translator as ct, abuse_watch as aw
    fake = _Fake('{"approved": false, "reason": "spam"}')
    monkeypatch.setattr(ge, "_llm_client", fake)
    monkeypatch.setattr(ge, "LLM_MODEL", "m-test")
    assert lc.client() is fake and lc.model() == "m-test" and lc.available() is True
    assert cm._call_llm("testo", timeout=3.0) == {"approved": False, "reason": "spam"}
    assert fake.calls[-1]["model"] == "m-test" and fake.calls[-1]["max_tokens"] == 256
    assert ct.is_available() is True
    fake.reply = '```json\n{"verdict": "ok"}\n```'
    assert aw._parse_verdict(aw._call_llm("u", 5.0)) == {"verdict": "ok"}
    assert fake.calls[-1]["extra_body"] == ge.THINKING_OFF_BODY
    monkeypatch.setattr(ge, "_llm_client", None)
    assert lc.available() is False and cm._call_llm("t", timeout=1) is None
    for mod in (cm, ct, aw):
        assert "import generation_engine" not in pathlib.Path(mod.__file__).read_text(encoding="utf-8")


def test_gcp_auth_service_account(monkeypatch, tmp_path):
    import gcp_auth
    creds_file = tmp_path / "sa.json"
    creds_file.write_text('{"project_id": "proj-1"}', encoding="utf-8")

    class _Creds:
        def __init__(self):
            self.valid = False
            self.token = None
            self.expiry = None
            self.refreshes = 0

        def refresh(self, _req):
            self.refreshes += 1
            self.valid = True
            self.token = f"tok{self.refreshes}"

    made = _Creds()
    fake_sa = types.SimpleNamespace(Credentials=types.SimpleNamespace(
        from_service_account_file=lambda path, scopes: made))
    fake_req = types.SimpleNamespace(Request=lambda: object())
    import sys
    monkeypatch.setitem(sys.modules, "google", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "google.oauth2", types.SimpleNamespace(service_account=fake_sa))
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", fake_sa)
    monkeypatch.setitem(sys.modules, "google.auth", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "google.auth.transport", types.SimpleNamespace())
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", fake_req)
    sa = gcp_auth.ServiceAccount(str(creds_file), ["scope"], margin_sec=300)
    assert sa.project_id() == "proj-1"
    assert sa.token() == "tok1" and sa.token() == "tok1"                  # valido: nessun refresh
    from datetime import datetime, timedelta, timezone
    made.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=100)
    assert sa.token() == "tok2"                                           # vicino alla scadenza
    made.expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=1)
    assert sa.token() == "tok2" and sa.token(force_refresh=True) == "tok3"


def test_llm_client_and_gcp_auth_are_leaves():
    import gcp_auth
    for mod, allowed in ((lc, {"json", "re", "threading", "pathlib", "env_utils"}),
                         (gcp_auth, {"json", "threading", "datetime", "google"})):
        src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
        mods = {(n.names[0].name if isinstance(n, ast.Import) else n.module).split(".")[0]
                for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Import, ast.ImportFrom))}
        assert mods <= allowed | {"openai"}, (mod.__name__, mods)
