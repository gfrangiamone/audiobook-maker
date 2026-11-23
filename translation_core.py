"""translation_core.py — Core condiviso di traduzione libro via LLM.

Libreria pura usata sia dal CLI scripts/translate_abm.py sia dalla web app
(generation_engine.run_translation). Nessun import dai moduli applicativi,
nessun side effect Flask. Thread-safe: lo stato di usage è per-istanza
(UsageTracker), mai module-global.

Config (env, con fallback ABM_LLM_*): vedi PARAMETRI_CONFIGURAZIONE.md.
"""

import io
import json
import llm_client
from gcp_auth import ServiceAccount
import os
from env_utils import env_float, env_int, env_str
import re
import fileio
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parent
PROMPT_DIR = REPO_ROOT / "prompt_opt_AI"

# Stima token quando il provider non riporta l'usage (chars per token).
EST_CHARS_PER_TOKEN = 4.0


# ---------------------------------------------------------------------------
# Errori
# ---------------------------------------------------------------------------

class TranslationError(Exception):
    """Errore generico di traduzione."""


class TranslationConfigError(TranslationError):
    """Configurazione backend LLM incompleta o invalida."""


class TranslationCancelled(TranslationError):
    """Traduzione annullata (cancel_cb ha restituito True)."""


class TranslationContentBlocked(TranslationError):
    """Il provider ha interrotto la risposta per il contenuto (filtro
    safety/recitation): ripetere la stessa richiesta allo stesso modello non
    serve, il chiamante puo' ripiegare su un altro LLM."""

    def __init__(self, message, finish_reason=""):
        super().__init__(message)
        self.finish_reason = finish_reason


# ---------------------------------------------------------------------------
# Config (letta a ogni chiamata: testabile con monkeypatch.setenv)
# ---------------------------------------------------------------------------

def _env(name, fallback_name="", default=""):
    return env_str(name, default, fallback=fallback_name or None)


def api_key():
    return _env("ABM_TRANSLATE_API_KEY", "ABM_LLM_API_KEY")


def api_base():
    return _env("ABM_TRANSLATE_API_BASE", "ABM_LLM_API_BASE",
                "https://api.deepseek.com")


def model_name():
    # SOLO ABM_TRANSLATE_MODEL: nessun fallback a ABM_LLM_MODEL ne' default.
    # Il modello dell'ottimizzazione (ABM_LLM_MODEL) e' pensato per il backend
    # DeepSeek diretto; ereditato qui finirebbe su Vertex come google/<nome> ->
    # 404 (incidente 2026-06). Vuoto = traduzione NON configurata: is_available()
    # ritorna False e l'UI disabilita la feature.
    return _env("ABM_TRANSLATE_MODEL")


def gcp_project():
    return _env("ABM_GCP_PROJECT_ID")


def gcp_creds_file():
    return _env("ABM_GOOGLE_CREDENTIALS_FILE")


def vertex_location():
    return _env("ABM_TRANSLATE_VERTEX_LOCATION", default="global")


def _env_num(cast, name, default):
    """Numero da env (env_utils): malformato -> default con avviso, virgola ok."""
    return (env_int if cast is int else env_float)(name, default)


def chunk_chars():
    return _env_num(int, "ABM_TRANSLATE_CHUNK_CHARS", 20000)


def max_retries():
    return _env_num(int, "ABM_TRANSLATE_MAX_RETRIES", 4)


def temperature():
    return _env_num(float, "ABM_TRANSLATE_TEMPERATURE", 0.3)


def request_timeout():
    return _env_num(float, "ABM_TRANSLATE_REQUEST_TIMEOUT_SEC", 300)


def block_attempts():
    """Tentativi sullo stesso chunk quando il provider lo blocca per il
    contenuto, prima di arrendersi (TranslationContentBlocked). Il blocco e'
    quasi sempre deterministico: 2 bastano a coprire il caso sporadico."""
    return max(1, _env_num(int, "ABM_TRANSLATE_BLOCK_ATTEMPTS", 2))


def fallback_sticky_after():
    """Dopo quanti chunk bloccati il resto del libro va direttamente al
    modello di ripiego (0 = mai: si ripiega solo chunk per chunk)."""
    return max(0, _env_num(int, "ABM_TRANSLATE_FALLBACK_STICKY_AFTER", 2))


