# ottimizzazione_testo_AI.md — Ottimizzazione testo AI (LLM)

Riferimento operativo per la fase di **ottimizzazione AI del testo** prima della sintesi TTS. L'ottimizzazione adatta il testo affinché venga letto in modo naturale dal motore TTS (qualunque esso sia: Edge, Google Chirp3-HD, Gemini), correggendo punteggiatura, espandendo acronimi/numeri, spezzando periodi troppo lunghi, disambiguando eteronimi e mitigando il *language drift* delle voci multilingua.

> **Convenzione UI**: il provider LLM (DeepSeek) non viene mai nominato all'utente. Etichetta in UI: "Ottimizzazione testo AI". Vedi memoria `feedback_ui_provider_naming.md`.

---

## 1. Scopo

L'ottimizzazione è una fase **opzionale** posta tra Phase 1 (Upload & Analysis) e Phase 3 (Audio Preview). Quando attiva:

1. Per ogni capitolo selezionato, il testo viene inviato a un LLM (DeepSeek `deepseek-chat`) con un *system prompt* specifico per la lingua TTS scelta.
2. Il modello restituisce il testo "audio-ready": stessa lingua, stesso contenuto, ma con punteggiatura/struttura/diacritici adattati per la lettura ad alta voce.
3. Il testo ottimizzato sostituisce quello originale nel `BookInfo.chapters` del job e viene archiviato in un `.abm` (project archive) re-importabile.

Filosofia del prompt:

- **Editing, non rewriting**: il modello modifica struttura (punteggiatura, sentence split, accenti su eteronimi) ma **non** riscrive contenuto. Ogni parola dell'output deve essere già presente nell'originale (con la sola eccezione di parole connettive minime per spezzare periodi lunghi).
- **Mai tradurre**: la lingua del testo non cambia mai.
- **Preserva struttura paragrafi**: i `\n\n` vanno mantenuti (sono pause prosodiche TTS).
- **Mitigation language-drift**: per voci multilingua (Edge `*-MultilingualNeural`, Gemini), gli acronimi vengono separati con punti (`C.E.O.`), e le righe orfane vengono unite per dare contesto sufficiente al modello vocale.

---

## 2. Architettura

```
audiobook_app.py
   └── /api/optimize  (POST)
         ├── Validazione job + concorrenza (MAX_CONCURRENT_LLM_PER_CLIENT)
         ├── job["opt_lang"] = lang.split("-")[0].lower()   # ← chiave per Gemini
         ├── Cap selezione (ABM_MAX_TEXT_CHARS)
         ├── Calcolo costo: _estimate_llm_cost_eur(chars)
         ├── Se cost > LLM_FREE_THRESHOLD_EUR → validazione payment_token
         │     ├── PayPal: payment._payments[token] → consume atomico
         │     └── Voucher: payment._vouchers[token] → _voucher_consume()
         ├── Batch mode? → registra notify_email
         ├── Auto-generate? → salva opt_voice/opt_rate/opt_single_file/opt_output_format
         └── threading.Thread(target=run_optimization).start()

generation_engine.py
   └── run_optimization(job_id, selected_chapters)
         ├── _set_job_status(job, "optimizing")
         ├── Calcolo total_chars + finalization_weight
         ├── lang = job["opt_lang"] or job["lang"] or "it"
         ├── prompt = _get_llm_prompt(lang)
         │     └── prompt_opt_AI/prompt_tts_<lang>.md
         │         (fallback: prompt_tts_generic.md)
         ├── per ogni capitolo:
         │     ├── Heartbeat check (60s, salvo batch mode)
         │     ├── _optimize_chapter_text(ch.text, ...)
         │     │     ├── Se len(text) ≤ LLM_SAFE_OUTPUT_CHUNK:
         │     │     │     _call_llm(text)
         │     │     └── Else:
         │     │           chunks = _split_text_into_chunks(text, ...)
         │     │           per chunk: _call_llm(prefisso + chunk)
         │     │           time.sleep(LLM_INTER_CHUNK_SLEEP_SEC)  # rate limiting inter-chunk
         │     │           _sanitize_llm_output("\n\n".join(results))
         │     └── ch.text = optimized_text
         ├── ai_optimized = True
         ├── _generate_optimized_abm()   # snapshot project archive
         └── if auto_generate: run_generation(...)

_call_llm(user_content, job)
   ├── lang = job["opt_lang"] || (voice extraction if non-Gemini) || "it"
   ├── prompt = _get_llm_prompt(lang)
   ├── messages = [{system: prompt}, {user: user_content}]
   ├── openai.chat.completions.create(stream=True, ...)
   │     ├── max_tokens = LLM_MAX_TOKENS (default 65536)
   │     ├── temperature = LLM_TEMPERATURE (0.3)
   │     ├── reasoning_effort = LLM_REASONING_EFFORT (se ≠ "none")
   │     └── extra_body.thinking.type = "enabled" (se LLM_THINKING)
   ├── Streaming loop:
   │     ├── if job["opt_cancelled"]: stream.close() + raise _CancelledError
   │     ├── result_parts += event.choices[0].delta.content
   │     └── opt_streamed_chars += len(chunk)
   ├── _sanitize_llm_output(raw)
   └── Retry policy (transient errors: 4 attempts, backoff 1-8s)
```

**Vincoli di dipendenza**:

- `generation_engine` importa `payment` per refund/voucher (no circular: `payment` non importa `generation_engine`).
- `_llm_client` (OpenAI-compatible) è singleton inizializzato in `_init_llm()` chiamato da `configure()`.
- I file prompt sono letti da disco (`prompt_opt_AI/prompt_tts_<lang>.md`) con cache in-memory `_llm_prompts` per lingua.

