# Traduzione libro — Design (branch TRADUZ)

Data: 2026-06-05 · Stato: approvato dall'utente

## Obiettivo

Nuovo percorso utente alternativo al TTS: tradurre il libro caricato (txt/pdf/epub/abm)
da una lingua a un'altra via LLM, con ottimizzazione AI opzionale integrata, pagamento
voucher/PayPal sopra soglia, modalità interattiva o batch (email), download del
risultato (.epub/.abm/.txt) e possibilità di proseguire verso la generazione audio.

## Architettura — libreria condivisa (opzione B)

### `translation_core.py` (nuovo, root repo)

Core estratto da `scripts/translate_abm.py`, importabile sia dal CLI sia dall'app:

- `resolve_backend()` / `make_client_provider()` — backend `vertex | apikey | auto`
  (Vertex con service account GCP condiviso con Gemini TTS; fallback API key
  DeepSeek). Stesse env `ABM_TRANSLATE_*` con fallback `ABM_LLM_*`.
- `split_text_into_chunks(text, max_chars)` — chunking paragraph-aware (default 20k).
- `build_system_prompt(source, target, optimize)` — prompt di traduzione; con
  `optimize=True` integra le regole TTS per-lingua da `prompt_opt_AI/` nello
  **stesso passaggio LLM** (singola chiamata, singolo output).
- `call_llm(...)` — streaming + retry 4× backoff esponenziale (1-8s).
- `translate_titles(...)` — batch JSON, fallback titoli originali su risposta invalida.
- Writer: `write_abm()`, `write_epub()`, **nuovo `write_txt()`** (testo piatto:
  titoli capitolo + corpo, separatore riga vuota).

Refactor per uso in-app (thread-safe, multi-esecuzione):

- Globali `_USAGE` / `_NO_STREAM_OPTIONS` → classe `UsageTracker` per-esecuzione.
- `call_llm()` accetta callback opzionali: `progress_cb(chars_ricevuti)` per SSE,
  `cancel_cb()` per annullo cooperativo (heartbeat).
- Niente `sys.exit()` / `print()` nel core: eccezioni dedicate + logger callback.

### `scripts/translate_abm.py` (refactor)

Diventa CLI sottile: argparse, `parse_abm` locale, report costi a console, chiamate al
core. Comportamento CLI invariato (verifica con `--dry-run`).

### `generation_engine.py`

Nuovo thread di background `run_translation(job_id, ...)` — stesso pattern di
`run_optimization`:

- progress su `jobs[job_id]` (capitolo/chunk/caratteri ricevuti);
- annullo via heartbeat 60s (disattivato in batch mode);
- refund completo su errore/annullo (regole esistenti: voucher → riaccredito,
  PayPal → ordine unmarked / voucher bonus +10% dove previsto);
- email di completamento in batch mode con token di download.

## Backend — endpoint

| Endpoint | Ruolo |
|---|---|
| `GET /api/translate_estimate/<job_id>?target&optimize&chapters` | Stima costo sui capitoli selezionati |
| `POST /api/translate` | Valida, consuma pagamento, occupa slot LLM, spawna `run_translation` |
| `GET /api/translate_progress/<job_id>` | SSE avanzamento |
| `POST /api/translate_adopt/<job_id>` | Adotta la traduzione come libro attivo per il percorso TTS |
| `GET /api/download_translation/<job_id>` | Download interattivo del file tradotto |
| `GET /dl/<token>/translated` | Download da email batch (nuovo kind `translated` nel token) |

### Pricing

```
raw = chars_selezionati / 1M × ABM_TRANSLATE_COST
    + (chars_selezionati / 1M × ABM_LLM_RATE_EUR_PER_MCHAR  se ottimizzazione attiva)

se raw ≤ ABM_LLM_FREE_THRESHOLD_EUR  → gratis
altrimenti                            → dovuto = max(raw, ABM_TRANSLATE_MIN_COST)
```

- Il floor `ABM_TRANSLATE_MIN_COST` si applica al **totale**, solo quando si paga.
- L'ottimizzazione è tariffata a parte (rate LLM esistente) anche se eseguita nella
  stessa chiamata LLM della traduzione.
