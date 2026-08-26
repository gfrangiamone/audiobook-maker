# Backend Cloudflare per Gemini TTS — nucleo tecnico (Fasi 0, 2-4) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** rendere Cloudflare Workers AI un terzo backend di `gemini_tts.py`, selezionabile per modello, con failover automatico su Vertex quando Cloudflare esce di servizio, rientro manuale da console admin e nessuna modifica al vocabolario di eccezioni su cui poggia la macchina dei rimborsi B1-B4.

**Architecture:** oggi `synthesize()` è l'unica funzione di `gemini_tts.py` che fa I/O di rete, e `_resolve_backend()` astrae già la scelta fra Vertex e API key. L'integrazione introduce un contratto di trasporto unico — `{"pcm", "input_tokens", "output_tokens"}` in uscita, `TransportError` come sola eccezione — con due implementazioni: quella Vertex (estratta dal corpo attuale di `synthesize`, resta in `gemini_tts.py` perché dipende dal client SDK e dagli helper di quel modulo) e quella Cloudflare (modulo foglia nuovo, dipende solo da `requests`). Sopra il trasporto siedono un resolver di backend per-modello e un circuit breaker persistito che, allo scatto, dirotta la stessa chiamata su Vertex senza interrompere il job in corso. L'audio è identico byte per byte fra i due backend — PCM s16le 24 kHz mono — ed è questo che rende lecito il failover a metà libro.

**Tech Stack:** Python 3.12, `requests`, `google-genai`, pytest.

**Spec:** `docs/superpowers/specs/2026-08-26-cloudflare-tts-prod-backend-design.md` (§4 Architettura, §9 Configurazione, §10.1 Verifica voci, §11 Fasi 0 e 2-4).

**Piano gemello:** `docs/superpowers/plans/2026-08-26-cloudflare-tts-backend-economics.md` copre le Fasi 5-7 (pricing parametrico, contabilità del costo reale, email di trip, endpoint e pulsante admin, docs, rollout). Va eseguito **dopo** questo.

**Prerequisito indipendente:** `docs/superpowers/plans/2026-08-26-tts-chunking-degenerate-fix.md` (Fase 1) è rilasciabile da solo e non blocca questo piano.

## Global Constraints

Valori vincolanti, copiati dalla §9 della spec. Ogni task li eredita.

| Variabile | Significato | Default |
|---|---|---|
| `ABM_GEMINI_BACKEND` | `vertex` / `apikey` / `cloudflare` / `auto`. **`auto` non seleziona mai Cloudflare**: Cloudflare è solo opt-in esplicito. | `auto` |
| `ABM_CF_ACCOUNT_ID` | Account Cloudflare | *(vuoto)* |
| `ABM_CF_API_TOKEN` | Token API Cloudflare | *(vuoto)* |
| `ABM_CF_TIMEOUT_MS` | Timeout per chiamata Cloudflare | `60000` |
| `ABM_CF_TRIP_FAILURES` | Fallimenti consecutivi che fanno scattare il breaker | `3` |
| `ABM_CF_CREDIT_TOPUP_FEE` | Commissione di ricarica del credito AI Gateway | `0.05` |
| `ABM_CF_CREDIT_BALANCE_EUR` | Saldo credito dichiarato dall'admin, base del pre-allarme | `0` |
| `ABM_CF_CREDIT_ALERT_EUR` | Soglia sotto la quale scatta il pre-allarme credito | `5.00` |

Vincoli non negoziabili:

- **Il token Cloudflare arriva solo da variabile d'ambiente.** Mai in codice, mai in un log, mai in un messaggio di errore, mai in un report. Nessuna eccezione può includere gli header della richiesta.
- **Il vocabolario di eccezioni verso l'esterno non cambia.** `synthesize()` continua a sollevare esattamente `GeminiQuotaExhausted`, `GeminiBudgetExceeded`, `GeminiUnavailable`, `GeminiEmptyResponse`, `ValueError`, `RuntimeError`. `TransportError` è interna e non deve mai uscire da `synthesize()`. È così che la macchina di rimborso B1-B4 resta valida senza essere riscritta.
- **Criterio di accettazione della Fase 2:** la suite passa **senza modifiche ai test esistenti**. Se un test va toccato, l'estrazione ha cambiato comportamento e va corretta l'estrazione, non il test.
- **Cloudflare non entra in gioco senza opt-in esplicito.** Un ambiente che non setta `ABM_GEMINI_BACKEND=cloudflare` deve comportarsi esattamente come oggi.
- **Il failover è a senso unico.** Dopo lo scatto si torna a Cloudflare solo con un'azione manuale dell'admin, mai automaticamente.
- Il valore di `_audio_tokens_per_second("flash31")` resta **25**: è già corretto in produzione, non va toccato.
- Commit in stile Conventional Commits, senza trailer di attribuzione.
- `docs/`, `*.md` e `scripts/` sono coperti da `.gitignore`: serve `git add -f`.
- Mai `git add -A` né `git add .`: la working copy contiene modifiche non correlate di altre sessioni.

## Deviazione deliberata dalla spec

La spec (§4.1) colloca entrambi gli adapter nel modulo foglia `gemini_transport.py`. Questo piano ci mette **il contratto e il solo adapter Cloudflare**, lasciando l'adapter Vertex dentro `gemini_tts.py`.

Motivo: l'adapter Vertex dipende da `_get_client`, `_extract_audio_pcm`, `_is_429`, `_is_daily_quota_error`, `_parse_retry_after`, `_rpd_increment` e dai tipi `google.genai` — tutti in `gemini_tts.py`. Spostarlo significherebbe o spostare quegli helper (grosso rischio su un modulo da 2336 righe già in produzione) o far importare `gemini_tts` al trasporto, violando la convenzione di progetto n. 1 sugli import circolari. Il contratto resta unico e i due adapter restano intercambiabili: è questo che conta per il failover.

---

### Task 1: Fase 0 — ricognizione del credito e chiusura di G4

**Files:**
- Create: `scripts/cf_credit_probe.py`
- Create: `docs/superpowers/specs/2026-08-26-cloudflare-tts-prod-backend-design.md` — sezione nuova `§10.2 Ricognizione credito e latenza` (append)

**Interfaces:**
- Consumes: le variabili `CF_ACCOUNT_ID` / `CF_API_TOKEN` già usate da `scripts/cf_tts_bench.env.ps1` (file locale, mai committato).
- Produces: la risposta documentata alla domanda «esiste un'API che espone il saldo del credito AI Gateway?», che determina se il pre-allarme del Task 8 può leggere il saldo reale o deve accontentarsi del ledger locale.

**Perché è un task e non un'assunzione:** il Task 8 costruisce un pre-allarme sul credito. Se Cloudflare espone il saldo, il pre-allarme è esatto; se non lo espone, è una stima cumulativa che deriva dal ledger locale e va dichiarata tale all'admin. La differenza cambia il testo dell'allarme e il grado di fiducia che merita.

- [ ] **Step 1: Scrivi il probe**

Crea `scripts/cf_credit_probe.py`:

```python
"""Verifica se Cloudflare espone via API il saldo del credito AI Gateway.

Non stampa mai il token. Nessuna chiamata di inferenza: solo endpoint di
lettura, quindi nessun addebito.

Uso:
    $env:CF_ACCOUNT_ID = "..."; $env:CF_API_TOKEN = "..."
    python scripts/cf_credit_probe.py
"""
import json
import os
import sys

import requests

ACCOUNT = os.environ.get("CF_ACCOUNT_ID", "").strip()
TOKEN = os.environ.get("CF_API_TOKEN", "").strip()
if not ACCOUNT or not TOKEN:
    sys.exit("CF_ACCOUNT_ID / CF_API_TOKEN assenti nell'ambiente")

BASE = "https://api.cloudflare.com/client/v4"
CANDIDATES = [
    f"/accounts/{ACCOUNT}/ai-gateway/credits",
    f"/accounts/{ACCOUNT}/ai/credits",
    f"/accounts/{ACCOUNT}/billing/profile",
    f"/accounts/{ACCOUNT}/ai-gateway/gateways",
]

session = requests.Session()
session.headers["Authorization"] = f"Bearer {TOKEN}"

for path in CANDIDATES:
    try:
        r = session.get(BASE + path, timeout=30)
    except requests.RequestException as e:
        print(f"{path}: errore di rete ({type(e).__name__})")
        continue
    print(f"\n=== {path} -> HTTP {r.status_code}")
    try:
        body = r.json()
    except ValueError:
        print(r.text[:400])
        continue
    # Stampa compatta: cerchiamo chiavi che somiglino a un saldo.
    print(json.dumps(body, indent=2)[:1500])
```

- [ ] **Step 2: Esegui il probe**

Run (PowerShell, dalla radice del progetto):

```powershell
. '.\scripts\cf_tts_bench.env.ps1'
python .\scripts\cf_credit_probe.py
```

Attenzione: `cf_tts_bench.env.ps1` è locale e non committato; se non esiste, esporta a mano `CF_ACCOUNT_ID` e `CF_API_TOKEN`.

- [ ] **Step 3: Registra l'esito nella spec**

Aggiungi in coda alla spec una sezione `## 10.2 Ricognizione credito e latenza (26/08/2026)` con:

1. **Credito** — per ciascun endpoint provato: status HTTP e se il corpo contiene un saldo utilizzabile. Concludi con una riga netta: «Il saldo è leggibile via API» oppure «Il saldo non è esposto: il pre-allarme si basa sul ledger locale ed è una stima».
2. **G4 (latenza p95)** — le latenze per chiamata già misurate sul banco Cloudflare (report `matrix` in `./out/*/report.md`: 30 chiamate, 6,9-9,6 s su testi da ~200 caratteri) confrontate con la latenza Vertex osservabile in produzione. Se il confronto diretto non è possibile senza una campagna dedicata, dichiaralo e marca G4 come **non chiuso**, indicando cosa servirebbe per chiuderlo. Non fingere una misura che non hai.
3. **G3 (qualità A/B)** — verificato a orecchio dall'utente su audio identici fra i due backend. Registralo come chiuso per giudizio dell'esercente, non per misura strumentale.