---

## 3. Selezione del prompt per lingua

### 3.1 Fonte autoritativa: `job["opt_lang"]`

La lingua del prompt LLM coincide con la **lingua TTS selezionata in UI**, NON con la lingua dell'input. Motivazione: l'ottimizzazione deve produrre testo adatto alla **voce che lo leggerà**.

Esempio: l'utente carica un PDF in inglese ma vuole farlo leggere da una voce italiana → l'ottimizzazione deve usare `prompt_tts_it.md` (regole di accentazione/punteggiatura italiana), non `prompt_tts_en.md`.

Flusso:

1. Frontend (`static/js/app.js`) raccoglie `lang` UI dal selettore TTS.
2. `POST /api/optimize` con `{lang: "it"}`.
3. Backend (`audiobook_app.py:6120`): `job["opt_lang"] = lang.split("-")[0].lower()` (es. `"it-IT"` → `"it"`).
4. `run_optimization` (`generation_engine.py:1304`): `lang = job["opt_lang"] or job["lang"] or "it"`.
5. `_call_llm` (`generation_engine.py:477`): preferisce `opt_lang`, altrimenti estrae dal `voice_id` (solo per voci non-Gemini).

### 3.2 Fallback chain in `_call_llm`

```python
lang = "it"   # default finale
if job:
    opt_lang = (job.get("opt_lang") or "").strip()
    if opt_lang:
        lang = opt_lang.split("-")[0].lower()       # ← preferito
    else:
        voice = job.get("voice") or job.get("opt_voice", "")
        if isinstance(voice, str) and voice and not voice.startswith("gemini:"):
            lang = voice.split("-")[0].lower()      # ← fallback solo non-Gemini
```

La distinzione "non-Gemini" è critica: i voice ID Edge/Google (`it-IT-DiegoNeural`, `en-US-Chirp3-HD-Alnilam`) iniziano con il codice locale, quindi `split("-")[0]` produce un risultato valido. I voice ID Gemini (`gemini:flash25:Zephyr`) NON contengono lingua, quindi un'estrazione su di essi produrrebbe la stringa `"gemini:flash25:zephyr"` come lang → file inesistente → fallback a `prompt_tts_generic.md`.

Test di regressione: [test/test_llm_prompt_lang_selection.py](test/test_llm_prompt_lang_selection.py) blinda:

- Voce Gemini + `opt_lang` → usa la lingua di `opt_lang`.
- Voce Edge + `opt_lang` diverso da voce → vince `opt_lang`.
- Voce Edge senza `opt_lang` → fallback su estrazione voce.
- Voce Gemini senza `opt_lang` → fallback a `"it"`.

### 3.3 File prompt (cartella `prompt_opt_AI/`)

| File | Uso |
|------|-----|
| `prompt_tts_master.md` | **Source of truth multilingua**. Governance: si modifica prima, poi si propaga ai singoli file lingua. Non usato in produzione per testi monolingua (è troppo lungo, diluisce enforcement) |
| `prompt_tts_it.md` | Italiano |
| `prompt_tts_en.md` | Inglese |
| `prompt_tts_fr.md` | Francese |
| `prompt_tts_es.md` | Spagnolo |
| `prompt_tts_de.md` | Tedesco |
| `prompt_tts_zh.md` | Cinese mandarino (polifoni con pinyin in brackets) |
| `prompt_tts_hi.md` | Hindi (Devanagari, gestione Hinglish) |
| `prompt_tts_ru.md` | Russo (stress marks per omografi, restoration ё→ё) |
| `prompt_tts_pt.md` | Portoghese |
| `prompt_tts_generic.md` | **Fallback**: lingue senza prompt dedicato OR voice Gemini senza `opt_lang`. Include self-calibration: regole solo strutturali a confidence bassa |

Caricamento in `_get_llm_prompt(lang)` (`generation_engine.py:437`):

```python
lang = (lang_code or "it").split("-")[0].lower()
if lang in _llm_prompts: return _llm_prompts[lang]   # cache hit
path = prompt_dir / f"prompt_tts_{lang}.md"
if not path.exists(): path = prompt_dir / "prompt_tts_generic.md"
print(f"[LLM] Using prompt file: {path.name}")   # ← log diagnostico
return path.read_text(encoding="utf-8").strip()
```

Il log `[LLM] Using prompt file: prompt_tts_generic.md` quando ci si attende un prompt specifico è il segnale che `opt_lang` non è arrivato o è inconsistente — vedi §10 (Troubleshooting).

### 3.4 Regole comuni nel master prompt (estratto)

`prompt_tts_master.md` definisce 5 sezioni:

- **A — Universal rules**: testo corrotto, numeri/numerali romani, acronimi (con dot-separation per language-drift), simboli, artefatti non parlati (`(ANSA)`, `(Photo)`), punteggiatura di respiro, periodi lunghi (>30-40 parole vanno spezzati), gestione virgolette/parentesi/em-dash, language-drift prevention (merge di righe orfane).
- **B — Heteronym disambiguation**: per ciascuna lingua, lista di eteronimi specifici (it: `principi`/`prìncipi`; en: `lead`/`lèad`; ru: `за́мок`/`замо́к`; zh: pinyin in brackets per polifoni).
- **C — What you must NOT do**: no sostituzione parole, no aggiunta contenuto, no rimozione info, no collasso paragrafi, no interpretazione ambiguità, no cambio lingua, no fact-check, no over-accent.
- **D — Error correction**: solo typo evidenti e univoci.
- **E — Output format**: solo testo ottimizzato, nessun commento/changelog/note.

---

