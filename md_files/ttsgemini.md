# ttsgemini.md — Integrazione Gemini TTS

Riferimento operativo per il motore TTS Premium basato su **Google Gemini 2.5 / 3.1 Flash TTS**. Documento parallelo a `CLAUDE.md`: copre architettura, pipeline di sintesi, pricing, throttling, retry, budget guard, audit, UI e variabili `ABM_GEMINI_*`. Il documento è **generico rispetto al tier Google** (Free / Tier 1 / Tier 2 / Tier 3): i numeri di esempio si riferiscono al tier corrente solo come illustrazione e sono interamente override-abili via env.

> **Convenzione UI**: nelle interfacce utente il provider non viene mai nominato. Etichette: "Voci PREMIUM", "Ottimizzazione testo AI". Il nome "Gemini" compare solo in log tecnici, audit file e codice. Vedi memoria `feedback_ui_provider_naming.md`.

---

## 1. Scopo e posizionamento

Gemini TTS è il terzo motore di sintesi vocale dell'app, accanto a:

| Motore | Modulo | Output | Costo | Tier free |
|--------|--------|--------|-------|-----------|
| **Edge TTS** (Microsoft) | `tts_split.py` async | MP3 48 kbps mono | gratuito | illimitato |
| **Google Chirp3-HD** | `google_tts.py` | MP3/PCM | a pagamento | 1M char/mese |
| **Gemini Flash TTS** | `gemini_tts.py` | PCM 24 kHz mono 16-bit | a pagamento | RPD limitato |

Gemini si distingue per:

- **Voci multilingue native**: 30 voci × 2 modelli, ciascuna disponibile sotto ogni lingua UI supportata (vedi `SUPPORTED_UI_LANGUAGES` in `gemini_tts.py:415`: 23 codici ISO 639-1 ufficiali Google + `zh` legacy = 24 lingue; `en-US` ed `en-IN` collassano sotto `en`). Non c'è un catalogo per lingua: la stessa voce parla qualsiasi delle lingue supportate.
- **Stile controllabile via prompt**: `style_instruction` (max 200 char user-side; cap calibrato per lasciare spazio alla rate directive ~95 char nello stesso blocco `[style: ...]`) viene prefissata a ogni chunk per orientare tono/emozione.
- **Direttive di velocità in linguaggio naturale**: 7 step (`-30%`..`+30%`) mappati su istruzioni testuali ("Read this text slowly...", "Read this text very quickly...") perché Gemini non espone una `speaking_rate` API.
- **Costing per token**: input + output token tariffati separatamente in USD per MTok, con conversione EUR + margine + fee PayPal.

---

## 2. Architettura

```
audiobook_app.py
   ├── /api/preview_audio              → gemini_tts.synthesize() (chunk singolo)
   ├── /api/gemini_estimate            → gemini_tts.estimate_book_cost()
   ├── /api/optimize  (Premium path)   → preflight_budget_check + preflight_can_run
   └── /api/generate                   → spawn run_generation() (background)

generation_engine.py
   └── run_generation(..., gemini_style_instruction=...)
         ├── preflight_can_run(model_key, total_chunks)   # RPD guard
         ├── per chunk:
         │     tts_split.generate_chunk_pcm_gemini(text, voice_id,
         │                                         output_path,
         │                                         style_instruction)
         │       └── gemini_tts.synthesize(text, voice_id,
         │                                 rate=rate_pct,
         │                                 style_instruction=style)
         │             ├── _check_rpd_cap()    # quota locale
         │             ├── _throttle_rpm()     # interval floor
         │             ├── client.models.generate_content(...)
         │             ├── _rpd_increment()    # solo su success
         │             └── retry policy (retryDelay-aware)
         └── _write_gemini_audit() → gemini_cost_audit_YYYY-MM.jsonl

gemini_tts.py
   ├── Voci e modelli: GEMINI_MODELS, GEMINI_VOICE_NAMES, parse_voice_id()
   ├── Cost: estimate_input_tokens / estimate_output_tokens /
   │         google_cost_breakdown / compute_user_price_eur / estimate_book_cost
   ├── Budget: preflight_budget_check / get_daily_spent_eur / budget_status
   ├── Throttle: _check_rpd_cap / _throttle_rpm / preflight_can_run / rpd_status
   ├── Retry: _parse_retry_after / _is_429 / _is_daily_quota_error
   ├── Rate log: record_rate_sample / get_empirical_rate (calibrazione audio/char)
   ├── Preview cap: check_preview_cap / increment_preview
   └── synthesize()  — sintesi + retry + audit token

tts_split.py
   ├── _pick_chunk_max_bytes(voice_id)  → MAX_BYTES_PER_CALL per Gemini, None altrove
   ├── _max_chunk_chars()               → DEFAULT_CHUNK_CHARS per Gemini
   ├── _synthesize_pcm_pieces_and_concat()  → emergency byte-split + concat PCM
   └── generate_chunk_pcm_gemini()      → wrapper retry sopra synthesize()
```

**Vincoli di dipendenza**:

- `gemini_tts` non importa mai `audiobook_app` né `generation_engine` (no circular).
- `tts_split` fa late-import di `gemini_tts` (`import gemini_tts` dentro la funzione) per mantenere il modulo opzionale: se `google-genai` non è installato, Edge/Google continuano a funzionare.
- `gemini_tts.is_available()` è la *single source of truth* per "Gemini è utilizzabile". Cached dopo la prima chiamata (lock-protected). Override admin in cima: se il kill-switch `is_admin_disabled()` è True, ritorna sempre `False` indipendentemente dalla capability detection.
- **Kill-switch admin** (`set_admin_disabled(disabled, reason)`) persistito in `ABM_DATA_DIR/gemini_admin_state.json` (mirror in-memory `_admin_disabled`, ricaricato in `init()`). Endpoint: `GET/POST /admin/api/gemini_kill_switch`. UI: pannello in `/admin/audit-tts`. Quando attivo, `/api/voices` non include più l'optgroup PREMIUM, le stime e i flussi di pagamento Premium rispondono 503 (gateano già su `is_available()`). `is_capability_available()` espone la capability bypassando il kill-switch (usata dal pannello admin per distinguere "spento per scelta" da "non configurato").

---

## 3. Selezione voci e modelli

### 3.1 Voice ID

Formato canonico: `gemini:<model_key>:<voice_name>`.

- `<model_key>` ∈ {`flash25`, `flash31`} (chiavi interne; vedi tabella sotto)
- `<voice_name>` ∈ `GEMINI_VOICE_NAMES` (30 nomi, es. `Zephyr`, `Kore`, `Algenib`)

Esempi: `gemini:flash25:Zephyr`, `gemini:flash31:Kore`.

`parse_voice_id()` valida i tre componenti e solleva `ValueError` se uno è sconosciuto.

### 3.2 Modelli supportati

Definiti in `GEMINI_MODELS` (`gemini_tts.py:62`). Ogni entry contiene id API (API key + Vertex) + label umana + tariffe USD/MTok + margine default. **Nota**: l'ID effettivo passato a `client.models.generate_content` dipende dal backend attivo (vedi §16 "Autenticazione e Backend") ed è risolto da `_resolve_model_id(model_key)`.

| `model_key` | API key ID | Vertex ID (GA) | Label | Input USD/MTok | Output USD/MTok |
|-------------|------------|----------------|-------|----------------|-----------------|
| `flash25` | `gemini-2.5-flash-preview-tts` | `gemini-2.5-flash-tts` | "Gemini 2.5 Flash TTS" | `ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK` | `ABM_GEMINI_25FLASH_OUTPUT_USD_PER_MTOK` |
| `flash31` | `gemini-3.1-flash-tts-preview` | `gemini-3.1-flash-tts-preview` | "Gemini 3.1 Flash TTS" | `ABM_GEMINI_31FLASH_INPUT_USD_PER_MTOK` | `ABM_GEMINI_31FLASH_OUTPUT_USD_PER_MTOK` |

**Aggiungere un nuovo modello**: estendere `GEMINI_MODELS` con un nuovo `<model_key>` + ID per entrambi i backend (API key + Vertex) + relative env per pricing/margine + (se necessario) tuning RPM/RPD dedicato + region default (`_resolve_location`).

### 3.3 Catalogo voci

`get_voices()` produce il dict `{lang_code: [voice_entry, ...]}` consumato dal frontend. Ogni voce è esposta **sotto ogni lingua UI** (vedi `SUPPORTED_UI_LANGUAGES`, `gemini_tts.py:415`) perché le voci Gemini sono multilingue native — la stessa `Zephyr` legge IT, EN, FR ecc. senza scelta esplicita di locale al backend.

Lingue esposte (24 ISO 639-1): le **23 ufficiali** Google AI per Gemini TTS al netto del doppione `en-US`/`en-IN` (`it, en, fr, es, de, pt, nl, pl, ro, tr, ru, uk, ja, ko, hi, ar, bn, mr, ta, te, th, id, vi`; locale di default in `_LANG_LOCALE`, `gemini_tts.py:422`) **+ `zh` legacy** (non ufficialmente supportato da Google ma funzionante empiricamente, mantenuto per retrocompatibilità).

Filtro UI: il dropdown `#vlPremium` del tab Premium (`static/js/app.js`, funzione `syncLanguageOptions()`) **elenca solo le lingue per cui esiste almeno una voce Premium** (id `gemini:`). Le lingue Edge non coperte da Gemini restano disponibili nel tab Standard ma non compaiono nel Premium dropdown — evita la pessima UX dell'elenco voci vuoto al cambio lingua.

