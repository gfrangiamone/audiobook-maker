"""llm_client — client chat LLM (SDK OpenAI-compatibile) e parser delle risposte.

Modulo foglia (stdlib + `env_utils`). Prima: sei percorsi «chat completion +
retry + parse» in `generation_engine`, `community_moderator`,
`community_translator`, `abuse_watch`, `translation_core`; quattro modi
diversi di togliere i fence JSON; due client per lo stesso provider; il
body di opt-out del thinking in due copie; i moduli community che
importavano `generation_engine` per raggiungere `_llm_client`.

Chi detiene il client (`generation_engine`) lo registra con `configure()`:
`client()`, `model()` e `available()` lo chiedono a lui a ogni chiamata,
cosi' i test che sostituiscono `generation_engine._llm_client` valgono per
tutti. Senza registrazione il client si costruisce da `ABM_LLM_*`.

- `chat_once(system, user, ...)`: una chiamata non streaming, thinking
  spento salvo richiesta, `json_mode` opzionale; ritorna il testo.
- `thinking_kwargs(effort, thinking)`: kwargs espliciti per il reasoning.
- `is_transient(exc)` / `is_overload(exc)`: errori da ritentare.
- `strip_fences`, `extract_json_object`: pulizia delle risposte.
- `tts_prompt(lang)`: prompt di ottimizzazione TTS, con cache.
"""
import json
import re
import threading
from pathlib import Path

from env_utils import env_str

DEFAULT_API_BASE = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"
PROMPT_DIR = Path(__file__).resolve().parent / "prompt_opt_AI"

# Opt-out esplicito del thinking: sull'API DeepSeek (v4) il ragionamento e'
# acceso di default quando la richiesta non dice nulla, e su chiamate con
# `max_tokens` piccoli (lang-detect, moderazione) svuoterebbe la risposta.
THINKING_OFF_BODY = {"thinking": {"type": "disabled"}}
REASONING_OFF = ("none", "off", "no", "false", "disabled", "0", "")
REASONING_VALID = ("low", "high", "max")

# Provider sovraccarico: transitorio, ma con pause lunghe.
OVERLOAD_MARKERS = (
    "unable to start processing", "try again later", "overloaded",
    "server is busy", "server busy",
)
# Errori di rete client-side (httpx / wrapper openai), per nome di classe.
TRANSIENT_EXC_NAMES = (
    "ReadError", "ConnectError", "ConnectTimeout", "ReadTimeout",
    "RemoteProtocolError", "APIConnectionError", "APITimeoutError",
)
TRANSIENT_STATUS = (429, 500, 502, 503, 504)

_client_fn = None
_model_fn = None
_available_fn = None
_own_client = None
_own_key = ""
_lock = threading.Lock()
_prompts: dict = {}


def configure(*, client_fn=None, model_fn=None, available_fn=None):
    """Registra chi possiede il client (callable risolte a ogni chiamata)."""
    global _client_fn, _model_fn, _available_fn
    if client_fn is not None:
        _client_fn = client_fn
    if model_fn is not None:
        _model_fn = model_fn
    if available_fn is not None:
        _available_fn = available_fn


def api_key():
    return env_str("ABM_LLM_API_KEY", "").strip()


def api_base():
    return env_str("ABM_LLM_API_BASE", "").strip() or DEFAULT_API_BASE


def build_client(key, base_url, timeout=None):
    """Client OpenAI-compatibile; `None` se l'SDK non e' installato."""
    try:
        from openai import OpenAI
    except ImportError:
        return None
    kwargs = {"api_key": key, "base_url": base_url}
    if timeout is not None:
        kwargs["timeout"] = timeout
    return OpenAI(**kwargs)


def client():
    """Il client registrato con `configure`, altrimenti uno proprio costruito
    da `ABM_LLM_API_KEY`/`ABM_LLM_API_BASE` (ricreato se la chiave cambia)."""
    global _own_client, _own_key
    if _client_fn is not None:
        return _client_fn()
    key = api_key()
    if not key:
        return None
    with _lock:
        if _own_client is None or _own_key != key:
            _own_client = build_client(key, api_base())
            _own_key = key
        return _own_client


def model():
    return _model_fn() if _model_fn is not None else env_str("ABM_LLM_MODEL", DEFAULT_MODEL)


def available():
    """True se c'e' un client con cui chiamare."""
    if _available_fn is not None:
        return bool(_available_fn())
    return client() is not None