## 4. Chunking del testo per il LLM

Il context window DeepSeek è ampio (1M token), ma il `max_tokens` di output è volutamente contenuto a **65k** di default per preservare l'aderenza al prompt: generazioni molto lunghe (> 100k token) tendono a degradare le regole (eteronimi, correzioni, no-riassunto). Il chunking è quindi guidato dalla **safety dell'output**, non dell'input.

Costanti (`generation_engine.py:63-73`):

```python
LLM_MAX_TOKENS = int(os.environ.get("ABM_LLM_MAX_TOKENS", "65536"))  # output cap, env-configurable
LLM_CHARS_PER_TOKEN = 3.5
LLM_TEMPERATURE = 0.3
LLM_MAX_CONTEXT_TOKENS = 1000000   # 1M context window (V4 Flash)
LLM_RESERVED_OUTPUT_TOKENS = LLM_MAX_TOKENS  # segue MAX_TOKENS
LLM_RESERVED_PROMPT_TOKENS = 4000
LLM_MAX_INPUT_TOKENS  = MAX_CONTEXT - RESERVED_OUTPUT - RESERVED_PROMPT  # ~930k con default
LLM_MAX_INPUT_CHARS   = MAX_INPUT_TOKENS * 3.5                            # ~3.26M con default
LLM_SAFE_OUTPUT_CHUNK = MAX_TOKENS * 3.5 * 0.85                           # ~195k chars con default
```

`LLM_SAFE_OUTPUT_CHUNK` (~195k caratteri con default 65536) è il **vero limite operativo per chunk**: garantisce che la risposta entri in `max_tokens` con un margine di sicurezza dell'85%. Un libro tipico (~500k char) genera quindi 3-4 chunk, ognuno con prompt ricaricato da zero → aderenza alle regole costante per tutto il testo.

### 4.1 Strategia di split

`_optimize_chapter_text` (`generation_engine.py:559`):

- Se `len(ch.text) ≤ LLM_SAFE_OUTPUT_CHUNK`: **single call**.
- Altrimenti: `_split_text_into_chunks(text, LLM_SAFE_OUTPUT_CHUNK)` → loop sui chunk.

`_split_text_into_chunks` (`generation_engine.py:303`) preserva **paragrafi** (`\n\n`):

1. Split su `\n\s*\n`.
2. Per ogni paragrafo:
   - Se `>max_chars` da solo: split su confine di frase (`[.!?…]\s+`).
   - Altrimenti: accumula nei `current_chunk` finché c'è spazio.
3. Concatena con `\n\n`.

### 4.2 Marker contestuali tra chunk

Quando un capitolo viene spezzato in più chunk, ognuno riceve un prefisso che orienta il modello:

```
[Parte 1 di N — inizio del testo]\n\n<chunk>
[Parte 2 di N — continuazione]\n\n<chunk>
...
[Parte N di N — fine del testo]\n\n<chunk>
```

Questo aiuta il modello a:

- Non aggiungere preamboli/conclusioni a metà capitolo.
- Mantenere uniformità di stile attraverso i chunk.
- Sapere se può "chiudere" la prosa (ultima parte) o lasciarla aperta.

### 4.3 Rate limiting inter-chunk

Tra un chunk e il successivo: `time.sleep(LLM_INTER_CHUNK_SLEEP_SEC)` (default `0.5s`, env `ABM_LLM_INTER_CHUNK_SLEEP_SEC`). Evita di saturare la coda upstream durante capitoli molto lunghi.

### 4.4 Riassemblaggio + seconda passata di sanitize

I chunk ottimizzati vengono uniti con `"\n\n".join(results)` e passati nuovamente a `_sanitize_llm_output()` per rimuovere eventuali residui di preamboli/postfazioni al confine tra chunk.

---

## 5. Configurazione LLM (engine-agnostic)

Tutti i parametri sono **env-driven** (`ABM_LLM_*`) con default hardcoded tarati sul provider corrente (DeepSeek-Chat). Cambiare provider OpenAI-compatible richiede **solo** di rivalorizzare le env var — nessuna modifica al codice. Riferimenti: `generation_engine.py:54-108`.

### 5.1 Tutti i parametri (env var → default → significato)

#### Connection

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_LLM_API_KEY` | *(empty)* | API key del provider. Se vuoto → ottimizzazione disabilitata |
| `ABM_LLM_API_BASE` | `https://api.deepseek.com` | Endpoint OpenAI-compatible. Cambiare provider = override qui |
| `ABM_LLM_MODEL` | `deepseek-v4-flash` | Nome modello |

#### Generation behavior

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_LLM_THINKING` | `false` | Thinking mode (chain-of-thought). Aggiunge `extra_body.thinking.type="enabled"` |
| `ABM_LLM_REASONING_EFFORT` | `none` | `none`/`low`/`medium`/`high`. Se ≠ `none`, passato come `reasoning_effort` |
| `ABM_LLM_TEMPERATURE` | `0.3` | Bassa → editing deterministico, non riscrittura creativa |
| `ABM_LLM_MAX_TOKENS` | `65536` | Cap output token per call. Governa `LLM_SAFE_OUTPUT_CHUNK` (≈ MAX_TOKENS × CHARS_PER_TOKEN × SAFETY_MARGIN ≈ 195k char). Valore basso = aderenza al prompt costante anche su libri lunghi (ogni chunk = call separata con system prompt ricaricato identico) |

#### Token economy

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_LLM_CHARS_PER_TOKEN` | `3.5` | Heuristica char→token (lingue latine). Cinese ≈ 2.0, lingue agglutinanti ≈ 4.0+ |
| `ABM_LLM_MAX_CONTEXT_TOKENS` | `1000000` | Context window totale del modello |
| `ABM_LLM_RESERVED_PROMPT_TOKENS` | `4000` | Token riservati al system prompt nel computo di `MAX_INPUT_TOKENS` |
| `ABM_LLM_OUTPUT_SAFETY_MARGIN` | `0.85` | Coeff. di sicurezza sul `SAFE_OUTPUT_CHUNK` (15% di margine per evitare troncamenti) |

