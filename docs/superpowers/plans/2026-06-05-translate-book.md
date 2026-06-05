# Traduzione Libro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Percorso wizard alternativo al TTS che traduce il libro caricato in un'altra lingua via LLM (ottimizzazione AI opzionale integrata), con pagamento voucher/PayPal, modalità interattiva/batch email, output .epub/.abm/.txt e adozione del risultato per la generazione audio.

**Architecture:** Libreria condivisa `translation_core.py` (root repo) estratta da `scripts/translate_abm.py` (che diventa CLI sottile); thread di background `run_translation()` in `generation_engine.py` sul pattern di `run_optimization`; nuovi endpoint in `audiobook_app.py` che riusano pagamento/voucher/token-download esistenti; frontend SPA con `wizMode='translate'` sui 5 step esistenti.

**Tech Stack:** Python/Flask, OpenAI SDK (Vertex/DeepSeek), ebooklib, vanilla JS SPA, pytest.

**Spec:** `docs/superpowers/specs/2026-06-05-translate-book-design.md`

**Branch:** `TRADUZ` (lavorare e committare qui; mai push senza conferma esplicita).

**Convenzioni vincolanti:**
- Shell di sviluppo: PowerShell. Niente `&&` per concatenare; comandi singoli.
- Validare la sintassi Python prima di committare: `python -m py_compile <file>`.
- I file `.md` sono in `.gitignore`: per committare piani/doc usare `git add -f`.
- Test in `test/` (non `tests/`). Eseguire con `pytest test/<file> -v --tb=short`.

---

## File Structure

| File | Azione | Responsabilità |
|---|---|---|
| `translation_core.py` | **Create** | Libreria pura traduzione: config env, backend LLM, chunking, prompt, chiamate streaming con retry, writer abm/epub/txt, `UsageTracker` per-esecuzione. Nessun import Flask/app. |
| `scripts/translate_abm.py` | **Rewrite** | CLI sottile: argparse, parse_abm locale, report costi, delega a `translation_core`. |
| `payment.py` | **Modify** | Pricing traduzione: rate/min da env, `_estimate_translation_cost_eur()`. |
| `generation_engine.py` | **Modify** | `run_translation(job_id)`, `_send_translation_email(job_id)`. |
| `storage_tiering.py` | **Modify** | `_OFFLOADABLE_EXT` += `.epub`, `.txt`. |
| `audiobook_app.py` | **Modify** | Endpoint: estimate, translate, progress SSE, cancel, download, adopt, paypal order translate; `register_email` kind `translated`; `/dl/<token>/translated`; concorrenza con stato `translating`. |
| `static/js/app.js` | **Modify** | `wizMode`, navigazione/etichette wizard, pannello config, stima+pagamento, avvio, SSE, completamento, adopt. |
| `templates/_fragments/html_head.html` | **Modify** | Bottone «Traduci»+badge, `panelT3`, `panelT4`, bottone adopt in panel5, CSS badge. |
| `templates/_fragments/i18n_data.js` | **Modify** | Nuove chiavi `tr_*`, `wiz_step3_tr`, `wiz_step4_tr`, `btn_translate`; `btn_export_abm` → ".ABM". |
| `i18n/download_pages.json` | **Modify** | Blocco pagina download per kind `translated`. |
| `test/test_translation_core.py` | **Create** | Unit core: chunking, UsageTracker, prompt, writers, call_llm mock. |
| `test/test_translation_pricing.py` | **Create** | Pricing: soglia free, floor, virgola decimale. |
| `test/test_run_translation.py` | **Create** | Thread: successo, errore→refund, cancel→refund, batch email. |
| `test/test_translate_endpoints.py` | **Create** | API: estimate, translate (validazioni/pagamento), adopt, cancel, download. |
| `PARAMETRI_CONFIGURAZIONE.md` | **Modify** | Nuove variabili `ABM_TRANSLATE_COST`, `ABM_TRANSLATE_MIN_COST`; nota che le `ABM_TRANSLATE_*` dello script ora governano anche l'app. |

**Riferimenti di riuso (verificati, con riga):**
- `run_optimization`: `generation_engine.py:1882` — struttura loop/heartbeat/refund.
- `_refund_job_payment(job_id, job, reason)`: `generation_engine.py:1793`.
- `_send_optimization_email(job_id)`: `generation_engine.py:1278` — pattern token+email.
- `_generate_optimized_abm(job_id)`: `generation_engine.py:901` — fonte per logica cover.
- `_offload_to_cloud`: `generation_engine.py:2330`; `is_offloadable`: `storage_tiering.py:43`.
- `/api/optimize_estimate`: `audiobook_app.py:7621`; `/api/optimize`: `:8125`; SSE: `:8425`.
- `_active_optimizing_for_client_unlocked`: `audiobook_app.py:849`.
- `/dl/<token>` pagina: `audiobook_app.py:8537`; `/dl/<token>/abm`: `:8653`.
- `payment._voucher_consume`: `payment.py:332`; `_voucher_refund`: `:419`; rate parsing: `:50-51`.
- Frontend: `goToStep`: `app.js:464`; `_fetchCostEstimate`: `:1907`; `startCombinedGeneration`: `:2140`; `_listenOptProgressWiz`: `:2477`; `submitEmailLate`: `:3705`; `fillLangs`: `:790`; `exportAbm`: `:1827`; stato globale: `:233-237`.

---

### Task 1: `translation_core.py` — skeleton, UsageTracker, utility testo

**Files:**
- Create: `translation_core.py`
- Test: `test/test_translation_core.py`

- [ ] **Step 1.1: Scrivi i test falliti per UsageTracker, chunking, strip fences**

```python
# test/test_translation_core.py
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
```

- [ ] **Step 1.2: Esegui i test e verifica che falliscano**

Run: `pytest test/test_translation_core.py -v --tb=short`
Expected: FAIL/ERROR con `ModuleNotFoundError: No module named 'translation_core'`

- [ ] **Step 1.3: Crea `translation_core.py` (parte 1)**

Contenuto iniziale. Le funzioni `split_text_into_chunks`, `load_tts_prompt`, `build_system_prompt`, `_strip_fences` e la costante `EDGE_LANGS_FALLBACK` sono **copiate INVARIATE** da `scripts/translate_abm.py` (rispettivamente righe 202-237, 244-257, 260-287, 433-437, 91-98) — unica differenza: in `load_tts_prompt` sostituire i `print(...)` con `log(...)` parametro (default `print`).

```python
"""translation_core.py — Core condiviso di traduzione libro via LLM.

Libreria pura usata sia dal CLI scripts/translate_abm.py sia dalla web app
(generation_engine.run_translation). Nessun import dai moduli applicativi,
nessun side effect Flask. Thread-safe: lo stato di usage è per-istanza
(UsageTracker), mai module-global.

Config (env, con fallback ABM_LLM_*): vedi PARAMETRI_CONFIGURAZIONE.md.
"""

import io
import json
import os
import re
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

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


# ---------------------------------------------------------------------------
# Config (letta a ogni chiamata: testabile con monkeypatch.setenv)
# ---------------------------------------------------------------------------

def _env(name, fallback_name="", default=""):
    v = os.environ.get(name, "").strip()
    if not v and fallback_name:
        v = os.environ.get(fallback_name, "").strip()
    return v or default


def api_key():
    return _env("ABM_TRANSLATE_API_KEY", "ABM_LLM_API_KEY")


def api_base():
    return _env("ABM_TRANSLATE_API_BASE", "ABM_LLM_API_BASE",
                "https://api.deepseek.com")


def model_name():
    return _env("ABM_TRANSLATE_MODEL", "ABM_LLM_MODEL", "deepseek-chat")


def backend_choice():
    return (_env("ABM_TRANSLATE_BACKEND") or "auto").lower()


def gcp_project():
    return _env("ABM_GCP_PROJECT_ID")


def gcp_creds_file():
    return _env("ABM_GOOGLE_CREDENTIALS_FILE")


def vertex_location():
    return _env("ABM_TRANSLATE_VERTEX_LOCATION", default="global")


def chunk_chars():
    return int(_env("ABM_TRANSLATE_CHUNK_CHARS", default="20000"))


def max_retries():
    return int(_env("ABM_TRANSLATE_MAX_RETRIES", default="4"))


def temperature():
    return float(_env("ABM_TRANSLATE_TEMPERATURE", default="0.3"))


def request_timeout():
    return float(_env("ABM_TRANSLATE_REQUEST_TIMEOUT_SEC", default="300"))


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
```

Poi, sotto, incollare le sezioni copiate dallo script (con la firma modificata di `load_tts_prompt`):

```python
# EDGE_LANGS_FALLBACK: copia invariata da scripts/translate_abm.py:91-98

# split_text_into_chunks(text, max_chars): copia invariata da scripts/translate_abm.py:202-237

def load_tts_prompt(lang, log=print):
    """Carica il prompt di ottimizzazione TTS per la lingua (fallback generic)."""
    path = PROMPT_DIR / f"prompt_tts_{lang}.md"
    if not path.exists():
        path = PROMPT_DIR / "prompt_tts_generic.md"
    if path.exists():
        try:
            log(f"[prompt] Ottimizzazione TTS: uso {path.name}")
            return path.read_text(encoding="utf-8").strip()
        except Exception as e:
            log(f"[prompt] WARNING: lettura {path} fallita: {e}")
    else:
        log(f"[prompt] WARNING: nessun prompt TTS trovato in {PROMPT_DIR}")
    return ""

# build_system_prompt(source, target, optimize): copia da scripts/translate_abm.py:260-287
#   (chiama load_tts_prompt(target) — invariato)

# _strip_fences(text): copia invariata da scripts/translate_abm.py:433-437
```

- [ ] **Step 1.4: Valida sintassi ed esegui i test**

Run: `python -m py_compile translation_core.py`
Run: `pytest test/test_translation_core.py -v --tb=short`
Expected: PASS (tutti)

- [ ] **Step 1.5: Commit**

```
git add translation_core.py test/test_translation_core.py
git commit -m "feat(translate): translation_core skeleton - UsageTracker, chunking, prompt utils"
```

---

### Task 2: `translation_core.py` — layer LLM (backend, call_llm con callback, titoli)

**Files:**
- Modify: `translation_core.py`
- Test: `test/test_translation_core.py` (append)

- [ ] **Step 2.1: Scrivi i test falliti**

Append a `test/test_translation_core.py`:

```python
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
    assert tc.is_available() is True
    monkeypatch.delenv("ABM_TRANSLATE_API_KEY")
    monkeypatch.delenv("ABM_LLM_API_KEY", raising=False)
    assert tc.is_available() is False
```

- [ ] **Step 2.2: Esegui — verifica che i nuovi test falliscano**

Run: `pytest test/test_translation_core.py -v --tb=short -k "call_llm or titles or backend or available"`
Expected: FAIL con `AttributeError` (funzioni non definite)

- [ ] **Step 2.3: Implementa il layer LLM in `translation_core.py`**

`resolve_backend` e `make_client_provider` derivano da `scripts/translate_abm.py:294-375` con queste differenze: env letti via le funzioni `api_key()`/`gcp_project()`/ecc. (non costanti module-level), `sys.exit(...)` → `raise TranslationConfigError(...)`.