# ---------------------------------------------------------------------------
# Usage tracking per-esecuzione (thread-safe per istanza)
# ---------------------------------------------------------------------------

class UsageTracker:
    """Contatori cumulativi token/chiamate di UNA esecuzione di traduzione."""

    def __init__(self):
        self.calls = 0
        self.calls_with_usage = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.est_prompt_chars = 0
        self.est_completion_chars = 0
        # Settato a True se il provider rifiuta stream_options.
        self.no_stream_options = False
        # Settato a True se il modello rifiuta reasoning_effort.
        self.no_reasoning_effort = False

    def track(self, system_prompt, user_content, output_text, usage_obj=None):
        self.calls += 1
        self.est_prompt_chars += len(system_prompt) + len(user_content)
        self.est_completion_chars += len(output_text)
        if usage_obj is not None:
            self.prompt_tokens += getattr(usage_obj, "prompt_tokens", 0) or 0
            self.completion_tokens += getattr(usage_obj, "completion_tokens", 0) or 0
            self.calls_with_usage += 1

    def report(self):
        """Riepilogo: token reali se completi, altrimenti stima da caratteri."""
        estimated = self.calls_with_usage < self.calls
        if estimated:
            pt = int(self.est_prompt_chars / EST_CHARS_PER_TOKEN)
            ct = int(self.est_completion_chars / EST_CHARS_PER_TOKEN)
        else:
            pt, ct = self.prompt_tokens, self.completion_tokens
        return {"calls": self.calls, "estimated": estimated,
                "prompt_tokens": pt, "completion_tokens": ct}


# ---------------------------------------------------------------------------
# Lingue edge-tts (costante copiata invariata da scripts/translate_abm.py)
# ---------------------------------------------------------------------------

EDGE_LANGS_FALLBACK = {
    "af", "am", "ar", "az", "bg", "bn", "bs", "ca", "cs", "cy", "da", "de",
    "el", "en", "es", "et", "fa", "fi", "fil", "fr", "ga", "gu", "he", "hi",
    "hr", "hu", "id", "is", "it", "ja", "jv", "ka", "kk", "km", "kn", "ko",
    "lo", "lt", "lv", "mk", "ml", "mr", "ms", "mt", "my", "nb", "ne", "nl",
    "pl", "ps", "pt", "ro", "ru", "si", "sk", "sl", "so", "sq", "sr", "sv",
    "sw", "ta", "te", "th", "tr", "uk", "ur", "uz", "vi", "zh", "zu",
}


# ---------------------------------------------------------------------------
# Chunking (copiato da scripts/translate_abm.py:202-237, con fix sep space)
# ---------------------------------------------------------------------------

def split_text_into_chunks(text, max_chars):
    """Spezza il testo in chunk rispettando i confini di paragrafo."""
    paragraphs = re.split(r'\n\s*\n', text)
    chunks = []
    current_chunk = []
    current_size = 0

    for para in paragraphs:
        para_size = len(para)
        if para_size > max_chars:
            if current_chunk:
                chunks.append("\n\n".join(current_chunk))
                current_chunk = []
                current_size = 0
            sentences = re.split(r'(?<=[.!?…])\s+', para)
            sub_chunk = []
            sub_size = 0
            for sent in sentences:
                sep = 1 if sub_chunk else 0
                if sub_size + sep + len(sent) > max_chars and sub_chunk:
                    chunks.append(" ".join(sub_chunk))
                    sub_chunk = []
                    sub_size = 0
                    sep = 0
                sub_chunk.append(sent)
                sub_size += sep + len(sent)
            if sub_chunk:
                chunks.append(" ".join(sub_chunk))
            continue
        if current_size + para_size + 2 > max_chars and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = []
            current_size = 0
        current_chunk.append(para)
        current_size += para_size + 2
    if current_chunk:
        chunks.append("\n\n".join(current_chunk))
    return chunks


# ---------------------------------------------------------------------------
# Prompt (copiato da scripts/translate_abm.py:244-287, con modifica
# load_tts_prompt: print(...) → log(...), parametro log=print)
# ---------------------------------------------------------------------------