#### Reliability / pacing

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_LLM_REQUEST_TIMEOUT_SEC` | `120.0` | Timeout di una singola chiamata HTTP streaming |
| `ABM_LLM_MAX_RETRIES` | `4` | Tentativi su errore transient. Sono transient: (a) errori di rete client-side (`ReadError`, `ConnectError`, `ConnectTimeout`, `ReadTimeout`, `RemoteProtocolError`, `APIConnectionError`, `APITimeoutError`); (b) risposte provider con `status_code ∈ {429, 500, 502, 503, 504}` (es. `openai.InternalServerError`, `RateLimitError`). Backoff esponenziale `2**attempt` (1s, 2s, 4s, 8s) |
| `ABM_LLM_INTER_CHUNK_SLEEP_SEC` | `0.5` | Pausa tra chunk consecutivi dentro lo stesso capitolo (rate limiting client-side) |
| `ABM_LLM_HEARTBEAT_TIMEOUT_SEC` | `60.0` | Se l'UI non poll-a il progress entro questo intervallo → auto-cancel (solo modalità interattiva: in batch è disattivato) |

### 5.2 Costanti derivate (computed, non env)

Calcolate al boot da `LLM_MAX_TOKENS`, `LLM_CHARS_PER_TOKEN`, `LLM_MAX_CONTEXT_TOKENS`, `LLM_RESERVED_PROMPT_TOKENS`, `LLM_OUTPUT_SAFETY_MARGIN`:

```python
LLM_RESERVED_OUTPUT_TOKENS = LLM_MAX_TOKENS
LLM_MAX_INPUT_TOKENS  = LLM_MAX_CONTEXT_TOKENS - LLM_RESERVED_OUTPUT_TOKENS - LLM_RESERVED_PROMPT_TOKENS
LLM_MAX_INPUT_CHARS   = int(LLM_MAX_INPUT_TOKENS * LLM_CHARS_PER_TOKEN)
LLM_SAFE_OUTPUT_CHUNK = int(LLM_MAX_TOKENS * LLM_CHARS_PER_TOKEN * LLM_OUTPUT_SAFETY_MARGIN)
```

Con i default → `MAX_INPUT_TOKENS ≈ 930k`, `MAX_INPUT_CHARS ≈ 3.26M`, `SAFE_OUTPUT_CHUNK ≈ 195k char`.

### 5.3 Thinking / reasoning effort

Le opzioni `THINKING` e `REASONING_EFFORT` sono ortogonali:

- `THINKING=true`: attiva il chain-of-thought interno del modello (output ha un campo `reasoning_content` streamed separatamente). I caratteri di ragionamento contano nel progress (`opt_streamed_chars`) ma non finiscono nell'output finale.
- `REASONING_EFFORT=low|medium|high`: parametro server-side che istruisce il modello a investire più o meno calcolo in ragionamento.

Trade-off: alzare entrambi migliora la qualità dell'ottimizzazione (specie su periodi lunghi o disambiguazione eteronimi) ma allunga il tempo e aumenta il costo per token. Default `none/false` per coerenza con il tier base.

### 5.4 Init del client

`_init_llm()` (`generation_engine.py:166`) chiamato da `configure()`:

- Se `ABM_LLM_API_KEY` vuoto → disabilita (log `LLM text optimization disabled`).
- Verifica che `prompt_opt_AI/prompt_tts_generic.md` esista (warning se assente).
- Importa `openai` con `base_url = LLM_API_BASE`.
- `_llm_available()` ritorna `_llm_client is not None`.

`/api/optimize` rifiuta con `503 LLM optimization not available` se `_llm_available()` è False.

---

## 6. Streaming, progress, cancellazione

`_call_llm` usa `stream=True`. Vantaggi:

- Aggiornamento `opt_streamed_chars` in tempo reale → progress bar smooth lato client.
- Cancellazione immediata: ogni event verifica `job["opt_cancelled"]` e fa `stream.close() + raise _CancelledError`.
- Token usage non si paga oltre il punto di cancellazione (DeepSeek interrompe la generazione lato server).

### 6.1 Stream loop

```python
stream = _llm_client.chat.completions.create(stream=True, ...)
for event in stream:
    if job["opt_cancelled"]:
        stream.close()
        raise _CancelledError(...)
    if event.choices and event.choices[0].delta.content:
        chunk = event.choices[0].delta.content
        result_parts.append(chunk)
        job["opt_streamed_chars"] += len(chunk)
    # Reasoning content (thinking mode) → counts toward progress, not output
    if hasattr(delta, "reasoning_content") and delta.reasoning_content:
        job["opt_streamed_chars"] += len(delta.reasoning_content)
```

### 6.2 Heartbeat

Per evitare job zombie quando il client chiude la pagina, `run_optimization` controlla ogni capitolo:

```python
last_poll = job.get("last_poll", start_time)
if time.time() - last_poll > 60:
    raise _CancelledError("Optimization cancelled (heartbeat lost)")