```python
# ---------------------------------------------------------------------------
# Backend LLM
# ---------------------------------------------------------------------------

def _vertex_ready():
    return bool(gcp_project()) and bool(gcp_creds_file()) \
        and os.path.isfile(gcp_creds_file())


def resolve_backend():
    """Risolve il backend LLM. Ritorna "vertex" | "apikey".
    Solleva TranslationConfigError se la config richiesta è incompleta."""
    choice = backend_choice()
    if choice == "vertex":
        if not _vertex_ready():
            raise TranslationConfigError(
                "backend vertex richiesto ma config incompleta: servono "
                "ABM_GCP_PROJECT_ID e ABM_GOOGLE_CREDENTIALS_FILE (file leggibile)")
        return "vertex"
    if choice == "apikey":
        if not api_key():
            raise TranslationConfigError(
                "backend apikey richiesto ma nessuna API key: imposta "
                "ABM_TRANSLATE_API_KEY (o ABM_LLM_API_KEY)")
        return "apikey"
    if _vertex_ready():
        return "vertex"
    if api_key():
        return "apikey"
    raise TranslationConfigError(
        "nessun backend LLM configurato: imposta ABM_GCP_PROJECT_ID + "
        "ABM_GOOGLE_CREDENTIALS_FILE (Vertex) oppure ABM_TRANSLATE_API_KEY")


def is_available():
    """True se un backend LLM di traduzione è configurato."""
    try:
        resolve_backend()
        return True
    except TranslationConfigError:
        return False


def _vertex_base_url():
    loc = vertex_location()
    host = "aiplatform.googleapis.com" if loc == "global" \
        else f"{loc}-aiplatform.googleapis.com"
    return (f"https://{host}/v1/projects/{gcp_project()}/locations/"
            f"{loc}/endpoints/openapi")


def make_client_provider(backend):
    """Ritorna (provider, model, base_url). provider() restituisce un client
    OpenAI pronto; per Vertex rinnova il bearer token prima della scadenza."""
    from openai import OpenAI

    if backend == "apikey":
        client = OpenAI(api_key=api_key(), base_url=api_base(),
                        timeout=request_timeout())
        return (lambda: client), model_name(), api_base()

    from google.oauth2 import service_account
    from google.auth.transport.requests import Request as _GAuthRequest

    creds = service_account.Credentials.from_service_account_file(
        gcp_creds_file(),
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    base_url = _vertex_base_url()
    mdl = model_name()
    model = mdl if "/" in mdl else f"google/{mdl}"
    state = {"client": None}

    def provider():
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        expiry = getattr(creds, "expiry", None)
        near_expiry = (expiry is not None and
                       (expiry - now).total_seconds() < 300)
        if not creds.valid or near_expiry or state["client"] is None:
            creds.refresh(_GAuthRequest())
            state["client"] = OpenAI(api_key=creds.token, base_url=base_url,
                                     timeout=request_timeout())
        return state["client"]

    return provider, model, base_url


# ---------------------------------------------------------------------------
# Chiamate LLM
# ---------------------------------------------------------------------------

def call_llm(client_provider, system_prompt, user_content, *, model, usage,
             label="", progress_cb=None, cancel_cb=None, log=print):
    """Chiamata LLM streaming con retry esponenziale. Ritorna il testo.

    usage: UsageTracker dell'esecuzione (anche stato no_stream_options).
    progress_cb(received_chars): notificata col cumulativo caratteri ricevuti.
    cancel_cb() -> bool: se True a inizio chiamata o tra gli eventi dello
    stream, solleva TranslationCancelled.
    """
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content},
    ]
    retries = max_retries()
    last_exc = None
    attempt = 0
    while attempt < retries:
        if cancel_cb and cancel_cb():
            raise TranslationCancelled("cancelled before LLM call")
        try:
            client = client_provider()
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature(),
                "stream": True,
            }
            if not usage.no_stream_options:
                kwargs["stream_options"] = {"include_usage": True}
            stream = client.chat.completions.create(**kwargs)
            parts = []
            received = 0
            usage_obj = None
            for event in stream:
                if cancel_cb and cancel_cb():
                    raise TranslationCancelled("cancelled mid-stream")
                if event.choices and event.choices[0].delta.content:
                    chunk = event.choices[0].delta.content
                    parts.append(chunk)
                    received += len(chunk)
                    if progress_cb:
                        progress_cb(received)
                if getattr(event, "usage", None):
                    usage_obj = event.usage
            text = _strip_fences("".join(parts))
            usage.track(system_prompt, user_content, text, usage_obj)
            return text
        except TranslationCancelled:
            raise
        except KeyboardInterrupt:
            raise
        except Exception as e:
            # Provider senza stream_options: disabilita e riprova subito
            # senza consumare un tentativo (errore di config, non transient).
            if not usage.no_stream_options and "stream_options" in str(e).lower():
                usage.no_stream_options = True
                log(f"  {label} [LLM] provider senza stream_options: "
                    f"report costi in modalità stima")
                continue
            last_exc = e
            if attempt >= retries - 1:
                break
            wait = 2 ** attempt  # 1, 2, 4, 8 secondi
            log(f"  {label} [LLM] {type(e).__name__} (tentativo "
                f"{attempt + 1}/{retries}), riprovo tra {wait}s: {e}")
            time.sleep(wait)
            attempt += 1
        else:
            attempt += 1
    raise TranslationError(
        f"Chiamata LLM fallita dopo {retries} tentativi: {last_exc}")


def translate_titles(client_provider, titles, source, target, *, model,
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
        raw = call_llm(client_provider, system,
                       json.dumps(titles, ensure_ascii=False),
                       model=model, usage=usage, label="[titoli]", log=log)
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
```

**Attenzione al loop retry:** nel ramo `try` riuscito si fa `return`, quindi l'`attempt += 1` serve solo nel ramo eccezione (come nello script originale, che incrementa dentro l'except). Replica esattamente la struttura mostrata sopra (incremento in `except`, `continue` senza incremento per il fallback stream_options): il test `test_call_llm_stream_options_fallback` verifica che il fallback non consumi tentativi. Rimuovere il ramo `else: attempt += 1` se il linter lo segnala irraggiungibile dopo `return`.

- [ ] **Step 2.4: Valida ed esegui**

Run: `python -m py_compile translation_core.py`
Run: `pytest test/test_translation_core.py -v --tb=short`
Expected: PASS (tutti)

- [ ] **Step 2.5: Commit**

```
git add translation_core.py test/test_translation_core.py
git commit -m "feat(translate): translation_core LLM layer - backend, call_llm con callback, titoli"
```

---

### Task 3: `translation_core.py` — writer .abm / .epub / .txt

**Files:**
- Modify: `translation_core.py`
- Test: `test/test_translation_core.py` (append)

- [ ] **Step 3.1: Scrivi i test falliti**

Append a `test/test_translation_core.py`:

```python
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
```

- [ ] **Step 3.2: Esegui — verifica fallimento**

Run: `pytest test/test_translation_core.py -v --tb=short -k "write or writer"`
Expected: FAIL con `AttributeError`

- [ ] **Step 3.3: Implementa i writer**

`_safe_filename`, `write_abm`, `write_epub`: **copia INVARIATA** da `scripts/translate_abm.py` (righe 539-541, 544-592, 595-639). Aggiungi in coda:

```python
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


_WRITERS = {"abm": None, "epub": None, "txt": None}  # popolato sotto


def writer_for_format(fmt):
    """Ritorna la funzione writer per il formato. ValueError se sconosciuto."""
    w = {"abm": write_abm, "epub": write_epub, "txt": write_txt}.get(fmt)
    if w is None:
        raise ValueError(f"formato output non supportato: {fmt!r}")
    return w
```

(Rimuovere la riga `_WRITERS = ...` se inutilizzata — il dict letterale dentro `writer_for_format` basta.)

- [ ] **Step 3.4: Valida ed esegui tutto il file di test**

Run: `python -m py_compile translation_core.py`
Run: `pytest test/test_translation_core.py -v --tb=short`
Expected: PASS (tutti)

- [ ] **Step 3.5: Commit**

```
git add translation_core.py test/test_translation_core.py
git commit -m "feat(translate): translation_core writer abm/epub/txt"
```

---

### Task 4: Refactor CLI `scripts/translate_abm.py`

**Files:**
- Rewrite: `scripts/translate_abm.py`

- [ ] **Step 4.1: Baseline pre-refactor (dry-run)**

Serve un .abm di test. Crearne uno minimale via PowerShell+Python:

```
python -c "import io,json,zipfile; zf=zipfile.ZipFile('_test_book.abm','w'); zf.writestr('chapters/001_uno.txt','Testo di prova capitolo uno.'); zf.writestr('manifest.json',json.dumps({'format':'audiobook-maker-project','format_version':'1.0','title':'Test','author':'A','language':'it','has_cover':False,'cover_file':'','chapters':[{'index':1,'filename':'001_uno.txt','title':'Uno','word_count':5}]})); zf.close()"
```

Run: `python scripts/translate_abm.py _test_book.abm it en --dry-run`
Expected: output `Fatto: _test_book_en.abm` + report `[costo] DRY-RUN ...`. Salvare l'output come riferimento.

- [ ] **Step 4.2: Riscrivi lo script come CLI sottile**

Sostituire il contenuto di `scripts/translate_abm.py`. Restano locali allo script: docstring (aggiornata), `parse_abm` + `_safe_member` (righe 105-171 attuali, invariate), `get_edge_languages` (righe 178-195, invariata), `print_cost_report`, `main`. Tutto il resto viene da `translation_core`.

```python
#!/usr/bin/env python3
"""
translate_abm.py — Traduzione standalone di un progetto .abm in un'altra lingua.

CLI sottile sopra translation_core.py (libreria condivisa con la web app).
Prende un file .abm, lingua origine e destinazione, e produce un nuovo
.abm/.epub/.txt tradotto via LLM. Con --optimize integra nello stesso
passaggio LLM l'ottimizzazione del testo per la narrazione TTS.

Uso:
    python scripts/translate_abm.py libro.abm it en [--optimize]
        [--format abm|epub|txt] [--output out.abm] [--dry-run]

Configurazione: vedi translation_core.py e PARAMETRI_CONFIGURAZIONE.md
(env ABM_TRANSLATE_* con fallback ABM_LLM_*).

Report costi (solo CLI):
    ABM_TRANSLATE_INPUT_USD_PER_MTOK   (default 0.10 — gemini-2.5-flash-lite)
    ABM_TRANSLATE_OUTPUT_USD_PER_MTOK  (default 0.40 — gemini-2.5-flash-lite)
    ABM_TRANSLATE_USD_EUR_RATE         (default 0.86)
"""

import argparse
import json
import os
import re
import sys
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

import translation_core as tc  # noqa: E402

INPUT_USD_PER_MTOK = float(os.environ.get("ABM_TRANSLATE_INPUT_USD_PER_MTOK", "0.10"))
OUTPUT_USD_PER_MTOK = float(os.environ.get("ABM_TRANSLATE_OUTPUT_USD_PER_MTOK", "0.40"))
USD_EUR_RATE = float(os.environ.get("ABM_TRANSLATE_USD_EUR_RATE", "0.86"))


# parse_abm + _safe_member: INVARIATI (copiare dalle righe 105-171 della
# versione precedente dello script — restano qui perché la app ha il suo
# parse_abm con BookInfo e il core non deve dipendere dal formato input CLI).

# get_edge_languages: INVARIATA (righe 178-195 della versione precedente,
# usa tc.EDGE_LANGS_FALLBACK come fallback statico).


def print_cost_report(usage, dry_run):
    """Stampa il riepilogo costi dell'esecuzione (da UsageTracker.report())."""
    r = usage.report()
    if r["calls"] == 0:
        if dry_run:
            print("[costo] DRY-RUN senza testo: nessun costo")
        return
    pt, ct = r["prompt_tokens"], r["completion_tokens"]
    in_usd = pt / 1e6 * INPUT_USD_PER_MTOK
    out_usd = ct / 1e6 * OUTPUT_USD_PER_MTOK
    tot_usd = in_usd + out_usd
    tot_eur = tot_usd * USD_EUR_RATE
    tag = " (STIMA da caratteri)" if r["estimated"] else ""
    head = "[costo] DRY-RUN — costo che AVREBBE avuto l'operazione:" \
        if dry_run else "[costo] Costo dell'operazione:"
    print(head)
    print(f"[costo]   Token input: {pt:,} | output: {ct:,}{tag} "
          f"su {r['calls']} chiamate LLM")
    print(f"[costo]   ${in_usd:.4f} input + ${out_usd:.4f} output = "
          f"${tot_usd:.4f} USD  ~  €{tot_eur:.4f} EUR "
          f"(tasso {USD_EUR_RATE}, tariffe {INPUT_USD_PER_MTOK}/"
          f"{OUTPUT_USD_PER_MTOK} $/Mtok)")


def main():
    ap = argparse.ArgumentParser(
        description="Traduce un progetto .abm in un'altra lingua via LLM.")
    ap.add_argument("abm_file", help="File .abm di input")
    ap.add_argument("source_lang", help="Lingua di origine (codice ISO, es. it)")
    ap.add_argument("target_lang",
                    help="Lingua di destinazione (codice ISO, tra le lingue "
                         "delle voci standard edge-tts)")
    ap.add_argument("--optimize", action="store_true",
                    help="Integra l'ottimizzazione AI del testo per TTS")
    ap.add_argument("--format", choices=("abm", "epub", "txt"), default="abm",
                    help="Formato di output: abm (default), epub o txt")
    ap.add_argument("--output", help="Path del file di output "
                                     "(default: <input>_<target>.<formato>)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Pipeline completa senza chiamate LLM (pass-through)")
    args = ap.parse_args()

    in_path = Path(args.abm_file)
    if not in_path.is_file():
        sys.exit(f"Errore: file non trovato: {in_path}")

    source = args.source_lang.strip().lower().split("-")[0]
    target = args.target_lang.strip().lower().split("-")[0]
    if not re.fullmatch(r"[a-z]{2,3}", source):
        sys.exit(f"Errore: codice lingua origine non valido: '{args.source_lang}'")
    if not re.fullmatch(r"[a-z]{2,3}", target):
        sys.exit(f"Errore: codice lingua destinazione non valido: '{args.target_lang}'")
    if source == target:
        sys.exit("Errore: lingua di origine e destinazione coincidono")

    edge_langs, langs_source = get_edge_languages()
    if target not in edge_langs:
        sys.exit(f"Errore: lingua destinazione '{target}' non disponibile tra "
                 f"le voci standard edge-tts (lista {langs_source}). "
                 f"Lingue valide: {', '.join(sorted(edge_langs))}")

    usage = tc.UsageTracker()
    client_provider = None
    model = tc.model_name()
    if not args.dry_run:
        try:
            backend = tc.resolve_backend()
        except tc.TranslationConfigError as e:
            sys.exit(f"Errore: {e}")
        client_provider, model, base_url = tc.make_client_provider(backend)

    manifest, chapters, cover = parse_abm(in_path)
    total_chars = sum(len(ch["text"]) for ch in chapters)
    print(f"Progetto: \"{manifest.get('title', in_path.stem)}\" — "
          f"{len(chapters)} capitoli, {total_chars} caratteri")
    print(f"Traduzione {source} -> {target}"
          + (" + ottimizzazione TTS" if args.optimize else "")
          + (" [DRY-RUN]" if args.dry_run else ""))
    if not args.dry_run:
        print(f"Backend: {backend} | Modello: {model} @ {base_url}")

    system_prompt = tc.build_system_prompt(source, target, args.optimize)

    out_chapters = []
    for i, ch in enumerate(chapters, 1):
        chunks = tc.split_text_into_chunks(ch["text"], tc.chunk_chars())
        print(f"[{i}/{len(chapters)}] \"{ch['title']}\" "
              f"({len(ch['text'])} caratteri, {len(chunks)} chunk)")
        translated_parts = []
        for j, chunk in enumerate(chunks, 1):
            label = f"[cap {i}/{len(chapters)} chunk {j}/{len(chunks)}]"
            if args.dry_run:
                usage.track(system_prompt, chunk, chunk)
                translated_parts.append(chunk)
            else:
                translated_parts.append(tc.call_llm(
                    client_provider, system_prompt, chunk,
                    model=model, usage=usage, label=label,
                    progress_cb=lambda n, _l=label: print(
                        f"\r  {_l} ricevuti {n} caratteri...", end="", flush=True)))
                print()
        out_chapters.append({
            "index": ch["index"],
            "title": ch["title"],
            "text": "\n\n".join(translated_parts),
        })

    print("Traduzione titoli capitoli...")
    titles = [ch["title"] for ch in out_chapters]
    translated_titles = tc.translate_titles(
        client_provider, titles, source, target,
        model=model, usage=usage, dry_run=args.dry_run)
    for ch, t in zip(out_chapters, translated_titles):
        ch["title"] = t.strip() or ch["title"]

    out_path = Path(args.output) if args.output \
        else in_path.with_name(f"{in_path.stem}_{target}.{args.format}")
    tc.writer_for_format(args.format)(
        out_path, manifest, out_chapters, cover, source, target, args.optimize)
    print(f"Fatto: {out_path}")
    print_cost_report(usage, args.dry_run)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4.3: Verifica equivalenza dry-run**

Run: `python -m py_compile scripts/translate_abm.py`
Run: `python scripts/translate_abm.py _test_book.abm it en --dry-run`
Expected: stesso esito della baseline (Step 4.1): `Fatto: _test_book_en.abm`, report `[costo] DRY-RUN` con stessi token stimati.

Run: `python scripts/translate_abm.py _test_book.abm it en --dry-run --format txt`
Expected: `Fatto: _test_book_en.txt` e file leggibile.

Pulizia: `Remove-Item _test_book*.abm, _test_book*.txt -Confirm:$false`

- [ ] **Step 4.4: Commit**

```
git add scripts/translate_abm.py
git commit -m "refactor(translate): CLI sottile sopra translation_core (opzione B), +formato txt"
```

---

### Task 5: `payment.py` — pricing traduzione

**Files:**
- Modify: `payment.py` (accanto a `_estimate_llm_cost_eur`, ~riga 64)
- Test: `test/test_translation_pricing.py`

- [ ] **Step 5.1: Scrivi i test falliti**

```python
# test/test_translation_pricing.py
import importlib
import pytest