- [ ] **Step 4: Commit**

```bash
git add -f scripts/cf_credit_probe.py docs/superpowers/specs/2026-08-26-cloudflare-tts-prod-backend-design.md
git commit -m "docs(tts): ricognizione credito Cloudflare e stato dei criteri G3/G4"
```

---

### Task 2: contratto di trasporto

**Files:**
- Create: `gemini_transport.py`
- Test: `test/test_gemini_transport_contract.py` (nuovo)

**Interfaces:**
- Consumes: niente. Modulo foglia: importa solo stdlib e `requests`.
- Produces:
  - `class TransportError(RuntimeError)` con attributi `kind`, `retry_after_sec`, `billed`, `http_status`, `provider_code`.
  - `TRANSPORT_KINDS: frozenset` = `{"retryable", "rate_limited", "quota_daily", "content_rejected", "backend_down", "fatal"}`.

- [ ] **Step 1: Scrivi il test che fallisce**

Crea `test/test_gemini_transport_contract.py`:

```python
"""Contratto dell'eccezione di trasporto condivisa dagli adapter TTS."""
import pytest

from gemini_transport import TRANSPORT_KINDS, TransportError


def test_kinds_are_the_closed_set_from_the_spec():
    assert TRANSPORT_KINDS == frozenset({
        "retryable", "rate_limited", "quota_daily",
        "content_rejected", "backend_down", "fatal",
    })


def test_defaults_are_conservative():
    err = TransportError("boom", kind="retryable")
    assert err.kind == "retryable"
    assert err.retry_after_sec is None
    # Il default e' "non fatturato": sovrastimare la spesa e' meno dannoso che
    # sottostimarla, ma inventare un addebito che non c'e' e' peggio ancora.
    assert err.billed is False
    assert err.http_status is None
    assert err.provider_code is None


def test_carries_the_diagnostic_fields():
    err = TransportError("overload", kind="backend_down", retry_after_sec=12,
                         billed=True, http_status=503, provider_code=7003)
    assert (err.retry_after_sec, err.billed) == (12, True)
    assert (err.http_status, err.provider_code) == (503, 7003)


def test_rejects_an_unknown_kind():
    with pytest.raises(ValueError):
        TransportError("boom", kind="misterioso")


def test_is_a_runtime_error():
    # I caller storici intercettano RuntimeError: la sottoclasse preserva
    # quel comportamento se mai una TransportError sfuggisse.
    assert isinstance(TransportError("x", kind="fatal"), RuntimeError)
```

- [ ] **Step 2: Esegui il test e verifica che fallisca**

Run: `python -m pytest test/test_gemini_transport_contract.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'gemini_transport'`

- [ ] **Step 3: Implementa il modulo**

Crea `gemini_transport.py`:

```python
"""Contratto di trasporto per la sintesi Gemini TTS e adapter Cloudflare.

Modulo foglia: importa solo stdlib e `requests`. Non importa mai `gemini_tts`
(convenzione di progetto n. 1 sugli import circolari).

Un adapter di trasporto ha questa firma:

    call(*, final_text, voice_name, model_key, model_id, timeout_ms,
         temperature) -> {"pcm": bytes,
                          "input_tokens": int | None,
                          "output_tokens": int | None}

e solleva `TransportError` e nient'altro. `input_tokens`/`output_tokens` valgono
None quando il provider non li restituisce: la stima spetta al chiamante, che
conosce il modello.
"""

TRANSPORT_KINDS = frozenset({
    # Riprovabile con lo stesso payload: glitch, 5xx, timeout, risposta vuota.
    "retryable",
    # 429 esplicito: riprovabile ma con attesa dettata dal provider.
    "rate_limited",
    # Quota giornaliera esaurita: riprovare oggi non serve.
    "quota_daily",
    # Il provider rifiuta il contenuto: riprovare lo stesso testo non serve.
    "content_rejected",
    # Il backend e' fuori uso (credito esaurito, indisponibilita' prolungata):
    # e' questo il kind che fa scattare il circuit breaker.
    "backend_down",
    # Errore deterministico di configurazione o di parametri: nessun retry,
    # nessun failover, va corretto dall'operatore.
    "fatal",
})


class TransportError(RuntimeError):
    """Sola eccezione che un adapter di trasporto puo' sollevare.

    Sottoclasse di RuntimeError per non peggiorare il comportamento di un
    eventuale caller storico che intercettava RuntimeError.

    Args:
        kind: uno di TRANSPORT_KINDS. Determina la reazione del chiamante.
        retry_after_sec: attesa suggerita dal provider, se dichiarata.
        billed: True se la chiamata e' stata comunque addebitata. Sul piano
            partner-model di Cloudflare una HTTP 200 e' addebitata anche quando
            il corpo non contiene audio; le 4xx/5xx non lo sono.
        http_status: status HTTP grezzo, per diagnostica.
        provider_code: codice di errore proprietario del provider.
    """

    def __init__(self, message, *, kind, retry_after_sec=None,
                 billed=False, http_status=None, provider_code=None):
        if kind not in TRANSPORT_KINDS:
            raise ValueError(f"kind sconosciuto: {kind!r}")
        super().__init__(message)
        self.kind = kind
        self.retry_after_sec = retry_after_sec
        self.billed = bool(billed)
        self.http_status = http_status
        self.provider_code = provider_code
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `python -m pytest test/test_gemini_transport_contract.py -v`
Expected: PASS (5 test)

- [ ] **Step 5: Commit**

```bash
git add gemini_transport.py test/test_gemini_transport_contract.py
git commit -m "feat(tts): contratto di trasporto condiviso per i backend Gemini"
```

---

### Task 3: adapter Vertex ed estrazione da `synthesize()`

**Files:**
- Modify: `gemini_tts.py` (nuova funzione prima di `synthesize`, riga 2136; corpo del ciclo di retry, righe 2234-2318)
- Test: `test/test_gemini_transport_vertex.py` (nuovo)

**Interfaces:**
- Consumes: `TransportError`, `TRANSPORT_KINDS` dal Task 2; gli helper già presenti in `gemini_tts.py`: `_get_client`, `_extract_audio_pcm`, `_is_429`, `_is_daily_quota_error`, `_parse_retry_after`, `_http_timeout_ms`, `GeminiEmptyResponse`.
- Produces: `_vertex_transport_call(*, final_text, voice_name, model_key, model_id, timeout_ms, temperature) -> dict`, conforme al contratto del Task 2.

**Criterio di accettazione vincolante:** al termine del task la suite passa **senza che un solo test esistente sia stato modificato**. L'estrazione è un refactor a comportamento invariato; qualunque test che si rompe segnala un cambiamento di comportamento da correggere nel codice.

- [ ] **Step 1: Registra la baseline della suite**

Run: `python -m pytest test/ -q --tb=line`
Annota il numero esatto di test passati e falliti prima di toccare qualsiasi cosa. È il metro con cui giudicherai lo Step 7.

- [ ] **Step 2: Scrivi il test che fallisce**

Crea `test/test_gemini_transport_vertex.py`:

```python
"""L'adapter Vertex rispetta il contratto di trasporto."""
import pytest

import gemini_tts
from gemini_transport import TRANSPORT_KINDS, TransportError


class _Usage:
    prompt_token_count = 11
    candidates_token_count = 250


class _FakeModels:
    def __init__(self, behaviour):
        self._behaviour = behaviour
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        return self._behaviour(kwargs)


class _FakeClient:
    def __init__(self, behaviour):
        self.models = _FakeModels(behaviour)


def _install(monkeypatch, behaviour, pcm=b"\x01\x02"):
    client = _FakeClient(behaviour)
    monkeypatch.setattr(gemini_tts, "_get_client", lambda model_key=None: client)
    monkeypatch.setattr(gemini_tts, "_extract_audio_pcm", lambda resp, mk: pcm)
    return client


def _call(**over):
    kwargs = dict(final_text="ciao", voice_name="Kore", model_key="flash31",
                  model_id="gemini-3.1-flash-tts-preview", timeout_ms=60000,
                  temperature=0.75)
    kwargs.update(over)
    return gemini_tts._vertex_transport_call(**kwargs)


def test_returns_pcm_and_usage(monkeypatch):
    class _Resp:
        usage_metadata = _Usage()

    _install(monkeypatch, lambda kw: _Resp(), pcm=b"\x00" * 48)
    out = _call()
    assert out["pcm"] == b"\x00" * 48
    assert out["input_tokens"] == 11
    assert out["output_tokens"] == 250


def test_missing_usage_metadata_yields_zero_not_crash(monkeypatch):
    class _Resp:
        usage_metadata = None

    _install(monkeypatch, lambda kw: _Resp())
    out = _call()
    assert out["input_tokens"] == 0
    assert out["output_tokens"] == 0


def test_passes_voice_and_model_through(monkeypatch):
    class _Resp:
        usage_metadata = _Usage()

    client = _install(monkeypatch, lambda kw: _Resp())
    _call(voice_name="Zephyr", model_id="modello-x")
    sent = client.models.calls[0]
    assert sent["model"] == "modello-x"
    assert "Zephyr" in repr(sent["config"])


def test_non_retryable_empty_response_becomes_content_rejected(monkeypatch):
    def _boom(kw):
        raise gemini_tts.GeminiEmptyResponse(
            "safety", block_reason="SAFETY", finish_reason="SAFETY",
            retryable=False)

    _install(monkeypatch, _boom)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "content_rejected"


def test_retryable_empty_response_becomes_retryable(monkeypatch):
    def _boom(kw):
        raise gemini_tts.GeminiEmptyResponse("vuota", finish_reason="OTHER",
                                             retryable=True)

    _install(monkeypatch, _boom)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "retryable"


def test_daily_quota_becomes_quota_daily_with_retry_after(monkeypatch):
    def _boom(kw):
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota per day")

    _install(monkeypatch, _boom)
    monkeypatch.setattr(gemini_tts, "_is_429", lambda e: True)
    monkeypatch.setattr(gemini_tts, "_is_daily_quota_error", lambda e: True)
    monkeypatch.setattr(gemini_tts, "_parse_retry_after", lambda e: 3600)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "quota_daily"
    assert ei.value.retry_after_sec == 3600