def load_tts_prompt(lang, log=print):
    """Carica il prompt di ottimizzazione TTS per la lingua (fallback generic),
    dalla cache condivisa di `llm_client`."""
    prompt = llm_client.tts_prompt(lang, prompt_dir=PROMPT_DIR,
                                   log=lambda name: log(f"[prompt] Ottimizzazione TTS: uso {name}"))
    if not prompt:
        log(f"[prompt] WARNING: nessun prompt TTS trovato in {PROMPT_DIR}")
    return prompt


def build_system_prompt(source, target, optimize):
    base = (
        f"You are a professional literary translator.\n"
        f"Translate the text provided by the user from the language with "
        f"ISO 639-1 code '{source}' to the language with ISO 639-1 code "
        f"'{target}'.\n\n"
        "Rules:\n"
        "- Preserve the meaning, tone, register and narrative style of the "
        "original.\n"
        "- Preserve the paragraph structure and blank lines exactly.\n"
        "- Keep proper names unchanged unless a conventional translation "
        "exists in the target language.\n"
        "- Do not summarize, omit or add content.\n"
        "- Output ONLY the translated text: no comments, no preambles, no "
        "explanations, no markdown fences."
    )
    if optimize:
        tts_prompt = load_tts_prompt(target)
        if tts_prompt:
            base += (
                "\n\nAfter translating, apply to the TRANSLATED text the "
                "following text-optimization rules for TTS narration, and "
                "output only the final optimized translation (single pass, "
                "single output):\n\n"
                "----- TTS OPTIMIZATION RULES -----\n"
                f"{tts_prompt}"
            )
    return base


_strip_fences = llm_client.strip_fences


# ---------------------------------------------------------------------------
# Provider LLM di traduzione (registro dei backend)
# ---------------------------------------------------------------------------
#
# Un provider e' tutto cio' che serve a una chiamata: client, modello e
# parametri della richiesta. Due ruoli con lo stesso schema di env:
#   primario  ABM_TRANSLATE_<X>
#   ripiego   ABM_TRANSLATE_FALLBACK_<X>
# con <X> = BACKEND, MODEL, MAX_TOKENS, API_KEY, API_BASE, OPENROUTER_ORDER.
# Aggiungere un provider = scrivere un builder e registrarlo in _BUILDERS.

PRIMARY = "primary"
FALLBACK = "fallback"
_ROLE_PREFIX = {PRIMARY: "ABM_TRANSLATE_", FALLBACK: "ABM_TRANSLATE_FALLBACK_"}
_OFF_VALUES = ("off", "none", "0")
OPENROUTER_HOST = "openrouter.ai"


@dataclass(frozen=True)
class TranslationProvider:
    backend: str            # chiave del registro: finisce in tr_backend e nell'audit
    model: str
    base_url: str
    client: Callable        # () -> client OpenAI-compatibile pronto all'uso
    request_kwargs: dict = field(default_factory=dict)   # max_tokens, timeout, extra_body
    thinking_kwargs: dict = field(default_factory=dict)  # opt-out del thinking
    role: str = PRIMARY

    @property
    def channel(self):
        """Identita' del canale: due provider con lo stesso canale fanno la
        stessa chiamata (stesso host, stesso modello)."""
        return ((self.base_url or "").rstrip("/"), self.model)


def _role_env(role, suffix, default=""):
    return env_str(_ROLE_PREFIX[role] + suffix, default)


def backend_choice(role=PRIMARY):
    default = "auto" if role == PRIMARY else "llm"
    return (_role_env(role, "BACKEND") or default).lower()


def _role_model(role, backend):
    if role == PRIMARY:
        return model_name()
    v = _role_env(FALLBACK, "MODEL")
    if not v and backend == "llm":
        # Ripiego storico: il modello dell'ottimizzazione AI.
        v = env_str("ABM_LLM_MODEL", llm_client.DEFAULT_MODEL)
    return v


def _role_api_key(role):
    return api_key() if role == PRIMARY else _role_env(FALLBACK, "API_KEY")


def _role_api_base(role):
    return api_base() if role == PRIMARY else _role_env(FALLBACK, "API_BASE")