@pytest.fixture
def pay(monkeypatch):
    """payment ricaricato con env di default note."""
    monkeypatch.setenv("ABM_TRANSLATE_COST", "3.0")
    monkeypatch.setenv("ABM_TRANSLATE_MIN_COST", "1.5")
    monkeypatch.setenv("ABM_LLM_RATE_EUR_PER_MCHAR", "1.10")
    monkeypatch.setenv("ABM_LLM_FREE_THRESHOLD_EUR", "0.50")
    import payment
    importlib.reload(payment)
    yield payment
    importlib.reload(payment)  # ripristina (env tornano com'erano)


def test_small_book_is_free(pay):
    # 100k chars: raw = 0.30 ≤ 0.50 → gratis
    est = pay._estimate_translation_cost_eur(100_000, optimize=False)
    assert est["raw_eur"] == 0.30
    assert est["requires_payment"] is False
    assert est["due_eur"] == 0.0


def test_floor_applies_when_paid(pay):
    # 300k chars: raw = 0.90 > 0.50 → dovuto = max(0.90, 1.5) = 1.5
    est = pay._estimate_translation_cost_eur(300_000, optimize=False)
    assert est["requires_payment"] is True
    assert est["due_eur"] == 1.5


def test_large_book_above_floor(pay):
    # 1M chars: raw = 3.0 → dovuto 3.0
    est = pay._estimate_translation_cost_eur(1_000_000, optimize=False)
    assert est["due_eur"] == 3.0


def test_optimize_adds_llm_rate(pay):
    # 1M chars + opt: raw = 3.0 + 1.10 = 4.10
    est = pay._estimate_translation_cost_eur(1_000_000, optimize=True)
    assert est["raw_eur"] == 4.10
    assert est["due_eur"] == 4.10


def test_optimize_counts_toward_free_threshold(pay):
    # 130k chars + opt: raw = 0.39 + 0.143 = 0.53 > 0.50 → si paga, floor 1.5
    est = pay._estimate_translation_cost_eur(130_000, optimize=True)
    assert est["requires_payment"] is True
    assert est["due_eur"] == 1.5


def test_comma_decimal_env(monkeypatch):
    monkeypatch.setenv("ABM_TRANSLATE_COST", "3,5")
    monkeypatch.setenv("ABM_TRANSLATE_MIN_COST", "1,5")
    import payment
    importlib.reload(payment)
    assert payment.TRANSLATE_RATE_EUR_PER_MCHAR == 3.5
    assert payment.TRANSLATE_MIN_COST_EUR == 1.5
    monkeypatch.delenv("ABM_TRANSLATE_COST")
    monkeypatch.delenv("ABM_TRANSLATE_MIN_COST")
    importlib.reload(payment)
```

- [ ] **Step 5.2: Esegui — verifica fallimento**

Run: `pytest test/test_translation_pricing.py -v --tb=short`
Expected: FAIL con `AttributeError: ... _estimate_translation_cost_eur`

- [ ] **Step 5.3: Implementa in `payment.py`**

Subito dopo le costanti `LLM_RATE_EUR_PER_MCHAR` / `LLM_FREE_THRESHOLD_EUR` (`payment.py:50-51`):

```python
# Traduzione libro: €/M caratteri input e costo minimo (floor sul totale,
# applicato solo quando si paga). Accettano virgola decimale.
TRANSLATE_RATE_EUR_PER_MCHAR = float(
    os.environ.get("ABM_TRANSLATE_COST", "3.0").replace(",", "."))
TRANSLATE_MIN_COST_EUR = float(
    os.environ.get("ABM_TRANSLATE_MIN_COST", "1.5").replace(",", "."))
```

Subito dopo `_estimate_llm_cost_eur` (`payment.py:64-66`):

```python
def _estimate_translation_cost_eur(char_count, optimize=False):
    """Stima costo traduzione (+ eventuale ottimizzazione AI integrata).

    raw = chars/1M × TRANSLATE_RATE (+ chars/1M × LLM_RATE se optimize).
    Se raw ≤ LLM_FREE_THRESHOLD_EUR → gratis (due=0).
    Altrimenti due = max(raw, TRANSLATE_MIN_COST_EUR) — floor sul totale.
    """
    raw = (char_count / 1_000_000.0) * TRANSLATE_RATE_EUR_PER_MCHAR
    if optimize:
        raw += (char_count / 1_000_000.0) * LLM_RATE_EUR_PER_MCHAR
    raw = round(raw, 2)
    requires = raw > LLM_FREE_THRESHOLD_EUR
    due = round(max(raw, TRANSLATE_MIN_COST_EUR), 2) if requires else 0.0
    return {
        "chars": char_count,
        "raw_eur": raw,
        "due_eur": due,
        "requires_payment": requires,
        "rate_eur_per_mchar": TRANSLATE_RATE_EUR_PER_MCHAR,
        "min_cost_eur": TRANSLATE_MIN_COST_EUR,
        "free_threshold_eur": LLM_FREE_THRESHOLD_EUR,
        "optimize": bool(optimize),
    }
```

- [ ] **Step 5.4: Valida ed esegui**

Run: `python -m py_compile payment.py`
Run: `pytest test/test_translation_pricing.py -v --tb=short`
Expected: PASS

- [ ] **Step 5.5: Commit**

```
git add payment.py test/test_translation_pricing.py
git commit -m "feat(translate): pricing traduzione (ABM_TRANSLATE_COST, ABM_TRANSLATE_MIN_COST)"
```

---

### Task 6: `generation_engine.py` — `run_translation` + email batch; offload .epub/.txt

**Files:**
- Modify: `generation_engine.py` (dopo `run_optimization`, ~riga 2127)
- Modify: `storage_tiering.py:43`
- Test: `test/test_run_translation.py`

**Prerequisito di lettura per l'esecutore:** aprire `generation_engine.py:1882-2127` (`run_optimization`) e `:1278-1416` (`_send_optimization_email`) come riferimento ravvicinato — `run_translation` e `_send_translation_email` ne replicano la forma. Verificare i nomi esatti di: `_jobs` (dict job iniettato da `configure()`), `_set_job_status`, `_refund_job_payment`, `_download_tokens`, `_save_tokens`, `UPLOAD_DIR`, `BASE_URL`, `LLM_HEARTBEAT_TIMEOUT_SEC`, `_spawn_cloud_offload`, e l'helper email (`email_service` o wrapper locale `_send_email`). Se un nome differisce, adeguare il codice qui sotto al nome reale — la struttura resta quella.

- [ ] **Step 6.1: Scrivi i test falliti**

```python
# test/test_run_translation.py
import time
import types
import pytest
from pathlib import Path
from unittest.mock import patch

import generation_engine as ge
import translation_core as tc


class _Ch:
    def __init__(self, index, title, text):
        self.index, self.title, self.text = index, title, text
        self.char_count = len(text)
        self.word_count = len(text.split())


class _Info:
    title = "Libro"
    author = "Autore"
    language = "it"
    def __init__(self):
        self.chapters = [_Ch(1, "Uno", "Testo uno."), _Ch(2, "Due", "Testo due.")]


def _seed_job(tmp_path, **extra):
    job_id = "TRJOB1"
    job = {
        "status": "translating",
        "client_id": "c1",
        "info": _Info(),
        "original_filename": "libro.epub",
        "last_poll": time.time(),
        "tr_params": {
            "source_lang": "it", "target_lang": "en",
            "output_format": "txt", "output_name": "libro",
            "optimize": False, "selected_chapters": [1, 2],
        },
    }
    job.update(extra)
    ge._jobs[job_id] = job
    return job_id, job


@pytest.fixture
def fake_llm(monkeypatch, tmp_path):
    """Mock del layer LLM del core: traduzione = upper()."""
    monkeypatch.setattr(ge, "UPLOAD_DIR", tmp_path, raising=True)
    monkeypatch.setattr(tc, "resolve_backend", lambda: "apikey")
    monkeypatch.setattr(tc, "make_client_provider",
                        lambda b: ((lambda: None), "m", "http://x"))
    monkeypatch.setattr(
        tc, "call_llm",
        lambda provider, sys_p, user, **kw: user.upper())
    monkeypatch.setattr(
        tc, "translate_titles",
        lambda provider, titles, s, t, **kw: [x + "_EN" for x in titles])
    yield


def test_run_translation_success_writes_file(fake_llm, tmp_path):
    job_id, job = _seed_job(tmp_path)
    ge.run_translation(job_id)
    assert job["status"] == "translated"
    out = Path(job["translated_path"])
    assert out.exists() and out.suffix == ".txt"
    body = out.read_text(encoding="utf-8")
    assert "TESTO UNO." in body
    assert job["translated_name"] == "libro.txt"
    assert [c["title"] for c in job["translated_chapters"]] == ["Uno_EN", "Due_EN"]
    assert job["translated_lang"] == "en"


def test_run_translation_respects_selection(fake_llm, tmp_path):
    job_id, job = _seed_job(tmp_path)
    job["tr_params"]["selected_chapters"] = [2]
    ge.run_translation(job_id)
    assert len(job["translated_chapters"]) == 1
    assert job["translated_chapters"][0]["text"] == "TESTO DUE."


def test_run_translation_error_refunds(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path, payment_type="voucher",
                            payment_token="V1", payment_amount_eur=2.0)
    def _boom(*a, **kw):
        raise tc.TranslationError("LLM giù")
    monkeypatch.setattr(tc, "call_llm", _boom)
    refunds = []
    monkeypatch.setattr(ge, "_refund_job_payment",
                        lambda jid, j, reason: refunds.append((jid, reason)))
    ge.run_translation(job_id)
    assert job["status"] == "error"
    assert refunds == [(job_id, "error")]


def test_run_translation_cancel_refunds_and_reverts(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path, tr_cancelled=True,
                            payment_type="voucher", payment_token="V1")
    refunds = []
    monkeypatch.setattr(ge, "_refund_job_payment",
                        lambda jid, j, reason: refunds.append(reason))
    ge.run_translation(job_id)
    assert job["status"] == "analyzed"
    assert refunds == ["cancel"]


def test_run_translation_heartbeat_timeout_cancels(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path)
    job["last_poll"] = time.time() - 9999
    refunds = []
    monkeypatch.setattr(ge, "_refund_job_payment",
                        lambda jid, j, reason: refunds.append(reason))
    ge.run_translation(job_id)
    assert job["status"] == "analyzed"
    assert refunds == ["cancel"]


def test_run_translation_batch_skips_heartbeat_and_sends_email(fake_llm, tmp_path, monkeypatch):
    job_id, job = _seed_job(tmp_path, email_registered=True,
                            notify_email="u@x.it")
    job["last_poll"] = time.time() - 9999  # ignorato in batch
    sent = []
    monkeypatch.setattr(ge, "_send_translation_email",
                        lambda jid: sent.append(jid))
    ge.run_translation(job_id)
    assert job["status"] == "translated"
    assert sent == [job_id]