```

`/api/optimize_progress/{job_id}` (SSE) aggiorna `last_poll` a ogni tick (ogni 2s). Se il client non polla per >60s, il job si auto-cancella.

**Eccezione batch mode**: se `job["email_registered"]` è True (l'utente ha registrato un'email per ricevere il risultato), l'heartbeat NON viene controllato — il job può procedere anche con browser chiuso, e a fine generazione partirà l'email.

### 6.3 Refund del partial streamed

Se la call fallisce a metà streaming, il `partial_streamed` viene **decrementato** da `opt_streamed_chars` per non gonfiare falsamente il progress su retry.

### 6.4 Retry policy

Errori considerati transient (`generation_engine.py:617-642`):

1. **Errori di rete client-side** (match per nome classe httpx/openai connection wrappers):

```python
transient = any(s in type(e).__name__ for s in (
    "ReadError", "ConnectError", "ConnectTimeout", "ReadTimeout",
    "RemoteProtocolError", "APIConnectionError", "APITimeoutError",
))
```

2. **Errori provider-side 429/5xx** (ispezione `status_code`, con fallback `e.response.status_code`):

```python
_sc = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
if isinstance(_sc, int) and _sc in (429, 500, 502, 503, 504):
    transient = True
```

Necessario perche' `openai.InternalServerError` (503), `RateLimitError` (429), `APIStatusError` non matchano la lista per-nome ma sono comunque retry-safe.

- 4 tentativi totali (default `ABM_LLM_MAX_RETRIES=4`).
- Backoff esponenziale: 1s, 2s, 4s, 8s (= `2**attempt`).
- Errori non-transient (es. `BadRequestError`, `AuthenticationError`, 4xx ≠ 429): re-raise immediato.

---

## 7. Sanitization output

`_sanitize_llm_output(text)` (`generation_engine.py:363`) rimuove contaminazioni meta. Il prompt vieta esplicitamente preamboli/postfazioni (Sezione E), ma il modello a volte sfugge:

1. **Preamboli**: pattern regex multilingua catturano frasi tipo `"Sure, here is the optimized text:"`, `"Capito, ecco il testo:"`, `"Voici le texte:"`, `"Verstanden, hier ist:"` etc. Rimosse dalle prime righe.
2. **Headers meta**: linee corte (≤80 char) che terminano con `:` dopo un preambolo già strippato.
3. **Postfazioni**: ultime righe tipo `"Note: ..."`, `"[End of optimized text]"`, `"— End"`.
4. **Dedup paragrafi consecutivi**: paragrafi identici back-to-back vengono fusi (il modello a volte ripete il finale per chunk lunghi).
5. **Dedup righe consecutive** dentro un paragrafo.

Il delta caratteri rimossi viene **sottratto** da `opt_streamed_chars` per coerenza progress.

Log: `[LLM] sanitized output: removed N chars of meta/duplicates`.

---

## 8. Differenze comportamentali per motore TTS

L'ottimizzazione AI è **largely engine-agnostic**: il pipeline DeepSeek non cambia. Le differenze sono concentrate in **come la lingua del prompt viene derivata** e in **alcune raccomandazioni del prompt master che mitigano problemi specifici di certi motori**.

### 8.1 Edge TTS (Microsoft)

| Aspetto | Comportamento |
|---------|---------------|
| Voice ID | `it-IT-DiegoNeural`, `en-US-AriaNeural` (locale `<lang>-<region>-<name>Neural`) |
| Estrazione lingua | Funziona: `voice.split("-")[0]` → `"it"`, `"en"` |
| Source per prompt | Preferito: `opt_lang`. Fallback: estrazione da voice ID |
| Voci multilingue | `*-MultilingualNeural` → suscettibili a language-drift sui chunk corti |
| Mitigation prompt | Regola A4 (dot-separation acronimi: `CEO` → `C.E.O.`) e A15 (merge righe orfane) particolarmente importanti |

### 8.2 Google Chirp3-HD

| Aspetto | Comportamento |
|---------|---------------|
| Voice ID | `en-US-Chirp3-HD-Alnilam`, `it-IT-Chirp3-HD-Aoede` |
| Estrazione lingua | Funziona: prefisso `en-US`, `it-IT` |
| Source per prompt | Identica a Edge |
| Voci multilingue | Limitate; Chirp3 è generalmente monolingua per locale |
| Mitigation prompt | Stesse regole del master, no specifiche aggiuntive |

### 8.3 Gemini Flash TTS (Premium)

| Aspetto | Comportamento |
|---------|---------------|
| Voice ID | `gemini:flash25:Zephyr`, `gemini:flash31:Kore` |
| Estrazione lingua | **NON funziona**: `"gemini".split("-")[0]` → `"gemini"` (non valido) |
| Source per prompt | **OBBLIGATORIO**: `opt_lang`. Senza `opt_lang`, fallback hardcoded a `"it"` |
| Voci multilingue | Tutte le 30 voci sono multilingue (it/en/fr/es/de/zh/hi) |
| Mitigation prompt | **Più critica** che con Edge: il drift Gemini è meno tollerante. Le regole A4/A15 sono load-bearing |

**Implicazione di design**: `audiobook_app.py:6120` setta `job["opt_lang"]` SEMPRE su `/api/optimize`, indipendentemente dal motore. Questo è il vincolo che rende l'integrazione Gemini funzionante senza romper Edge/Google.

### 8.4 Tabella di sintesi

| Motore | Lingua prompt da | Senza `opt_lang` |
|--------|------------------|------------------|
| Edge | `opt_lang` (preferito), `voice.split("-")[0]` (fallback) | Funziona |
| Google | `opt_lang` (preferito), `voice.split("-")[0]` (fallback) | Funziona |
| Gemini | `opt_lang` (UNICO) | **Cade a `it`** (default hardcoded, NON a `generic`) |

Il fallback per Gemini è ITA e non `generic` per scelta intenzionale: meglio un prompt specifico (probabilmente sbagliato di lingua) che il generic (più debole su tutte le lingue). Vedi test `test_gemini_voice_without_opt_lang_does_not_corrupt_lang`.

---

## 9. Pricing e payment flow

### 9.1 Calcolo costo

`payment._estimate_llm_cost_eur(chars)` (`payment.py:47`):

```python
cost_eur = round((chars / 1_000_000) × LLM_RATE_EUR_PER_MCHAR, 2)
```

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_LLM_RATE_EUR_PER_MCHAR` | `1.10` | EUR per 1M char input. Include markup + fee PayPal (NO conversione USD/EUR perché DeepSeek fattura in CNY/USD ma il prezzo è già lordo) |
| `ABM_LLM_FREE_THRESHOLD_EUR` | `0.50` | Sotto questa soglia il job è gratuito |