def _merge_kwargs(*kwargs_list):
    """Unisce i kwargs di richiesta; gli extra_body si fondono di un livello
    (routing OpenRouter e opt-out del thinking convivono)."""
    out = {}
    for kw in kwargs_list:
        for k, v in (kw or {}).items():
            if k == "extra_body" and isinstance(out.get(k), dict):
                body = dict(out[k])
                for bk, bv in v.items():
                    if isinstance(bv, dict) and isinstance(body.get(bk), dict):
                        body[bk] = {**body[bk], **bv}
                    else:
                        body[bk] = bv
                out[k] = body
            else:
                out[k] = v
    return out


def _base_request_kwargs(role, max_tokens_default):
    """Timeout per richiesta e max_tokens del ruolo (0 = non inviato: vale il
    default del provider)."""
    kw = {"timeout": request_timeout()}
    mt = max(0, _env_num(int, _ROLE_PREFIX[role] + "MAX_TOKENS", max_tokens_default))
    if mt:
        kw["max_tokens"] = mt
    return kw


# Famiglie Gemini che accettano reasoning_effort='minimal' (Vertex e
# OpenRouter): 2.5 e 3.x, ramo flash/flash-lite, con o senza prefisso
# 'google/'. I Pro non scendono sotto 'low'. Vertex rifiuta 'none' (400,
# incidente 2026-06): 'minimal' e' il minimo e azzera il reasoning su flash.
_GEMINI_MINIMAL_RE = re.compile(r"gemini-(?:2\.5|3(?:\.\d+)?)-flash")


def _gemini_thinking_off(model):
    if _GEMINI_MINIMAL_RE.search((model or "").lower()):
        return {"reasoning_effort": "minimal"}
    return {}


def _openai_thinking_off(base_url, model):
    """Opt-out del thinking su un endpoint OpenAI-compatibile generico.
    Nella traduzione il thinking non serve mai (confronto 22/11/2026, tutto a
    thinking spento): si spegne sempre, nessuna env lo riaccende."""
    gemini = _gemini_thinking_off(model)
    if gemini:
        return gemini
    host = (base_url or "").lower()
    if OPENROUTER_HOST in host:
        # Verificato su DeepSeek V4.1 Flash: 0 token di reasoning.
        return {"extra_body": {"reasoning": {"enabled": False}}}
    if "deepseek" in host:
        return {"extra_body": llm_client.THINKING_OFF_BODY}
    return {}


def _openrouter_routing(role, base_url):
    """Provider OpenRouter fissato (ABM_TRANSLATE[_FALLBACK]_OPENROUTER_ORDER,
    lista separata da virgole): niente host a caso e niente conservazione dei
    testi. Vuoto = routing di default di OpenRouter."""
    order = [p.strip() for p in _role_env(role, "OPENROUTER_ORDER").split(",")
             if p.strip()]
    if not order or OPENROUTER_HOST not in (base_url or "").lower():
        return {}
    return {"extra_body": {"provider": {
        "order": order, "allow_fallbacks": False, "data_collection": "deny"}}}


def _build_llm(role, model):
    """Il provider dell'ottimizzazione AI (ABM_LLM_API_KEY/_API_BASE), con lo
    stesso client condiviso: nessuna seconda connessione allo stesso provider.
    Il timeout di traduzione viaggia per richiesta."""
    if not llm_client.api_key():
        raise TranslationConfigError(
            "backend llm richiesto ma ABM_LLM_API_KEY non impostata")

    def client():
        c = llm_client.client()
        if c is None:
            raise TranslationConfigError("client LLM non disponibile")
        return c

    return TranslationProvider(
        backend="llm", model=model, base_url=llm_client.api_base(), client=client,
        request_kwargs=_base_request_kwargs(role, 65536),
        thinking_kwargs={"extra_body": llm_client.THINKING_OFF_BODY}, role=role)