def thinking_kwargs(effort, thinking, *, log=print):
    """kwargs OpenAI-compatibili per governare il thinking del modello.

    Ritorna SEMPRE una configurazione esplicita (mai il default del provider):
    - effort fra `REASONING_OFF` -> {"extra_body": {"thinking": {"type":
      "disabled"|"enabled"}}} secondo `thinking`;
    - effort low/high/max -> {"reasoning_effort": effort} ("medium" degrada
      a "high"); un valore ignoto spegne il thinking con avviso.
    `reasoning_effort` e `thinking.type` non convivono nella stessa richiesta.
    """
    effort = str(effort if effort is not None else "").strip().lower()
    if effort in REASONING_OFF:
        return {"extra_body": {"thinking": {"type": "enabled" if thinking else "disabled"}}}
    if effort == "medium":
        effort = "high"
    if effort not in REASONING_VALID:
        log(f"[llm] ABM_LLM_REASONING_EFFORT={effort!r} non valido "
            f"(ammessi: none/low/high/max): thinking disabilitato")
        return {"extra_body": {"thinking": {"type": "disabled"}}}
    return {"reasoning_effort": effort}


def thinking_summary(kw):
    """Descrizione compatta di un risultato di `thinking_kwargs` (per i log)."""
    effort = kw.get("reasoning_effort")
    if effort:
        return f"reasoning_effort={effort}"
    body = kw.get("extra_body") or {}
    state = ((body.get("thinking") or {}).get("type")) if isinstance(body, dict) else None
    return f"thinking={state}"


def messages(system, user):
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def chat_once(system, user, *, max_tokens, timeout, temperature=0.0, json_mode=False,
              thinking_off=True, model_name=None, llm=None, extra=None):
    """Una chat completion non streaming. Ritorna il testo (strip) o "".

    Solleva `RuntimeError` se non c'e' un client; le eccezioni dell'SDK
    passano al chiamante, che decide se ritentare (`is_transient`).
    """
    c = llm if llm is not None else client()
    if c is None:
        raise RuntimeError("LLM client not configured")
    kwargs = {
        "model": model_name or model(),
        "messages": messages(system, user),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "timeout": timeout,
    }
    if thinking_off:
        kwargs["extra_body"] = THINKING_OFF_BODY
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    if extra:
        kwargs.update(extra)
    completion = c.chat.completions.create(**kwargs)
    return (completion.choices[0].message.content or "").strip()


# ---- errori ----------------------------------------------------------------------

def status_code(exc):
    """Codice HTTP di un'eccezione dell'SDK (o della sua response), se c'e'."""
    sc = getattr(exc, "status_code", None)
    if sc is None:
        resp = getattr(exc, "response", None)
        if resp is not None:
            sc = getattr(resp, "status_code", None)
    return sc if isinstance(sc, int) else None


def is_overload(exc):
    """Provider in coda o esplicitamente sovraccarico: si ritenta, ma con
    pause lunghe."""
    msg = str(exc).lower()
    return any(m in msg for m in OVERLOAD_MARKERS)


def is_transient(exc):
    """Errore da ritentare: sovraccarico, rete client-side (per nome di
    classe) o stato 429/5xx del provider."""
    if is_overload(exc):
        return True
    name = type(exc).__name__
    if any(s in name for s in TRANSIENT_EXC_NAMES):
        return True
    return status_code(exc) in TRANSIENT_STATUS


# ---- risposte -------------------------------------------------------------------------

_FENCE_RE = re.compile(r"^```[a-zA-Z]*\n(.*)\n```$", re.DOTALL)


def strip_fences(text):
    """Rimuove un eventuale wrapping completo in fence markdown."""
    stripped = (text or "").strip()
    m = _FENCE_RE.match(stripped)
    return m.group(1).strip() if m else stripped


def extract_json_object(raw):
    """Primo oggetto JSON (dict) nel testo: parse diretto, poi fence tolti,
    poi scansione bilanciata delle graffe (ignora quelle dentro le stringhe).
    `None` se non c'e' un dict valido."""
    raw = (raw or "").strip()
    if not raw:
        return None
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```\s*$", "", raw)
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:  # noqa: BLE001
        pass
    start = raw.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(raw)):
        c = raw[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(raw[start:i + 1])
                    return obj if isinstance(obj, dict) else None
                except Exception:  # noqa: BLE001
                    return None
    return None


# ---- prompt --------------------------------------------------------------------------

def tts_prompt(lang, *, log=None, prompt_dir=None):
    """Prompt di ottimizzazione TTS per la lingua (`prompt_tts_<lang>.md`,
    fallback `prompt_tts_generic.md`), letto una volta per lingua. `log(name)`
    e' chiamato al caricamento col nome del file. "" se non c'e'."""
    key = (lang or "generic", str(prompt_dir or ""))
    if key in _prompts:
        return _prompts[key]
    base = Path(prompt_dir) if prompt_dir else PROMPT_DIR
    path = base / f"prompt_tts_{lang}.md"
    if not path.exists():
        path = base / "prompt_tts_generic.md"
    if not path.exists():
        return ""
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        print(f"Error reading prompt {path}: {e}")
        return ""
    if log:
        log(path.name)
    _prompts[key] = content
    return content


def reset():
    """Scarta client proprio e cache dei prompt (test, rotazione chiave)."""
    global _own_client, _own_key
    with _lock:
        _own_client, _own_key = None, ""
    _prompts.clear()