```

- [ ] **Step 6.2: Esegui — verifica fallimento**

Run: `pytest test/test_run_translation.py -v --tb=short`
Expected: FAIL con `AttributeError: ... run_translation`

- [ ] **Step 6.3: Implementa `run_translation` in `generation_engine.py`**

In testa al file, accanto agli altri import: `import translation_core`.
Dopo `run_optimization` (~riga 2127):

```python
def run_translation(job_id):
    """Background thread: traduce i capitoli selezionati via LLM e scrive
    il file di output (abm/epub/txt). Parametri in job["tr_params"].
    Pattern speculare a run_optimization (heartbeat, refund, batch email).
    """
    job = _jobs.get(job_id)
    if not job:
        return
    p = job.get("tr_params") or {}
    source = p.get("source_lang", "")
    target = p.get("target_lang", "")
    optimize = bool(p.get("optimize"))
    out_format = p.get("output_format", "abm")
    out_name = p.get("output_name") or "translated"
    info = job.get("info")
    start_time = time.time()

    sel = p.get("selected_chapters") or [ch.index for ch in info.chapters]
    sel = set(sel)
    chapters = [{"index": ch.index, "title": ch.title, "text": ch.text}
                for ch in info.chapters if ch.index in sel]
    total_chars = sum(len(c["text"]) for c in chapters)

    job["tr_progress_current"] = 0
    job["tr_progress_total"] = len(chapters)
    job["tr_total_chars"] = total_chars
    job["tr_processed_chars"] = 0
    job["tr_streamed_chars"] = 0
    job["tr_elapsed_seconds"] = 0
    job["tr_progress_message"] = "Starting translation..."

    def _log(msg):
        print(f"[{job_id}] {msg}", flush=True)

    def _cancelled():
        if job.get("tr_cancelled"):
            return True
        if not job.get("email_registered"):
            last_poll = job.get("last_poll", start_time)
            if time.time() - last_poll > LLM_HEARTBEAT_TIMEOUT_SEC:
                return True
        return False

    usage = translation_core.UsageTracker()
    try:
        if _cancelled():
            raise translation_core.TranslationCancelled("cancelled at start")
        backend = translation_core.resolve_backend()
        provider, model, base_url = translation_core.make_client_provider(backend)
        _log(f"translation start {source}->{target} fmt={out_format} "
             f"opt={optimize} backend={backend} model={model} "
             f"chapters={len(chapters)} chars={total_chars}")
        system_prompt = translation_core.build_system_prompt(
            source, target, optimize)

        out_chapters = []
        for i, ch in enumerate(chapters):
            if _cancelled():
                raise translation_core.TranslationCancelled("cancelled")
            job["tr_progress_current"] = i
            job["tr_current_chapter"] = ch["title"]
            job["tr_current_chapter_num"] = i + 1
            job["tr_elapsed_seconds"] = round(time.time() - start_time)
            job["tr_progress_message"] = f"Translating chapter {i + 1}/{len(chapters)}"
            chunks = translation_core.split_text_into_chunks(
                ch["text"], translation_core.chunk_chars())
            parts = []
            done_in_chapter = 0
            for chunk in chunks:
                base = done_in_chapter

                def _pcb(n, _base=base):
                    job["tr_streamed_chars"] = job["tr_processed_chars"] + _base + n

                parts.append(translation_core.call_llm(
                    provider, system_prompt, chunk,
                    model=model, usage=usage,
                    label=f"[cap {i + 1}]",
                    progress_cb=_pcb, cancel_cb=_cancelled, log=_log))
                done_in_chapter += len(chunk)
            out_chapters.append({
                "index": ch["index"],
                "title": ch["title"],
                "text": "\n\n".join(parts),
            })
            job["tr_processed_chars"] += len(ch["text"])

        job["tr_progress_message"] = "Translating chapter titles..."
        titles = [c["title"] for c in out_chapters]
        translated_titles = translation_core.translate_titles(
            provider, titles, source, target,
            model=model, usage=usage, log=_log)
        for c, t in zip(out_chapters, translated_titles):
            c["title"] = (t or "").strip() or c["title"]

        # Scrittura output nella job dir (pattern output_<epoch> esistente)
        out_dir = Path(UPLOAD_DIR) / job_id / f"output_{int(start_time)}"
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = translation_core._safe_filename(out_name)[:80] or "translated"
        filename = f"{safe}.{out_format}"
        out_path = out_dir / filename
        manifest_src = {
            "title": getattr(info, "title", "") or "",
            "author": getattr(info, "author", "") or "",
            "original_filename": job.get("original_filename", ""),
        }
        cover = _job_cover_bytes(job_id, job)
        translation_core.writer_for_format(out_format)(
            out_path, manifest_src, out_chapters, cover,
            source, target, optimize)

        job["translated_path"] = str(out_path)
        job["translated_name"] = filename
        job["translated_chapters"] = out_chapters
        job["translated_lang"] = target
        job["translated_optimized"] = optimize
        job["tr_progress_current"] = len(chapters)
        job["tr_progress_message"] = "Translation complete"
        r = usage.report()
        _log(f"translation done: {filename} | token in={r['prompt_tokens']} "
             f"out={r['completion_tokens']} est={r['estimated']}")

        if job.get("email_registered"):
            _send_translation_email(job_id)
        _set_job_status(job, "translated")

        # Offload cold (best-effort, come per gli output audio)
        try:
            _spawn_cloud_offload(job_id, str(out_dir))
        except Exception as _e:
            _log(f"translation offload spawn failed (non-fatal): {_e}")

    except translation_core.TranslationCancelled:
        _set_job_status(job, "analyzed")  # consenti retry
        job["tr_progress_message"] = "Translation cancelled"
        job["tr_cancelled"] = True
        _refund_job_payment(job_id, job, "cancel")
    except Exception as e:
        _set_job_status(job, "error")
        job["error"] = f"Translation error: {e}"
        job["tr_progress_message"] = f"Translation error: {e}"
        _log(f"translation FAILED: {type(e).__name__}: {e}")
        _refund_job_payment(job_id, job, "error")
```

**Nota `_spawn_cloud_offload`:** verificare la firma reale a `generation_engine.py:3334` (chiamata esistente al COMPLETE) e usare la stessa forma; se richiede `when` o un job dict, adeguare.

**Nota deliberata:** la traduzione NON si registra in `pending_jobs` (il recovery non può riprendere una traduzione a metà; evita la classe di incidenti B1 sui job rimborsati).

- [ ] **Step 6.4: Implementa `_job_cover_bytes` e `_send_translation_email`**

`_job_cover_bytes(job_id, job)`: helper che ritorna `(bytes, filename)` o `None`. **Replicare esattamente la logica di risoluzione cover usata da `_generate_optimized_abm` (`generation_engine.py:901`)**: aprire quella funzione, individuare da dove legge la cover (campo job / file nella job dir) e estrarre quella logica nell'helper; poi richiamare l'helper anche da `_generate_optimized_abm` per non duplicare (refactor in-place, i test esistenti dell'abm ottimizzato la coprono).

`_send_translation_email(job_id)`: **clonare `_send_optimization_email` (`generation_engine.py:1278-1416`)** con queste differenze:

```python
# 1) token dict:
token = str(uuid.uuid4())
_download_tokens[token] = {
    "job_id": job_id,
    "created_at": time.time(),
    "download_type": "translated",
    "book_title": book_title,
    "translated_path": job.get("translated_path", ""),
    "translated_name": job.get("translated_name", ""),
    "original_filename": job.get("original_filename", ""),
    "lang": lang,
    "output_format": job.get("tr_params", {}).get("output_format", ""),
    "ai_optimized": bool(job.get("translated_optimized")),
    "is_gemini": False,
}
_save_tokens()
job["email_token"] = token

# 2) link: {BASE_URL}/dl/{token}  (la pagina mostrerà il bottone "translated")
# 3) testi email: nuovo dict _tr_email_i18n (stesse lingue di _opt_email_i18n)
#    con subject/body "La tua traduzione è pronta" — vedi Task 12 per i testi.
# 4) oggetto attività log: "EMAIL_SENT" via _log_activity come nell'originale.
```

- [ ] **Step 6.5: Estendi gli offloadable in `storage_tiering.py:43`**

```python
_OFFLOADABLE_EXT = (".mp3", ".m4b", ".zip", ".abm", ".epub", ".txt")
```

**Verifica di sicurezza obbligatoria prima del commit:** cercare con Grep quali file `.txt` possono trovarsi nelle dir `output_*` dei job (`rg "output_" generation_engine.py audio_utils.py | rg -i "txt"`). Le dir `output_*` contengono solo output finali (mp3/m4b/zip/abm + ora epub/txt tradotti); i `.txt` dei capitoli stanno altrove (dentro gli archivi). Se emergesse un `.txt` transitorio scritto in `output_*`, escluderlo per nome invece di estendere l'estensione.

- [ ] **Step 6.6: Valida ed esegui**

Run: `python -m py_compile generation_engine.py`
Run: `python -m py_compile storage_tiering.py`
Run: `pytest test/test_run_translation.py -v --tb=short`
Expected: PASS

Run anche i test esistenti di offload/eviction (regressione):
`pytest test/test_cloud_offload.py test/test_hot_eviction.py -v --tb=short`
Expected: PASS

- [ ] **Step 6.7: Commit**

```
git add generation_engine.py storage_tiering.py test/test_run_translation.py
git commit -m "feat(translate): run_translation + email batch + offload epub/txt"
```

---

### Task 7: `audiobook_app.py` — endpoint estimate / translate / progress / cancel

**Files:**
- Modify: `audiobook_app.py`
- Test: `test/test_translate_endpoints.py`

**Prerequisito di lettura:** `/api/optimize_estimate` (`:7621-7664`), `/api/optimize` (`:8125-8422`), SSE (`:8425-8479`), `_active_optimizing_for_client_unlocked` (`:849`), `_parse_selected_chapters`, `_check_job_owner`. I nuovi endpoint sono cloni adattati: mantenere stesso stile, stessi helper.

- [ ] **Step 7.1: Scrivi i test falliti**

```python
# test/test_translate_endpoints.py
import time
import pytest
from unittest.mock import patch

import audiobook_app


@pytest.fixture
def client():
    audiobook_app.app.config["TESTING"] = True
    return audiobook_app.app.test_client()


class _Ch:
    def __init__(self, index, title, text):
        self.index, self.title, self.text = index, title, text
        self.char_count = len(text)
        self.word_count = len(text.split())


class _Info:
    title = "Libro"
    author = "A"
    language = "it"
    def __init__(self):
        self.chapters = [_Ch(1, "Uno", "x" * 100_000),
                         _Ch(2, "Due", "y" * 300_000)]


def _seed(job_id="TJ1", status="analyzed", **extra):
    job = {"status": status, "client_id": "c1", "client_ip": "127.0.0.1",
           "info": _Info(), "original_filename": "libro.epub",
           "last_poll": time.time()}
    job.update(extra)
    audiobook_app.jobs[job_id] = job
    return job


def _own(job_id="TJ1"):
    return patch("audiobook_app._check_job_owner",
                 return_value=(audiobook_app.jobs[job_id], None, None))


def test_estimate_translation(client):
    _seed()
    with _own():
        r = client.get("/api/translate_estimate/TJ1?target=en&optimize=0")
    assert r.status_code == 200
    d = r.get_json()
    assert d["chars"] == 400_000
    assert d["requires_payment"] is True
    assert d["due_eur"] == max(round(0.4 * audiobook_app.payment.TRANSLATE_RATE_EUR_PER_MCHAR, 2),
                               audiobook_app.payment.TRANSLATE_MIN_COST_EUR)


def test_estimate_translation_selected_chapters(client):
    _seed()
    with _own():
        r = client.get("/api/translate_estimate/TJ1?target=en&selected_chapters=1")
    assert r.get_json()["chars"] == 100_000


def test_translate_rejects_same_lang(client):
    _seed()
    with _own():
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "it",
            "output_format": "abm"})
    assert r.status_code == 400


def test_translate_rejects_bad_format(client):
    _seed()
    with _own():
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
            "output_format": "pdf"})
    assert r.status_code == 400


def test_translate_requires_payment_above_threshold(client):
    _seed()
    with _own():
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
            "output_format": "abm"})
    assert r.status_code == 402


def test_translate_free_book_starts_thread(client, monkeypatch):
    job = _seed()
    job["info"].chapters = [_Ch(1, "Uno", "x" * 10_000)]  # sotto soglia
    started = []
    monkeypatch.setattr(audiobook_app, "run_translation",
                        lambda jid: started.append(jid), raising=False)
    import threading
    real_thread = threading.Thread
    monkeypatch.setattr(threading, "Thread",
                        lambda target, args, daemon: real_thread(
                            target=lambda: target(*args), daemon=True))
    with _own():
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
            "output_format": "txt", "output_name": "libro"})
    assert r.status_code == 200
    assert job["status"] == "translating"
    assert job["tr_params"]["target_lang"] == "en"


def test_translate_concurrency_limit(client):
    _seed("TJ1")
    _seed("TJ2", status="translating")
    with _own("TJ1"):
        r = client.post("/api/translate", json={
            "job_id": "TJ1", "source_lang": "it", "target_lang": "en",
            "output_format": "abm"})
    assert r.status_code == 429


def test_translate_cancel_sets_flag(client):
    job = _seed(status="translating")
    with _own():
        r = client.post("/api/translate_cancel/TJ1")
    assert r.status_code == 200
    assert job["tr_cancelled"] is True


def test_download_translation(client, tmp_path):
    f = tmp_path / "libro.txt"
    f.write_text("tradotto", encoding="utf-8")
    _seed(status="translated", translated_path=str(f),
          translated_name="libro.txt")
    with _own():
        r = client.get("/api/download_translation/TJ1")
    assert r.status_code == 200
    assert b"tradotto" in r.data