def _build_openai(role, model):
    """Endpoint OpenAI-compatibile qualsiasi (OpenRouter, DeepSeek, ...), con
    chiave e base proprie del ruolo."""
    key, base = _role_api_key(role), _role_api_base(role)
    if not key or not base:
        p = _ROLE_PREFIX[role]
        raise TranslationConfigError(
            f"backend openai richiesto ma servono {p}API_KEY e {p}API_BASE")
    state = {}

    def client():
        if "c" not in state:
            state["c"] = llm_client.build_client(key, base, timeout=request_timeout())
        return state["c"]

    return TranslationProvider(
        backend="openai", model=model, base_url=base, client=client,
        request_kwargs=_merge_kwargs(_base_request_kwargs(role, 0),
                                     _openrouter_routing(role, base)),
        thinking_kwargs=_openai_thinking_off(base, model), role=role)


def _vertex_ready():
    return bool(gcp_project()) and bool(gcp_creds_file()) \
        and os.path.isfile(gcp_creds_file())


def _vertex_base_url():
    loc = vertex_location()
    host = "aiplatform.googleapis.com" if loc == "global" \
        else f"{loc}-aiplatform.googleapis.com"
    return (f"https://{host}/v1/projects/{gcp_project()}/locations/"
            f"{loc}/endpoints/openapi")


def _build_vertex(role, model):
    """Vertex AI (service account Google), endpoint OpenAI-compatibile."""
    if not _vertex_ready():
        raise TranslationConfigError(
            "backend vertex richiesto ma config incompleta: servono "
            "ABM_GCP_PROJECT_ID e ABM_GOOGLE_CREDENTIALS_FILE (file leggibile)")
    base_url = _vertex_base_url()
    model = model if "/" in model else f"google/{model}"
    state = {"sa": None, "client": None, "token": None}

    def client():
        # Il token si rinnova da solo prima della scadenza (gcp_auth); il
        # client OpenAI si ricrea quando il bearer cambia.
        if state["sa"] is None:
            state["sa"] = ServiceAccount(
                gcp_creds_file(), ["https://www.googleapis.com/auth/cloud-platform"])
        token = state["sa"].token()
        if state["client"] is None or token != state["token"]:
            state["client"] = llm_client.build_client(token, base_url,
                                                      timeout=request_timeout())
            state["token"] = token
        return state["client"]

    return TranslationProvider(
        backend="vertex", model=model, base_url=base_url, client=client,
        request_kwargs=_base_request_kwargs(role, 0),
        thinking_kwargs=_gemini_thinking_off(model), role=role)


_BUILDERS = {"llm": _build_llm, "openai": _build_openai, "vertex": _build_vertex}
# Nomi storici delle env di prod: restano validi.
_BACKEND_ALIASES = {"apikey": "openai"}


def _resolve_backend_name(role):
    choice = backend_choice(role)
    choice = _BACKEND_ALIASES.get(choice, choice)
    if choice != "auto":
        if choice not in _BUILDERS:
            raise TranslationConfigError(
                f"backend di traduzione sconosciuto: {choice!r} "
                f"(validi: auto, apikey, {', '.join(sorted(_BUILDERS))})")
        return choice
    if _vertex_ready():
        return "vertex"
    if _role_api_key(role) and _role_api_base(role):
        return "openai"
    raise TranslationConfigError(
        "nessun backend LLM configurato: imposta ABM_GCP_PROJECT_ID + "
        "ABM_GOOGLE_CREDENTIALS_FILE (Vertex) oppure ABM_TRANSLATE_API_KEY")


def resolve_provider(role=PRIMARY):
    """Provider del ruolo dato. Solleva TranslationConfigError se la config
    e' incompleta. Economico: nessuna connessione finche' non si chiama
    provider.client()."""
    backend = _resolve_backend_name(role)
    model = _role_model(role, backend)
    if not model:
        raise TranslationConfigError(
            f"modello di traduzione non configurato: imposta {_ROLE_PREFIX[role]}MODEL")
    return _BUILDERS[backend](role, model)


def resolve_fallback(primary, log=print):
    """Provider di ripiego, o None (disattivato con
    ABM_TRANSLATE_FALLBACK_MODEL=off, config incompleta o stesso canale del
    primario: ripiegare sulla stessa chiamata non serve)."""
    if _role_env(FALLBACK, "MODEL").lower() in _OFF_VALUES:
        return None
    try:
        fb = resolve_provider(FALLBACK)
    except TranslationConfigError as e:
        log(f"[traduzione] ripiego non disponibile: {e}")
        return None
    if primary is not None and fb.channel == primary.channel:
        log(f"[traduzione] ripiego disattivato: coincide col primario "
            f"({fb.model} @ {fb.base_url})")
        return None
    return fb