### 9.2 Threshold di gratuità

In `/api/optimize` (`audiobook_app.py:6175`):

```python
if estimated_cost > LLM_FREE_THRESHOLD_EUR:
    # richiedi payment_token
else:
    # parte gratis
```

Il default `0.50 €` copre testi fino a ~454k char (circa 100k parole, ~10 ore di audio). La grande maggioranza dei libri singoli passa senza pagamento.

### 9.3 Token di pagamento

Quando richiesto, il client invia `payment_token` validato server-side in modo atomico:

**Caso PayPal**:

```python
with payment._payments_lock:
    pay = payment._payments.get(token)
    if pay and not pay["used"] and pay["amount_eur"] >= estimated_cost:
        pay["used"] = True
        pay["used_at"] = time.time()
        pay["used_job_id"] = job_id
```

Persistenza fuori dal lock per evitare rientranza.

**Caso voucher**:

```python
v = payment._vouchers[token]
remaining = _voucher_remaining(v)
if v["expires_at"] > time.time() and remaining >= estimated_cost - 0.01:
    _voucher_consume(token, estimated_cost, job_id=job_id)
```

`job["payment_token"]`, `job["payment_type"]` (`paypal`|`voucher`), `job["payment_amount_eur"]` vengono memorizzati per il refund.

### 9.4 Refund policy

`_refund_job_payment(job_id, job, reason)` chiamato in `except _CancelledError` e `except Exception`:

| `payment_type` | Comportamento |
|----------------|---------------|
| `voucher` | `payment._voucher_refund(token, amt)`: il credito viene riaccreditato silenziosamente sull'originale. NESSUNA email |
| `paypal` | **Non si refunda l'ordine PayPal** (sarebbe rumoroso). Si emette un **nuovo voucher** di pari importo + `VOUCHER_BONUS_PERCENT` (10%) inviato via email all'utente |

Vedi memoria `feedback_refund_voucher_policy.md`.

### 9.5 Voucher bonus

`ABM_VOUCHER_BONUS_PERCENT=10`: il voucher di rimborso vale `original × 1.10` (10% di compensazione per il disagio). `ABM_VOUCHER_EXPIRY_DAYS=180`: validità 6 mesi.

### 9.6 Bundling con Voci PREMIUM (UI)

Quando l'utente seleziona la tab **Voci PREMIUM** (Gemini TTS), il costo LLM — anche se eccede `LLM_FREE_THRESHOLD_EUR` — **non** genera un popup voucher dedicato all'attivazione del toggle AI. Il pagamento LLM è bundlato nel modale di pagamento combinato (Premium TTS + LLM) aperto da `onGenerateClick` → `openPaymentModal` (`static/js/app.js`), che usa la stima `/api/combined_estimate` e produce un unico `payment_token` PayPal/voucher che copre `gemini_eur + llm_eur`.

Implementazione: `_fetchCostEstimate()` (`static/js/app.js:1668`) effettua un early-return se `wizardState.audioTab === 'premium'`, sopprimendo il popup `_showPaymentModal` LLM-only. Server-side `/api/optimize` accetta il token combinato (validato a `>= estimated_cost` LLM, vedi `audiobook_app.py:6364`) oppure consuma esplicitamente il token combinato nel branch "combined payment fallback" (`audiobook_app.py:6411`) quando LLM è sotto soglia ma Gemini è a pagamento.

In tab **Standard** il flusso resta invariato: il popup voucher LLM-only appare all'attivazione del toggle AI se il costo supera la soglia.

---

## 10. Limiti, concorrenza, salvaguardie

### 10.1 Cap selezione

`ABM_MAX_TEXT_CHARS=1500000` (1.5M char) è il cap di output audio. Prima di addebitare l'ottimizzazione, `/api/optimize` verifica che il totale dei capitoli selezionati (già ottimizzati + da ottimizzare) stia sotto questo limite. Se sforato, risponde `413 selection_too_large` e rilascia lo status `optimizing`.

### 10.2 Concorrenza per client

`ABM_MAX_CONCURRENT_LLM_PER_CLIENT=1`: ogni `client_id` cookie può avere **una sola** ottimizzazione attiva alla volta. Check atomico sotto `_jobs_lock`:

```python
if _active_optimizing_for_client_unlocked(client_id) >= MAX_CONCURRENT_LLM_PER_CLIENT:
    return 429 {"error": "Concurrent optimization limit reached", "error_code": "concurrent_optimize_limit"}
```

### 10.3 Suspend admin

`_suspend_new_jobs` (toggle admin): se attivo, `/api/optimize` risponde `503 System under maintenance`. Permette di drenare il sistema prima di restart/deploy.

### 10.4 Selezione capitoli