```

- [ ] **Step 7.2: Esegui — verifica fallimento**

Run: `pytest test/test_translate_endpoints.py -v --tb=short`
Expected: FAIL (404 sulle route mancanti / AttributeError)

- [ ] **Step 7.3: Concorrenza — estendi il conteggio a `translating`**

In `audiobook_app.py:849-856` modifica `_active_optimizing_for_client_unlocked`:

```python
def _active_optimizing_for_client_unlocked(client_id):
    """Internal: caller MUST hold _jobs_lock. Conta i job LLM attivi
    (ottimizzazione O traduzione) del client."""
    if not client_id:
        return 0
    return sum(
        1 for j in jobs.values()
        if j.get("client_id") == client_id
        and j.get("status") in ("optimizing", "translating")
    )
```

- [ ] **Step 7.4: Implementa gli endpoint (dopo `/api/optimize_progress`, ~riga 8480)**

```python
# ════════════════ TRADUZIONE LIBRO ════════════════

_TRANSLATE_FORMATS = ("abm", "epub", "txt")


def _translate_selected_chars(job, raw_sel):
    """(chars_totali, selected_indices) dei capitoli selezionati."""
    info = job.get("info")
    selected = _parse_selected_chapters(raw_sel) if raw_sel else \
        [ch.index for ch in info.chapters]
    sel = set(selected)
    chars = sum(ch.char_count for ch in info.chapters if ch.index in sel)
    return chars, selected