- Pagamento: voucher o PayPal, stesso flusso di `/api/optimize`; ordine PayPal con
  `purpose=translate`. Consumo a inizio lavoro, refund su errore/annullo.

### Validazioni

- Lingua origine ≠ destinazione; destinazione ∈ lingue voci standard edge-tts
  (stessa fonte di `/api/voices` / `LOCALE_NAMES`).
- Capitoli: si traducono (e pagano) solo i selezionati nel panel2.
- Concorrenza: la traduzione occupa lo slot LLM per client
  (`ABM_MAX_CONCURRENT_LLM_PER_CLIENT`, default 1).

### Nuovi parametri di configurazione

| Variabile | Default | Note |
|---|---|---|
| `ABM_TRANSLATE_COST` | `3.0` | €/M caratteri input; accetta virgola decimale |
| `ABM_TRANSLATE_MIN_COST` | `1.5` | Floor sul totale quando a pagamento; accetta virgola |

Le `ABM_TRANSLATE_*` già definite dallo script (BACKEND, MODEL, API_KEY, API_BASE,
VERTEX_LOCATION, CHUNK_CHARS, MAX_RETRIES, TEMPERATURE, REQUEST_TIMEOUT_SEC)
governano anche l'app. Aggiornare `PARAMETRI_CONFIGURAZIONE.md`.

### Ciclo di vita output

- File tradotto scritto nella job dir (`output_*`), nome = input senza estensione
  (modificabile dall'utente) + estensione formato.
- Retention standard (24h email token); incluso nell'offload cold R2 come gli altri
  output offloadabili.
- Errore su chunk dopo 4 retry → job `error` + refund completo (nessun fallback
  parziale). Fallimento traduzione titoli → titoli originali (non fatale).

## Frontend — percorso traduzione

### Panel2 (capitoli)

- Label `btnExport`: «Esporta .ABM» → «.ABM» (chiave i18n aggiornata).
- Nuovo bottone **«Traduci»** tra export-group e `btnGoToAudio`, badge «new»
  (CSS, angolo alto-dx).

### Navigazione wizard

- Flag `wizMode = 'audio' | 'translate'`.
- Stessi 5 pallini; etichette step 3-4-5 dinamiche in modalità traduzione:
  3 = Configura traduzione, 4 = Elaborazione, 5 = Completato.

### Pannello config traduzione (step 3, nuovo)

- Lingua origine: select lingue edge-tts, precompilata da lingua libro se nota.
- Lingua destinazione: select lingue edge-tts.
- Formato output: `epub | abm | txt`.
- Nome file output: input precompilato (nome file input senza estensione).
- Card ottimizzazione AI: stessa estetica di `aiOptCard` (stesse classi CSS,
  id propri), toggle + info.
- Stima costo + voucher/PayPal: riuso dei componenti esistenti.
- Bottone «Avvia traduzione».

### Step 4 (elaborazione)

- Progress bar alimentata da SSE; area email («inserisci email per notifica»,
  riuso `email-late-area`); bottone annulla.

### Step 5 (completamento)

- Riuso panel5: bottone «Scarica traduzione (EPUB/ABM/TXT)» + scadenza link
- Bottone «Genera audio da questa traduzione» → `POST /api/translate_adopt` →
  capitoli sostituiti in-memory (lingua = destinazione, titoli tradotti), stato
  `analyzed` → l'utente prosegue al pannello voci (step 3 audio).

### i18n

Nuove chiavi in `templates/_fragments/i18n_data.js` + 7 file `i18n/*.json`
(it/en/fr/es/de/zh + download_pages per la pagina `/dl`).

## Test

- Unit: pricing/estimate (soglia free, floor, virgola decimale), `write_txt`,
  `UsageTracker` per-esecuzione, refund su errore/annullo (LLM mock),
  adopt → `analyzed`, validazione lingue.
- CLI: `translate_abm.py --dry-run` invariato post-refactor.

## Fuori scope

- Traduzione con voci PREMIUM/Gemini TTS (non pertinente: la traduzione è solo testo).
- Streaming parziale del risultato all'utente prima del completamento.
- Modifica del formato .abm (il manifest usa i campi già introdotti dallo script:
  `translated_from`, `translated_at`).