def test_plain_429_becomes_rate_limited(monkeypatch):
    def _boom(kw):
        raise RuntimeError("429 too many requests")

    _install(monkeypatch, _boom)
    monkeypatch.setattr(gemini_tts, "_is_429", lambda e: True)
    monkeypatch.setattr(gemini_tts, "_is_daily_quota_error", lambda e: False)
    monkeypatch.setattr(gemini_tts, "_parse_retry_after", lambda e: 7)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "rate_limited"
    assert ei.value.retry_after_sec == 7


def test_unknown_error_becomes_retryable(monkeypatch):
    _install(monkeypatch, lambda kw: (_ for _ in ()).throw(RuntimeError("boh")))
    monkeypatch.setattr(gemini_tts, "_is_429", lambda e: False)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind == "retryable"


def test_every_raised_kind_is_in_the_closed_set(monkeypatch):
    _install(monkeypatch, lambda kw: (_ for _ in ()).throw(RuntimeError("boh")))
    monkeypatch.setattr(gemini_tts, "_is_429", lambda e: False)
    with pytest.raises(TransportError) as ei:
        _call()
    assert ei.value.kind in TRANSPORT_KINDS
```

- [ ] **Step 3: Esegui il test e verifica che fallisca**

Run: `python -m pytest test/test_gemini_transport_vertex.py -v`
Expected: FAIL con `AttributeError: module 'gemini_tts' has no attribute '_vertex_transport_call'`

- [ ] **Step 4: Implementa l'adapter**

In `gemini_tts.py`, aggiungi l'import in testa al modulo, accanto agli altri import di primo livello:

```python
from gemini_transport import TransportError
```

e inserisci, subito prima di `def synthesize(` (riga 2136):

```python
def _vertex_transport_call(*, final_text, voice_name, model_key, model_id,
                           timeout_ms, temperature):
    """Adapter di trasporto Vertex / API key.

    Estratto dal corpo del ciclo di retry di `synthesize()`: qui c'e' UNA
    chiamata, senza retry e senza sleep. La politica di retry resta nel
    chiamante, che e' l'unico a sapere quanti tentativi restano e se puo'
    dirottare su un altro backend.

    Conforme al contratto di `gemini_transport`: ritorna pcm + token, solleva
    solo TransportError.
    """
    from google.genai import types as genai_types

    config_kwargs = {
        "response_modalities": ["AUDIO"],
        "speech_config": genai_types.SpeechConfig(
            voice_config=genai_types.VoiceConfig(
                prebuilt_voice_config=genai_types.PrebuiltVoiceConfig(
                    voice_name=voice_name,
                )
            )
        ),
    }
    if temperature is not None:
        config_kwargs["temperature"] = temperature

    client = _get_client(model_key)
    try:
        response = client.models.generate_content(
            model=model_id,
            contents=final_text,
            config=genai_types.GenerateContentConfig(
                **config_kwargs,
                http_options=genai_types.HttpOptions(timeout=timeout_ms),
            ),
        )
        pcm_data = _extract_audio_pcm(response, model_key)
    except GeminiEmptyResponse as e:
        # Il caller storico distingueva retryable da non-retryable: la
        # distinzione sopravvive nel kind.
        raise TransportError(
            str(e),
            kind="retryable" if e.retryable else "content_rejected",
        ) from e
    except Exception as e:
        if _is_429(e):
            retry_after = _parse_retry_after(e)
            kind = "quota_daily" if _is_daily_quota_error(e) else "rate_limited"
            raise TransportError(str(e), kind=kind,
                                 retry_after_sec=retry_after) from e
        raise TransportError(str(e), kind="retryable") from e

    um = getattr(response, "usage_metadata", None)
    return {
        "pcm": pcm_data,
        "input_tokens": (getattr(um, "prompt_token_count", 0) or 0) if um else 0,
        "output_tokens": (getattr(um, "candidates_token_count", 0) or 0) if um else 0,
    }
```

- [ ] **Step 5: Riscrivi il ciclo di retry di `synthesize()` sopra l'adapter**

In `synthesize()` sostituisci il blocco `while attempt < max_attempts:` (righe 2234-2318) con:

```python
    while attempt < max_attempts:
        attempt += 1
        try:
            out = _vertex_transport_call(
                final_text=final_text,
                voice_name=voice_name,
                model_key=model_key,
                model_id=model_id,
                timeout_ms=_http_timeout_ms(model_key),
                temperature=_temperature(),
            )
            pcm_data = out["pcm"]
            usage_input = out["input_tokens"] or 0
            usage_output = out["output_tokens"] or 0
            _rpd_increment(model_key)
            break
        except TransportError as te:
            last_err = te.__cause__ or te

            # Contenuto rifiutato: riprovare lo stesso testo non aiuta.
            if te.kind == "content_rejected":
                cause = te.__cause__
                print(f"[gemini-tts] Empty response non-retryable: "
                      f"finish_reason={getattr(cause, 'finish_reason', None)} "
                      f"block={getattr(cause, 'block_reason', None)}. "
                      f"Aborting attempts.")
                raise cause if cause is not None else te

            # Quota giornaliera: sospendere invece di dormire per ore.
            if te.kind == "quota_daily" and abort_daily:
                print(f"[gemini-tts] Daily quota exhausted ({model_key}). "
                      f"retry_after={te.retry_after_sec}s. "
                      f"Aborting (ABM_GEMINI_ABORT_ON_QUOTA=true).")
                raise GeminiQuotaExhausted(
                    f"Gemini daily quota exhausted: {last_err}",
                    retry_after_sec=te.retry_after_sec,
                    reason="api_daily_quota",
                )

            is_429 = te.kind in ("rate_limited", "quota_daily")
            retry_after = te.retry_after_sec
            if honor_delay and retry_after is not None:
                if retry_after > max_wait:
                    print(f"[gemini-tts] 429 retry_after={retry_after}s > "
                          f"max_wait={max_wait}s. Suspending instead of "
                          f"sleeping ({model_key}).")
                    raise GeminiQuotaExhausted(
                        f"Gemini 429 with long retry: {last_err}",
                        retry_after_sec=retry_after,
                        reason="retry_too_long",
                    )
                wait = max(1.0, retry_after)
            else:
                wait = min(30.0, 2 ** attempt)

            if attempt < max_attempts:
                print(f"[gemini-tts] Attempt {attempt}/{max_attempts} failed "
                      f"({'429' if is_429 else 'other'}). Sleeping {wait:.1f}s. "
                      f"Err: {str(last_err)[:200]}")
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"Gemini TTS failed after {max_attempts} attempts: {last_err}")
```

Nota sul `raise cause`: il ramo `content_rejected` risolleva la `GeminiEmptyResponse` originale, non la `TransportError`. È ciò che mantiene invariato il vocabolario di eccezioni verso l'esterno.

- [ ] **Step 6: Esegui i test nuovi**

Run: `python -m pytest test/test_gemini_transport_vertex.py test/test_gemini_transport_contract.py -v`
Expected: PASS

- [ ] **Step 7: Verifica il criterio di accettazione della fase**

Run: `python -m pytest test/ -q --tb=short`
Expected: **stesso identico esito della baseline dello Step 1**, senza aver modificato alcun test esistente. Se qualcosa si rompe, correggi `_vertex_transport_call` o il ciclo — mai il test.

- [ ] **Step 8: Commit**

```bash
git add gemini_tts.py test/test_gemini_transport_vertex.py
git commit -m "refactor(tts): estrae la chiamata Vertex dietro il contratto di trasporto"
```

---

### Task 4: adapter Cloudflare

**Files:**
- Modify: `gemini_transport.py`
- Test: `test/test_gemini_transport_cloudflare.py` (nuovo)

**Interfaces:**
- Consumes: `TransportError` dal Task 2.
- Produces:
  - `cloudflare_call(*, final_text, voice_name, model_key, model_id, timeout_ms, temperature) -> dict`
  - `_interpret_cloudflare_response(resp) -> dict` — separata perché è la parte che merita test senza HTTP.
  - `CF_API_URL: str` (template con `{account_id}`).

**Mappatura degli esiti** (tabella §4.2 della spec, verificata sul banco di prova):

| Esito HTTP | `kind` | `billed` |
|---|---|---|
| 200 con `result.audio` | successo | sì |
| 200 senza `result.audio` | `retryable` | **sì** — 8 casi su 738 nel banco |
| 400 codice `7003` con messaggio `Invalid value at <campo>` | `fatal` | no |
| 400 codice `7003` altrimenti | `retryable` | no |
| 422 codice `2017` | `content_rejected` | no |
| 402 codice `2021` | `backend_down` | no |
| 429 | `rate_limited` | no |
| 5xx / timeout / errore di rete | `retryable` | no |

Il criterio testuale `Invalid value at ` distingue il 7003 deterministico (parametro rifiutato: voce inesistente, campo sbagliato) da quello transitorio (*overloaded*). Se Cloudflare cambiasse il formato del messaggio, il degrado è qualche retry sprecato su un errore deterministico — non un comportamento scorretto.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_gemini_transport_cloudflare.py`:

```python
"""Adapter Cloudflare: decodifica dell'audio e mappatura degli errori."""
import base64
import json

import pytest

from gemini_transport import TransportError, _interpret_cloudflare_response


class _Resp:
    """Doppio minimale di requests.Response."""

    def __init__(self, status_code, payload=None, text=None):
        self.status_code = status_code
        self._payload = payload
        self.text = text if text is not None else json.dumps(payload or {})

    def json(self):
        if self._payload is None:
            raise ValueError("corpo non JSON")
        return self._payload


def _ok(pcm=b"\x01\x02\x03"):
    b64 = base64.b64encode(pcm).decode("ascii")
    return _Resp(200, {"result": {"audio": f"data:audio/l16;base64,{b64}"},
                       "success": True})


def test_decodes_the_data_uri_into_raw_pcm():
    out = _interpret_cloudflare_response(_ok(b"\x00" * 32))
    assert out["pcm"] == b"\x00" * 32


def test_tokens_are_unknown_because_the_api_does_not_return_them():
    out = _interpret_cloudflare_response(_ok())
    assert out["input_tokens"] is None
    assert out["output_tokens"] is None


def test_200_without_audio_is_retryable_but_billed():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(200, {"result": {}, "success": True}))
    assert ei.value.kind == "retryable"
    assert ei.value.billed is True


def test_400_7003_invalid_value_is_fatal():
    body = {"success": False, "errors": [
        {"code": 7003,
         "message": "Invalid value at voice: Invalid option: expected one of Achernar, Achird"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(400, body))
    assert ei.value.kind == "fatal"
    assert ei.value.provider_code == 7003
    assert ei.value.billed is False


def test_400_7003_overloaded_is_retryable():
    body = {"success": False,
            "errors": [{"code": 7003, "message": "Model is overloaded"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(400, body))
    assert ei.value.kind == "retryable"


def test_422_2017_is_content_rejected():
    body = {"success": False,
            "errors": [{"code": 2017, "message": "content moderation"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(422, body))
    assert ei.value.kind == "content_rejected"


def test_402_2021_is_backend_down():
    body = {"success": False,
            "errors": [{"code": 2021, "message": "insufficient balance"}]}
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(402, body))
    assert ei.value.kind == "backend_down"


def test_429_is_rate_limited():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(429, {"success": False, "errors": []}))
    assert ei.value.kind == "rate_limited"


def test_5xx_is_retryable():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(503, None, text="upstream down"))
    assert ei.value.kind == "retryable"


def test_unparseable_body_does_not_crash():
    with pytest.raises(TransportError) as ei:
        _interpret_cloudflare_response(_Resp(200, None, text="<html>nope"))
    assert ei.value.kind == "retryable"
    assert ei.value.billed is True


def test_missing_credentials_are_fatal(monkeypatch):
    import gemini_transport

    monkeypatch.delenv("ABM_CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ABM_CF_API_TOKEN", raising=False)
    with pytest.raises(TransportError) as ei:
        gemini_transport.cloudflare_call(
            final_text="ciao", voice_name="Kore", model_key="flash31",
            model_id="google/gemini-3.1-flash-tts", timeout_ms=1000,
            temperature=None)
    assert ei.value.kind == "fatal"


def test_the_token_never_appears_in_an_error_message(monkeypatch):
    import gemini_transport

    secret = "cf-token-che-non-deve-trapelare"
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", secret)

    class _Boom(Exception):
        pass

    def _fake_post(url, **kw):
        raise gemini_transport.requests.RequestException("rete giu'")

    monkeypatch.setattr(gemini_transport.requests, "post", _fake_post)
    with pytest.raises(TransportError) as ei:
        gemini_transport.cloudflare_call(
            final_text="ciao", voice_name="Kore", model_key="flash31",
            model_id="google/gemini-3.1-flash-tts", timeout_ms=1000,
            temperature=None)
    assert secret not in str(ei.value)


def test_payload_carries_text_voice_and_temperature(monkeypatch):
    import gemini_transport

    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    seen = {}

    def _fake_post(url, headers=None, json=None, timeout=None):
        seen["url"] = url
        seen["json"] = json
        seen["timeout"] = timeout
        return _ok()

    monkeypatch.setattr(gemini_transport.requests, "post", _fake_post)
    gemini_transport.cloudflare_call(
        final_text="ciao", voice_name="Zephyr", model_key="flash31",
        model_id="google/gemini-3.1-flash-tts", timeout_ms=45000,
        temperature=0.75)

    assert "acc" in seen["url"]
    # Il campo si chiama "text", non "prompt": verificato sul banco.
    assert seen["json"]["input"]["text"] == "ciao"
    assert seen["json"]["input"]["voice"] == "Zephyr"
    assert seen["json"]["input"]["temperature"] == 0.75
    assert seen["json"]["model"] == "google/gemini-3.1-flash-tts"
    assert seen["timeout"] == 45.0
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_gemini_transport_cloudflare.py -v`
Expected: FAIL con `ImportError: cannot import name '_interpret_cloudflare_response'`

- [ ] **Step 3: Implementa l'adapter**

Aggiungi in cima a `gemini_transport.py`, sotto il docstring:

```python
import base64
import os

import requests
```

e in coda al modulo:

```python
CF_API_URL = "https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"
# Prefisso del data URI restituito da Cloudflare: PCM s16le 24 kHz mono, senza
# header RIFF. Identico al payload `inline_data` di Vertex: e' questa
# coincidenza che rende lecito il failover a meta' job.
_CF_AUDIO_PREFIX = "base64,"
# Distingue il 7003 deterministico (parametro rifiutato) da quello transitorio
# (modello sovraccarico). Se il formato del messaggio cambiasse, il degrado e'
# qualche retry sprecato, non un comportamento scorretto.
_CF_INVALID_VALUE_MARK = "Invalid value at "


def _cf_first_error(body):
    """(codice, messaggio) del primo errore Cloudflare, o (None, "")."""
    try:
        errors = body.get("errors") or []
        if errors:
            first = errors[0]
            return first.get("code"), str(first.get("message") or "")
    except AttributeError:
        pass
    return None, ""


def _interpret_cloudflare_response(resp):
    """Traduce una risposta Cloudflare nel contratto di trasporto.

    Separata da `cloudflare_call` perche' e' la parte che merita test senza
    HTTP: la tabella di mappatura e' il cuore del comportamento in avaria.
    """
    status = resp.status_code
    try:
        body = resp.json()
    except (ValueError, AttributeError):
        body = None

    if status == 200:
        # Doctrine di fatturazione verificata sul campo: una 200 e' addebitata
        # comunque, anche se il corpo non contiene audio.
        audio = None
        if isinstance(body, dict):
            audio = (body.get("result") or {}).get("audio")
        if not audio:
            raise TransportError(
                "Cloudflare ha risposto 200 senza audio",
                kind="retryable", billed=True, http_status=200)
        idx = audio.find(_CF_AUDIO_PREFIX)
        raw = audio[idx + len(_CF_AUDIO_PREFIX):] if idx >= 0 else audio
        try:
            pcm = base64.b64decode(raw)
        except (ValueError, TypeError) as e:
            raise TransportError(
                "audio Cloudflare non decodificabile",
                kind="retryable", billed=True, http_status=200) from e
        if not pcm:
            raise TransportError(
                "audio Cloudflare vuoto dopo la decodifica",
                kind="retryable", billed=True, http_status=200)
        # L'API non restituisce i token: la stima spetta al chiamante, che
        # conosce il modello e il rapporto token/secondo.
        return {"pcm": pcm, "input_tokens": None, "output_tokens": None}

    code, message = _cf_first_error(body or {})

    if status == 402 or code == 2021:
        raise TransportError(
            f"credito Cloudflare esaurito (codice {code}): {message}",
            kind="backend_down", http_status=status, provider_code=code)

    if status == 422 or code == 2017:
        raise TransportError(
            f"contenuto rifiutato da Cloudflare (codice {code}): {message}",
            kind="content_rejected", http_status=status, provider_code=code)

    if status == 429:
        raise TransportError(
            f"Cloudflare rate limit: {message}",
            kind="rate_limited", http_status=status, provider_code=code)

    if status == 400 and code == 7003:
        if _CF_INVALID_VALUE_MARK in message:
            raise TransportError(
                f"parametro rifiutato da Cloudflare: {message}",
                kind="fatal", http_status=status, provider_code=code)
        raise TransportError(
            f"Cloudflare temporaneamente non disponibile: {message}",
            kind="retryable", http_status=status, provider_code=code)

    detail = message or (getattr(resp, "text", "") or "")[:200]
    raise TransportError(
        f"Cloudflare HTTP {status}: {detail}",
        kind="retryable", http_status=status, provider_code=code)


def cloudflare_call(*, final_text, voice_name, model_key, model_id,
                    timeout_ms, temperature):
    """Adapter di trasporto Cloudflare Workers AI.

    Una chiamata, nessun retry: la politica di retry resta al chiamante.
    Il token viene letto dall'ambiente e non compare mai in un messaggio di
    errore: gli header non vengono mai serializzati in un'eccezione.
    """
    account_id = os.environ.get("ABM_CF_ACCOUNT_ID", "").strip()
    token = os.environ.get("ABM_CF_API_TOKEN", "").strip()
    if not account_id or not token:
        raise TransportError(
            "backend Cloudflare non configurato "
            "(ABM_CF_ACCOUNT_ID / ABM_CF_API_TOKEN assenti)",
            kind="fatal")

    payload = {"model": model_id,
               "input": {"text": final_text, "voice": voice_name}}
    if temperature is not None:
        payload["input"]["temperature"] = float(temperature)

    try:
        resp = requests.post(
            CF_API_URL.format(account_id=account_id),
            headers={"Authorization": f"Bearer {token}"},
            json=payload,
            timeout=timeout_ms / 1000.0,
        )
    except requests.Timeout as e:
        # Il timeout lato client lascia ambiguo l'addebito: la chiamata
        # potrebbe essere arrivata a destinazione. Non dichiariamo billed.
        raise TransportError("timeout verso Cloudflare",
                             kind="retryable") from e
    except requests.RequestException as e:
        raise TransportError(f"errore di rete verso Cloudflare: "
                             f"{type(e).__name__}", kind="retryable") from e

    return _interpret_cloudflare_response(resp)
```

- [ ] **Step 4: Esegui i test e verifica che passino**

Run: `python -m pytest test/test_gemini_transport_cloudflare.py -v`
Expected: PASS (13 test)

- [ ] **Step 5: Commit**

```bash
git add gemini_transport.py test/test_gemini_transport_cloudflare.py
git commit -m "feat(tts): adapter Cloudflare Workers AI per la sintesi Gemini"
```

---

### Task 5: risoluzione del backend per modello

**Files:**
- Modify: `gemini_tts.py` (`GEMINI_MODELS`, righe 144-163; `_BACKEND` e `_resolve_backend`, righe 169-215)
- Test: `test/test_gemini_backend_resolve.py` (nuovo)