Ordine output: tutte le **Female** prima (in ordine alfabetico), poi tutte le **Male**, in coerenza con l'`<optgroup>` del selettore voci Edge. Gender mappato in `GEMINI_VOICE_GENDER` (fonte: documentazione ufficiale Google AI Studio).

### 3.4 Selezione lingua TTS (≠ voice ID)

Le voci Gemini non hanno prefisso di lingua nel `voice_id`. La lingua TTS scelta dall'utente è propagata separatamente:

- Frontend salva `lang` UI nella request `/api/optimize`.
- Backend memorizza `job["opt_lang"]` (es. `"it"`, `"fr"`).
- `_call_deepseek()` (`generation_engine.py:477`) usa `opt_lang` per scegliere il prompt LLM (`prompt_tts_<lang>.md`), **non** estrae la lingua dal voice ID.
- Fallback (solo se `opt_lang` manca): per voci NON-Gemini estrae da `voice_id.split("-")[0]`; per Gemini cade su `it`.

Test che blindano questa logica: `test/test_llm_prompt_lang_selection.py`.

---

## 4. Pipeline di sintesi

```
testo capitolo
   └── tts_split._plan_chunks()
         max_chars = get_max_chunk_chars(lang)         # DEFAULT_CHUNK_CHARS (700)
         max_bytes = _pick_chunk_max_bytes(voice_id)   # MAX_BYTES_PER_CALL (soft)
   └── per ogni chunk:
         generate_chunk_pcm_gemini(text, voice_id, output_path, style_instruction)
           ├── if clean_bytes > MAX_BYTES_PER_CALL:
           │     _synthesize_pcm_pieces_and_concat()   # emergency split + concat
           └── gemini_tts.synthesize(text, voice_id, rate, style_instruction)
                 ├── [style: <user_style 300char> <rate_directive>] prepended
                 │   (style+rate fusi in unico blocco; omesso se entrambi vuoti)
                 ├── payload_bytes <= API_HARD_BYTES_CAP   (hard cap)
                 ├── _check_rpd_cap()
                 ├── _throttle_rpm()
                 ├── client.models.generate_content(...)
                 ├── _extract_audio_pcm()
                 ├── _rpd_increment()
                 └── usage_metadata → input/output token counts
   └── trim trailing silence di ogni PCM (cap trim_tail_ms, default 800 ms; soglia trim_tail_threshold, default 200)
   └── concat PCM di tutti i chunk con gap silenzio inter_chunk_gap_ms (default 100 ms)
   └── PCM → MP3 (encoder esterno) o PCM → AAC/M4B (FFmpeg)
```

### 4.1 Chunking

`tts_split._plan_chunks()` segmenta testo a confine di frase, rispettando due limiti:

- **`max_chars`**: cap morbido sulla quantità di caratteri per chunk. Per Gemini di default 700 (configurabile globalmente via `ABM_GEMINI_CHUNK_CHARS` o per-lingua via `ABM_GEMINI_MAX_CHUNK_CHARS_<LANG>`).
- **`max_bytes`** (solo Gemini): cap byte UTF-8 sul **testo puro** (= `MAX_BYTES_PER_CALL`). Edge/Google ricevono `None`.

Filosofia: chunk piccoli (~700 char) sacrificano numero di chiamate API in cambio di **stabilità acustica e prosodia uniforme**. È un trade-off pensato per tier con RPD elevato (Tier 2/3); su Free/Tier 1 si raccomanda di alzare `ABM_GEMINI_CHUNK_CHARS` per ridurre RPD consumati.

### 4.2 Prefissi di prompt (NON contati nel target qualità)

Il payload effettivamente inviato a `generate_content` è:

```
[style: <style_instruction trimmed a 200 char> <rate directive (max ~95 char)>] <testo>
```

Style utente e rate directive sono **fusi in un singolo blocco `[style: ...]`** (precedentemente erano due prefissi separati: causava il modello a ignorare la rate directive perché in lingua diversa dal testo e fuori da un contesto semantico). Caso degenerato: se entrambi sono vuoti (no style utente + rate `+0%`), il prefisso non viene aggiunto e il payload è solo `<testo>`.

Entrambi i contenuti sono **direttive di prompt, non testo audio**:

- Non concorrono al target qualità `MAX_BYTES_PER_CALL`.
- Concorrono al hard cap API `API_HARD_BYTES_CAP` (vedi §5).
- Sono applicati a **ogni chunk** (non solo al primo del capitolo), per garantire continuità di stile/velocità anche se Gemini "dimentica" tra una call e l'altra.

### 4.3 Rate directives

`_GEMINI_RATE_DIRECTIVES` mappa lo step intero (-3..+3, da `rate_pct/10`) a una frase in inglese:

| step | rate_pct | Directive |
|------|----------|-----------|
| -3 | -30% | "Read this text very slowly, with deliberate, measured pacing and long pauses..." |
| -2 | -20% | "Read this text slowly, taking your time and articulating clearly." |
| -1 | -10% | "Read this text at a slightly relaxed, slower than normal pace." |
| 0 | 0 | *(nessuna direttiva — più stabile)* |
| +1 | +10% | "Read this text at a slightly brisk pace, a bit faster than normal." |
| +2 | +20% | "Read this text at a quick, energetic pace." |
| +3 | +30% | "Read this text very quickly, with rapid pacing and minimal pauses." |

Kill-switch: `ABM_GEMINI_RATE_MODE`. Default `prompt` → la directive viene aggiunta dentro `[style: ...]` (vedi §4.2). Per disattivare (audio sempre a velocità nativa Gemini, indipendentemente dal rate selezionato dall'utente), setta a `disabled`. Valori legacy (`token`, `estimate`) ricevuti per retro-compatibilità sono trattati come `disabled` ma non influenzano nient'altro (es. cost calc) — sono soltanto disattivatori del prompt directive.

### 4.4 Trim trailing silence + inter-chunk gap

I chunk Gemini TTS portano con se` **trailing silence naturale variabile** (50–1500 ms), specialmente quando il testo termina con punto fermo o quando contiene chapter title / frasi di apertura. Sommato all'inter-chunk gap, questo silenzio creava pause percepibili di "qualche secondo" all'inizio del libro (sintomo: ascoltatore percepisce vuoti tra i primi chunk anche se la narrazione e` integra).

**Pipeline post-generazione chunk** (in `generation_engine.run_generation`, branch single-file e multi-file):

1. `generate_chunk_pcm_gemini()` → PCM 24 kHz mono 16-bit.
2. Se `result is not False` e `gemini_tts.trim_tail_ms() > 0` → `audio_utils.trim_pcm_trailing_silence(part_path, threshold=trim_tail_threshold(), max_trim_ms=trim_tail_ms())` tronca in-place i sample finali sotto soglia ampiezza. Cap protegge contro tagli sull'attacco di parola.
3. `current_ms`/marker M4B leggono `getsize(part_path)` DOPO il trim → timing in sync automatico.
4. `pcm_concat()` inserisce `inter_chunk_gap_ms()` (default 100 ms) tra ogni coppia di PCM consecutivi.

| Parametro | Default | Env var | Note |
|-----------|---------|---------|------|
| `inter_chunk_gap_ms()` | `100` | `ABM_GEMINI_INTER_CHUNK_GAP_MS` | Abbassato da 250 → 100 dopo introduzione del trim |
| `trim_tail_ms()` | `800` | `ABM_GEMINI_TRIM_TAIL_MS` | `0` disabilita il trim |
| `trim_tail_threshold()` | `200` | `ABM_GEMINI_TRIM_TAIL_THRESHOLD` | int16 assoluto, ≈ -44 dB |

Note: il trim non viene applicato sul file `_silence.pcm` (intro capitolo da `CHAPTER_SILENCE_SEC`), perche` quello e` silenzio per design. Inoltre se `result is False` (chunk fallito → segnaposto di 1 s di silenzio puro scritto da `_generate_silence_pcm`) il trim viene saltato, altrimenti azzererebbe il segnaposto e perderemmo il segnale di fallimento.

---

## 5. Soglie byte: target qualità vs hard cap API

Due limiti distinti, spesso confusi:

| Costante | Scope | Default | Comportamento se sforato |
|----------|-------|---------|-------------------------|
| `MAX_BYTES_PER_CALL` | testo puro (no prefissi) | `ABM_GEMINI_MAX_BYTES_PER_CALL` (8000) | **soft**: warning, sintesi prosegue. È un target qualità — Gemini regge il payload, ma la prosodia degrada |
| `API_HARD_BYTES_CAP` | payload completo (testo + prefissi) | `ABM_GEMINI_API_HARD_BYTES_CAP` (8000) | **hard**: `synthesize()` solleva `ValueError`. È il limite tecnico oltre cui Gemini rifiuta la chiamata |

Validazione in `synthesize()` in **due step**:

1. `check_text_byte_size(text)` → se `> MAX_BYTES_PER_CALL`: solo `print(WARN)` (acustica potenzialmente degradata)
2. Dopo aver prepended style + rate prefix, ricalcolo `payload_size`: se `> API_HARD_BYTES_CAP`: `raise ValueError`

In pratica, lo splitter (`tts_split`) garantisce già che il testo stia sotto entrambe le soglie. Le validazioni in `synthesize()` sono difesa in profondità.

### 5.1 Emergency byte-split

Quando il caller passa un chunk già troppo grande (e.g. una frase singola supera `MAX_BYTES_PER_CALL`), `generate_chunk_pcm_gemini()` invoca `_synthesize_pcm_pieces_and_concat()`: spezza in sotto-chunk per byte, sintetizza ciascuno, concatena PCM. Logga `Emergency byte-split`. È un fallback raro; se appare nei log è segnale che lo splitter va riconfigurato per la lingua specifica.