@app.route("/api/translate_estimate/<job_id>")
def api_translate_estimate(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    info = job.get("info")
    if not info or not info.chapters:
        return jsonify({"error": "No book data"}), 400
    raw_sel = request.args.getlist("selected_chapters") \
        + request.args.getlist("selected_chapters[]")
    optimize = (request.args.get("optimize") or "").strip() in ("1", "true")
    chars, _ = _translate_selected_chars(job, raw_sel)
    est = payment._estimate_translation_cost_eur(chars, optimize=optimize)
    est["available"] = translation_core.is_available()
    return jsonify(est)


@app.route("/api/translate", methods=["POST"])
def api_translate():
    data = request.get_json(silent=True) or {}
    job_id = (data.get("job_id") or "").strip()
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    info = job.get("info")
    if not info or not info.chapters:
        return jsonify({"error": "No book data"}), 400

    if not translation_core.is_available():
        return jsonify({"error": "Translation not configured on this server"}), 503

    source = (data.get("source_lang") or "").strip().lower().split("-")[0]
    target = (data.get("target_lang") or "").strip().lower().split("-")[0]
    import re as _re2
    if not _re2.fullmatch(r"[a-z]{2,3}", source or "") \
            or not _re2.fullmatch(r"[a-z]{2,3}", target or ""):
        return jsonify({"error": "Invalid language code"}), 400
    if source == target:
        return jsonify({"error": "Source and target language are the same",
                        "error_code": "same_lang"}), 400
    # Destinazione tra le lingue delle voci standard edge-tts
    try:
        edge_langs = set(get_voices().keys())
    except Exception:
        edge_langs = set()
    if not edge_langs:
        edge_langs = translation_core.EDGE_LANGS_FALLBACK
    if target not in edge_langs:
        return jsonify({"error": f"Target language '{target}' not supported",
                        "error_code": "bad_target_lang"}), 400

    out_format = (data.get("output_format") or "abm").strip().lower()
    if out_format not in _TRANSLATE_FORMATS:
        return jsonify({"error": f"Invalid output format '{out_format}'"}), 400
    out_name = (data.get("output_name") or "").strip() or "translated"
    optimize = bool(data.get("optimize"))
    raw_sel = data.get("selected_chapters") or []
    chars, selected = _translate_selected_chars(
        job, [str(x) for x in raw_sel])
    if chars <= 0:
        return jsonify({"error": "No chapters selected"}), 400

    est = payment._estimate_translation_cost_eur(chars, optimize=optimize)
    client_id = job.get("client_id", "")

    # Slot LLM per client (stesso slot dell'ottimizzazione) + claim atomico
    with _jobs_lock:
        if job["status"] not in ("analyzed", "translated"):
            return jsonify({"error": "Job busy or not ready"}), 400
        if client_id and MAX_CONCURRENT_LLM_PER_CLIENT > 0:
            if _active_optimizing_for_client_unlocked(client_id) >= MAX_CONCURRENT_LLM_PER_CLIENT:
                return jsonify({
                    "error": f"Concurrent LLM job limit reached ({MAX_CONCURRENT_LLM_PER_CLIENT}).",
                    "error_code": "concurrent_optimize_limit",
                }), 429
        job["status"] = "translating"

    def _release_claim():
        with _jobs_lock:
            if job.get("status") == "translating":
                job["status"] = "analyzed"

    # Pagamento (stesso flusso di /api/optimize, importo = est["due_eur"])
    if est["requires_payment"]:
        payment_token = (data.get("payment_token") or "").strip()
        if not payment_token:
            _release_claim()
            return jsonify({"error": "Payment required",
                            "error_code": "payment_required",
                            "due_eur": est["due_eur"]}), 402
        valid = False
        if payment_token in payment._payments:
            _claimed_pay = None
            with payment._payments_lock:
                pay = payment._payments.get(payment_token)
                if pay and not pay.get("used") \
                        and pay.get("amount_eur", 0) + 0.01 >= est["due_eur"]:
                    pay["used"] = True
                    pay["used_at"] = time.time()
                    pay["used_job_id"] = job_id
                    _claimed_pay = pay
            if _claimed_pay is not None:
                _save_payments()
                job["payment_token"] = payment_token
                job["payment_type"] = "paypal"
                job["payment_email"] = _claimed_pay.get("email", "")
                job["payment_amount_eur"] = _claimed_pay.get("amount_eur", 0)
                valid = True
        elif payment_token in payment._vouchers:
            v = payment._vouchers[payment_token]
            remaining = payment._voucher_remaining(v)
            if v.get("expires_at", 0) > time.time() \
                    and remaining >= est["due_eur"] - 0.01:
                try:
                    new_remaining = payment._voucher_consume(
                        payment_token, est["due_eur"], job_id=job_id)
                except ValueError as _ve:
                    _release_claim()
                    return jsonify({"error": f"Voucher not spendable: {_ve}"}), 402
                job["payment_token"] = payment_token
                job["payment_type"] = "voucher"
                job["payment_email"] = v.get("email", "")
                job["payment_amount_eur"] = round(float(est["due_eur"]), 2)
                job["voucher_remaining_after"] = new_remaining
                valid = True
        if not valid:
            _release_claim()
            return jsonify({"error": "Invalid or insufficient payment",
                            "error_code": "payment_invalid"}), 402

    # Batch mode (email)
    batch = bool(data.get("batch"))
    email = (data.get("email") or "").strip()
    if batch:
        import re as _re3
        if not email or not _re3.match(
                r'^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$', email):
            _release_claim()
            return jsonify({"error": "Valid email required for batch mode"}), 400
        if not _smtp_available():
            _release_claim()
            return jsonify({"error": "Email service not configured"}), 503
        job["notify_email"] = email
        job["notify_lang"] = data.get("lang", "en")
        job["email_registered"] = True
        job["notify_download_type"] = "translated"

    job["tr_cancelled"] = False
    job["tr_params"] = {
        "source_lang": source, "target_lang": target,
        "output_format": out_format, "output_name": out_name,
        "optimize": optimize, "selected_chapters": selected,
    }
    job["last_poll"] = time.time()

    thread = threading.Thread(target=run_translation, args=(job_id,),
                              daemon=True)
    thread.start()
    _log_activity(job_id, job.get("original_filename", ""), "TRANSLATE",
                  client_id, job.get("client_ip", ""), "",
                  browser_lang=job.get("browser_lang", ""))
    return jsonify({"status": "started", "batch": batch,
                    "due_eur": est["due_eur"]})


@app.route("/api/translate_progress/<job_id>")
def api_translate_progress(job_id):
    # Clone di /api/optimize_progress (:8425) con i campi tr_*
    def stream():
        while True:
            if job_id not in jobs:
                yield f"data: {json.dumps({'status': 'error', 'error': 'Job not found'})}\n\n"
                break
            job = jobs[job_id]
            job["last_poll"] = time.time()
            status = job.get("status", "unknown")
            payload = {
                "status": status,
                "tr_progress_current": job.get("tr_progress_current", 0),
                "tr_progress_total": job.get("tr_progress_total", 0),
                "tr_progress_message": job.get("tr_progress_message", ""),
                "tr_current_chapter": job.get("tr_current_chapter", ""),
                "tr_current_chapter_num": job.get("tr_current_chapter_num", 0),
                "tr_processed_chars": job.get("tr_processed_chars", 0),
                "tr_streamed_chars": job.get("tr_streamed_chars", 0),
                "tr_total_chars": job.get("tr_total_chars", 0),
                "tr_elapsed_seconds": job.get("tr_elapsed_seconds", 0),
                "translated_name": job.get("translated_name", ""),
                "error": job.get("error", ""),
            }
            if status == "error":
                yield f"data: {json.dumps(payload)}\n\n"
                break
            if job.get("tr_cancelled"):
                payload["status"] = "cancelled"
                yield f"data: {json.dumps(payload)}\n\n"
                break
            if status == "translated":
                yield f"data: {json.dumps(payload)}\n\n"
                break
            yield f"data: {json.dumps(payload)}\n\n"
            time.sleep(2)
    return Response(stream(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache",
                             "X-Accel-Buffering": "no"})


@app.route("/api/translate_cancel/<job_id>", methods=["POST"])
def api_translate_cancel(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    job["tr_cancelled"] = True
    return jsonify({"status": "cancelling"})


@app.route("/api/download_translation/<job_id>")
def api_download_translation(job_id):
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    path = job.get("translated_path", "")
    name = job.get("translated_name", "translated")
    if not path or not os.path.exists(path):
        _cold = _try_cold_serve(path, download_name=name)
        if _cold is not None:
            return _cold
        return jsonify({"error": "File not available"}), 404
    _log_activity(job_id, job.get("original_filename", ""),
                  "DOWNLOAD_TRANSLATION", job.get("client_id", ""),
                  job.get("client_ip", ""), "", "")
    return _send_file_throttled(path, as_attachment=True,
                                download_name=name, no_cache=True)
```

In testa a `audiobook_app.py`, accanto agli altri import: `import translation_core` e import di `run_translation` dallo stesso punto in cui si importa `run_optimization` da `generation_engine`.

**Verifiche per l'esecutore (nomi reali):** `get_voices()` (struttura ritorno: dict per lingua — vedere `:1383-1428`); `_smtp_available()`; `_try_cold_serve(path, download_name=...)` (firma usata in `/dl/<token>/abm` `:8653`); `Response` import; `MAX_CONCURRENT_LLM_PER_CLIENT`. Se `_try_cold_serve` ha firma diversa, adeguare.

- [ ] **Step 7.5: Valida ed esegui**

Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_translate_endpoints.py -v --tb=short`
Expected: PASS

Regressione concorrenza/ottimizzazione:
Run: `pytest test/ -v --tb=short -k "concurren or optimize"`
Expected: nessuna nuova failure rispetto a main (le 4 failure note `test_paypal_create_gemini` da ordering sono pre-esistenti).

- [ ] **Step 7.6: Commit**

```
git add audiobook_app.py test/test_translate_endpoints.py
git commit -m "feat(translate): endpoint estimate/translate/progress/cancel/download + slot LLM condiviso"
```

---

### Task 8: Batch email end-to-end — PayPal order, register_email, `/dl/<token>/translated`

**Files:**
- Modify: `audiobook_app.py`
- Test: `test/test_translate_endpoints.py` (append)

- [ ] **Step 8.1: Scrivi i test falliti**

Append a `test/test_translate_endpoints.py`:

```python
def test_dl_token_translated(client, tmp_path):
    f = tmp_path / "libro.epub"
    f.write_bytes(b"PK fake epub")
    audiobook_app._download_tokens["tok-tr-1"] = {
        "job_id": "TJ9", "created_at": time.time(),
        "download_type": "translated",
        "translated_path": str(f), "translated_name": "libro.epub",
        "book_title": "Libro", "lang": "it", "is_gemini": False,
    }
    r = client.get("/dl/tok-tr-1/translated")
    assert r.status_code == 200
    assert b"PK fake epub" in r.data


def test_dl_token_translated_expired(client, tmp_path):
    audiobook_app._download_tokens["tok-tr-2"] = {
        "job_id": "TJ9", "created_at": time.time() - 10 * 365 * 86400,
        "download_type": "translated",
        "translated_path": "/nope", "translated_name": "x.txt",
        "book_title": "Libro", "lang": "it", "is_gemini": False,
    }
    r = client.get("/dl/tok-tr-2/translated")
    assert r.status_code == 410


def test_paypal_create_order_translate_amount(client, monkeypatch):
    _seed("TJP")
    captured = {}
    def _fake_create(amount_eur, *a, **kw):
        captured["amount"] = amount_eur
        return {"order_id": "OID1"}
    # Adeguare il nome alla funzione reale di creazione ordine in payment.py
    monkeypatch.setattr(audiobook_app, "_paypal_create_order_impl",
                        _fake_create, raising=False)
    with _own("TJP"):
        r = client.post("/api/paypal_create_order_translate", json={
            "job_id": "TJP", "target_lang": "en", "optimize": False,
            "selected_chapters": [1, 2]})
    # 400.000 chars × 3.0/M = 1.20 → floor 1.50
    assert captured.get("amount") == 1.5 or r.status_code in (200, 503)
```

- [ ] **Step 8.2: Implementa `/dl/<token>/translated`**

Clonare `/dl/<token>/abm` (`audiobook_app.py:8653-8691`) sostituendo i campi:

```python
@app.route("/dl/<token>/translated")
def token_do_download_translated(token):
    token_info = _download_tokens.get(token)
    if not token_info:
        return "Link scaduto", 410
    _ret = _effective_retention_for_token_info(token_info)
    if time.time() - token_info["created_at"] > _ret:
        _download_tokens.pop(token, None)
        _save_tokens()
        return f"Link scaduto  -  i file sono stati cancellati dopo {_ret // 3600} ore", 410
    name = token_info.get("translated_name", "translated")
    path = token_info.get("translated_path", "")
    job_id = token_info.get("job_id", "")
    # Ricostruzione per-epoch se il path snapshot non esiste più
    if path and not os.path.exists(path) and job_id:
        job_dir = UPLOAD_DIR / job_id
        candidate = job_dir / Path(path).parent.name / Path(path).name
        if candidate.exists():
            path = str(candidate)
    if not path or not os.path.exists(path):
        _cold = _try_cold_serve(token_info.get("translated_path", ""),
                                download_name=name)
        if _cold is not None:
            return _cold
        return "File not available", 404
    _log_activity(job_id, token_info.get("original_filename", ""),
                  "DOWNLOAD_TRANSLATION_TOKEN", "", "", "", "")
    _mark_token_downloaded(token_info)
    return _send_file_throttled(path, as_attachment=True,
                                download_name=name, no_cache=True)
```

- [ ] **Step 8.3: Pagina `/dl/<token>` — bottone per kind `translated`**

In `GET /dl/<token>` (`audiobook_app.py:8537`): individuare il ramo che gestisce `download_type == "optimized_abm"` (link unico alla pagina) e aggiungere il ramo gemello `download_type == "translated"` che mostra un solo bottone «Scarica traduzione» puntato a `/dl/{token}/translated`, con testi dal blocco `translated` di `i18n/download_pages.json` (Task 12). Disponibilità file: locale (`translated_path`, con ricostruzione per-epoch) OR cold (`_cold_object_available`).

- [ ] **Step 8.4: `/api/register_email` — kind `translated`**

In `/api/register_email`: individuare la validazione di `download_type` (valori `audio|chapters|podcast`) e aggiungere `translated`. Quando `download_type == "translated"` impostare `job["notify_download_type"] = "translated"`. In `generation_engine`, nel punto in cui a fine job si decide quale email inviare (vedere `run_optimization` ramo batch), `run_translation` già chiama `_send_translation_email` direttamente — la registrazione tardiva via `/api/register_email` deve solo settare `email_registered`/`notify_email` (il resto è già letto da `_send_translation_email`).

- [ ] **Step 8.5: PayPal — `/api/paypal_create_order_translate`**

**Aprire `/api/paypal_create_order` (`audiobook_app.py:7667-7705`) e clonarlo** col nome `/api/paypal_create_order_translate`. Differenza unica: l'importo non viene dalla stima ottimizzazione ma da:

```python
raw_sel = [str(x) for x in (data.get("selected_chapters") or [])]
optimize = bool(data.get("optimize"))
chars, _ = _translate_selected_chars(job, raw_sel)
est = payment._estimate_translation_cost_eur(chars, optimize=optimize)
amount_eur = est["due_eur"]
```

Tutto il resto (creazione ordine via helper payment, descrizione, gestione errori, risposta `{order_id}`) identico all'originale — usare la stessa funzione di creazione ordine che usa l'endpoint esistente (verificarne il nome reale in `payment.py`; il test usa un monkeypatch tollerante). La cattura resta `/api/paypal_capture_order` (invariata: il token catturato finisce in `payment._payments` e viene consumato da `/api/translate`).

- [ ] **Step 8.6: Valida ed esegui**

Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_translate_endpoints.py -v --tb=short`
Expected: PASS

- [ ] **Step 8.7: Commit**

```
git add audiobook_app.py test/test_translate_endpoints.py
git commit -m "feat(translate): batch email e2e - /dl translated, register_email, paypal order"
```

---

### Task 9: `audiobook_app.py` — `/api/translate_adopt` (prosegui verso TTS)

**Files:**
- Modify: `audiobook_app.py`
- Test: `test/test_translate_endpoints.py` (append)

- [ ] **Step 9.1: Scrivi i test falliti**

Append a `test/test_translate_endpoints.py`:

```python
def test_translate_adopt_replaces_chapters(client):
    job = _seed(status="translated",
                translated_lang="en", translated_optimized=True,
                translated_chapters=[
                    {"index": 1, "title": "One", "text": "Translated one."},
                    {"index": 2, "title": "Two", "text": "Translated two."},
                ])
    with _own():
        r = client.post("/api/translate_adopt/TJ1")
    assert r.status_code == 200
    d = r.get_json()
    assert job["status"] == "analyzed"
    assert job["info"].language == "en"
    assert [c.title for c in job["info"].chapters] == ["One", "Two"]
    assert job["info"].chapters[0].text == "Translated one."
    assert job["ai_optimized"] is True
    assert sorted(job["optimized_chapters"]) == [1, 2]
    assert d["language"] == "en"
    assert len(d["chapters"]) == 2


def test_translate_adopt_requires_translated_status(client):
    _seed(status="analyzed")
    with _own():
        r = client.post("/api/translate_adopt/TJ1")
    assert r.status_code == 400
```

- [ ] **Step 9.2: Implementa l'endpoint**

Prima di scrivere, verificare i campi del dataclass `Chapter` in `epub_to_tts.py` (definizione citata dal CLAUDE.md; attesi: `index`, `title`, `text`, `word_count`, `char_count` — adeguare la costruzione se differiscono).

```python
@app.route("/api/translate_adopt/<job_id>", methods=["POST"])
def api_translate_adopt(job_id):
    """Adotta la traduzione come libro attivo: sostituisce i capitoli del
    job con quelli tradotti e torna in stato 'analyzed' per il percorso TTS."""
    job, err, sc = _check_job_owner(job_id)
    if err is not None:
        return err, sc
    if job.get("status") != "translated" or not job.get("translated_chapters"):
        return jsonify({"error": "No completed translation to adopt"}), 400
    info = job.get("info")
    from epub_to_tts import Chapter
    new_chapters = []
    for i, ch in enumerate(job["translated_chapters"], 1):
        text = ch.get("text", "")
        new_chapters.append(Chapter(
            index=i,
            title=ch.get("title", f"Chapter {i}"),
            text=text,
            word_count=len(text.split()),
            char_count=len(text),
        ))
    info.chapters = new_chapters
    info.language = job.get("translated_lang", info.language)
    # Se la traduzione includeva l'ottimizzazione TTS, i capitoli adottati
    # risultano già ottimizzati (niente doppio pagamento ottimizzazione).
    if job.get("translated_optimized"):
        job["ai_optimized"] = True
        job["optimized_chapters"] = [c.index for c in new_chapters]
    else:
        job["ai_optimized"] = False
        job["optimized_chapters"] = []
    job["status"] = "analyzed"
    job["tr_cancelled"] = False
    _log_activity(job_id, job.get("original_filename", ""), "TRANSLATE_ADOPT",
                  job.get("client_id", ""), job.get("client_ip", ""), "", "")
    return jsonify({
        "status": "analyzed",
        "language": info.language,
        "title": info.title,
        "ai_optimized": job["ai_optimized"],
        "chapters": [{"index": c.index, "title": c.title,
                      "words": c.word_count, "chars": c.char_count}
                     for c in new_chapters],
    })
```

- [ ] **Step 9.3: Valida ed esegui**

Run: `python -m py_compile audiobook_app.py`
Run: `pytest test/test_translate_endpoints.py -v --tb=short`
Expected: PASS

- [ ] **Step 9.4: Commit**

```
git add audiobook_app.py test/test_translate_endpoints.py
git commit -m "feat(translate): adopt traduzione come libro attivo per percorso TTS"
```

---

### Task 10: i18n — chiavi UI (7 lingue) + pagina download

**Files:**
- Modify: `templates/_fragments/i18n_data.js`
- Modify: `i18n/download_pages.json`
- Modify (se presenti chiavi speculari): `i18n/it.json`, `en.json`, `fr.json`, `es.json`, `de.json`, `zh.json` — **verificare prima** se questi file replicano le chiavi di `i18n_data.js`; se sì, aggiungere le stesse chiavi, altrimenti saltare.

- [ ] **Step 10.1: Modifica `btn_export_abm` in tutte le lingue**

In `i18n_data.js`, per ciascuna delle 7 lingue (`en,it,fr,es,de,zh,hi`) impostare `btn_export_abm: ".ABM"` (valore letterale identico; il tooltip `btn_export_abm_tip` resta invariato).

- [ ] **Step 10.2: Aggiungi le nuove chiavi**

Aggiungere in ogni blocco lingua di `i18n_data.js`. Valori completi:

```text
chiave                 it                                          en
btn_translate          Traduci                                     Translate
badge_new              new                                         new
wiz_step3_tr           Traduzione                                  Translation
wiz_step4_tr           Elaborazione                                Processing
tr_title               Traduci il libro                            Translate the book
tr_subtitle            Traduci il testo in un'altra lingua con l'AI   Translate the text into another language with AI
tr_lbl_source          Lingua di origine                           Source language
tr_lbl_target          Lingua di destinazione                      Target language
tr_lbl_format          Formato di output                           Output format
tr_lbl_output_name     Nome file di output                         Output file name
tr_btn_start           Avvia traduzione                            Start translation
tr_err_same_lang       La lingua di origine e destinazione coincidono   Source and target language are the same
tr_progress_title      Traduzione in corso…                        Translation in progress…
tr_progress_chapter    Capitolo {0} di {1}                         Chapter {0} of {1}
tr_done                Traduzione completata!                      Translation complete!
tr_cancelled           Traduzione annullata                        Translation cancelled
tr_btn_cancel          Annulla traduzione                          Cancel translation
tr_btn_download        Scarica traduzione                          Download translation
tr_btn_adopt           Genera audio da questa traduzione           Generate audio from this translation
tr_cost_detail         {0} caratteri da tradurre                   {0} characters to translate
tr_pay_label           Traduzione libro                            Book translation
```

```text
chiave                 fr                                          es
btn_translate          Traduire                                    Traducir
wiz_step3_tr           Traduction                                  Traducción
wiz_step4_tr           Traitement                                  Procesando
tr_title               Traduire le livre                           Traducir el libro
tr_subtitle            Traduisez le texte dans une autre langue avec l'IA   Traduce el texto a otro idioma con IA
tr_lbl_source          Langue source                               Idioma de origen
tr_lbl_target          Langue cible                                Idioma de destino
tr_lbl_format          Format de sortie                            Formato de salida
tr_lbl_output_name     Nom du fichier de sortie                    Nombre del archivo de salida
tr_btn_start           Lancer la traduction                        Iniciar traducción
tr_err_same_lang       Les langues source et cible sont identiques   El idioma de origen y destino coinciden
tr_progress_title      Traduction en cours…                        Traducción en curso…
tr_progress_chapter    Chapitre {0} sur {1}                        Capítulo {0} de {1}
tr_done                Traduction terminée !                       ¡Traducción completada!
tr_cancelled           Traduction annulée                          Traducción cancelada
tr_btn_cancel          Annuler la traduction                       Cancelar traducción
tr_btn_download        Télécharger la traduction                   Descargar traducción
tr_btn_adopt           Générer l'audio à partir de cette traduction   Generar audio desde esta traducción
tr_cost_detail         {0} caractères à traduire                   {0} caracteres a traducir
tr_pay_label           Traduction du livre                         Traducción del libro
```

```text
chiave                 de                                          zh                          hi
btn_translate          Übersetzen                                  翻译                         अनुवाद करें
wiz_step3_tr           Übersetzung                                 翻译                         अनुवाद
wiz_step4_tr           Verarbeitung                                处理中                       प्रोसेसिंग
tr_title               Buch übersetzen                             翻译图书                     पुस्तक का अनुवाद करें
tr_subtitle            Übersetzen Sie den Text mit KI in eine andere Sprache   使用 AI 将文本翻译成另一种语言   AI से पाठ का दूसरी भाषा में अनुवाद करें
tr_lbl_source          Ausgangssprache                             源语言                       स्रोत भाषा
tr_lbl_target          Zielsprache                                 目标语言                     लक्ष्य भाषा
tr_lbl_format          Ausgabeformat                               输出格式                     आउटपुट फ़ॉर्मेट
tr_lbl_output_name     Name der Ausgabedatei                       输出文件名                   आउटपुट फ़ाइल नाम
tr_btn_start           Übersetzung starten                         开始翻译                     अनुवाद शुरू करें
tr_err_same_lang       Ausgangs- und Zielsprache sind identisch    源语言和目标语言相同          स्रोत और लक्ष्य भाषा समान हैं
tr_progress_title      Übersetzung läuft…                          翻译进行中…                  अनुवाद जारी है…
tr_progress_chapter    Kapitel {0} von {1}                         第 {0} 章，共 {1} 章          अध्याय {0} / {1}
tr_done                Übersetzung abgeschlossen!                  翻译完成！                   अनुवाद पूर्ण!
tr_cancelled           Übersetzung abgebrochen                     翻译已取消                   अनुवाद रद्द
tr_btn_cancel          Übersetzung abbrechen                       取消翻译                     अनुवाद रद्द करें
tr_btn_download        Übersetzung herunterladen                   下载翻译                     अनुवाद डाउनलोड करें
tr_btn_adopt           Audio aus dieser Übersetzung erzeugen       从此翻译生成音频              इस अनुवाद से ऑडियो बनाएँ
tr_cost_detail         {0} Zeichen zu übersetzen                   待翻译 {0} 个字符             अनुवाद हेतु {0} अक्षर
tr_pay_label           Buchübersetzung                             图书翻译                     पुस्तक अनुवाद
```

(`badge_new` = "new" letterale in tutte le lingue.)

- [ ] **Step 10.3: `i18n/download_pages.json` — blocco `translated`**

Aggiungere il top-level key `translated` con la stessa struttura del blocco `download` esistente (stesse lingue presenti nel file). Testi IT/EN di riferimento (tradurre nelle altre lingue del file seguendo il registro esistente):

```json
"translated": {
  "it": {
    "title": "La tua traduzione è pronta",
    "h2": "La tua traduzione è pronta",
    "p1": "Il libro tradotto è pronto per il download.",
    "btn": "Scarica traduzione"
  },
  "en": {
    "title": "Your translation is ready",
    "h2": "Your translation is ready",
    "p1": "Your translated book is ready for download.",
    "btn": "Download translation"
  }
}
```

- [ ] **Step 10.4: Testi email `_tr_email_i18n` (usati dal Task 6)**

In `generation_engine.py`, accanto a `_opt_email_i18n`, definire `_tr_email_i18n` con le stesse lingue di `_opt_email_i18n` e questa coppia IT/EN di riferimento (altre lingue: tradurre nello stesso registro):

```python
_tr_email_i18n = {
    "it": {
        "subject": "📖 La tua traduzione è pronta — {title}",
        "ready": "La traduzione di \"{title}\" è completata!",
        "button": "Scarica la traduzione",
        "expiry": "Il link scade tra {hours} ore.",
    },
    "en": {
        "subject": "📖 Your translation is ready — {title}",
        "ready": "The translation of \"{title}\" is complete!",
        "button": "Download your translation",
        "expiry": "The link expires in {hours} hours.",
    },
    # fr/es/de/pt/zh: stesse chiavi, registro identico alle email esistenti
}
```

(Adattare nomi-chiave alla struttura effettiva di `_opt_email_i18n` — l'email del Task 6 è un clone, quindi le chiavi devono combaciare con quelle usate dal template clonato.)

- [ ] **Step 10.5: Verifica sintassi JS/JSON**

Run: `node --check templates/_fragments/i18n_data.js` (se `node` assente: aprire la SPA e controllare console)
Run: `python -c "import json; json.load(open('i18n/download_pages.json', encoding='utf-8'))"`
Expected: nessun errore

- [ ] **Step 10.6: Commit**

```
git add templates/_fragments/i18n_data.js i18n/download_pages.json generation_engine.py
git commit -m "feat(translate): i18n 7 lingue - chiavi tr_*, btn .ABM, pagina download, email"
```

---

### Task 11: Frontend HTML+CSS — bottone «Traduci», `panelT3`, `panelT4`, adopt in panel5

**Files:**
- Modify: `templates/_fragments/html_head.html`

- [ ] **Step 11.1: Bottone «Traduci» con badge nel footer di panel2**

In `html_head.html`, dentro `panel2 > .panel-footer > .right` (riga ~271), PRIMA di `btnGoToAudio`:

```html
<button class="btn btn-outline btn-badge-new" id="btnTranslate" onclick="goToTranslate()">
  <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="18" height="18"><path d="M5 8l6 6"/><path d="M4 14l6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="M22 22l-5-10-5 10"/><path d="M14 18h6"/></svg>
  <span data-t="btn_translate"></span>
  <span class="badge-new" data-t="badge_new"></span>
</button>
```

CSS (nel blocco `<style>` di `html_head.html`, vicino agli stili `.btn`):

```css
.btn-badge-new{position:relative}
.badge-new{position:absolute;top:-8px;right:-8px;background:var(--ac,#f97316);color:#fff;font-size:.58rem;font-weight:800;letter-spacing:.04em;text-transform:uppercase;padding:2px 6px;border-radius:8px;line-height:1.2;pointer-events:none}
```

- [ ] **Step 11.2: `panelT3` — config traduzione (dopo la chiusura di `panel2`, riga ~278)**

Stessa estetica della card AI di panel4 (`aiOptCard`, riga 418): riusare le stesse classi. Id con suffisso `Tr` per non collidere.

```html
<!-- ═══ PANEL T3: Translate config (wizMode=translate, step 3) ═══ -->
<section class="panel" id="panelT3" aria-labelledby="panelT3Heading">
  <h2 id="panelT3Heading" data-t="tr_title"></h2>
  <p class="subtitle" data-t="tr_subtitle"></p>

  <div class="form-row">
    <div class="form-group"><label data-t="tr_lbl_source"></label><select id="trSrcLang"></select></div>
    <div class="form-group"><label data-t="tr_lbl_target"></label><select id="trDstLang"></select></div>
  </div>
  <div class="form-row">
    <div class="form-group"><label data-t="tr_lbl_format"></label>
      <select id="trFormat">
        <option value="epub">EPUB</option>
        <option value="abm">ABM</option>
        <option value="txt">TXT</option>
      </select>
    </div>
    <div class="form-group"><label data-t="tr_lbl_output_name"></label>
      <input type="text" id="trOutName" maxlength="80" autocomplete="off">
    </div>
  </div>

  <div class="ai-opt-card" id="aiOptCardTr">
    <div class="toggle-row">
      <div>
        <div class="toggle-label">
          <svg class="ai-icon" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2l2.4 7.2h7.6l-6 4.8 2.4 7.2-6.4-4.8-6.4 4.8 2.4-7.2-6-4.8h7.6z"/><circle cx="12" cy="12" r="1" fill="currentColor" stroke="none" opacity="0.3"/></svg>
          <span data-t="lbl_ai_opt"></span>
        </div>
        <div class="toggle-desc" data-t="ai_opt_desc"></div>
      </div>
      <label class="toggle-switch" aria-label="Attiva ottimizzazione AI">
        <input type="checkbox" id="aiToggleTr" onchange="trUpdateEstimate()">
        <span class="toggle-slider"></span>
      </label>
    </div>
    <div class="cost-estimate visible" id="costEstimateTr">
      <div style="flex:1">
        <div class="cost-amount" id="costAmountTr">—</div>
        <div class="cost-detail" id="costDetailTr"></div>
      </div>
      <button class="btn btn-outline btn-sm" id="btnApplyCouponTr" onclick="showCouponTr()">
        <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="4" width="20" height="16" rx="2"/><circle cx="8" cy="11.5" r="1.5"/><circle cx="16" cy="11.5" r="1.5"/></svg>
        <span data-t="pay_tab_voucher"></span>
      </button>
    </div>
    <div class="coupon-row" id="couponRowTr">
      <input type="text" id="couponCodeTr" placeholder="XXXX-XXXX-XXXX" aria-label="Codice coupon">
      <input type="email" id="couponEmailTr" placeholder="Email associata" aria-label="Email buono">
      <button class="btn btn-p btn-sm" id="btnValidateCouponTr" onclick="validateCouponTr()">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
        <span data-t="pay_voucher_submit"></span>
      </button>
    </div>
    <div class="coupon-result" id="couponResultTr"></div>
  </div>

  <div id="trErr"></div>

  <div class="panel-footer">
    <div class="left">
      <button class="btn btn-g" id="btnBackT3" onclick="goToStep(2)">
        <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="18" height="18"><polyline points="15 18 9 12 15 6"/></svg>
        <span data-t="btn_back"></span>
      </button>
    </div>
    <div class="right">
      <button class="btn btn-p btn-lg" id="btnStartTranslate" onclick="startTranslation()">
        <span data-t="tr_btn_start"></span>
      </button>
    </div>
  </div>
</section>

<!-- ═══ PANEL T4: Translate progress (wizMode=translate, step 4) ═══ -->
<section class="panel" id="panelT4" aria-labelledby="panelT4Heading">
  <h2 id="panelT4Heading" data-t="tr_progress_title"></h2>
  <div class="progress-area-wiz" id="trProgressArea">
    <div class="generation-active-notice">
      <span class="pulse-dot" aria-hidden="true"></span>
      <span id="trActiveNoticeText" data-t="gen_active_notice"></span>
    </div>
    <div class="progress-bar-track">
      <div class="progress-bar-fill" id="trProgressFill" style="width:0%" role="progressbar" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
    </div>
    <div class="progress-stats-wiz">
      <span class="phase" id="trProgressPhase">—</span>
      <span class="pct" id="trProgressPct">0%</span>
    </div>
    <div class="email-late-area" id="emailLateAreaTr">
      <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="color:var(--txm)"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>
      <input type="email" id="notifyEmailLateTr" placeholder="" aria-label="Email per notifica">
      <button class="btn btn-p btn-sm" id="btnSubmitEmailLateTr" onclick="submitEmailLateTr()"><span data-t="email_late_btn"></span></button>
    </div>
  </div>
  <div id="trErr4"></div>
  <div style="margin-top:16px">
    <button class="btn btn-outline" id="btnCancelTr" onclick="cancelTranslation()">
      <svg class="btn-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="16" height="16"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
      <span data-t="tr_btn_cancel"></span>
    </button>
  </div>
</section>
```

- [ ] **Step 11.3: Bottone adopt in panel5**

In panel5, dentro `.download-buttons` (riga ~564), dopo `btnP`:

```html
<button class="btn btn-outline btn-lg" id="btnTrAdopt" style="display:none">&#x1F3A7; <span data-t="tr_btn_adopt"></span></button>
```

- [ ] **Step 11.4: Verifica resa**

Run: `python audiobook_app.py` (poi aprire `http://localhost:5601`)
Expected: panel2 mostra «.ABM», «Traduci» col badge "new" in alto a dx, «Prosegui» a destra. `panelT3`/`panelT4` non visibili (nessuna classe `active`). Fermare il server.

- [ ] **Step 11.5: Commit**

```
git add templates/_fragments/html_head.html
git commit -m "feat(translate): UI - bottone Traduci+badge, pannelli config/progress, adopt"
```

---

### Task 12: Frontend JS — `wizMode`, navigazione, config, stima e pagamento

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 12.1: Stato e navigazione**

Accanto allo stato globale (riga ~233):

```javascript
let wizMode='audio'; // 'audio' | 'translate'
let trPaymentToken=null, trEstimate=null, trEmailRegistered=false;
```

Modificare `goToStep()` (riga 464): la risoluzione del pannello target diventa mode-aware. Sostituire le due righe `const target=document.getElementById('panel'+n); if(target)target.classList.add('active');` con:

```javascript
  let panelId='panel'+n;
  if(wizMode==='translate'&&n===3)panelId='panelT3';
  if(wizMode==='translate'&&n===4)panelId='panelT4';
  const target=document.getElementById(panelId);
  if(target)target.classList.add('active');
```

E la riga `if(n===4)_updateSummary();` diventa `if(n===4&&wizMode==='audio')_updateSummary();`.

Etichette dinamiche: nuova funzione + chiamata in fondo a `updateWizardSteps()`:

```javascript
function _applyWizModeLabels(){
  const dots=document.querySelectorAll('.wizard-step-dot');
  if(dots.length<5)return;
  const l3=dots[2].querySelector('.label'),l4=dots[3].querySelector('.label');
  if(l3)l3.textContent=t(wizMode==='translate'?'wiz_step3_tr':'wiz_step3');
  if(l4)l4.textContent=t(wizMode==='translate'?'wiz_step4_tr':'wiz_step4');
}
```

In `updateWizardSteps(n)` aggiungere come ultima riga: `_applyWizModeLabels();`.

- [ ] **Step 12.2: Ingresso nel percorso: `goToTranslate()`**

```javascript
function goToTranslate(){
  if(!jobId||generating)return;
  if(_getSelectedChapterIndexes().length===0){showErr('p2info',t('sel_err_none')||'Select at least one chapter');return}
  wizMode='translate';
  trPaymentToken=null;
  _trFillLangSelects();
  _trPrefillOutName();
  const dst=document.getElementById('trDstLang');
  goToStep(3);
  trUpdateEstimate();
}

function _trFillLangSelects(){
  const langs=Object.keys(voices).filter(c=>!c.startsWith('_')).map(c=>{
    let ln=c;
    if(L[cl]&&L[cl].langs&&L[cl].langs[c])ln=L[cl].langs[c];
    else if(L.en&&L.en.langs&&L.en.langs[c])ln=L.en.langs[c];
    else ln=(voices[c]&&voices[c].name)||c;
    return {code:c,name:ln};
  }).sort((a,b)=>a.name.localeCompare(b.name,cl));
  ['trSrcLang','trDstLang'].forEach(id=>{
    const sel=document.getElementById(id);if(!sel)return;
    const old=sel.value;
    sel.innerHTML='';
    for(const l of langs){
      const o=document.createElement('option');
      o.value=l.code;o.textContent=l.name;
      sel.appendChild(o);
    }
    if(old&&voices[old])sel.value=old;
  });
  // Origine precompilata dalla lingua del libro se nota
  const src=document.getElementById('trSrcLang');
  if(src&&bookData&&bookData.language){
    const lc=bookData.language.split('-')[0].toLowerCase();
    if(src.querySelector('option[value="'+lc+'"]'))src.value=lc;
  }
}

function _trPrefillOutName(){
  const el=document.getElementById('trOutName');if(!el)return;
  let base=(bookData&&(bookData.original_filename||bookData.filename))||'';
  if(!base)base=(bookData&&bookData.title)||'translated';
  base=base.replace(/\.[^.]+$/,'');
  el.value=base;
}
```

**Verifica per l'esecutore:** controllare nei dintorni di `app.js:606-616` quali campi della risposta `/api/analyze` finiscono in `bookData` (se il filename originale non c'è, usare `bookData.title` come unico fallback e semplificare `_trPrefillOutName`).

- [ ] **Step 12.3: Stima costo + voucher + PayPal**

```javascript
async function trUpdateEstimate(){
  if(!jobId)return null;
  try{
    const url=new URL('/api/translate_estimate/'+jobId,window.location.origin);
    url.searchParams.append('target',document.getElementById('trDstLang').value||'');
    url.searchParams.append('optimize',document.getElementById('aiToggleTr').checked?'1':'0');
    _getSelectedChapterIndexes().forEach(i=>url.searchParams.append('selected_chapters',i));
    const est=await fetch(url.toString()).then(r=>r.json());
    if(est.error)return null;
    trEstimate=est;
    const amt=document.getElementById('costAmountTr');
    const det=document.getElementById('costDetailTr');
    if(amt)amt.textContent=est.requires_payment?('€ '+est.due_eur.toFixed(2)):(t('cost_free')||'€ 0.00');
    if(det)det.textContent=(t('tr_cost_detail')||'{0} characters').replace('{0}',est.chars.toLocaleString());
    return est;
  }catch(e){return null}
}

function showCouponTr(){
  const row=document.getElementById('couponRowTr');
  if(row)row.classList.toggle('visible');
}

async function validateCouponTr(){
  const code=(document.getElementById('couponCodeTr').value||'').trim().toUpperCase();
  const email=(document.getElementById('couponEmailTr').value||'').trim();
  if(!code||!email)return;
  const result=document.getElementById('couponResultTr');
  if(result){result.innerHTML='<div class="sp"></div>';result.className='coupon-result'}
  try{
    const r=await fetch('/api/voucher_validate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({code:code,email:email})});
    const d=await r.json();
    if(d.error){if(result){result.textContent=d.error;result.className='coupon-result error'}return}
    if(result){result.textContent='✅ '+(t('pay_voucher_valid')||'Voucher valid!');result.className='coupon-result success'}
    trPaymentToken=d.payment_token;
  }catch(e){if(result){result.textContent='Error: '+e.message;result.className='coupon-result error'}}
}
```

PayPal: riusare il modal pagamento esistente. **Aprire `_showPaymentModal` (chiamata da `_fetchCostEstimate`, app.js:1907-1960) e verificarne la firma**; se internamente crea l'ordine via `/api/paypal_create_order`, parametrizzare: aggiungere un terzo argomento opzionale `orderEndpointBody` — quando presente, l'ordine si crea con `POST /api/paypal_create_order_translate` e quel body. Chiamata dal flusso translate:

```javascript
const token=await _showPaymentModal(est.due_eur,est.chars,{
  endpoint:'/api/paypal_create_order_translate',
  body:{job_id:jobId,target_lang:document.getElementById('trDstLang').value,
        optimize:document.getElementById('aiToggleTr').checked,
        selected_chapters:_getSelectedChapterIndexes()}
});
```

(Default assente → comportamento attuale invariato per l'ottimizzazione.)

- [ ] **Step 12.4: Verifica manuale**

Run: `python audiobook_app.py` — caricare un txt, andare su «Traduci».
Expected: step 3 col pannello traduzione, lingue popolate, origine precompilata, nome file precompilato, stima visibile; pallini con etichette «Traduzione»/«Elaborazione». «Indietro» torna ai capitoli. Fermare il server.

- [ ] **Step 12.5: Commit**

```
git add static/js/app.js
git commit -m "feat(translate): JS wizMode, pannello config, stima e pagamento"
```

---

### Task 13: Frontend JS — avvio, SSE, email late, completamento, adopt

**Files:**
- Modify: `static/js/app.js`

- [ ] **Step 13.1: `startTranslation()` + SSE + cancel + email late**

```javascript
async function startTranslation(){
  if(!jobId||generating)return;
  const src=document.getElementById('trSrcLang').value;
  const dst=document.getElementById('trDstLang').value;
  if(src===dst){showErr('trErr',t('tr_err_same_lang'));return}
  const est=await trUpdateEstimate();
  if(!est)return;
  let payToken=trPaymentToken;
  if(est.requires_payment&&!payToken){
    payToken=await _showPaymentModal(est.due_eur,est.chars,{
      endpoint:'/api/paypal_create_order_translate',
      body:{job_id:jobId,target_lang:dst,
            optimize:document.getElementById('aiToggleTr').checked,
            selected_chapters:_getSelectedChapterIndexes()}
    });
    if(!payToken)return;
    trPaymentToken=payToken;
  }
  const payload={
    job_id:jobId,
    source_lang:src,target_lang:dst,
    output_format:document.getElementById('trFormat').value,
    output_name:(document.getElementById('trOutName').value||'').trim(),
    optimize:document.getElementById('aiToggleTr').checked,
    selected_chapters:_getSelectedChapterIndexes(),
    batch:false,lang:cl
  };
  if(payToken)payload.payment_token=payToken;
  try{
    const r=await fetch('/api/translate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
    const d=await r.json();
    if(d.error){showErr('trErr',d.error);return}
    generating=true;
    lockUI();
    goToStep(4);
    _listenTranslateProgress();
  }catch(e){showErr('trErr','Error: '+e.message)}
}

function _listenTranslateProgress(){
  const myJobId=jobId;
  const es=new EventSource('/api/translate_progress/'+myJobId);
  es.onmessage=ev=>{
    const d=JSON.parse(ev.data);
    const fill=document.getElementById('trProgressFill');
    const pct=document.getElementById('trProgressPct');
    const phase=document.getElementById('trProgressPhase');
    const total=d.tr_total_chars||1;
    const done=Math.min(d.tr_streamed_chars||d.tr_processed_chars||0,total);
    const p=Math.round(done/total*100);
    if(fill)fill.style.width=p+'%';
    if(pct)pct.textContent=p+'%';
    if(phase)phase.textContent=(t('tr_progress_chapter')||'Chapter {0} of {1}')
      .replace('{0}',d.tr_current_chapter_num||0)
      .replace('{1}',d.tr_progress_total||0);
    if(d.status==='error'){es.close();generating=false;unlockUI();showErr('trErr4',d.error||'Translation error');return}
    if(d.status==='cancelled'){es.close();generating=false;unlockUI();showErr('trErr4',t('tr_cancelled'));goToStep(3);return}
    if(d.status==='translated'){es.close();generating=false;unlockUI();_showTranslationDone(d);return}
  };
  es.onerror=()=>{es.close();setTimeout(()=>{if(generating)_listenTranslateProgress()},3000)};
}

async function cancelTranslation(){
  if(!jobId)return;
  try{await fetch('/api/translate_cancel/'+jobId,{method:'POST'})}catch(e){}
}

async function submitEmailLateTr(){
  const email=(document.getElementById('notifyEmailLateTr').value||'').trim();
  if(!email||!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email))return;
  try{
    const r=await fetch('/api/register_email',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({job_id:jobId,email:email,download_type:'translated',lang:cl})});
    const d=await r.json();
    if(d.error){alert(d.error);return}
    trEmailRegistered=true;
    const area=document.getElementById('emailLateAreaTr');
    _setEmailLateConfirm(area,'✅ '+(t('email_late_ok')||'Email registered!'));
  }catch(e){alert('Error: '+e.message)}
}
```

- [ ] **Step 13.2: Completamento + adopt**

```javascript
function _showTranslationDone(d){
  _unlockStep(5);
  jobDone=true;
  ['btnD','btnM','btnA','btnP'].forEach(id=>{const b=document.getElementById(id);if(b)b.style.display='none'});
  const btnD=document.getElementById('btnD');
  if(btnD){
    btnD.style.display='';
    const fmt=(document.getElementById('trFormat').value||'').toUpperCase();
    btnD.innerHTML='&#x2B07;&#xFE0F; <span>'+(t('tr_btn_download')||'Download translation')+' ('+fmt+')</span>';
    btnD.onclick=()=>{window.location='/api/download_translation/'+jobId};
  }
  const btnAdopt=document.getElementById('btnTrAdopt');
  if(btnAdopt){btnAdopt.style.display='';btnAdopt.onclick=adoptTranslation;}
  const h=document.getElementById('panel5Heading');
  if(h)h.textContent=t('tr_done')||'Translation complete!';
  goToStep(5);
}

async function adoptTranslation(){
  if(!jobId)return;
  try{
    const r=await fetch('/api/translate_adopt/'+jobId,{method:'POST'});
    const d=await r.json();
    if(d.error){alert(d.error);return}
    // Aggiorna stato libro lato client e torna al percorso audio
    if(bookData){
      bookData.language=d.language;
      bookData.chapters=d.chapters;
    }
    optimizedChapters=d.ai_optimized?d.chapters.map(c=>c.index):[];
    wizMode='audio';
    jobDone=false;
    const btnAdopt=document.getElementById('btnTrAdopt');
    if(btnAdopt)btnAdopt.style.display='none';
    _renderChaptersAfterAdopt(d);
    goToStep(3); // pannello voci (audio)
    fillLangs(); // ripreseleziona la lingua = nuova lingua del libro
  }catch(e){alert('Error: '+e.message)}
}
```

`_renderChaptersAfterAdopt(d)`: **individuare la funzione che costruisce le righe capitolo in panel2 dopo `/api/analyze`** (handler successo analyze, app.js ~606; la funzione che popola `#chapterRows` e `#bookLang`). Estrarne la parte di rendering in una funzione riutilizzabile se non lo è già, e chiamarla qui con i capitoli adottati (tutti selezionati di default) aggiornando anche `#bookLang` e i contatori. Se il rendering legge solo `bookData`, basta richiamarla dopo l'aggiornamento di `bookData` fatto sopra.

**Reset:** in `resetAll()` (cercare `function resetAll` in app.js) aggiungere `wizMode='audio';trPaymentToken=null;trEstimate=null;trEmailRegistered=false;` e il ripristino del titolo di panel5 (`panel5Heading` → `data-t` originale via `applyI18n()`).

- [ ] **Step 13.3: Verifica end-to-end manuale (LLM mock non necessario: usare libro corto sotto soglia free se `ABM_TRANSLATE_*` configurate, altrimenti verificare il 503 pulito)**

Run: `python audiobook_app.py`
Percorso: carica txt breve → Traduci → config → Avvia. Se il backend LLM non è configurato in dev: Expected = messaggio d'errore pulito "Translation not configured on this server" in `#trErr`. Se configurato: traduzione breve completa, panel5 con «Scarica traduzione (TXT)» + «Genera audio da questa traduzione»; adopt → step 3 audio con lingua destinazione preselezionata.

- [ ] **Step 13.4: Commit**

```
git add static/js/app.js
git commit -m "feat(translate): JS avvio/SSE/cancel/email/completamento/adopt"
```

---

### Task 14: Documentazione, regressione completa, chiusura

**Files:**
- Modify: `PARAMETRI_CONFIGURAZIONE.md`
- Modify: `docs/superpowers/specs/2026-06-05-translate-book-design.md` (stato)

- [ ] **Step 14.1: `PARAMETRI_CONFIGURAZIONE.md`**

Aggiungere sezione "Traduzione libro" con (formato del file esistente: valore, default, file:riga):
- `ABM_TRANSLATE_COST` (default `3.0`, €/M char input, virgola ok) — `payment.py`
- `ABM_TRANSLATE_MIN_COST` (default `1.5`, floor sul totale quando a pagamento) — `payment.py`
- Nota: le `ABM_TRANSLATE_BACKEND/MODEL/API_KEY/API_BASE/VERTEX_LOCATION/CHUNK_CHARS/MAX_RETRIES/TEMPERATURE/REQUEST_TIMEOUT_SEC` (già documentate per lo script) ora governano anche la web app via `translation_core.py` — aggiornare i riferimenti file:riga da `scripts/translate_abm.py` a `translation_core.py`.

- [ ] **Step 14.2: Suite completa + lint sintassi**

Run: `python -m py_compile audiobook_app.py generation_engine.py payment.py translation_core.py storage_tiering.py scripts/translate_abm.py`
Run: `pytest test/ -v --tb=short`
Expected: nessuna nuova failure rispetto a main (note: 4 failure pre-esistenti `test_paypal_create_gemini` da ordering/reload).

- [ ] **Step 14.3: Smoke CLI finale**

Ripetere Step 4.1 (creazione `_test_book.abm`) + `python scripts/translate_abm.py _test_book.abm it en --dry-run --format epub` → `Fatto: _test_book_en.epub`. Pulizia: `Remove-Item _test_book* -Confirm:$false`.

- [ ] **Step 14.4: Commit finale**

```
git add PARAMETRI_CONFIGURAZIONE.md
git add -f docs/superpowers/specs/2026-06-05-translate-book-design.md
git commit -m "docs(translate): parametri configurazione + chiusura spec traduzione"
```

**NON pushare:** il push su main = deploy automatico in produzione; il branch TRADUZ si pusha solo su conferma esplicita dell'utente.

---

## Note trasversali per l'esecutore

1. **Nomi da verificare sul codice reale** (il piano usa i nomi riportati dalla ricognizione; se un nome differisce, adeguare il nuovo codice, mai il vecchio): `_jobs`/`jobs`, `_set_job_status`, `_refund_job_payment`, `_spawn_cloud_offload`, `_try_cold_serve`, `_send_file_throttled`, `_mark_token_downloaded`, `_effective_retention_for_token_info`, `_smtp_available`, `get_voices`, `_parse_selected_chapters`, `_check_job_owner`, `_log_activity`, `_showPaymentModal`.
2. **Convenzione lingua**: commenti/stringhe log in italiano+inglese misti come il codice circostante; UI sempre via i18n.
3. **Mai** importare `audiobook_app` da `generation_engine`/`translation_core` (pattern `configure()`; incidente double-import documentato).
4. **File temporanei** (`_test_book*`): rimuovere sempre prima di chiudere.
5. Heartbeat lato client: il SSE `/api/translate_progress` aggiorna `last_poll` a ogni poll (come l'ottimizzazione) — non serve beacon aggiuntivo durante la traduzione interattiva.