**Interfaces:**
- Consumes: niente dai task precedenti.
- Produces:
  - `GEMINI_MODELS[k]["id_cloudflare"]` — identificativo del modello lato Cloudflare (`None` per i modelli non ospitati lì).
  - `_resolve_backend(model_key=None) -> "vertex" | "apikey" | "cloudflare" | None`, con cache **per modello**.
  - `_set_backend(model_key, backend)` — imposta il backend attivo di un modello a runtime, sotto `_BACKEND_LOCK`. È il gancio che il Task 7 usa per il failover.

**Perché per modello:** solo `flash31` è verificato su Cloudflare. `flash25` resta su Vertex finché non è confermato che Cloudflare lo ospiti (`id_cloudflare = None` significa esattamente questo). Una cache globale renderebbe impossibile questa asimmetria.

**Perché mutabile:** il failover del Task 7 deve poter spostare `flash31` da `cloudflare` a `vertex` a processo vivo. La cache attuale è congelata al primo uso proprio per evitare flip-flop da env: la mutabilità va concessa solo alla via esplicita `_set_backend`, non alla rilettura dell'ambiente.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_gemini_backend_resolve.py`:

```python
"""Risoluzione del backend Gemini, per modello."""
import pytest

import gemini_tts


@pytest.fixture(autouse=True)
def _reset_backend_cache():
    gemini_tts._BACKEND = {}
    yield
    gemini_tts._BACKEND = {}


def _vertex_env(monkeypatch, tmp_path):
    creds = tmp_path / "sa.json"
    creds.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("ABM_GCP_PROJECT_ID", "progetto")
    monkeypatch.setenv("ABM_GOOGLE_CREDENTIALS_FILE", str(creds))


def test_flash31_has_a_cloudflare_id():
    assert gemini_tts.GEMINI_MODELS["flash31"]["id_cloudflare"] == \
        "google/gemini-3.1-flash-tts"


def test_flash25_has_no_cloudflare_id_until_verified():
    # Nessuna verifica che Cloudflare ospiti flash25: finche' non c'e',
    # il modello resta su Vertex.
    assert gemini_tts.GEMINI_MODELS["flash25"]["id_cloudflare"] is None


def test_auto_never_selects_cloudflare(monkeypatch, tmp_path):
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_explicit_cloudflare_is_honoured(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    assert gemini_tts._resolve_backend("flash31") == "cloudflare"


def test_cloudflare_without_credentials_is_disabled(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.delenv("ABM_CF_ACCOUNT_ID", raising=False)
    monkeypatch.delenv("ABM_CF_API_TOKEN", raising=False)
    assert gemini_tts._resolve_backend("flash31") is None


def test_a_model_without_cloudflare_id_falls_back_to_vertex(monkeypatch, tmp_path):
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    # flash25 non e' su Cloudflare: non deve finirci per errore.
    assert gemini_tts._resolve_backend("flash25") == "vertex"


def test_resolution_is_cached_per_model(monkeypatch, tmp_path):
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "vertex")
    assert gemini_tts._resolve_backend("flash31") == "vertex"
    # Cambiare l'ambiente dopo la risoluzione non deve muovere nulla.
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "apikey")
    monkeypatch.setenv("ABM_GEMINI_API_KEY", "k")
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_set_backend_overrides_the_cache(monkeypatch):
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    assert gemini_tts._resolve_backend("flash31") == "cloudflare"
    gemini_tts._set_backend("flash31", "vertex")
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_set_backend_rejects_an_unknown_backend():
    with pytest.raises(ValueError):
        gemini_tts._set_backend("flash31", "piccione-viaggiatore")


def test_resolve_without_model_key_still_works(monkeypatch, tmp_path):
    # Retro-compatibilita': i caller storici chiamano _resolve_backend() nudo.
    _vertex_env(monkeypatch, tmp_path)
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "auto")
    assert gemini_tts._resolve_backend() == "vertex"
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_gemini_backend_resolve.py -v`
Expected: FAIL — `id_cloudflare` non esiste e `_BACKEND` non è un dict.

- [ ] **Step 3: Aggiungi `id_cloudflare` a `GEMINI_MODELS`**

In `gemini_tts.py`, dentro `GEMINI_MODELS` (righe 144-163), aggiungi a `flash25`, subito sotto `"id_vertex"`:

```python
        # Nessuna verifica che Cloudflare ospiti questo modello: finche' non
        # c'e', flash25 resta su Vertex anche con backend=cloudflare.
        "id_cloudflare": None,
```

e a `flash31`, nella stessa posizione:

```python
        # Verificato il 26/08/2026: 30/30 voci sintetizzate, enum voci
        # coincidente con GEMINI_VOICE_NAMES (spec §10.1).
        "id_cloudflare": "google/gemini-3.1-flash-tts",
```

- [ ] **Step 4: Riscrivi il resolver**

Sostituisci il blocco righe 169-215 (`_BACKEND = None` … fine di `_resolve_backend`) con:

```python
# Cache per modello: il backend viene risolto al primo uso di quel modello e
# congelato, per evitare flip-flop se un task cambia env fra due chiamate.
# Muta solo per via esplicita, tramite `_set_backend` (failover del breaker).
# Reset esplicito (per test): `gemini_tts._BACKEND = {}`.
# Valori: "vertex" | "apikey" | "cloudflare" | False (DISABLED).
_BACKEND = {}
_BACKEND_LOCK = threading.Lock()

_VALID_BACKENDS = ("vertex", "apikey", "cloudflare")


def _set_backend(model_key, backend):
    """Forza il backend attivo di un modello. Usato dal failover.

    Non tocca l'ambiente: e' una decisione di runtime, e sopravvive solo per la
    vita del processo. La persistenza dello stato di trip e' responsabilita' di
    `tts_backend_state`.
    """
    if backend not in _VALID_BACKENDS and backend is not False:
        raise ValueError(f"backend sconosciuto: {backend!r}")
    with _BACKEND_LOCK:
        _BACKEND[model_key or "_default"] = backend
    print(f"[gemini-tts] Backend di {model_key} impostato su {backend}")


def _resolve_backend(model_key=None):
    """Risolve quale backend Gemini usare per un modello.

    Returns:
        "vertex" | "apikey" | "cloudflare" | None (None = TTS disabilitato).

    Logica:
    - ABM_GEMINI_BACKEND=vertex: richiede ABM_GCP_PROJECT_ID +
      ABM_GOOGLE_CREDENTIALS_FILE leggibile. Se mancano -> DISABLED.
    - ABM_GEMINI_BACKEND=apikey: richiede ABM_GEMINI_API_KEY.
    - ABM_GEMINI_BACKEND=cloudflare: richiede ABM_CF_ACCOUNT_ID +
      ABM_CF_API_TOKEN, E che il modello abbia un `id_cloudflare`. Un modello
      non ospitato su Cloudflare ricade su Vertex, non va in errore.
    - ABM_GEMINI_BACKEND unset o "auto": Vertex se la config e' completa,
      altrimenti API key se presente, altrimenti DISABLED. **auto non seleziona
      mai Cloudflare**: quel backend e' solo opt-in esplicito.
    """
    key = model_key or "_default"
    cached = _BACKEND.get(key)
    if cached is not None:
        return cached if cached else None
    with _BACKEND_LOCK:
        cached = _BACKEND.get(key)
        if cached is not None:
            return cached if cached else None

        choice = (os.environ.get("ABM_GEMINI_BACKEND", "auto") or "auto").strip().lower()
        project = os.environ.get("ABM_GCP_PROJECT_ID", "").strip()
        creds = os.environ.get("ABM_GOOGLE_CREDENTIALS_FILE", "").strip()
        api_key = os.environ.get("ABM_GEMINI_API_KEY", "").strip()
        cf_account = os.environ.get("ABM_CF_ACCOUNT_ID", "").strip()
        cf_token = os.environ.get("ABM_CF_API_TOKEN", "").strip()

        vertex_ready = bool(project) and bool(creds) and os.path.isfile(creds)
        apikey_ready = bool(api_key)
        model_on_cf = bool((GEMINI_MODELS.get(key) or {}).get("id_cloudflare"))
        cf_ready = bool(cf_account) and bool(cf_token) and model_on_cf

        if choice == "vertex":
            resolved = "vertex" if vertex_ready else False
        elif choice == "apikey":
            resolved = "apikey" if apikey_ready else False
        elif choice == "cloudflare":
            if cf_ready:
                resolved = "cloudflare"
            elif model_on_cf:
                # Credenziali Cloudflare assenti: e' un errore di
                # configurazione, non un motivo per usare Vertex di nascosto.
                resolved = False
            elif vertex_ready:
                # Il modello non e' ospitato su Cloudflare: Vertex e' la scelta
                # corretta, non un ripiego.
                resolved = "vertex"
            else:
                resolved = False
        else:  # auto / sconosciuto
            if vertex_ready:
                resolved = "vertex"
            elif apikey_ready:
                resolved = "apikey"
            else:
                resolved = False

        _BACKEND[key] = resolved
        if resolved:
            print(f"[gemini-tts] Backend resolved ({key}): {resolved}")
        return resolved if resolved else None
```

- [ ] **Step 5: Allinea i caller storici di `_resolve_backend`**

Run: `grep -n "_resolve_backend\|_BACKEND" gemini_tts.py test/ -r`

Ogni chiamata senza argomenti continua a funzionare (chiave `_default`). Verifica in particolare i test esistenti che azzerano la cache con `gemini_tts._BACKEND = None`: vanno riletti, e se ce ne sono, **è l'unico caso in cui questo task tocca un test esistente** — la cache non è più uno scalare. Documenta nel commit quali test hai dovuto adeguare e perché.

- [ ] **Step 6: Esegui i test**

Run: `python -m pytest test/test_gemini_backend_resolve.py -v`
Expected: PASS (10 test)

- [ ] **Step 7: Verifica la suite**

Run: `python -m pytest test/ -q --tb=short`
Expected: nessun fallimento nuovo.

- [ ] **Step 8: Commit**

```bash
git add gemini_tts.py test/test_gemini_backend_resolve.py
git commit -m "feat(tts): risoluzione del backend Gemini per modello, con Cloudflare opt-in"
```

---

### Task 6: stato persistito del backend e circuit breaker