`POST /api/optimize` accetta `selected_chapters` (lista di `chapter.index`). Solo i capitoli **non già ottimizzati** vengono inviati al LLM. `job["optimized_chapters"]` tiene traccia per re-run incrementali.

---

## 11. Auto-generate vs interactive vs batch

`/api/optimize` accetta tre modalità:

| Modalità | `batch` | `auto_generate` | `email` | Comportamento |
|----------|---------|-----------------|---------|---------------|
| **Interactive** | `false` | `true` (wizard) | — | Browser polla SSE, ottimizzazione → auto avvia TTS, scarica al termine |
| **Interactive solo opt** | `false` | `false` | — | Browser polla, ottimizzazione finisce, l'utente decide se generare |
| **Batch** | `true` | `false`/`true` | obbligatoria | Browser può chiudersi; al termine arriva email con link |

### 11.1 Wizard (auto-generate)

L'utente preme "Genera audiolibro": il frontend chiama `/api/optimize` con `auto_generate=true` + voice/rate/single_file/output_format. Il backend salva i parametri in `job["opt_*"]` e a fine ottimizzazione `run_optimization` chiama direttamente `run_generation(...)` senza passare per `/api/generate`.

```python
voice = job["opt_voice"]
rate = job["opt_rate"]
single_file = job["opt_single_file"]
output_format = job["opt_output_format"]
podcast_base_url = job["opt_podcast_base_url"]
job["gen_epoch"] += 1   # nuova directory output_<epoch>/
run_generation(job_id, info, voice, rate, single_file, output_format=..., podcast_base_url=...)
```

### 11.2 Batch + email

Se `email_registered`: a fine ottimizzazione (eventualmente anche dopo TTS auto-generate) parte email tramite `email_service` con `download_token` (24h validità) per `.abm` + `.mp3`/`.m4b`/`.zip`.

---

## 12. Snapshot `.abm` (project archive)

A fine ottimizzazione, `_generate_optimized_abm(job_id)` (`generation_engine.py:592`) produce un file `.abm` (ZIP con manifest + chapter texts + cover opzionale):

```
<job_dir>/optimized_<title>.abm
├── manifest.json     {"format": "audiobook-maker-project", "title": ..., "author": ..., "chapters": [...]}
├── chapters/
│   ├── 001_<slug>.txt
│   ├── 002_<slug>.txt
│   └── ...
└── cover.<ext>       (se disponibile)
```

Lo scopo:

- **Re-import**: l'utente può caricare il `.abm` mesi dopo e rigenerare l'audio senza ri-pagare l'ottimizzazione.
- **Audit**: l'utente vede esattamente cosa il LLM ha prodotto (testo leggibile, non solo audio).
- **Download separato** dal MP3/M4B/ZIP via `btnA` (vedi CLAUDE.md - Output Format Flow).

`job["optimized_abm_path"]` e `job["optimized_abm_name"]` puntano al file. Persistito in `_download_tokens.json` per accesso post-cleanup.

---

## 13. Variabili ABM_LLM_* (riferimento rapido completo)

**Tutti i parametri dell'ottimizzazione AI sono env-driven** (`ABM_LLM_*`). Cambiare provider LLM (purché OpenAI-compatible) richiede di toccare solo queste env var — nessuna modifica al codice.

### 13.1 Engine (connection)

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_LLM_API_KEY` | *(empty)* | API key del provider. Vuoto → modulo disabilitato |
| `ABM_LLM_API_BASE` | `https://api.deepseek.com` | Endpoint OpenAI-compatible |
| `ABM_LLM_MODEL` | `deepseek-chat` | Model id |

### 13.2 Generation behavior

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_LLM_THINKING` | `false` | Thinking mode (CoT) — supportato da modelli `*-thinking` |
| `ABM_LLM_REASONING_EFFORT` | `none` | `none`/`low`/`medium`/`high` |
| `ABM_LLM_TEMPERATURE` | `0.3` | Bassa → editing deterministico |
| `ABM_LLM_MAX_TOKENS` | `65536` | Cap output token. Influenza `SAFE_OUTPUT_CHUNK` (~195k char) |

### 13.3 Token economy

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_LLM_CHARS_PER_TOKEN` | `3.5` | Heuristica char→token (lingue latine) |
| `ABM_LLM_MAX_CONTEXT_TOKENS` | `1000000` | Context window totale |
| `ABM_LLM_RESERVED_PROMPT_TOKENS` | `4000` | Token riservati al system prompt |
| `ABM_LLM_OUTPUT_SAFETY_MARGIN` | `0.85` | Coefficiente di sicurezza su `SAFE_OUTPUT_CHUNK` |

### 13.4 Reliability / pacing

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_LLM_REQUEST_TIMEOUT_SEC` | `120.0` | Timeout singola chiamata HTTP streaming |
| `ABM_LLM_MAX_RETRIES` | `4` | Tentativi su errore transient (backoff `2**attempt`) |
| `ABM_LLM_INTER_CHUNK_SLEEP_SEC` | `0.5` | Pausa tra chunk dello stesso capitolo |
| `ABM_LLM_HEARTBEAT_TIMEOUT_SEC` | `60.0` | Auto-cancel se UI non poll-a (solo interactive) |

### 13.5 Pricing (LLM)

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_LLM_RATE_EUR_PER_MCHAR` | `1.10` | EUR per 1M char (markup + fee inclusi) |
| `ABM_LLM_FREE_THRESHOLD_EUR` | `0.50` | Soglia gratuità |