---

## 6. Style instruction

Stringa libera fino a **200 char** (dopo strip; cap user-side enforced via `maxlength="200"` in HTML, `.slice(0,200)` in JS, `[:200]` in `gemini_tts.synthesize`). Esempi:

- `"Calm, intimate narrator with measured pauses"`
- `"Energetic storyteller, varied intonation"`
- `"Neutral audiobook reading, clear and steady"`

Caratteristiche:

- Iniettata su **ogni chunk** come prefisso `[style: ...]`. Non c'è "primo chunk speciale": Gemini è stateless tra call, lo stile va ripetuto.
- Cap 200 char user-side: oltre, il modello inizia a interpretare lo stile come parte del testo da leggere. Il budget storico "comprensibile" e` ~300 char nel blocco `[style: ...]`; 200 di user input + ~95 di rate directive piu` lunga + 1 separatore = 296, dentro budget.
- Conta nel `API_HARD_BYTES_CAP` ma non nel `MAX_BYTES_PER_CALL`.
- Configurabile in fase di generazione: `gemini_style_instruction` argomento di `run_generation()`. Passata da `/api/generate` se l'utente lo specifica.
- Persistita nel job dict (`job["gemini_style_instruction"]`) per audit.

---

## 7. Rate limiting

Due meccanismi indipendenti, entrambi configurabili per modello.

### 7.1 RPM (Requests Per Minute) — `_throttle_rpm`

Intervallo minimo tra due chiamate consecutive **per modello**. Implementato come sleep client-side:

```
elapsed_ms = (now - last_call_ts[model_key]) * 1000
wait_ms = min_interval_ms - elapsed_ms
if wait_ms > 0: sleep(wait_ms / 1000)
```

Configurabile:

| Modello | Env | Default | Tipico free | Tipico Tier 1 | Tipico Tier 2/3 |
|---------|-----|---------|-------------|---------------|-----------------|
| flash25 | `ABM_GEMINI_MIN_INTERVAL_FLASH25_MS` | `0` | 6500 ms (10 RPM) | 80 ms (~750 RPM) | 0 (no throttle) |
| flash31 | `ABM_GEMINI_MIN_INTERVAL_FLASH31_MS` | `0` | 21000 ms (3 RPM) | 200 ms (~300 RPM) | 0 (no throttle) |

`0` disabilita il throttle (delega al rate-limit server-side di Google).

### 7.2 RPD (Requests Per Day) — `_check_rpd_cap` / `_rpd_increment`