**Files:**
- Create: `tts_backend_state.py`
- Test: `test/test_tts_backend_state.py` (nuovo)

**Interfaces:**
- Consumes: niente. Modulo foglia, inizializzato con `init(data_dir)` secondo la convenzione di progetto n. 1.
- Produces:
  - `init(data_dir)` — fissa il percorso di `_tts_backend_state.json`.
  - `state(model_key) -> dict` — lo stato corrente del modello (dizionario vuoto se mai scritto).
  - `trip(model_key, *, reason, detail, job_id) -> bool` — **True solo al primo chiamante**; idempotente sotto lock.
  - `reset(model_key) -> bool` — rientro manuale; True se c'era un trip da azzerare.
  - `record_failure(model_key) -> int` / `record_success(model_key)` — contatore di fallimenti consecutivi.
  - `is_tripped(model_key) -> bool`.

**Forma del file** (`ABM_DATA_DIR/_tts_backend_state.json`):

```json
{"flash31": {"active": "vertex",
             "tripped_at": "2026-08-26T10:11:12Z",
             "trip_reason": "cf_credit_exhausted",
             "trip_detail": "HTTP 402 code 2021",
             "trip_job_id": "abc123",
             "consecutive_failures": 3,
             "notified": true}}
```

**Perché `trip()` ritorna un booleano:** con più job in corso, N thread possono scoprire l'avaria nello stesso istante. Solo il primo deve mandare l'email all'admin. Il ritorno del lock è ciò che distingue il primo dagli altri, e non richiede un secondo meccanismo di deduplica.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_tts_backend_state.py`:

```python
"""Stato persistito del backend TTS e circuit breaker."""
import json
import threading

import pytest

import tts_backend_state as st


@pytest.fixture(autouse=True)
def _fresh(tmp_path):
    st.init(str(tmp_path))
    yield


def test_unknown_model_has_empty_state():
    assert st.state("flash31") == {}
    assert st.is_tripped("flash31") is False


def test_trip_marks_the_model_and_persists(tmp_path):
    assert st.trip("flash31", reason="cf_credit_exhausted",
                   detail="HTTP 402 code 2021", job_id="j1") is True
    s = st.state("flash31")
    assert s["active"] == "vertex"
    assert s["trip_reason"] == "cf_credit_exhausted"
    assert s["trip_detail"] == "HTTP 402 code 2021"
    assert s["trip_job_id"] == "j1"
    assert s["tripped_at"]
    assert st.is_tripped("flash31") is True

    on_disk = json.loads((tmp_path / "_tts_backend_state.json").read_text("utf-8"))
    assert on_disk["flash31"]["active"] == "vertex"


def test_trip_is_idempotent_only_the_first_caller_gets_true():
    assert st.trip("flash31", reason="r", detail="d", job_id="j1") is True
    assert st.trip("flash31", reason="r2", detail="d2", job_id="j2") is False
    # Il primo trip resta quello registrato: la causa originale e' quella utile.
    assert st.state("flash31")["trip_job_id"] == "j1"


def test_trip_is_idempotent_under_concurrency():
    winners = []
    barrier = threading.Barrier(8)

    def _worker(i):
        barrier.wait()
        if st.trip("flash31", reason="r", detail=f"d{i}", job_id=f"j{i}"):
            winners.append(i)

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(winners) == 1


def test_reset_clears_the_trip():
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    assert st.reset("flash31") is True
    assert st.is_tripped("flash31") is False
    assert st.state("flash31")["active"] == "cloudflare"
    # Un reset a vuoto e' innocuo e lo dichiara.
    assert st.reset("flash31") is False


def test_consecutive_failures_accumulate_and_reset():
    assert st.record_failure("flash31") == 1
    assert st.record_failure("flash31") == 2
    st.record_success("flash31")
    assert st.state("flash31")["consecutive_failures"] == 0


def test_failures_do_not_trip_on_their_own():
    for _ in range(10):
        st.record_failure("flash31")
    # Il conteggio e' un dato; la decisione di scattare spetta al chiamante,
    # che confronta con ABM_CF_TRIP_FAILURES.
    assert st.is_tripped("flash31") is False


def test_state_survives_a_reload(tmp_path):
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    st.init(str(tmp_path))  # simula un riavvio del processo
    assert st.is_tripped("flash31") is True


def test_a_corrupt_file_does_not_crash_the_module(tmp_path):
    (tmp_path / "_tts_backend_state.json").write_text("{non json", encoding="utf-8")
    st.init(str(tmp_path))
    # Uno stato illeggibile non deve impedire la sintesi: si riparte puliti.
    assert st.state("flash31") == {}
    assert st.trip("flash31", reason="r", detail="d", job_id="j") is True


def test_notified_flag_is_settable():
    st.trip("flash31", reason="r", detail="d", job_id="j1")
    assert st.state("flash31")["notified"] is False
    st.mark_notified("flash31")
    assert st.state("flash31")["notified"] is True
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_tts_backend_state.py -v`
Expected: FAIL con `ModuleNotFoundError: No module named 'tts_backend_state'`

- [ ] **Step 3: Implementa il modulo**

Crea `tts_backend_state.py`:

```python
"""Stato persistito del backend TTS: circuit breaker a senso unico.

Modulo foglia. Nessun import di `audiobook_app` o `gemini_tts`: lo stato e'
un dato, non una decisione. Chi decide di far scattare il breaker e' il
chiamante, che confronta `record_failure` con ABM_CF_TRIP_FAILURES.

Il rientro su Cloudflare avviene solo per azione manuale dell'admin
(`reset`), mai automaticamente: un backend che e' andato giu' per credito
esaurito tornerebbe a cadere subito, e ogni caduta costa un job.

File di stato: <data_dir>/_tts_backend_state.json
"""
import json
import os
import threading
from datetime import datetime, timezone

_STATE_PATH = None
_LOCK = threading.RLock()
_CACHE = {}

_FILENAME = "_tts_backend_state.json"


def init(data_dir):
    """Fissa la directory dello stato e ricarica dal disco."""
    global _STATE_PATH, _CACHE
    with _LOCK:
        _STATE_PATH = os.path.join(data_dir, _FILENAME)
        _CACHE = _load()


def _load():
    if not _STATE_PATH or not os.path.isfile(_STATE_PATH):
        return {}
    try:
        with open(_STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError) as e:
        # Uno stato illeggibile non deve impedire la sintesi: si riparte
        # puliti. Il caso peggiore e' un'email di trip in piu'.
        print(f"[tts-backend-state] stato illeggibile, riparto vuoto: {e}")
        return {}


def _save():
    if not _STATE_PATH:
        return
    tmp = _STATE_PATH + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_CACHE, f, ensure_ascii=False, indent=2)
        os.replace(tmp, _STATE_PATH)
    except OSError as e:
        print(f"[tts-backend-state] scrittura fallita: {e}")


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def state(model_key):
    with _LOCK:
        return dict(_CACHE.get(model_key) or {})


def is_tripped(model_key):
    return bool(state(model_key).get("tripped_at"))


def trip(model_key, *, reason, detail, job_id):
    """Fa scattare il breaker. True solo al PRIMO chiamante.

    Con piu' job in corso, N thread scoprono l'avaria nello stesso istante:
    il ritorno booleano sotto lock e' cio' che permette di mandare una sola
    email all'admin senza un secondo meccanismo di deduplica.
    """
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        if entry.get("tripped_at"):
            return False
        entry.update({
            "active": "vertex",
            "tripped_at": _now(),
            "trip_reason": reason,
            "trip_detail": str(detail)[:300],
            "trip_job_id": job_id,
            "notified": False,
        })
        _save()
        print(f"[tts-backend-state] TRIP {model_key}: {reason} ({detail})")
        return True


def mark_notified(model_key):
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        entry["notified"] = True
        _save()


def reset(model_key):
    """Rientro manuale su Cloudflare. True se c'era davvero un trip."""
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        had_trip = bool(entry.get("tripped_at"))
        entry.update({
            "active": "cloudflare",
            "tripped_at": None,
            "trip_reason": None,
            "trip_detail": None,
            "trip_job_id": None,
            "consecutive_failures": 0,
            "notified": False,
        })
        _save()
        print(f"[tts-backend-state] RESET {model_key} (aveva trip: {had_trip})")
        return had_trip


def record_failure(model_key):
    """Incrementa e ritorna i fallimenti consecutivi. Non fa scattare nulla."""
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        entry["consecutive_failures"] = int(entry.get("consecutive_failures", 0)) + 1
        _save()
        return entry["consecutive_failures"]


def record_success(model_key):
    with _LOCK:
        entry = _CACHE.setdefault(model_key, {})
        if entry.get("consecutive_failures"):
            entry["consecutive_failures"] = 0
            _save()
```

- [ ] **Step 4: Inizializza il modulo all'avvio**

In `audiobook_app.py`, accanto alla riga che inizializza `community_store` (`community_store.init(_DATA_DIR)`), aggiungi:

```python
tts_backend_state.init(_DATA_DIR)
```

con il relativo `import tts_backend_state` fra gli import di primo livello. Trova la riga esistente con:

Run: `grep -n "community_store.init" audiobook_app.py`

- [ ] **Step 5: Esegui i test**

Run: `python -m pytest test/test_tts_backend_state.py -v`
Expected: PASS (10 test)

- [ ] **Step 6: Verifica che l'app parta**

Run: `python -c "import audiobook_app"`
Expected: nessuna eccezione di import.

- [ ] **Step 7: Commit**

```bash
git add tts_backend_state.py audiobook_app.py test/test_tts_backend_state.py
git commit -m "feat(tts): stato persistito del backend con circuit breaker idempotente"
```

---

### Task 7: failover automatico su Vertex

**Files:**
- Modify: `gemini_tts.py` (`synthesize`, ciclo di retry riscritto nel Task 3)
- Test: `test/test_gemini_failover.py` (nuovo)