def is_available():
    """True se il provider primario e' configurato, modello compreso
    (ABM_TRANSLATE_MODEL esplicito).

    Senza modello la feature e' considerata non configurata: la UI nasconde
    l'opzione traduzione e gli endpoint la rifiutano (evita che la traduzione
    erediti silenziosamente un modello di un altro backend -> 404)."""
    if not model_name():
        return False
    try:
        resolve_provider(PRIMARY)
        return True
    except TranslationConfigError:
        return False


# ---------------------------------------------------------------------------
# Chiamate LLM
# ---------------------------------------------------------------------------

# finish_reason che indicano una risposta interrotta per il contenuto. Vertex
# (endpoint OpenAI-compatibile) mappa SAFETY/RECITATION/BLOCKLIST/
# PROHIBITED_CONTENT/SPII su "content_filter"; i nomi nativi restano per i
# proxy che li passano invariati.
_BLOCK_FINISH_RE = re.compile(
    r"content_filter|safety|recitation|blocklist|prohibited|spii",
    re.IGNORECASE)


def _is_block_finish(reason):
    return bool(reason) and bool(_BLOCK_FINISH_RE.search(str(reason)))


def _thinking_rejected(exc):
    """400 di un modello che non accetta l'opt-out del thinking inviato."""
    msg = str(exc).lower()
    return any(m in msg for m in ("reasoning", "thinking"))