### 13.6 Voucher (condivise con sistema pagamento)

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_VOUCHER_EXPIRY_DAYS` | `180` | Validità voucher |
| `ABM_VOUCHER_BONUS_PERCENT` | `10` | Bonus voucher di rimborso (su importo PayPal originale) |
| `ABM_PAYMENT_RETENTION_DAYS` | `730` | Retention record pagamenti (GDPR/fiscale) |

### 13.7 Concorrenza & cap

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_MAX_CONCURRENT_LLM_PER_CLIENT` | `1` | Massimo ottimizzazioni concorrenti per `client_id` |
| `ABM_MAX_TEXT_CHARS` | `1500000` | Hard cap caratteri totali (vale anche prima dell'ottimizzazione) |

### 13.8 Costanti derivate (computed)

Calcolate al boot, **non configurabili direttamente** (variano in funzione di `MAX_TOKENS`, `CHARS_PER_TOKEN`, `MAX_CONTEXT_TOKENS`, `RESERVED_PROMPT_TOKENS`, `OUTPUT_SAFETY_MARGIN`):

- `LLM_RESERVED_OUTPUT_TOKENS = LLM_MAX_TOKENS`
- `LLM_MAX_INPUT_TOKENS = LLM_MAX_CONTEXT_TOKENS - LLM_RESERVED_OUTPUT_TOKENS - LLM_RESERVED_PROMPT_TOKENS`
- `LLM_MAX_INPUT_CHARS = int(LLM_MAX_INPUT_TOKENS * LLM_CHARS_PER_TOKEN)`
- `LLM_SAFE_OUTPUT_CHUNK = int(LLM_MAX_TOKENS * LLM_CHARS_PER_TOKEN * LLM_OUTPUT_SAFETY_MARGIN)` ≈ 195k char con default

---

## 14. Troubleshooting

### 14.1 `[LLM] Using prompt file: prompt_tts_generic.md` quando ci si attendeva uno specifico

Diagnostica:

1. **Voce Gemini senza `opt_lang`?** Non dovrebbe succedere su flussi normali (`/api/optimize` lo setta sempre). Verifica che il client invii `lang` nel body.
2. **Lingua non supportata?** Verifica che `prompt_opt_AI/prompt_tts_<lang>.md` esista (vedi §3.3).
3. **`opt_lang` malformato?** Es. `"zh-CN"` viene strippato a `"zh"` → cerca `prompt_tts_zh.md` (esiste). Ma `"zh-Hans"` viene strippato a `"zh"` → idem OK. Stringhe ibride come `"gemini:flash25:zephyr"` cadrebbero su generic, ma per Gemini il fallback in `_call_llm` cade a `"it"` (vedi §3.2).

Nei log si vede sempre il file effettivamente caricato. Il log è la fonte di verità.

### 14.2 Job bloccato in `optimizing` con browser chiuso

Se `email_registered` è True → comportamento atteso (batch). Se False, dovrebbe auto-cancellarsi dopo 60s. Se non accade, verifica che `last_poll` venga aggiornato in `/api/optimize_progress`. Cleanup loop background dovrebbe comunque rimuovere job idle (`ABM_JOB_RETENTION_SEC`, default 64800s = 18h).

### 14.3 Pagamento consumato ma ottimizzazione fallita

`_refund_job_payment` viene invocato nelle eccezioni di `run_optimization`. Se non parte: 1) verifica i log per il traceback completo, 2) la riga `_refund_job_payment(job_id, job, "error")` è in `except Exception` quindi cattura tutto; 3) check `job["payment_token"]` ancora presente — il record `payment._payments[token]` dovrebbe avere `"used": False` ripristinato o un voucher di refund emesso. Per audit: `data/_payments.json` (PayPal) + `data/_vouchers.json`.

### 14.4 Output con preamboli ("Sure, here is...")

`_sanitize_llm_output` dovrebbe gestirli (vedi §7). Se sfugge un pattern nuovo, aggiungere il regex a `_LLM_PREAMBLE_PATTERNS` (`generation_engine.py:343`). Pattern multilingua: IT, EN, FR, ES, DE attualmente coperti.

---

## 15. Manutenzione prompt

Workflow per modificare le regole di ottimizzazione (vedi `prompt_opt_AI/README.md`):

1. Editare `prompt_tts_master.md` per primo (single source of truth).
2. Propagare la modifica a `prompt_tts_<lang>.md` affected (la maggior parte delle regole è universale — Sezione A).
3. Se la regola è universale, propagare anche a `prompt_tts_generic.md`.
4. Run regression test suite (input fissi + output noti per lingua) prima di deploy.
5. Bump `version.py` se la modifica è significativa.

**NON modificare** la sezione "Output Format" (Sezione E del master) senza aggiornare anche `_sanitize_llm_output` (`generation_engine.py:363`): i due lavorano in coppia per garantire output pulito anche se il modello sgarra.

---

## 16. Riepilogo punti di attenzione

- **`opt_lang` è la chiave**: senza, Gemini cade su prompt italiano. Verificare sempre che `/api/optimize` riceva `lang`.
- **Edge & Google funzionano anche senza `opt_lang`** grazie al fallback su voice ID, ma è comunque preferibile passarlo (UI multilingua).
- **Chunking guidato dall'output**: `LLM_SAFE_OUTPUT_CHUNK ≈ 1.14M char`. Il context input è 10× più grande ma irrilevante per il limite operativo.
- **Refund asimmetrico**: voucher → silent recredit, PayPal → nuovo voucher +10% via email. Vedi `feedback_refund_voucher_policy.md`.
- **Heartbeat 60s** salvo batch mode con `email_registered=True`.
- **Sanitization a due passate**: prima dopo ogni call, poi sul testo ricomposto post-join chunk.
- **UI: mai "DeepSeek"**: vedi `feedback_ui_provider_naming.md`. Etichetta sempre "Ottimizzazione testo AI".