Contatore persistito in `gemini_tts_rpd.json` (chiave: data UTC). Rolla a mezzanotte UTC. Incrementato **solo su success** della call (`synthesize()` aggiorna dopo l'extract PCM riuscito).

Configurabile:

| Modello | Env | Default |
|---------|-----|---------|
| flash25 | `ABM_GEMINI_RPD_FLASH25` | `0` (= no cap locale, delega all'API) |
| flash31 | `ABM_GEMINI_RPD_FLASH31` | `0` |
| Safety reserve | `ABM_GEMINI_RPD_SAFETY_RESERVE` | `0` |

Quando `used + reserve >= cap`, `_check_rpd_cap()` solleva `GeminiQuotaExhausted(reason="rpd_local_cap")` con `retry_after_sec` = secondi residui fino a mezzanotte UTC.

### 7.3 Preflight RPD

Prima di avviare un job, `preflight_can_run(model_key, chunks_needed)`:

```
available = cap - used - reserve
shortfall = max(0, chunks_needed - available)
```

Se `shortfall > 0`, restituisce `ok: False` + `retry_after_sec`. Frontend mostra il modale "gemini_overload" con countdown a mezzanotte UTC. Il job NON viene avviato, NESSUN addebito viene effettuato.

`rpd_status()` espone lo stato a `/admin` per dashboard.

---

## 8. Retry policy

Implementata in `synthesize()` (loop `while attempt < max_attempts`). Configurabile:

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_GEMINI_SYNTH_MAX_ATTEMPTS` | `3` | Numero massimo di tentativi per call (override-able via parametro `max_attempts` di `synthesize()`) |
| `ABM_GEMINI_RETRY_HONOR_DELAY` | `true` | Se `true`, rispetta `retryDelay` server-side |
| `ABM_GEMINI_RETRY_MAX_WAIT_SEC` | `60` | Se `retryDelay > max_wait`, abort invece di sleep |
| `ABM_GEMINI_ABORT_ON_QUOTA` | `true` | Su 429 daily-quota, abort immediato (no retry) |
| `ABM_GEMINI_HTTP_TIMEOUT_MS` | `25000` | Timeout HTTP in ms per le call all'API Gemini su modello **`flash25`** (applicato per-call via `GenerateContentConfig.http_options=HttpOptions(timeout=...)`; il client singleton mantiene lo stesso valore come default fallback). Evita che `generate_content()` penda indefinitamente su API lenta/irraggiungibile. Per preview il ThreadPoolExecutor timeout di 30s funge da secondo limite. |
| `ABM_GEMINI_HTTP_TIMEOUT_MS_FLASH31` | `60000` | Timeout HTTP in ms per le call su modello **`flash31`** (`gemini-3.1-flash-tts-preview`). Default piu` permissivo (60s vs 25s di flash25) perche` flash31 ha RPM cap inferiore (3/300 vs 10/750) e audio gen piu` lenta lato Google: senza maggiorazione i chunk normali finiscono in 504 `DEADLINE_EXCEEDED`, saturano i 3 retry e producono silenzio. Selezione automatica via `_http_timeout_ms(model_key)` in `gemini_tts.py:1161` -- nessuna azione manuale necessaria, ma override possibile via env. |
| `ABM_GEMINI_PREVIEW_TIMEOUT_SEC_FLASH31` | `65` | Timeout in **secondi** del `ThreadPoolExecutor` wrapper in `/api/preview_audio` per modello **`flash31`**. Deve essere ≥ `ABM_GEMINI_HTTP_TIMEOUT_MS_FLASH31/1000` + buffer per non strozzare la call Google. Default `65` (= 60s HTTP + 5s buffer). flash25 mantiene il wrapper hardcoded a 30s. Catena timeout preview: HTTP Google → wrapper → client JS; ognuno con ~5s di buffer sul precedente. |

**Override per-caller**: `synthesize()` accetta un argomento opzionale `max_attempts` che, se passato (>0), vince sull'env. Usato dal path **preview** (`/api/preview_audio`) con `max_attempts=1` per fallire velocemente su `EMPTY-RESPONSE finish_reason=OTHER` (retry deterministicamente inutile per stesso payload) e non saturare il timeout client di 30s → 504. La generazione lunga continua a usare il default 3 perche` ha il fallback "1s silenzio" su chunk falliti.

**Mapping errori → HTTP status in `/api/preview_audio` (per feedback UI)**:

| Eccezione | Status | JSON body | i18n key frontend |
|-----------|--------|-----------|-------------------|
| `GeminiEmptyResponse` (finish_reason=OTHER/MAX_TOKENS/etc) | 502 | `{error, code: "empty_response", finish_reason}` | `gemini_empty_response` |
| `GeminiQuotaExhausted` (RPD server-wide raggiunto) | 503 | `{error, code: "quota_exhausted", retry_after_sec}` | `gemini_quota_exhausted` |
| `GeminiBudgetExceeded` (budget EUR daily/per-job) | 503 | `{error, code: "budget_exceeded"}` | `gemini_budget_exceeded` |
| `httpx.TimeoutException` (HTTP timeout API Gemini) | 504 | `{error, code: "http_timeout"}` | `gemini_timeout` |
| `concurrent.futures.TimeoutError` (preview > 30s) | 504 | `{error}` | `gemini_timeout` |
| Preview cap per-client superato | 429 | `{error, used, cap, reset_in_seconds}` | `gemini_preview_cap_exceeded` |
| Servizio Gemini non configurato (env mancanti) | 503 | `{error}` (no `code`) | `gemini_not_configured` |
| Altre eccezioni | 500 | `{error}` (testo eccezione) | `prev_error` (generico) |

Tutte le chiavi i18n sopra sono presenti in `templates/_fragments/i18n_data.js` per 7 lingue. Il frontend (`previewRead()` in `static/js/app.js`) discrimina 503 in base al campo `code` del JSON; assenza di `code` → "not configured".

Flow su eccezione:

1. **`GeminiEmptyResponse` non-retryable** (safety/prohibited/recitation): abort immediato.
2. **429 daily-quota** + `ABORT_ON_QUOTA=true`: `raise GeminiQuotaExhausted(reason="api_daily_quota")`.
3. **429 con `retryDelay > RETRY_MAX_WAIT_SEC`**: `raise GeminiQuotaExhausted(reason="retry_too_long")` invece di sleep prolungato.
4. **429 con `retryDelay ≤ RETRY_MAX_WAIT_SEC`**: sleep `retryDelay`, poi retry.
5. **Altre eccezioni**: backoff esponenziale `min(30, 2^attempt)` secondi.

`_parse_retry_after()` estrae il delay da:

- Attributo SDK strutturato: `err.details[*].retry_delay.seconds`
- Stringa: `retryDelay: "22371s"` (formato API standard)
- Stringa: `retry in 6h12m51.7s` / `retry in 5s` (fallback human-readable)

### 8.1 Comportamento del caller

`generate_chunk_pcm_gemini` (`tts_split.py:412`) NON ricattura `GeminiQuotaExhausted` né `GeminiBudgetExceeded`: le lascia propagare a `run_generation()` che le gestisce a livello job:

- Sospende il job (status `paused`).
- Refunda il pagamento (voucher accreditato o ordine PayPal smarcato).
- Notifica l'utente con `_send_gemini_overload_email` / `_send_gemini_failed_refund_email`.
- Logga record di audit in `gemini_cost_audit_YYYY-MM.jsonl`.

---

## 9. Budget guard

Cap su spesa **EUR** (non token / chunk). Indipendente da RPD, complementare. Pensato per Tier 1+ dove la quota Google non è il vincolo binding (RPD elevato) ma la spesa giornaliera può sorprendere.

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_GEMINI_DAILY_BUDGET_EUR` | `0.0` | Cap giornaliero. `0` = disabilitato |
| `ABM_GEMINI_PER_JOB_BUDGET_EUR` | `0.0` | Cap per singolo job. `0` = disabilitato |
| `ABM_GEMINI_BUDGET_ALERT_PCT` | `80` | Soglia warning sopra il quale logga `[alert]` |
| `ABM_GEMINI_BUDGET_HARD_STOP` | `true` | Se `true`, blocca; se `false`, solo warning |

`preflight_budget_check(estimated_cost_eur)`:

- Se `estimated > per_job_cap`: `raise GeminiBudgetExceeded(scope="per_job")`.
- Se `spent_today + estimated > daily_cap`: `raise GeminiBudgetExceeded(scope="daily", used_eur=...)`.
- Se `projected > daily_cap * alert_pct/100`: log warning, prosegue.
- Se `HARD_STOP=false`: warning sempre, mai raise.

`get_daily_spent_eur()` aggrega i record del giorno corrente da `gemini_cost_audit_YYYY-MM.jsonl` (campo `google_cost_eur_actual`). Lettura graceful: cade su `0.0` se il file non esiste / corrotto.

`budget_status()` snapshot per admin: `daily_cap_eur`, `daily_spent_eur`, `daily_remaining_eur`, `daily_used_pct`, `per_job_cap_eur`, `alert_pct`, `hard_stop`.

**Atomic budget reservation** (`reserve_budget(job_id, eur)` / `release_reservation(job_id)`): tracker in-memory `_active_reservations: dict[job_id, eur]` sotto `_reservations_lock`. Necessario perché il cost viene scritto nel JSONL audit solo a fine job: due preflight concorrenti vedono lo stesso `spent` e potrebbero entrambi passare il cap. `reserve_budget` somma `spent + sum(other reservations) + new` e raise `GeminiBudgetExceeded` se >= `daily_cap`. Chiamato da `audiobook_app.api_generate` dopo `preflight_budget_check`; rilasciato in `generation_engine.run_generation` dopo `gemini_cost_audit.append_record` (e su ogni early-return tra preflight e dispatch async). Idempotente per `job_id`.

---

## 10. Modalità billing

`ABM_GEMINI_RATE_MODE` controlla **cosa** viene fatturato. Tre opzioni:

| Valore | Significato |
|--------|-------------|
| `prompt` (legacy) | Conteggio basato su caratteri testo (stima grossa). Inietta anche le direttive di rate nel prompt |
| `token` (default consigliato) | Usa `usage_metadata.prompt_token_count` + `candidates_token_count` reali restituiti da Gemini. Più accurato, è la fonte autoritativa per la riconciliazione |
| `estimate` | Stima ex-ante via `estimate_input_tokens` + `estimate_output_tokens`; usato per UI preventiva, non per addebito |

Le **stime ex-ante** (`estimate_book_cost`) e il **costo reale ex-post** (`record_job_completion`) sono entrambi tracciati: la reconciliation `estimated_cost_eur_total` vs `actual_cost_eur_total` è esposta in `get_usage()` e usata in `/admin` per misurare l'accuratezza del preventivo.

### 10.1 Stima ex-ante (`estimate_book_cost`)

```
chars_total = sum(len(_normalize_text(ch.text)) for ch in chapters)
input_tokens = chars_total / CHARS_PER_TOKEN_BY_LANG[lang]
audio_seconds = chars_total / empirical_rate(lang, model)   # con fallback CHARS_PER_AUDIO_SECOND
audio_seconds /= max(0.5, 1 + rate_pct/100)                 # scaling velocità
output_tokens = audio_seconds * AUDIO_TOKENS_PER_SECOND      # 25 tok/s
google_cost_eur = (input_tokens × input_usd/MTok + output_tokens × output_usd/MTok) × USD_EUR_RATE
user_price = compute_user_price_eur(google_cost_eur, model_key)
```

`empirical_rate` viene letto dal `rate_log` (vedi §13) con fallback a `CHARS_PER_AUDIO_SECOND` (15).

#### Risoluzione della lingua per la stima

`lang` governa due variabili sensibili:

1. **`CHARS_PER_TOKEN_BY_LANG[lang]`** — ratio chars/token (4.0 latine, 1.5 zh/ja, 2.0 hi/ar, 3.0 ru). Influenza `input_tokens` (≈1% del costo totale).
2. **Cluster `rate_log`** — `get_empirical_rate(lang, model_key, 0)` pesca i campioni char/sec dal cluster della lingua: influenza `audio_seconds` e quindi `output_tokens` (≈99% del costo totale).

Per questo la lingua **non è quella del libro per metadata, ma quella TTS scelta dall'utente in "Impostazioni audio"** (selettore `#vl` Standard / `#vlPremium` Premium). Priorità di risoluzione negli endpoint `/api/gemini_estimate`, `/api/combined_estimate`, `/api/paypal_create_order_gemini`:

```
lang = (body["lang"] or "").split("-")[0].lower()       # UI override esplicito
    or (info.language or "").split("-")[0].lower()       # metadata libro
    or "it"                                              # fallback
```

Razionali:
- **TXT**: non ha mai metadata di lingua → senza override prevarrebbe sempre "it" (errato).
- **Metadata errati**: capita su EPUB/PDF con `dc:language` mancante o sbagliato; l'utente è la fonte autoritativa.
- **Coerenza pipeline**: la stessa convenzione vale già per `opt_lang` (LLM prompt routing) e `synthesize(lang=...)`. La stima si allinea.

Frontend: la cache-key (`getEstimateCacheKey`) include `lang` e i listener `onchange` di `#vl` / `#vlPremium` richiamano `requestCombinedEstimate()` — il preventivo si aggiorna al volo al cambio lingua.

PayPal: lo stesso `lang` è ripassato a `/api/paypal_create_order_gemini` perche' il server-side amount-check ricalcola la stima con la formula identica; un disallineamento di lingua tra `/api/combined_estimate` (UI-driven) e create-order (default metadata) genererebbe un `amount mismatch` HTTP 400 e blocco pagamento.

---

## 11. Pricing, markup, conversione valuta

Catena di calcolo da costo Google netto a prezzo utente finale:

```
google_cost_eur = google_cost_usd × USD_EUR_RATE
base_eur        = google_cost_eur × (1 + margin_pct/100)
gross_eur       = (base_eur + PAYPAL_FIXED_FEE_EUR) / (1 - PAYPAL_PERCENT_FEE/100)
user_price_eur  = round(gross_eur, 2)
is_free         = user_price_eur < FREE_THRESHOLD_EUR
```

### 11.1 Parametri

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_GEMINI_USD_EUR_RATE` | `0.86` | Cambio statico USD→EUR (aggiornato manualmente) |
| `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR` | `0.34` | Fee fissa PayPal per transazione |
| `ABM_GEMINI_PAYPAL_PERCENT_FEE` | `3.4` | Fee percentuale PayPal (gross-up) |
| `ABM_GEMINI_FREE_THRESHOLD_EUR` | `0.50` | Sotto questa soglia il job è gratis (no addebito) |
| `ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK` | `0.50` | Pricing input flash25 |
| `ABM_GEMINI_25FLASH_OUTPUT_USD_PER_MTOK` | `10.00` | Pricing output flash25 |
| `ABM_GEMINI_25FLASH_MARGIN_PERCENT` | `35.0` | Margine flash25 |
| `ABM_GEMINI_31FLASH_INPUT_USD_PER_MTOK` | `1.00` | Pricing input flash31 |
| `ABM_GEMINI_31FLASH_OUTPUT_USD_PER_MTOK` | `20.00` | Pricing output flash31 |
| `ABM_GEMINI_31FLASH_MARGIN_PERCENT` | `25.0` | Margine flash31 |

I default sono allineati al pricing pubblico Google al momento dello sviluppo. **Aggiornare i valori di pricing**: bumpare le env in `.env` di produzione; il modulo li legge a runtime (no caching), quindi un restart applica i nuovi valori.

### 11.1.1 Semantica di `MARGIN_PERCENT` (IMPORTANTE)

`MARGIN_PERCENT` è il **margine netto operatore**, NON il ricarico apparente all'utente. La formula è costruita in modo che, dopo che PayPal preleva la sua quota, l'operatore intaschi esattamente `google_cost × (1 + margin/100)`. Le fee PayPal vengono scaricate sopra (gross-up) e gonfiano il prezzo finale visibile all'utente.

Esempio numerico con `flash31` (output $20/MTok), `MARGIN_PERCENT=30`, `USD_EUR_RATE=0.86`, `PAYPAL_PERCENT_FEE=3.4`, `PAYPAL_FIXED_FEE_EUR=0.34`, libro di 290 minuti audio:

| Componente | EUR | % vs Google |
|------------|-----|-------------|
| Google cost (1500 tok/min × 290 min × $20/MTok × 0.86) | 7.49 | base |
| + Margine operatore 30% | +2.25 | +30.0% |
| + PayPal 3.4% sul totale (gross-up) | +0.34 | +4.6% |
| + PayPal €0.34 fissa | +0.34 | +4.5% |
| **= Prezzo utente** | **10.42** | **+39.1%** |

Rate per minuto mostrato in UI: ~€0.0359/min. Il "ricarico apparente" 39–40% è atteso e non un bug: 30% finiscono all'operatore netti, ~9% sono fee PayPal che il cliente paga oltre il margine.

Asintoto su libri grandi (fee fissa diluita): `user_per_min → google_per_min × (1 + margin/100) / (1 − paypal_pct/100)` ≈ Google × 1.346 con i parametri di default.

Per ottenere un ricarico utente apparente del 30%: impostare `MARGIN_PERCENT ≈ 21` (così `1.21 / 0.966 ≈ 1.253`, più la fee fissa diluita ≈ 30% complessivo a libro lungo). Trade-off: il margine netto operatore scende dal 30% al 21%.

### 11.2 Free threshold

Quando `user_price_eur < FREE_THRESHOLD_EUR`, `compute_user_price_eur` restituisce `user_price_eur=0.0, is_free=True`: il job parte senza pagamento. Anche `ABM_LLM_FREE_THRESHOLD_EUR` esiste per l'ottimizzazione DeepSeek; il valore tipico è lo stesso (`0.50`) ma sono indipendenti.

---

## 12. Anteprima audio (preview cap)

`/api/preview_audio` genera un campione corto (200–600 char del libro corrente) per far valutare la voce all'utente. Per Gemini c'è un cap anti-abuso:

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_GEMINI_PREVIEW_CAP_PER_DAY` | `3` | Numero max anteprime in finestra (per `client_id` cookie) |
| `ABM_GEMINI_PREVIEW_WINDOW_SEC` | `300` | Lunghezza finestra rolling (default 5 min) |

**Reset**: dopo `PREVIEW_WINDOW_SECONDS` di inattività, il contatore di quel `client_id` torna a 0. Persistenza: `gemini_tts_previews.json`.

`check_preview_cap(client_id)` ritorna `(used, remaining, reset_ts)`. Se `remaining == 0`, l'endpoint risponde `429` con payload `{"error": "preview_cap_reached", "reset_ts": ..., "cap": ..., "remaining": 0}`. Frontend mostra "Hai esaurito le anteprime, riprova tra Nm".

`increment_preview(client_id)` viene chiamato **solo dopo** sintesi riuscita (non si addebita una preview fallita).

**Niente cache chunk al cambio voce**: vedi memoria `feedback_voice_preview_no_cache.md`. La preview viene sempre rigenerata ex-novo, mai servita da cache.

---

## 13. Rate logging (audio / token ratio)

Per migliorare nel tempo l'accuratezza della stima durata audio, ogni preview/job memorizza un campione `(chars, audio_seconds, lang, model_key, rate_step)` in `gemini_tts_rate_log.json`. La stima ex-ante usa la mediana mobile degli ultimi N campioni filtrati per `(lang, model, rate_step)`.

| Env | Default | Significato |
|-----|---------|-------------|
| `ABM_GEMINI_RATE_LOG_MAX_SAMPLES` | `2000` | Rolling buffer max |
| `ABM_GEMINI_RATE_LOG_WINDOW` | `20` | Numero di campioni recenti usati per la mediana |
| `ABM_GEMINI_RATE_LOG_MIN_SAMPLES` | `5` | Sotto questo numero, fallback a `CHARS_PER_AUDIO_SECOND` (15) |

`get_empirical_rate(lang, model_key, rate_step)` applica cascading fallback: `(lang, model, step)` → `(lang, model, 0)` → `(lang, *, 0)` → `CHARS_PER_AUDIO_SECOND`.

`get_rate_log_stats()` espone N campioni, mediane per cluster, copertura. Utile per admin.

---

## 14. Audit & reconciliation

### 14.0 Forensic retention della work_dir

Quando un job Gemini fallisce con refund (qualunque `kind` ∈ `quality` / `quota` / `budget` / `preflight` / `generic`), la sua `work_dir` (`<ABM_DATA_DIR>/<job_id>/`) viene **preservata** per analisi post-mortem invece di essere cancellata dal cleanup automatico.

**Meccanismo**:
1. `generation_engine._admin_alert_gemini_failure()` (linea ~1123) chiama `_write_forensic_marker()` che scrive un file JSON `.forensic_retain.json` nella work_dir:
   ```json
   {
     "retain_until": 1748459337.0,
     "created_at": 1748456337.0,
     "kind": "quality",
     "outcome": "failed_quality_refunded",
     "reason": "1/625 chunk silenziati (0.2%)",
     "job_id": "...",
     "days": 7
   }
   ```
2. `audiobook_app._forensic_marker_protects()` (linea ~8956) controlla `now < retain_until` ed è invocato in:
   - `_cleanup_job()` (status `error` dopo 120s),
   - branch "token-orphan dir" del cleanup loop,
   - branch "orphan output dir",
   - branch "orphan dir" generico.

L'entry in memoria del job viene comunque rimossa (così il loop non si ripropone), ma la dir su disco sopravvive.

**Configurazione**: `ABM_GEMINI_FORENSIC_RETENTION_DAYS` (default 7; 0 disabilita). Vedi `PARAMETRI_CONFIGURAZIONE.md`.

**Endpoint download admin**: `GET /admin/job/<job_id>/forensic.zip` (`audiobook_app.admin_forensic_zip`) — zippa on-the-fly la `work_dir` includendo `chunk_*.pcm`, `_silence.pcm`, output finale, file ABM, eventuali prompt debug se `ABM_GEMINI_DEBUG_PROMPTS=true`. Auth: cookie HttpOnly `abm_admin_session` (set da `/admin/login`) o header `X-Admin-Token` (ABM_ADMIN_TOKEN richiesto). 404 se la dir è scaduta o non esistente, 401 se non autenticato.

**Email admin**: `email_service._admin_notify_gemini_failure()` aggiunge un blocco "Analisi forense" con scadenza retention e link diretto allo ZIP.

### 14.1 Audit file mensile

`gemini_cost_audit_YYYY-MM.jsonl` (uno per mese, JSON-lines). Append-only. Scritto da `_write_gemini_audit()` (`generation_engine.py:1549`) alla fine di ogni job (success, error, cancel). Record:

```json
{
  "ts": "2026-05-19T14:32:11Z",
  "job_id": "...",
  "outcome": "completed|error|cancelled_refunded|cancelled_partial|gemini_overload|budget_exceeded",
  "voice_id": "gemini:flash25:Zephyr",
  "language": "it",
  "rate_pct": 0,
  "rate_step": 0,
  "input_tokens_actual": 123456,
  "output_tokens_actual": 234567,
  "google_cost_eur_actual": 0.7821,
  "user_price_eur_charged": 1.50,
  "should_have_been": 1.49,
  "estimated_eur": 1.45,
  "delta_pct": 2.7,
  "chars_total": 45000,
  "audio_seconds_real": 3010.5,
  "model_key": "flash25",
  "style_instruction": "Calm narrator",
  "chunks_total": 65,
  "chunks_failed": 0,
  "payment_method": "paypal|voucher",
  "payment_token_short": "ABC12345...",
  "payment_source": "combined_optimize_autogen|legacy_fallback|"
}
```

**Campi pagamento (introdotti 2026-05)**:
- `payment_method` — `"paypal"` o `"voucher"` (o vuoto se gratuito/non addebitato).
- `payment_token_short` — primi 8 char del token PayPal/voucher seguiti da `...` (audit-friendly, non sensibile).
- `payment_source` — provenienza del record di pagamento:
  - `"combined_optimize_autogen"` quando il token combined LLM+Gemini viene consumato in `/api/optimize` durante il flusso auto-generate (vedi §14.3 sotto);
  - `"legacy_fallback"` quando `job["payment"]` non è popolato ma `job["payment_amount_eur"]` legacy è > 0 (compatibilità con vecchi flussi);
  - stringa vuota negli altri casi (path nominale `/api/generate`).

**Diagnostic WARNING**: se `outcome == "completed"` e `user_price_eur_charged <= 0` mentre `should_have_been > ABM_GEMINI_FREE_THRESHOLD_EUR`, `_write_gemini_audit()` stampa una riga `[<job_id>] AUDIT WARNING: completed job sopra soglia ma charged=0 ...` su stdout. Sintomo di token non consumato server-side: indagare il flusso di pagamento per quel job_id.

**Lingua registrata (campo `language`)**: derivata da `generation_engine._audit_language(job, info)` (generation_engine.py:~1741) e rappresenta la **lingua TTS scelta dall'utente**, non la lingua metadata del libro. Preferenze in ordine: (1) `job["opt_lang"]` settato da `/api/optimize` quando il body porta `lang`; (2) `job["gen_lang"]` settato da `/api/generate` (branch Gemini, audiobook_app.py:~5930) quando il body porta `lang`; (3) `job["payment"]["gemini_est"]["language"]` — lingua passata a `estimate_book_cost` al booking (catturata in `payment.total_eur` lockato; copre il caso in cui opt_lang/gen_lang non siano stati settati ma il pagamento sì); (4) `info.language` (metadata libro) come ultimo fallback. Esempio: libro arabo (`info.language="ar-sa"`) letto da voce italiana → audit registra `language="it"`. Tutti i callsite (`completed`, `failed_quality_refunded`, `failed_quota_refunded`, `failed_budget_refunded`, `failed_refunded`, `preflight_blocked_refunded`, `cancelled_partial`, `cancelled_refunded`) usano l'helper. **Effetto retroattivo nullo**: i record JSONL già scritti con `ar-sa` non vengono riscritti.

**Rate log empirico (`gemini_tts_rate_log.json`)**: stessa regola del campo `language` dell'audit. `record_rate_sample(lang=...)` viene chiamato dai 3 callsite Gemini con la lingua TTS scelta (`_audit_language(job, info)` nei branch single-file e multi-file di `generation_engine.py`, `request.args["lang"] || job.opt_lang || job.gen_lang || info.language` nel preview di `audiobook_app.py`). Senza questa risoluzione i campioni char/sec di una voce italiana applicata a un EPUB arabo finivano nel cluster `lang=ar` distorcendo `get_empirical_rate("ar", ...)`. Frontend: `_buildPreviewUrl()` (static/js/app.js) aggiunge `&lang=<selLang>` per propagare la scelta UI al server.

**Ricavo effettivo nella UI `/admin/audit-tts`**: i record persistiti conservano sempre `user_price_eur_charged` come importo originario pagato. Prima del rendering, `audiobook_app._apply_cancel_effective()` (audiobook_app.py:3908) calcola tre campi derivati (`_eff_revenue_eur`, `_eff_margin_eur`, `_eff_delta_eur`) applicando questa logica:

- **Outcome di rimborso totale** (`_FULL_REFUND_OUTCOMES`: `failed_refunded`, `failed_quota_refunded`, `failed_budget_refunded`, `failed_quality_refunded`, `preflight_blocked_refunded`, `cancelled_refunded`): ricavo effettivo = `0`, quindi margine = `−google_cost_eur_actual` (perdita pari al costo Google non recuperato).
- **`cancelled_partial`**: ricavo effettivo = `cancel_retained_eur` (quota trattenuta a copertura del consumato).
- **Altri** (`completed`, `running`, ecc.): ricavo effettivo = `user_price_eur_charged`.

Le colonne Prezzo €/Margine €/Margine % della tabella `/admin/audit-tts` usano questi campi `_eff_*`. Gli aggregati in alto (Ricavi/Costo/Margine totali) escludono già a monte gli outcome non-revenue contando solo `completed`, `running`, `cancelled_partial` (linea ~3998).

### 14.3 Combined payment in auto-generate flow

Quando l'utente avvia un job con ottimizzazione AI + voce Gemini e PayPal combined token, il flusso normale è:

1. `/api/optimize` riceve `payment_token` (combined): valida → consuma → popola `job["payment"]` (Gemini portion) → ottimizza testo → al termine chiama `run_generation()` direttamente (bypass `/api/generate`).
2. `_write_gemini_audit()` legge `job["payment"].total_eur` come `user_price_eur_charged`.

**Edge case (fix 2026-05)**: se il costo LLM è sotto `LLM_FREE_THRESHOLD_EUR` (es. 0.08€ per 72k char @ 1.10€/MChar) il blocco di pagamento LLM originale veniva saltato e il token combined non era consumato → audit registrava `charged=0` nonostante PayPal capture confermato.

Fix: `/api/optimize` ora, prima di iniziare l'ottimizzazione, controlla esplicitamente la combinazione `auto_generate + voice Gemini + payment_token` e:
- ricalcola server-side la quota Gemini via `gemini_tts.estimate_book_cost()`,
- valida l'importo contro `_payments[token].amount_eur` con tolleranza 0.05€ (PayPal) o `consume_voucher()` (voucher),
- popola `job["payment"] = {token, total_eur, method, ts, gemini_est, llm_eur, source: "combined_optimize_autogen"}`,
- **persiste lo snapshot pre-LLM in `job["gemini_estimate"] = _est_gemini`** (audiobook_app.py:~7303): è la stima sulla quale è stato lockato `payment["total_eur"]`, quindi deve rimanere l'unica fonte per i campi `*_est` dell'audit JSONL.

`_finalize_optimization_complete()` (`generation_engine.py:~1643`) recupera `job["gemini_estimate"]`: se è già presente (combined-payment path) **non lo sovrascrive**; lo ricalcola solo se assente (es. percorsi free sub-soglia o legacy). Questo evita il disallineamento storico tra `cost_est` (post-LLM) e `user_price_eur_charged` (pre-LLM lockato) che distorceva `delta_pct` e `margin_eur_actual` nei record JSONL del flusso auto-generate.

**Legacy fallback**: se `job["payment"]` resta vuoto ma `job["payment_amount_eur"] > 0` (formato pre-fix), `_write_gemini_audit()` lo usa come `charged` e marca `payment_source="legacy_fallback"`.

### 14.4 Reconciliation mensile

`record_job_completion(model_key, estimated_eur, actual_eur, user_price_eur)` aggiorna `gemini_tts_usage.json` (struttura mensile):

```json
{
  "month": "2026-05",
  "chars_total": ...,
  "input_tokens_total": ...,
  "output_tokens_total": ...,
  "google_cost_eur": ...,
  "user_revenue_eur_net": ...,
  "margin_eur": ...,
  "jobs_completed": ...,
  "estimated_cost_eur_total": ...,
  "actual_cost_eur_total": ...,
  "previews_count": ...,
  "previews_cost_eur": ...
}
```

`get_usage()` espone snapshot a `/admin`. `margin_eur` = `user_revenue_eur_net - google_cost_eur` (al netto delle fee PayPal stimate).

---

## 15. UI integration

### 15.1 Selettore voci

`<optgroup label="Voci PREMIUM">` aggregato nel frontend in `static/js/app.js` quando `gemini_tts.is_available()` ritorna True (esposto via `/api/voices`). All'utente sono presentate le voci nella lingua TTS scelta (dropdown lingua), ordinate F poi M.

Il dropdown lingua del tab Premium (`#vlPremium`) è popolato da `syncLanguageOptions()` filtrando le option di `#vl` per le sole lingue in cui `voices[lang].voices` contiene almeno una voce con id `gemini:`. Conseguenze:

- Le lingue Edge non coperte da Gemini (es. `nb`, `cs`, `sv`, `sw`, ecc.) **non compaiono** nel dropdown Premium — l'utente non viene messo nella condizione di selezionare una lingua a cui non corrisponde nessuna voce Premium.
- Quando l'utente cambia lingua nel tab Standard, il listener di `#vl` propaga il valore a `#vlPremium` **solo se compatibile**; altrimenti `#vlPremium` mantiene la sua selezione corrente (no value reset silenzioso).
- Il set di lingue Premium viene dalla intersezione `(SUPPORTED_UI_LANGUAGES Gemini) ∩ (lingue presenti in /api/voices)`. Aggiungere/rimuovere lingue da `gemini_tts.SUPPORTED_UI_LANGUAGES` si riflette automaticamente nel dropdown senza modifiche JS.
- Il **conteggio voci** mostrato accanto al nome lingua è **per-tab**: in `#vl` (Standard) viene escluso `engine=gemini` (es. `Italiano (4)` = 4 voci Edge); in `#vlPremium` viene riscritto in `syncLanguageOptions()` con il numero di **voci Gemini distinte** (regardless del model, es. `Italiano (30)` = 30 voci uniche). Senza questa separazione, l'elenco Premium mostrava lo stesso conteggio totale del Standard (es. `Italiano (64)` = 4 Edge + 60 entry Gemini), facendo apparire identiche le due liste.

### 15.2 Modali

- **`geminiPayModal`**: mostrato dopo `/api/gemini_estimate` se `user_price_eur > 0`. Pulsanti: "Paga con PayPal" / "Usa voucher" / "Annulla". Equivalente PAID-LLM ma per il TTS Premium.
- **`geminiOverloadModal`**: triggerato da SSE `error_kind=gemini_overload`. Mostra countdown a mezzanotte UTC + messaggio "Servizio in sovraccarico, riprova alle HH:MM". NON addebita.
- **`selTooLargeModal`**: triggerato in due punti distinti, mai prima:
  - `tryGoToAudioSettings()` (panel 2 → panel 3, pulsante "Continue"): cap **Standard** (`max_text_chars`, ~1.5M). A questo step l'utente non ha ancora dichiarato di voler usare Premium, quindi non si applica il cap Gemini.
  - `switchAudioTab('premium')` (click sul tab "Voci PREMIUM" da Standard): cap **Gemini** (`max_gemini_text_chars`, ~800k). Se la selezione lo supera, lo switch viene annullato (`return` prima di mutare `wizardState.audioTab`) e il tab resta su Standard.
  Cosi` chi usa solo voci Standard non viene bloccato a torto da un cap che non lo riguarda, e il warning Gemini compare nel momento esatto in cui l'utente esprime l'intento Premium.

### 15.3 Tab Premium

Tab dedicato (oltre a Standard/Free) che espone:

- Slider velocità (-30%..+30%).
- Selettore voce raggruppato per gender.
- Campo `style_instruction` (textarea, contatore char 300).
- Stima durata + costo live (chiama `/api/gemini_estimate` on-change).

I dettagli tecnici di provider/modello sono **nascosti** all'utente. Vedi `feedback_ui_provider_naming.md`.

### 15.4 Cancel volontario PREMIUM (cancel-floor)

Riferimento spec: `docs/superpowers/specs/2026-05-25-cancel-gemini-floor-design.md`.

Per i job con voce PREMIUM (`gemini:*`) il cancel volontario è soggetto a una policy a due livelli, motivata dal costo non recuperabile speso lato Google al momento del cancel:

**1. Soglia di lock**: `ABM_GEMINI_CANCEL_LOCK_PCT` (default `70`). Oltre questa % di progresso, `/api/cancel/<job_id>` (`audiobook_app.py:5698`) ritorna HTTP 409:

```json
{
  "error": "cancel_locked_progress",
  "progress_pct": 84,
  "lock_pct": 70
}
```

Il client (`static/js/app.js`, costante hardcoded `_GEMINI_CANCEL_LOCK_PCT_CLIENT=70`) disabilita preventivamente il pulsante "Cancel" sopra la stessa soglia via `_updateGeminiCancelLockUI(pct)` con tooltip i18n `cancel_locked_body`. Se per qualunque motivo (race, override DOM) la richiesta arriva al server sopra soglia, il modal info `cancel_locked_title` viene mostrato leggendo `lock_pct` dal body 409. **Allineare** il valore client se si cambia l'env var server.

**2. Computo trattenuto** (`cancel_policy.compute_cancel_retention(provider_cost_eur, payment_method, paid_eur)`, file `cancel_policy.py`):

```
floor    = provider_cost_eur + paypal_fees  (paypal_fees applicate solo se method == "paypal")
paypal_fees = ABM_GEMINI_PAYPAL_FIXED_FEE_EUR + paid * ABM_GEMINI_PAYPAL_PERCENT_FEE / 100
retained = min(paid, max(0, floor))
refund   = paid - retained
```

Il provider cost reale viene letto da `job["gemini_actual"]["google_cost_eur"]` (accumulato chunk-per-chunk in `generation_engine.py`). Pagamento gratuito (sotto `ABM_GEMINI_FREE_THRESHOLD_EUR`) → `paid=0` → `refund=0`, `retained=0`.

**3. Branch `_CancelledError`** (`generation_engine.py:2708+`):

1. Calcola `retained` e `refund` via `compute_cancel_retention`.
2. Encoding best-effort MP3 parziale dai `chunk_*.pcm` accumulati in `work_dir` (usa `audio_utils.pcm_to_mp3` con `inter_chunk_gap_ms` corrente). Se almeno un PCM è non-vuoto, crea token download `<BASE_URL>/dl/<token>/download` con `partial_cancel: True`, `is_gemini: True`.
3. Popola `job["cancel_meta"] = {paid_eur, retained_eur, refund_eur, progress_pct, partial_audio_delivered}` e `job["partial_download_url"]` / `job["partial_download_token"]`.
4. Outcome audit:
   - `cancelled_partial` se `retained > 0` (almeno una quota di costo trattenuto).
   - `cancelled_refunded` se `retained == 0` (job a costo zero — es. cancel istantaneo).
5. Refund tramite `_refund_gemini_payment(job_id, job, "cancelled", retained_eur=retained)`:
   - **Voucher** (metodo `voucher`): riaccredito silenzioso al saldo originale, **nessun codice voucher in email** (vedi `feedback_refund_voucher_policy.md`).
   - **PayPal**: nuovo voucher bonus emesso, codice presente in email.
6. Email `_send_gemini_cancelled_partial_email` (IT-only, `email_service.py:457`) inviata se `email registrata AND partial_audio_delivered`. Subject neutro: `"Audiobook Maker — Generazione annullata, audio parziale disponibile ({refund_eur:.2f} EUR rimborsati)"`. Body include link MP3 parziale, breakdown paid/retained/refund, codice voucher se PayPal. **Nessun riferimento a "Gemini"/provider TTS nel testo** (vedi `feedback_ui_provider_naming.md`).
7. Cleanup mirato: PCM chunks rimossi da `work_dir` ma `output_dir` (contiene MP3 parziale) preservato finché il token vive.

**4. SSE → UI**: il payload `/api/progress/<job_id>` con `status=cancelled` (`audiobook_app.py:5643+`) espone:

```json
{
  "status": "cancelled",
  "cancel_meta": {
    "paid_eur": 2.50, "retained_eur": 0.78, "refund_eur": 1.72,
    "progress_pct": 38, "partial_audio_delivered": true
  },
  "partial_download_url": "https://.../dl/<token>/download"
}
```

Il client renderizza un blocco riepilogo via `_renderGeminiCancelSummary(d)` con pulsante download MP3 parziale (chiave i18n `cancel_partial_dl`) e summary numerico (`cancel_summary` con placeholder `{paid}/{retained}/{refund}`).

**5. Audit**: vedi §14.1 — sui record `cancelled_partial` / `cancelled_refunded` il JSONL contiene anche i 5 campi `cancel_paid_eur`, `cancel_retained_eur`, `cancel_refund_eur`, `cancel_progress_pct`, `cancel_partial_audio_delivered` (popolati da `_write_gemini_audit` leggendo `job["cancel_meta"]`).

**6. Retention output parziale**: i token con `partial_cancel: True` e `is_gemini: True` ereditano la retention PREMIUM estesa (§16 sezione "Caps & retention PREMIUM"); il moltiplicatore no-download `× 2` si applica finché `downloaded_at` non viene settato dal primo `GET /dl/<token>/download`.

**7. Tests**: `test/test_cancel_policy.py` (compute_cancel_retention), `test/test_email_cancel_partial.py` (template email).

---

## 16. Variabili ABM_GEMINI_* (riferimento rapido)

> **Convenzione**: parsing tollerante (virgola decimale OK, whitespace ignorato). Tutte lette **a ogni call** (no cache), quindi modificabili senza restart in dev. In produzione, restart è raccomandato per coerenza tra moduli.

### Autenticazione e Backend

Gemini TTS supporta due backend, selezionabili via `ABM_GEMINI_BACKEND`:

| `ABM_GEMINI_BACKEND` | Env richieste | Note |
|---|---|---|
| `vertex` (consigliato prod) | `ABM_GCP_PROJECT_ID` + `ABM_GOOGLE_CREDENTIALS_FILE` (path al SA JSON, lo stesso usato da Cloud TTS) | Quote a livello progetto GCP, no Tier API. Service account JSON deve avere ruolo `roles/aiplatform.user`. |
| `apikey` (dev / fallback) | `ABM_GEMINI_API_KEY` (chiave Gemini AI Studio) | Quote tiered Google AI Studio (Tier 1/2/3). |
| `auto` (default) o non settato | una delle due sopra | Preferisce Vertex se presente; cade su API key. |

#### Mapping modello → backend

I modelli hanno ID differenti tra Vertex (GA) e API key (legacy "-preview"):

| Modello key | API key ID | Vertex ID | Vertex region default |
|---|---|---|---|
| `flash25` | `gemini-2.5-flash-preview-tts` | `gemini-2.5-flash-tts` (GA) | `global` |
| `flash31` | `gemini-3.1-flash-tts-preview` | `gemini-3.1-flash-tts-preview` | `us-central1` |

Override region per modello: `ABM_VERTEX_LOCATION_FLASH25` / `ABM_VERTEX_LOCATION_FLASH31`.

Vertex client cache: un client `genai.Client(vertexai=True, project, location)` per ogni `(backend, location)` distinta. flash25/flash31 vivono su client separati per via della region diversa.

Resolver implementato in `gemini_tts.py`:
- `_resolve_backend()` — sceglie vertex/apikey
- `_resolve_model_id(model_key)` — ID corretto per backend
- `_resolve_location(model_key)` — region Vertex
- `_get_client(model_key)` — client cached per (backend, location)

#### Env vars autenticazione

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_BACKEND` | `auto` | `vertex` / `apikey` / `auto` — selettore backend. |
| `ABM_GCP_PROJECT_ID` | — | ID progetto GCP per Vertex. Obbligatorio se backend=vertex. |
| `ABM_GOOGLE_CREDENTIALS_FILE` | *(empty)* | Path JSON service account (re-uso da Cloud TTS). Obbligatorio se backend=vertex. |
| `ABM_VERTEX_LOCATION_FLASH25` | `global` | Region Vertex per flash25 (override). |
| `ABM_VERTEX_LOCATION_FLASH31` | `us-central1` | Region Vertex per flash31 (override). |
| `ABM_GEMINI_API_KEY` | *(empty)* | API key Google AI Studio (backend=apikey). |
| `ABM_GEMINI_USE_VERTEX` | `false` | **DEPRECATED** — usa `ABM_GEMINI_BACKEND=vertex`. Conservato per backward-compat. |
| `ABM_GEMINI_VERTEX_CREDENTIALS_FILE` | *(empty)* | **DEPRECATED** — usa `ABM_GOOGLE_CREDENTIALS_FILE` (condiviso con Cloud TTS). |

### Chunking

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_CHUNK_CHARS` | `700` | Cap char per chunk (target qualità) |
| `ABM_GEMINI_MAX_CHUNK_CHARS_<LANG>` | — | Override per lingua (es. `_IT`, `_EN`, `_ZH`) |
| `ABM_GEMINI_MAX_BYTES_PER_CALL` | `8000` | Soft cap byte UTF-8 sul testo puro |
| `ABM_GEMINI_API_HARD_BYTES_CAP` | `8000` | Hard cap byte payload completo |
| `ABM_GEMINI_INTER_CHUNK_GAP_MS` | `100` | Silenzio tra chunk PCM consecutivi (abbassato da 250 in combinazione col trim) |
| `ABM_GEMINI_TRIM_TAIL_MS` | `800` | Cap massimo trim trailing silence per chunk (`0` disabilita) |
| `ABM_GEMINI_TRIM_TAIL_THRESHOLD` | `200` | Soglia ampiezza int16 (0-32767) sotto cui un sample e` "silenzio" |
| `ABM_GEMINI_TEMPERATURE` | `0.75` | Temperature GenerateContentConfig |

### Rate limiting

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_MIN_INTERVAL_FLASH25_MS` | `0` | RPM throttle flash25 (0 = off) |
| `ABM_GEMINI_MIN_INTERVAL_FLASH31_MS` | `0` | RPM throttle flash31 |
| `ABM_GEMINI_RPD_FLASH25` | `0` | RPD cap flash25 (0 = no cap locale) |
| `ABM_GEMINI_RPD_FLASH31` | `0` | RPD cap flash31 |
| `ABM_GEMINI_RPD_SAFETY_RESERVE` | `0` | Riserva sottratta dal cap RPD |

### Retry

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_SYNTH_MAX_ATTEMPTS` | `3` | Tentativi max per call |
| `ABM_GEMINI_RETRY_HONOR_DELAY` | `true` | Rispetta `retryDelay` server-side |
| `ABM_GEMINI_RETRY_MAX_WAIT_SEC` | `60` | Sopra questo, abort invece di sleep |
| `ABM_GEMINI_ABORT_ON_QUOTA` | `true` | Su daily-quota 429, abort immediato |

### Budget

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_DAILY_BUDGET_EUR` | `0.0` | Cap spesa/giorno (0 = off) |
| `ABM_GEMINI_PER_JOB_BUDGET_EUR` | `0.0` | Cap spesa/job (0 = off) |
| `ABM_GEMINI_BUDGET_ALERT_PCT` | `80` | Soglia warning |
| `ABM_GEMINI_BUDGET_HARD_STOP` | `true` | Blocca o solo warn |

### Pricing

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_USD_EUR_RATE` | `0.86` | Cambio statico |
| `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR` | `0.34` | Fee fissa PayPal |
| `ABM_GEMINI_PAYPAL_PERCENT_FEE` | `3.4` | Fee % PayPal |
| `ABM_GEMINI_FREE_THRESHOLD_EUR` | `0.50` | Soglia gratuità |
| `ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK` | `0.50` | Pricing flash25 input |
| `ABM_GEMINI_25FLASH_OUTPUT_USD_PER_MTOK` | `10.00` | Pricing flash25 output |
| `ABM_GEMINI_25FLASH_MARGIN_PERCENT` | `35.0` | Margine flash25 |
| `ABM_GEMINI_31FLASH_INPUT_USD_PER_MTOK` | `1.00` | Pricing flash31 input |
| `ABM_GEMINI_31FLASH_OUTPUT_USD_PER_MTOK` | `20.00` | Pricing flash31 output |
| `ABM_GEMINI_31FLASH_MARGIN_PERCENT` | `25.0` | Margine flash31 |
| `ABM_GEMINI_RATE_MODE` | `prompt` | Modalità billing: `prompt`/`token`/`estimate` |

### Preview

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_PREVIEW_CAP_PER_DAY` | `3` | Max anteprime per finestra |
| `ABM_GEMINI_PREVIEW_WINDOW_SEC` | `300` | Durata finestra rolling |

### Cancel policy PREMIUM

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_CANCEL_LOCK_PCT` | `70` | Soglia % oltre cui `/api/cancel` su job PREMIUM ritorna 409 `cancel_locked_progress`. Range `(0..100)`; valori `<=0` o `>=100` disabilitano il lock. Client `static/js/app.js` allinea hardcoded `_GEMINI_CANCEL_LOCK_PCT_CLIENT=70`. Vedi §15.4. |

### Caps & retention PREMIUM (specifici per voci `gemini:*`)

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_MAX_GEMINI_TEXT_CHARS` | `800000` | Cap caratteri sui capitoli selezionati per job con voce PREMIUM. Più basso del cap standard (`ABM_MAX_TEXT_CHARS=1500000`) per allinearsi a costi/throughput Gemini. Selezione via `_max_text_chars_for_voice(voice)` in `/api/generate`, `/api/optimize`, `/api/optimize_estimate`. Il frontend riceve entrambi i cap nella risposta upload e applica quello giusto in `tryGoToAudioSettings` in base al tab attivo. |
| `ABM_GEMINI_JOB_RETENTION_SEC` | `172800` (48h) | Retention estesa per job/token PREMIUM. Selezione via `_retention_for_job(job)` e `_retention_for_token_info(info)` in audiobook_app.py (cleanup loop, endpoint `/dl/<token>`, `/dl/<token>/abm`, `/dl/<token>/m4b`, `/dl/<token>/download`) e `_retention_for_job(job)` in generation_engine.py (email completion + email .abm). Il token download persiste il flag `is_gemini` derivato da `_is_gemini_voice(job["voice"] or job["opt_voice"])` al momento della creazione. |

#### Protezione no-download per voci PREMIUM (costose)

| Costante | Valore | Note |
|----------|--------|------|
| `GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER` | `2` (hardcoded in `audiobook_app.py`) | Moltiplicatore retention applicato a job/token PREMIUM **mai scaricati**. Default effettivo: `172800s × 2 = 345600s` (96h / 4 giorni). |

**Regola**: se un job/token con voce PREMIUM (`gemini:*`) non ha mai registrato un download (`job["downloaded_at"]` e `token_info["downloaded_at"]` entrambi assenti), la sua cartella output non viene cancellata prima di `2 × GEMINI_FILE_RETENTION_SEC`. Garanzia di sicurezza per utenti che ricevono l'email tardi o non cliccano il link entro la finestra standard di 48h.

**Selezione retention effettiva**:
- `_effective_retention_for_job(job)` (audiobook_app.py): `base × 2` se `_is_gemini_voice(voice|opt_voice) AND not job["downloaded_at"]`; altrimenti `_retention_for_job(job)`.
- `_effective_retention_for_token_info(info)` (audiobook_app.py): `base × 2` se `info["is_gemini"] AND not info["downloaded_at"]`; altrimenti `_retention_for_token_info(info)`.

**Tracking download reali**:
- `_mark_token_downloaded(token_info)` aggiorna `token_info["downloaded_at"]` e persiste via `_save_tokens()`.
- Chiamato in `/dl/<token>/abm`, `/dl/<token>/m4b` (M4B nativo + fallback MP3), `/dl/<token>/download` (optimized_abm, podcast cached/built, audio standard via `_serve_audio_download._do_log()`).
- Gated by `_is_resume_or_probe_request()`: HEAD e Range non contano come download. Idempotente: prima chiamata vince, le successive sono no-op.

**Applicazione nel cleanup loop**:
- Branch `optimized`: `_effective_retention_for_job(job)` dal `opt_completed_at`.
- Branch `done` con email: `_effective_retention_for_job(job)` dal `email_sent_at`.
- Expired tokens scan: `_effective_retention_for_token_info(info) + 300s` dal `created_at`.
- Token merge/load on startup: stessa formula.

**Upper bound senza contesto-job**:
- `_email_marker_protects()` (timestamp branch): `max(EMAIL_FILE_RETENTION_SEC, GEMINI_FILE_RETENTION_SEC × 2) + 300s`.
- Orphan output dirs cleanup: `age > max(EMAIL_FILE_RETENTION_SEC, GEMINI_FILE_RETENTION_SEC × 2)`.

Il marker `.email_sent` e i path di cleanup orfano non hanno accesso a `voice`/`downloaded_at` del job — usano il bound massimo per evitare cancellazione prematura di output PREMIUM non ancora scaricati.

### Rate logging

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_RATE_LOG_MAX_SAMPLES` | `2000` | Buffer rolling massimo |
| `ABM_GEMINI_RATE_LOG_WINDOW` | `20` | N campioni per mediana |
| `ABM_GEMINI_RATE_LOG_MIN_SAMPLES` | `5` | Soglia fallback statico |

---

## 17. Note di tier (illustrative, non normative)

I default in `gemini_tts.py` sono prudenti (free tier friendly). Per **Tier 1+** copiare `.env.gemini.tier1` come base e adattare:

- Abbassare `MIN_INTERVAL_*_MS` (più RPM).
- Alzare `RPD_*` (più richieste/giorno).
- Settare `DAILY_BUDGET_EUR` + `PER_JOB_BUDGET_EUR` (in free tier inutili, RPD è il guard).
- `ABORT_ON_QUOTA=false` (i retry brevi sono utili in Tier 1).

Per **Tier 2/3** (RPD ampio):

- `MIN_INTERVAL_*_MS=0` (no throttle locale).
- `RPD_*=0` (delega all'API).
- Mantenere `DAILY_BUDGET_EUR` come safety net economico.

Per **Free tier**:

- `MIN_INTERVAL_FLASH25_MS=6500`, `MIN_INTERVAL_FLASH31_MS=21000`.
- `RPD_FLASH25=15`, `RPD_FLASH31=15`, `RPD_SAFETY_RESERVE=2`.
- `ABORT_ON_QUOTA=true` (retry inutili: quota giornaliera).

I numeri sopra sono indicativi e vanno verificati sul portale Google AI Studio al cambio di tier.

---

## 18. Disabilitazione del motore

Se nessun backend è configurabile (`ABM_GEMINI_BACKEND=vertex` ma `ABM_GCP_PROJECT_ID`/`ABM_GOOGLE_CREDENTIALS_FILE` mancanti, oppure `ABM_GEMINI_BACKEND=apikey` ma `ABM_GEMINI_API_KEY` mancante, oppure `auto` con entrambe le credenziali assenti), oppure `google-genai` non è installato, `gemini_tts.is_available()` ritorna `False`. Conseguenze:

- `/api/voices` non include voci `gemini:*`.
- Tab Premium nascosto nel frontend.
- `/api/preview_audio` con voice `gemini:*` ritorna `503 gemini_tts_not_configured`.
- `/api/generate` con voice `gemini:*` ritorna `400 gemini_tts_not_configured`.

Il resto dell'app (Edge / Google / DeepSeek) continua a funzionare normalmente.