def call_llm(provider, system_prompt, user_content, *, usage,
             label="", progress_cb=None, cancel_cb=None, log=print):
    """Chiamata LLM streaming con retry esponenziale. Ritorna il testo.

    provider: TranslationProvider (client, modello, parametri di richiesta).
    usage: UsageTracker dell'esecuzione (anche stato no_stream_options).
    progress_cb(received_chars): notificata col cumulativo caratteri ricevuti.
    cancel_cb() -> bool: se True a inizio chiamata o tra gli eventi dello
    stream, solleva TranslationCancelled.

    Una risposta interrotta per il contenuto (finish_reason di blocco) non e'
    mai restituita, nemmeno se parziale: dopo block_attempts() tentativi
    solleva TranslationContentBlocked, senza consumare tutti i retry.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    retries = max_retries()
    last_exc = None
    attempt = 0
    blocked = 0
    while attempt < retries:
        if cancel_cb and cancel_cb():
            raise TranslationCancelled("cancelled before LLM call")
        try:
            client = provider.client()
            kwargs = _merge_kwargs(
                {"model": provider.model, "messages": messages,
                 "temperature": temperature(), "stream": True},
                provider.request_kwargs,
                None if usage.no_reasoning_effort else provider.thinking_kwargs)
            if not usage.no_stream_options:
                kwargs["stream_options"] = {"include_usage": True}
            stream = client.chat.completions.create(**kwargs)
            parts = []
            received = 0
            usage_obj = None
            finish = ""
            for event in stream:
                if cancel_cb and cancel_cb():
                    raise TranslationCancelled("cancelled mid-stream")
                choice = event.choices[0] if event.choices else None
                if choice is not None:
                    # Vertex chiude lo stream bloccato con una choice senza
                    # delta: leggere delta.content qui era l'AttributeError
                    # che faceva fallire i job (incidente 2026-10-05).
                    finish = getattr(choice, "finish_reason", None) or finish
                    delta = getattr(choice, "delta", None)
                    chunk = getattr(delta, "content", None) if delta else None
                    if chunk:
                        parts.append(chunk)
                        received += len(chunk)
                        if progress_cb:
                            progress_cb(received)
                if getattr(event, "usage", None):
                    usage_obj = event.usage
            text = _strip_fences("".join(parts))
            if _is_block_finish(finish):
                # Il consumo c'e' stato anche se il testo si scarta.
                usage.track(system_prompt, user_content, text, usage_obj)
                raise TranslationContentBlocked(
                    f"response blocked by provider (finish_reason={finish}, "
                    f"{len(text)} chars discarded)", finish)
            if finish and finish not in ("stop", "length"):
                log(f"  {label} [LLM] finish_reason inatteso: {finish}")
            if not text.strip():
                raise TranslationError("empty completion from provider")
            usage.track(system_prompt, user_content, text, usage_obj)
            return text
        except TranslationCancelled:
            raise
        except KeyboardInterrupt:
            raise
        except TranslationContentBlocked as e:
            blocked += 1
            last_exc = e
            if blocked >= block_attempts():
                raise
            log(f"  {label} [LLM] risposta bloccata per il contenuto "
                f"({e.finish_reason}), tentativo {blocked}/{block_attempts()}")
            attempt += 1
            continue
        except Exception as e:
            # Provider senza stream_options: disabilita e riprova subito
            # senza consumare un tentativo (errore di config, non transient).
            if not usage.no_stream_options and "stream_options" in str(e).lower():
                usage.no_stream_options = True
                log(f"  {label} [LLM] provider senza stream_options: "
                    f"report costi in modalità stima")
                continue
            # Modello che rifiuta l'opt-out del thinking (400 su
            # reasoning_effort/thinking): toglie il parametro e riprova subito
            # senza consumare un tentativo. Il thinking resta al default del
            # modello (costo output piu' alto, ma la traduzione non si blocca).
            if (not usage.no_reasoning_effort and provider.thinking_kwargs
                    and _thinking_rejected(e)):
                usage.no_reasoning_effort = True
                log(f"  {label} [LLM] opt-out del thinking rifiutato da "
                    f"{provider.model}: riprovo senza (thinking al default del modello)")
                continue
            last_exc = e
            if attempt >= retries - 1:
                break
            wait = 2 ** attempt  # 1, 2, 4, 8 secondi
            log(f"  {label} [LLM] {type(e).__name__} (tentativo "
                f"{attempt + 1}/{retries}), riprovo tra {wait}s: {e}")
            time.sleep(wait)
            attempt += 1
    if isinstance(last_exc, TranslationContentBlocked):
        raise last_exc
    raise TranslationError(
        f"Chiamata LLM fallita dopo {retries} tentativi: {last_exc}")


def translate_titles(provider, titles, source, target, *,
                     usage, log=print, dry_run=False):
    """Traduce i titoli dei capitoli in una singola chiamata batch (JSON).
    Su risposta invalida ritorna i titoli originali (non fatale)."""
    if dry_run:
        return list(titles)
    system = (
        f"You translate book chapter titles from the language with ISO 639-1 "
        f"code '{source}' to the language with ISO 639-1 code '{target}'.\n"
        "The user sends a JSON array of strings. Reply with ONLY a JSON array "
        "of the translated strings, same length, same order. No comments, no "
        "markdown fences."
    )
    try:
        raw = call_llm(provider, system,
                       json.dumps(titles, ensure_ascii=False),
                       usage=usage, label="[titoli]", log=log)
        out = json.loads(_strip_fences(raw))
        if isinstance(out, list) and len(out) == len(titles) \
                and all(isinstance(t, str) for t in out):
            return out
        raise ValueError("struttura JSON inattesa")
    except TranslationCancelled:
        raise
    except Exception as e:
        log(f"  [titoli] WARNING: risposta non valida ({e}), "
            f"mantengo i titoli originali")
        return list(titles)


# ---------------------------------------------------------------------------
# Output writers (copiati invariati da scripts/translate_abm.py:539-639)
# ---------------------------------------------------------------------------

def _safe_filename(name):
    """Forma «traduzione» della regola unica di `fileio.safe_filename`:
    caratteri vietati sostituiti da `_`, punti conservati (c'e' l'estensione),
    nessun limite qui (lo mette il chiamante), `untitled` se resta vuoto."""
    cleaned = fileio.safe_filename(name, replacement="_", keep_dots=True, collapse_spaces=False,
                                   guard_dash=False, max_chars=None, max_bytes=None).strip(" .")
    return cleaned or "untitled"


def write_abm(out_path, manifest_src, chapters, cover, source, target,
              optimize):
    """Scrive il nuovo .abm con capitoli tradotti."""
    buf = io.BytesIO()
    now = datetime.now(timezone.utc).isoformat()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        chapters_manifest = []
        for ch in chapters:
            ch_safe = _safe_filename(ch["title"])[:50] or f"ch_{ch['index']}"
            ch_filename = f"{ch['index']:03d}_{ch_safe}.txt"
            zf.writestr(f"chapters/{ch_filename}", ch["text"])
            chapters_manifest.append({
                "index": ch["index"],
                "filename": ch_filename,
                "title": ch["title"],
                "word_count": len(ch["text"].split()),
            })

        has_cover = False
        cover_file = ""
        if cover:
            data, orig_name = cover
            ext = ".png" if orig_name.lower().endswith(".png") else ".jpg"
            cover_file = f"cover{ext}"
            zf.writestr(cover_file, data)
            has_cover = True

        manifest = {
            "format": "audiobook-maker-project",
            "format_version": "1.0",
            "title": manifest_src.get("title", ""),
            "author": manifest_src.get("author", ""),
            "language": target,
            "has_cover": has_cover,
            "cover_file": cover_file,
            "exported_at": now,
            "original_filename": manifest_src.get("original_filename", ""),
            "translated_from": source,
            "translated_at": now,
            "ai_optimized": bool(optimize),
            "chapters": chapters_manifest,
        }
        if optimize:
            manifest["ai_optimized_at"] = now
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))

    with open(out_path, "wb") as f:
        f.write(buf.getvalue())


def write_epub(out_path, manifest_src, chapters, cover, source, target,
               optimize):
    """Scrive il libro tradotto come .epub (ebooklib, già dipendenza app)."""
    import html as _html
    from ebooklib import epub

    title = manifest_src.get("title", "") or "Untitled"
    author = manifest_src.get("author", "")

    book = epub.EpubBook()
    book.set_identifier(f"abm-translate-{_safe_filename(title)}-{target}")
    book.set_title(title)
    book.set_language(target)
    if author:
        book.add_author(author)
    book.add_metadata("DC", "contributor", "Audiobook Maker translate_abm")
    book.add_metadata("DC", "source", f"translated from '{source}'"
                      + (", AI-optimized for TTS" if optimize else ""))

    if cover:
        data, orig_name = cover
        ext = ".png" if orig_name.lower().endswith(".png") else ".jpg"
        book.set_cover(f"cover{ext}", data)

    items = []
    for ch in chapters:
        ch_title = _html.escape(ch["title"])
        paras = [p.strip() for p in re.split(r'\n\s*\n', ch["text"])
                 if p.strip()]
        body = "\n".join(
            f"<p>{_html.escape(p).replace(chr(10), '<br/>')}</p>"
            for p in paras)
        item = epub.EpubHtml(title=ch["title"],
                             file_name=f"chap_{ch['index']:03d}.xhtml",
                             lang=target)
        item.content = (f"<html><head><title>{ch_title}</title></head>"
                        f"<body><h1>{ch_title}</h1>{body}</body></html>")
        book.add_item(item)
        items.append(item)

    book.toc = items
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav"] + items
    epub.write_epub(str(out_path), book)


def write_txt(out_path, manifest_src, chapters, cover, source, target,
              optimize):
    """Scrive il libro tradotto come testo piatto UTF-8.

    Intestazione (titolo/autore), poi per ogni capitolo: titolo su riga
    propria, riga vuota, corpo. La cover è ignorata (formato solo testo).
    """
    title = manifest_src.get("title", "") or "Untitled"
    author = manifest_src.get("author", "")
    lines = [title]
    if author:
        lines.append(author)
    lines.append("")
    for ch in chapters:
        lines.append(ch["title"])
        lines.append("")
        lines.append(ch["text"])
        lines.append("")
    Path(out_path).write_text("\n".join(lines).rstrip() + "\n",
                              encoding="utf-8")


def writer_for_format(fmt):
    """Ritorna la funzione writer per il formato. ValueError se sconosciuto."""
    w = {"abm": write_abm, "epub": write_epub, "txt": write_txt}.get(fmt)
    if w is None:
        raise ValueError(f"formato output non supportato: {fmt!r}")
    return w