**Interfaces:**
- Consumes: `_vertex_transport_call` (Task 3), `gemini_transport.cloudflare_call` (Task 4), `_resolve_backend` / `_set_backend` (Task 5), `tts_backend_state` (Task 6).
- Produces:
  - `set_backend_switch_notifier(fn)` — registra la callback invocata al primo trip, con firma `fn(model_key, reason, detail, job_id)`. Il Task del piano gemello ci aggancia l'email all'admin. Default: nessuna callback.
  - `synthesize(..., job_id=None)` — nuovo parametro opzionale, propagato allo stato di trip per rendere tracciabile quale job ha visto l'avaria.

**Regola di scatto** (spec §4.4):

1. Un `TransportError` con `kind="backend_down"` fa scattare il breaker **immediatamente**: il credito esaurito non migliora riprovando.
2. Un `kind="retryable"` o `"rate_limited"` incrementa i fallimenti consecutivi; al raggiungimento di `ABM_CF_TRIP_FAILURES` (default 3) fa scattare il breaker.
3. Un successo azzera il contatore.
4. `kind="fatal"` e `kind="content_rejected"` **non** fanno scattare nulla: sono difetti del payload, non del backend. Farebbero cadere Cloudflare per colpa di un chunk sbagliato.
5. Allo scatto la **stessa chiamata prosegue su Vertex**, con i tentativi rimanenti. L'audio è identico byte per byte, quindi il job in corso non si accorge del cambio. Se Vertex non è pronto, `GeminiUnavailable`.

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_gemini_failover.py`:

```python
"""Failover automatico da Cloudflare a Vertex."""
import pytest

import gemini_tts
import tts_backend_state as st
from gemini_transport import TransportError


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    gemini_tts._BACKEND = {}
    monkeypatch.setenv("ABM_GEMINI_BACKEND", "cloudflare")
    monkeypatch.setenv("ABM_CF_ACCOUNT_ID", "acc")
    monkeypatch.setenv("ABM_CF_API_TOKEN", "tok")
    monkeypatch.setattr(gemini_tts, "is_available", lambda: True)
    monkeypatch.setattr(gemini_tts, "_check_rpd_cap", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_throttle_rpm", lambda mk: None)
    monkeypatch.setattr(gemini_tts, "_rpd_increment", lambda mk: None)
    gemini_tts.set_backend_switch_notifier(None)
    yield
    gemini_tts._BACKEND = {}
    gemini_tts.set_backend_switch_notifier(None)


def _pcm(n=48):
    return {"pcm": b"\x00" * n, "input_tokens": None, "output_tokens": None}


def _synth(tmp_path, **kw):
    return gemini_tts.synthesize(
        "ciao mondo", "gemini:flash31:Kore",
        output_path=str(tmp_path / "o.pcm"), **kw)


def test_credit_exhausted_trips_and_continues_on_vertex(tmp_path, monkeypatch):
    vertex_calls = []

    def _cf(**kw):
        raise TransportError("credito esaurito", kind="backend_down",
                             http_status=402, provider_code=2021)

    def _vx(**kw):
        vertex_calls.append(kw)
        return {"pcm": b"\x01" * 48, "input_tokens": 10, "output_tokens": 200}

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _vx)

    out = _synth(tmp_path, job_id="j42")

    assert out["success"] is True
    assert len(vertex_calls) == 1
    assert st.is_tripped("flash31") is True
    assert st.state("flash31")["trip_job_id"] == "j42"
    assert gemini_tts._resolve_backend("flash31") == "vertex"


def test_the_notifier_fires_once_at_the_trip(tmp_path, monkeypatch):
    seen = []
    gemini_tts.set_backend_switch_notifier(
        lambda model_key, reason, detail, job_id: seen.append(
            (model_key, reason, job_id)))

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    _synth(tmp_path, job_id="j1")
    _synth(tmp_path, job_id="j2")

    assert len(seen) == 1
    assert seen[0][0] == "flash31"


def test_transient_failures_trip_only_at_the_threshold(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_CF_TRIP_FAILURES", "3")
    monkeypatch.setattr(gemini_tts, "_synth_max_attempts", lambda: 1)
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("glitch", kind="retryable")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    for _ in range(2):
        with pytest.raises(RuntimeError):
            _synth(tmp_path)
    assert st.is_tripped("flash31") is False

    # Il terzo fallimento consecutivo fa scattare il breaker: la chiamata
    # prosegue su Vertex invece di fallire.
    out = _synth(tmp_path)
    assert out["success"] is True
    assert st.is_tripped("flash31") is True


def test_a_success_resets_the_failure_counter(tmp_path, monkeypatch):
    monkeypatch.setenv("ABM_CF_TRIP_FAILURES", "3")
    monkeypatch.setattr(gemini_tts, "_synth_max_attempts", lambda: 1)
    outcomes = [TransportError("glitch", kind="retryable"), None,
                TransportError("glitch", kind="retryable")]

    def _cf(**kw):
        exc = outcomes.pop(0)
        if exc:
            raise exc
        return _pcm()

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call", _cf)
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(RuntimeError):
        _synth(tmp_path)
    _synth(tmp_path)  # successo: azzera
    with pytest.raises(RuntimeError):
        _synth(tmp_path)
    assert st.state("flash31")["consecutive_failures"] == 1


def test_content_rejected_does_not_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("moderazione", kind="content_rejected",
                                           provider_code=2017)))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(Exception):
        _synth(tmp_path)
    # Un chunk sbagliato non deve buttare giu' il backend per tutti.
    assert st.is_tripped("flash31") is False


def test_fatal_does_not_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("voce inesistente", kind="fatal",
                                           provider_code=7003)))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    with pytest.raises(Exception):
        _synth(tmp_path)
    assert st.is_tripped("flash31") is False


def test_trip_without_a_ready_vertex_raises_unavailable(tmp_path, monkeypatch):
    def _vx(**kw):
        raise gemini_tts.GeminiUnavailable("Vertex non configurato")

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: (_ for _ in ()).throw(
                            TransportError("giu'", kind="backend_down")))
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", _vx)

    with pytest.raises(gemini_tts.GeminiUnavailable):
        _synth(tmp_path)


def test_a_tripped_model_goes_straight_to_vertex(tmp_path, monkeypatch):
    st.trip("flash31", reason="cf_credit_exhausted", detail="d", job_id="j0")
    gemini_tts._set_backend("flash31", "vertex")
    cf_calls = []

    monkeypatch.setattr(gemini_tts._transport, "cloudflare_call",
                        lambda **kw: cf_calls.append(kw) or _pcm())
    monkeypatch.setattr(gemini_tts, "_vertex_transport_call", lambda **kw: _pcm())

    _synth(tmp_path)
    assert cf_calls == []
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_gemini_failover.py -v`
Expected: FAIL — `set_backend_switch_notifier` e `_transport` non esistono.

- [ ] **Step 3: Implementa il dispatch e il failover**

In `gemini_tts.py`, accanto all'import del Task 3, aggiungi:

```python
import gemini_transport as _transport
import tts_backend_state as _backend_state
```

Sotto le costanti del modulo aggiungi:

```python
# Callback invocata una sola volta, al primo scatto del breaker. Il piano
# gemello (Fase 6) ci aggancia l'email all'admin; qui resta un gancio nudo per
# non far dipendere gemini_tts da email_service.
_backend_switch_notifier = None


def set_backend_switch_notifier(fn):
    """Registra la callback di trip: fn(model_key, reason, detail, job_id)."""
    global _backend_switch_notifier
    _backend_switch_notifier = fn


def _cf_trip_failures():
    try:
        return max(1, int(os.environ.get("ABM_CF_TRIP_FAILURES", "3") or 3))
    except (TypeError, ValueError):
        return 3


def _transport_for(backend):
    """Adapter di trasporto corrispondente al backend risolto."""
    if backend == "cloudflare":
        return _transport.cloudflare_call
    return _vertex_transport_call


def _trip_to_vertex(model_key, *, reason, detail, job_id):
    """Fa scattare il breaker e sposta il modello su Vertex.

    L'email parte solo al primo chiamante: con piu' job in corso N thread
    scoprono l'avaria insieme, e `trip()` e' idempotente sotto lock.
    """
    first = _backend_state.trip(model_key, reason=reason, detail=detail,
                                job_id=job_id)
    _set_backend(model_key, "vertex")
    if first and _backend_switch_notifier is not None:
        try:
            _backend_switch_notifier(model_key, reason, detail, job_id)
            _backend_state.mark_notified(model_key)
        except Exception as e:
            # Un guasto nella notifica non deve fermare il job: il failover
            # e' gia' avvenuto, l'email e' un di piu'.
            print(f"[gemini-tts] notifica di switch backend fallita: {e}")
```

Nella firma di `synthesize` aggiungi il parametro `job_id=None` in coda e documentalo nel docstring: «job_id: opzionale, id del job in corso; viene registrato nello stato di trip per rendere tracciabile quale job ha visto l'avaria del backend.»

Poi, nel ciclo di retry, sostituisci la riga di chiamata al trasporto con la selezione dinamica, e aggiungi la gestione del trip **prima** della logica di retry esistente:

```python
    while attempt < max_attempts:
        attempt += 1
        backend = _resolve_backend(model_key)
        transport = _transport_for(backend)
        try:
            out = transport(
                final_text=final_text,
                voice_name=voice_name,
                model_key=model_key,
                model_id=(GEMINI_MODELS[model_key].get("id_cloudflare")
                          if backend == "cloudflare" else model_id),
                timeout_ms=(_cf_timeout_ms() if backend == "cloudflare"
                            else _http_timeout_ms(model_key)),
                temperature=_temperature(),
            )
            pcm_data = out["pcm"]
            usage_input = out["input_tokens"] or 0
            usage_output = out["output_tokens"] or 0
            if backend == "cloudflare":
                _backend_state.record_success(model_key)
            _rpd_increment(model_key)
            break
        except TransportError as te:
            last_err = te.__cause__ or te

            # --- Circuit breaker: solo per Cloudflare, solo per guasti del
            # backend. Un contenuto rifiutato o un parametro sbagliato sono
            # difetti del payload: farebbero cadere il backend per colpa di un
            # chunk.
            if backend == "cloudflare" and te.kind in ("backend_down",
                                                       "retryable",
                                                       "rate_limited"):
                if te.kind == "backend_down":
                    _trip_to_vertex(model_key,
                                    reason="cf_backend_down",
                                    detail=f"HTTP {te.http_status} "
                                           f"code {te.provider_code}",
                                    job_id=job_id)
                    # La stessa chiamata prosegue su Vertex con i tentativi
                    # rimanenti: l'audio e' identico byte per byte, il job in
                    # corso non si accorge del cambio.
                    attempt -= 1
                    continue
                failures = _backend_state.record_failure(model_key)
                if failures >= _cf_trip_failures():
                    _trip_to_vertex(model_key,
                                    reason="cf_consecutive_failures",
                                    detail=f"{failures} fallimenti consecutivi; "
                                           f"ultimo: {str(te)[:120]}",
                                    job_id=job_id)
                    attempt -= 1
                    continue
            # --- da qui la logica di retry gia' esistente (Task 3), invariata.
```

Aggiungi anche l'helper del timeout Cloudflare accanto a `_http_timeout_ms`:

```python
def _cf_timeout_ms():
    try:
        return max(1000, int(os.environ.get("ABM_CF_TIMEOUT_MS", "60000") or 60000))
    except (TypeError, ValueError):
        return 60000
```

Nota su `attempt -= 1; continue`: il tentativo speso contro un backend caduto non deve consumare il budget di tentativi del job. Il rischio di ciclo infinito non esiste perché `_set_backend` ha già spostato il modello su Vertex: al giro successivo `backend` non vale più `"cloudflare"` e il ramo non è raggiungibile.

- [ ] **Step 4: Propaga `job_id` dal motore di generazione**

Run: `grep -n "generate_chunk_pcm_gemini" tts_split.py generation_engine.py`

Estendi `generate_chunk_pcm_gemini` con un parametro `job_id=None` e passalo a `_gemini.synthesize(...)`; nei due siti di chiamata di `generation_engine.py` passa `job_id=job_id`. Se il parametro non arriva, lo stato di trip registra `None` e il failover funziona comunque: la tracciabilità è un di più, non una precondizione.

- [ ] **Step 5: Esegui i test**

Run: `python -m pytest test/test_gemini_failover.py -v`
Expected: PASS (8 test)

- [ ] **Step 6: Verifica la suite**

Run: `python -m pytest test/ -q --tb=short`
Expected: nessun fallimento nuovo.

- [ ] **Step 7: Commit**

```bash
git add gemini_tts.py tts_split.py generation_engine.py test/test_gemini_failover.py
git commit -m "feat(tts): failover automatico da Cloudflare a Vertex con breaker a senso unico"
```

---

### Task 8: pre-allarme sul credito Cloudflare

**Files:**
- Modify: `tts_backend_state.py`
- Test: `test/test_cf_credit_ledger.py` (nuovo)

**Interfaces:**
- Consumes: `state`, `_save`, `_LOCK` dal Task 6; l'esito del Task 1 sulla leggibilità del saldo via API.
- Produces:
  - `add_spend(model_key, eur)` — accumula la spesa stimata sul ledger locale.
  - `credit_left_eur()` — saldo residuo stimato = `ABM_CF_CREDIT_BALANCE_EUR` − speso cumulato.
  - `should_alert_credit()` — True quando il residuo scende sotto `ABM_CF_CREDIT_ALERT_EUR` e l'allarme non è già stato dato.
  - `mark_credit_alerted()`.

**Perché serve:** il margine in failover su Vertex è **+1,9%** contro il +61,7% su Cloudflare (spec §4.7). Un failover prolungato non fa perdere soldi, ma azzera il guadagno. Il pre-allarme esiste perché l'admin ricarichi il credito *prima* che il breaker scatti, non dopo.

**Se il Task 1 ha stabilito che il saldo è leggibile via API:** sostituisci il ledger locale con la lettura diretta e adegua i test — una misura vera batte una stima. Se non lo è, il ledger resta l'unica fonte e l'allarme va dichiarato come stima nel testo che l'admin riceve (piano gemello, Fase 6).

- [ ] **Step 1: Scrivi i test che falliscono**

Crea `test/test_cf_credit_ledger.py`:

```python
"""Ledger locale della spesa Cloudflare e pre-allarme sul credito."""
import pytest

import tts_backend_state as st


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    st.init(str(tmp_path))
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "50")
    monkeypatch.setenv("ABM_CF_CREDIT_ALERT_EUR", "5")
    yield


def test_spend_accumulates():
    st.add_spend("flash31", 1.25)
    st.add_spend("flash31", 0.75)
    assert st.credit_left_eur() == pytest.approx(48.0)


def test_spend_is_global_not_per_model():
    # Il credito AI Gateway e' uno solo: la spesa di ogni modello lo intacca.
    st.add_spend("flash31", 10.0)
    st.add_spend("flash25", 10.0)
    assert st.credit_left_eur() == pytest.approx(30.0)


def test_no_alert_while_the_balance_is_comfortable():
    st.add_spend("flash31", 40.0)
    assert st.should_alert_credit() is False


def test_alert_fires_below_the_threshold():
    st.add_spend("flash31", 46.0)
    assert st.should_alert_credit() is True


def test_alert_fires_only_once():
    st.add_spend("flash31", 46.0)
    assert st.should_alert_credit() is True
    st.mark_credit_alerted()
    assert st.should_alert_credit() is False


def test_a_topup_rearms_the_alert(monkeypatch):
    st.add_spend("flash31", 46.0)
    st.mark_credit_alerted()
    # L'admin ricarica: alza il saldo dichiarato e azzera il ledger.
    st.reset_spend()
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "100")
    assert st.credit_left_eur() == pytest.approx(100.0)
    assert st.should_alert_credit() is False


def test_a_zero_balance_disables_the_alert(monkeypatch):
    # Saldo non dichiarato (default 0): l'allarme sarebbe rumore costante.
    monkeypatch.setenv("ABM_CF_CREDIT_BALANCE_EUR", "0")
    st.add_spend("flash31", 5.0)
    assert st.should_alert_credit() is False


def test_the_ledger_survives_a_reload(tmp_path):
    st.add_spend("flash31", 12.0)
    st.init(str(tmp_path))
    assert st.credit_left_eur() == pytest.approx(38.0)
```

- [ ] **Step 2: Esegui i test e verifica che falliscano**

Run: `python -m pytest test/test_cf_credit_ledger.py -v`
Expected: FAIL con `AttributeError: module 'tts_backend_state' has no attribute 'add_spend'`

- [ ] **Step 3: Implementa il ledger**

Aggiungi in coda a `tts_backend_state.py`:

```python
# --- Ledger della spesa Cloudflare -----------------------------------------
# Il credito AI Gateway e' unico per l'account: la spesa di ogni modello lo
# intacca, quindi il ledger e' globale e vive sotto la chiave "_credit".
_CREDIT_KEY = "_credit"


def _f_env(name, default):
    try:
        return float((os.environ.get(name, "") or "").replace(",", ".") or default)
    except (TypeError, ValueError):
        return float(default)


def add_spend(model_key, eur):
    """Accumula la spesa stimata di una chiamata sul ledger locale."""
    with _LOCK:
        entry = _CACHE.setdefault(_CREDIT_KEY, {})
        entry["spent_eur"] = float(entry.get("spent_eur", 0.0)) + float(eur or 0.0)
        _save()


def reset_spend():
    """Azzera il ledger: da chiamare quando l'admin ricarica il credito."""
    with _LOCK:
        _CACHE[_CREDIT_KEY] = {"spent_eur": 0.0, "alerted": False}
        _save()


def credit_left_eur():
    """Residuo stimato: saldo dichiarato meno speso cumulato.

    E' una STIMA: l'API Cloudflare non restituisce i token, quindi la spesa e'
    calcolata dal chiamante sui secondi di audio prodotti. Vedi §10.2 della
    spec per l'esito della ricognizione sull'API del saldo.
    """
    with _LOCK:
        spent = float((_CACHE.get(_CREDIT_KEY) or {}).get("spent_eur", 0.0))
    return _f_env("ABM_CF_CREDIT_BALANCE_EUR", 0.0) - spent


def should_alert_credit():
    """True quando il residuo scende sotto soglia e l'allarme non e' gia' dato.

    Con saldo dichiarato a 0 (default) l'allarme e' disattivato: sarebbe
    rumore costante su un'installazione che non usa Cloudflare.
    """
    balance = _f_env("ABM_CF_CREDIT_BALANCE_EUR", 0.0)
    if balance <= 0:
        return False
    with _LOCK:
        if (_CACHE.get(_CREDIT_KEY) or {}).get("alerted"):
            return False
    return credit_left_eur() < _f_env("ABM_CF_CREDIT_ALERT_EUR", 5.0)


def mark_credit_alerted():
    with _LOCK:
        entry = _CACHE.setdefault(_CREDIT_KEY, {})
        entry["alerted"] = True
        _save()
```

- [ ] **Step 4: Esegui i test**

Run: `python -m pytest test/test_cf_credit_ledger.py -v`
Expected: PASS (8 test)

- [ ] **Step 5: Verifica la suite completa**

Run: `python -m pytest test/ -q --tb=short`
Expected: nessun fallimento nuovo.

- [ ] **Step 6: Commit**

```bash
git add tts_backend_state.py test/test_cf_credit_ledger.py
git commit -m "feat(tts): ledger locale della spesa Cloudflare e pre-allarme sul credito"
```

---

## Stato al termine di questo piano

Cloudflare è un backend funzionante, selezionabile con `ABM_GEMINI_BACKEND=cloudflare`, con failover automatico su Vertex e stato persistito. **Non è ancora usabile in produzione**: mancano il pricing parametrico sulle tariffe Cloudflare, la contabilità del costo reale, l'email di trip all'admin, il pulsante di rientro in console e la procedura di rollout. Sono le Fasi 5-7, nel piano gemello `2026-08-26-cloudflare-tts-backend-economics.md`.

Fino ad allora il codice resta **dormiente**: nessun ambiente setta `ABM_GEMINI_BACKEND=cloudflare` e `auto` non seleziona mai Cloudflare, quindi il comportamento in produzione è identico a oggi.
