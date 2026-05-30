# Batch Mode per Gemini TTS Premium — Design Spec

**Data**: 2026-05-21
**Stato**: Spec parcheggiata fino a unlock Tier 3 (≈1000 USD cumulativi + 30 giorni dalla prima fattura su Google AI Studio). Implementazione non avviata. Spec pronta per `writing-plans` quando il Tier 3 sarà attivo.
**Autore**: Giuseppe Frangiamone (decision owner) + Claude (drafting)

---

## 1. Contesto

Google offre per i modelli Gemini TTS (`gemini-2.5-flash-preview-tts`, `gemini-3.1-flash-tts`) una **Batch API** che applica uno sconto del 50% sul listino "interactive" in cambio di una SLA fino a 24h. Il sistema è stato verificato disponibile sull'account in Tier 2, con limiti di coda token aggregati:

| Modello | Tier 2 (corrente) | Tier 3 (target unlock) |
|---|---|---|
| Gemini 2.5 Flash TTS | 400K token in coda | **4M** token in coda (verificato da dashboard) |
| Gemini 3.1 Flash TTS | 100K token in coda | **da verificare al momento dell'unlock** — l'utente riporta ≈4M "per entrambi i modelli", ma lo screenshot Tier 3 mostrava solo `gemini-2.5-flash-tts` (4M) e `gemini-2.5-pro-tts` (1M). Default conservativo nella spec: 1M. **Da riallineare in env var quando Tier 3 sarà attivo e la riga `gemini-3.1-flash-tts` sarà osservabile in dashboard.** |
| Max batch jobs simultanei | 100 (entrambi) | 100 (entrambi) |

In Tier 2 i limiti sono troppo stretti per un'app multi-tenant (un libro medio = ~125K token sfora il cap 100K del 3.1 e satura il 30% del 2.5). La feature è quindi **parcheggiata fino a Tier 3**, dove un libro medio occupa ≤3% della capacità e regge il multi-tenant.

L'app AudioBook-Maker oggi genera audio in modalità **sincrona** (engine: edge, google, gemini) con progress bar SSE e pagamento upfront. Questa spec introduce una **modalità asincrona** opt-in che:

- Si attiva solo se l'utente sceglie una voce Premium (`voice_id` con prefisso `gemini:`).
- Offre uno sconto del 40% sul prezzo sync (G batch è -50%, tratteniamo 10pp).
- Differisce la generazione fino a 24h.
- Sostituisce la progress bar con una **monitoring page** dedicata.
- Notifica l'utente per email a launch + completion.
- Non si applica mai alle **anteprime** (sempre sync).
- Si attiva sull'UI solo se c'è **capienza reale** sulla coda Google al momento del check.

---

## 2. Requisiti utente (estratti dalla conversazione)

R1. Bottone "Risparmia" nel pannello stima costo (alto-destra, accanto al totale), visibile **solo per voci Premium**.
R2. Click "Risparmia" apre **popup esplicativa** (caratteristiche batch, sconto %, SLA fino a 24h, cancellabilità).
R3. Aderisci → stima costo si ricalcola al ribasso, bottone si attiva (highlight). Annulla → niente cambia.
R4. Anteprime audio rimangono **sempre sincrone**, mai batch.
R5. Pannello "Riepilogo" del wizard evidenzia la scelta batch fra le opzioni selezionate.
R6. Conferma "Avvia generazione" → modale **email obbligatoria** prima del submit.
R7. Post-launch: **nessuna progress bar**, nessun box email; al loro posto un messaggio "Processo in modalità batch avviato. Clicca qui per monitorare l'avanzamento e per scaricare l'audio al termine: <link>".
R8. Lo stesso link arriva contestualmente per email.
R9. Il link apre una **nuova scheda** su una pagina dove ogni 10 minuti si vede l'eventuale aggiornamento dell'avanzamento con countdown "Aggiornamento avanzamento lavori tra X minuti…".
R10. (Aggiunta esplicita) Il sistema deve **monitorare la soglia token-in-coda** e attivare automaticamente l'opzione batch sull'interfaccia **solo quando c'è capienza**.

---

## 3. Decision Points (confermati)

| ID | Punto | Decisione | Motivazione |
|---|---|---|---|
| **D1** | Sconto utente | **40% off** sul prezzo sync | Google batch = -50%, trasferiamo 40% e tratteniamo 10pp per overhead orchestrazione e rischio refund. |
| **D2** | Payment timing | **Upfront** al click "Avvia" | Coerente con flusso sync. Refund applicato se batch fallisce. Evita user-abbandono dopo 24h. |
| **D3** | Cancellazione | Finestra **5 min** dopo submit (configurable `ABM_GEMINI_BATCH_CANCEL_WINDOW_MIN`). Dopo, Google ha già iniziato processing → cancel = abbandono senza refund (salvo failure). | Google Batch consente cancel solo pre-processing. 5 min copre ripensamenti. |
| **D4** | Refund policy | Riusa asimmetrica esistente: voucher → silenzioso, PayPal → nuovo voucher bonus +10%. Applica su: failure totale, cancel in finestra, partial > `MAX_FAILED_RATIO`. | Memoria utente consolidata. |
| **D5** | Modello 3.1 in batch | **Sempre disponibile su Tier 3** | Cap ~1M token = ~4M char copre libri di qualunque dimensione ragionevole. |
| **D6** | Capacity threshold | Safety reserve **20%** sotto il cap Google. Se `tokens_in_queue + estimated_job_tokens > cap × 0.80` → batch non disponibile. | Buffer per concorrenza fra richieste simultanee. |
| **D7** | Monitor URL security | Token random **32-byte URL-safe** in path, mai esposto su altri endpoint, scade dopo `ABM_GEMINI_BATCH_MAX_AGE_HOURS=72`. | No login (coerente con app), segretezza pratica via token. |
| **D8** | Email schedule | 2 mail success-path: (a) avvio con link monitoraggio, (b) completamento con link download. Su failure: 1 mail con motivazione + voucher (se PayPal). | Minimo necessario, no spam. |
| **D9** | Background poller | Thread Python in-process lanciato a startup. NON cron esterno. | Coerente con thread heartbeat / cleanup esistenti. |
| **D10** | Anteprime in batch | **Mai**. Anteprime sempre sync. | Vincolo esplicito utente (R4). |

---

## 4. Architettura

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                                    UI (SPA)                                  │
│  audio_settings → "Risparmia" btn → popup → recalc estimate → wizard summary │
│  launch confirm → email modal → POST /api/batch/launch                       │
│  post-launch state: monitor link (replaces progress bar)                     │
│                                                                              │
│  monitoring page (separate route /batch/<token>):                            │
│  polling /api/batch/status every 10min + countdown + download btn            │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                         API layer (audiobook_app.py)                         │
│  /api/batch/capacity       GET   pre-flight: capienza coda + libro entra?    │
│  /api/combined_estimate    POST  esteso con flag batch=true                  │
│  /api/batch/launch         POST  submit a Google + email + token monitor     │
│  /api/batch/status/<tok>   GET   stato job per polling monitoring page       │
│  /api/batch/cancel/<tok>   POST  cancel se in finestra                       │
│  /batch/<tok>              GET   template pagina monitoraggio                │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                       Engine layer (batch_engine.py, NEW)                    │
│  submit_batch(job, chunks, voice_id, email) -> batch_record                  │
│  poll_batch(batch_record) -> updated_record                                  │
│  assemble_batch_output(batch_record) -> audio_path                           │
│  batch_poller_loop() (thread, ogni POLL_INTERVAL_MIN)                        │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
┌──────────────────────────────────────────────────────────────────────────────┐
│                              Storage layer                                   │
│  _batch_jobs.json         record per batch (monitor_token, google_id, ...)   │
│  _batch_queue_state.json  contatori token-in-coda per modello                │
└──────────────────────────────────────────────────────────────────────────────┘
                                       │
                                       ▼
                          ┌─────────────────────────┐
                          │  Google Gemini Batch API │
                          │   batches.create/get/    │
                          │   cancel/listFiles       │
                          └─────────────────────────┘
```

---

## 5. Componenti

### 5.1 Nuovi file

**`batch_engine.py`** — orchestratore batch.
Funzioni principali:
- `submit_batch(job: dict, chunks: list[dict], voice_id: str, email: str, payment_ref: dict) -> dict` — costruisce input JSONL (una riga per chunk con prompt + style), uploada via `files.create` o inline, chiama `batches.create`, salva record in `_batch_jobs.json`, aggiorna `_batch_queue_state.json`, restituisce `{monitor_token, google_batch_id, estimated_completion_at, ...}`.
- `poll_batch(batch_record: dict) -> dict` — wrapper `batches.get`, normalizza stato (`QUEUED|PROCESSING|SUCCEEDED|FAILED|CANCELLED|EXPIRED`).
- `download_and_assemble(batch_record: dict) -> dict` — scarica audio chunk dai file di output Google, assembla MP3 (e M4B se richiesto) tramite `audio_utils`. Riusa logica chunk-merge esistente.
- `cancel_batch(monitor_token: str) -> dict` — verifica finestra, chiama `batches.cancel`, dispatch refund.
- `batch_poller_loop()` — thread daemon, scansiona record pendenti, polla Google, transita stati, dispatch email, refund su failure.
- `get_queue_capacity(voice_id: str, estimated_book_tokens: int) -> dict` — ritorna `{available, free_tokens, would_fit}`.

**`templates/batch_monitor.html`** — pagina monitoraggio standalone (full page, NON fragment SPA).
Layout minimal: header con logo/titolo libro, status pill, countdown JS, eventuale lista chunk completati / falliti, bottone download a fine. Auto-refresh via `fetch('/api/batch/status/<token>')` ogni 10 min con countdown visibile.

**`templates/_fragments/batch_popup.html`** — popup esplicativa "Risparmia" + modale email pre-launch.

### 5.2 File modificati

**`audiobook_app.py`**
- Nuovi endpoint listati in §4.
- A startup: `batch_engine.start_poller_thread()` (gated da `ABM_GEMINI_BATCH_ENABLED`).
- Estensione `/api/combined_estimate`: accetta `batch: bool` in payload, se true applica `discount = ABM_GEMINI_BATCH_DISCOUNT_PERCENT/100` su `gemini_eur` (NON su llm_eur).
- Estensione `/api/payment/*` (PayPal): segna `purpose="batch_gemini"` per audit refund.

**`gemini_tts.py`**
- `build_batch_request_lines(chunks: list[dict], voice_id: str, language: str, rate_pct: str) -> list[str]` — emette righe JSONL conformi al formato Google Batch (`{"key": "<chunk_id>", "request": {"contents": [...], "config": {...}}}`).
- `estimate_book_cost(..., batch: bool=False)` — se `batch=True`, applica sconto a `user_price_eur` (formula sotto §10).
- `count_tokens_for_capacity(chunks: list[dict], voice_id: str) -> int` — calcolo token-input atteso per il check `/api/batch/capacity`.

**`payment.py`**
- `consume_payment_for_batch(token: str, job_id: str, monitor_token: str)` — marca pagamento come "in-flight batch".
- `refund_batch(monitor_token: str, reason: str)` — applica refund asimmetrico (voucher silent / PayPal new voucher) coerentemente con sync. Marca `_batch_jobs.json` record con `refunded_at`.

**`email_service.py`**
- `send_batch_launch_email(email, book_title, monitor_url, lang)` — template "Generazione avviata, controlla tra qualche ora".
- `send_batch_complete_email(email, book_title, download_url, monitor_url, lang)` — template "Audio pronto".
- `send_batch_failure_email(email, book_title, reason, voucher_code, lang)` — template failure + (opz) voucher.
- Tutti i template in 6 lingue UI (`i18n/*.json`).

**`static/js/app.js`**
- Funzione `checkBatchCapacity(voiceId, jobId)` chiamata al cambio voce / al render del pannello stima.
- Toggle visibilità bottone "Risparmia" basato su risposta.
- Gestione popup, recalc `combined_estimate` con `batch=true`.
- Modale email pre-launch.
- Stato post-launch: rimpiazza `#progress-section` con `#batch-monitor-link`.
- I18n key nuove (~12-15 stringhe).

**`templates/_fragments/`**
- `_audio_settings.html` (o equivalente): aggiunge slot bottone "Risparmia".
- `_wizard_summary.html`: aggiunge badge "MODALITÀ BATCH" condizionale.
- `_progress.html`: aggiunge variante "batch placeholder".

**`i18n/*.json`** — nuove chiavi (esempio):
```json
{
  "batch.save_button": "Risparmia",
  "batch.popup.title": "Risparmia il {discount}% con la generazione batch",
  "batch.popup.body": "L'elaborazione partirà entro 24h. ...",
  "batch.popup.accept": "Aderisci",
  "batch.popup.cancel": "Annulla",
  "batch.summary.badge": "MODALITÀ BATCH",
  "batch.email.required": "Inserisci la tua email per ricevere il link di monitoraggio",
  "batch.launched.heading": "Processo in modalità batch avviato",
  "batch.launched.link": "Clicca qui per monitorare l'avanzamento e scaricare l'audio al termine",
  "batch.monitor.next_refresh": "Aggiornamento avanzamento lavori tra {min} minuti...",
  "batch.monitor.status.queued": "In coda",
  "batch.monitor.status.processing": "Elaborazione in corso",
  "batch.monitor.status.completed": "Completato",
  "batch.monitor.status.failed": "Fallito"
}
```

### 5.3 Doc da aggiornare (Documentation Sync Rule)

- `md_files/ttsgemini.md` — nuova sezione "Modalità Batch": architettura, env var, flusso, refund.
- `md_files/PARAMETRI_CONFIGURAZIONE.md` — voci `ABM_GEMINI_BATCH_*` con default e file sorgente.
- `md_files/architettura.md` — engine asincrono + thread `batch_poller_loop`.
- `md_files/output_formats.md` — verificare che `output_format` `mp3`/`m4b`/`zip`/`zip_rss` siano supportati anche in batch (sì: assemble usa stessa pipeline).
- `CLAUDE.md` — riga in tabella reference puntatori se rilevante.

---

## 6. API contracts

### 6.1 `GET /api/batch/capacity`

**Query params**: `voice_id` (required), `job_id` (required).

**Response (capacity OK)**:
```json
{
  "available": true,
  "estimated_book_tokens": 125000,
  "free_tokens_in_queue": 3500000,
  "model_key": "flash25",
  "discount_percent": 40
}
```

**Response (capacity exhausted)**:
```json
{
  "available": false,
  "reason": "queue_full",
  "retry_after_minutes": 30,
  "estimated_book_tokens": 125000,
  "free_tokens_in_queue": 50000
}
```

**Response (book troppo grande)**:
```json
{
  "available": false,
  "reason": "book_too_large_for_batch",
  "estimated_book_tokens": 4500000,
  "queue_cap": 4000000
}
```

**Response (voce non Premium)**:
```json
{ "available": false, "reason": "voice_not_eligible" }
```

### 6.2 `POST /api/combined_estimate` (esteso)

**Payload aggiunto**:
```json
{ "batch": true }
```

**Response (con sconto applicato)**:
```json
{
  "gemini_eur": 6.00,
  "gemini_eur_sync": 10.00,
  "batch_applied": true,
  "discount_percent": 40,
  "llm_eur": 0.50,
  "total_eur": 6.50,
  "is_free": false,
  ...
}
```

### 6.3 `POST /api/batch/launch`

**Payload**:
```json
{
  "job_id": "abc123",
  "voice_id": "gemini:flash25:Charon",
  "selected_chapters": [1,2,3],
  "ai_opt_enabled": true,
  "rate": "+0%",
  "output_format": "m4b",
  "email": "user@example.com",
  "payment_token": "pp_xyz...",
  "lang": "it"
}
```

**Response (success)**:
```json
{
  "ok": true,
  "monitor_token": "Vk9sZ3Y3a0...",
  "monitor_url": "https://app.example/batch/Vk9sZ3Y3a0...",
  "google_batch_id": "batches/abc...",
  "estimated_completion_at": "2026-05-22T12:30:00Z",
  "cancel_window_expires_at": "2026-05-21T12:35:00Z"
}
```

**Response (errori)**: `400` payload invalido, `402` pagamento mancante/non valido, `409` capacity exhausted nel frattempo, `500` errore submit Google.

### 6.4 `GET /api/batch/status/<monitor_token>`

**Response**:
```json
{
  "status": "processing",          
  "book_title": "Il nome della rosa",
  "submitted_at": "2026-05-21T12:30:00Z",
  "estimated_completion_at": "2026-05-22T12:30:00Z",
  "progress_pct": 47,
  "chunks_done": 47,
  "chunks_total": 100,
  "download_url": null,
  "cancellable": false,
  "next_refresh_in_seconds": 600
}
```

Su `status="completed"`: `download_url` populato, `progress_pct=100`.
Su `status="failed"`: aggiunto `failure_reason` + `refund_info` (voucher_code se PayPal).

### 6.5 `POST /api/batch/cancel/<monitor_token>`

**Response**:
```json
{
  "ok": true,
  "refund": {
    "method": "voucher_restore" | "paypal_new_voucher",
    "voucher_code": null | "BONUS-XYZ",
    "amount_eur": 6.00,
    "user_visible": false | true
  }
}
```

Semantica:
- `method="voucher_restore"`: il pagamento originale era un voucher; il saldo è stato riaccreditato silenziosamente. `voucher_code=null`, `user_visible=false` (UI non mostra il codice perché non c'è codice nuovo da comunicare).
- `method="paypal_new_voucher"`: il pagamento originale era PayPal; emesso un nuovo voucher bonus (+10%). `voucher_code` populato, `user_visible=true`, il codice è anche inviato per email.

Errori: `403` fuori finestra, `404` token non trovato, `409` già completato/cancellato.

### 6.6 `GET /batch/<monitor_token>`

Restituisce HTML `templates/batch_monitor.html`. Token validato; se scaduto/inesistente → 404 con messaggio user-friendly.

---

## 7. Data flow / state machine

**Batch record states**:

```
        ┌──────────┐
        │ SUBMITTING│  (transitorio, durante chiamata batches.create)
        └──────────┘
              │
              ▼
        ┌──────────┐
        │  QUEUED  │  (in coda Google, cancellabile)
        └──────────┘
              │
              ▼
        ┌────────────┐
        │ PROCESSING │  (Google sta elaborando, NON cancellabile)
        └────────────┘
              │
   ┌──────────┼──────────┬──────────┐
   ▼          ▼          ▼          ▼
┌───────┐ ┌──────┐ ┌─────────┐ ┌─────────┐
│SUCCESS│ │FAILED│ │CANCELLED│ │ EXPIRED │
└───────┘ └──────┘ └─────────┘ └─────────┘
   │         │         │           │
   ▼         ▼         ▼           ▼
┌──────────────────────────────────────┐
│  ASSEMBLED / REFUNDED (terminal)     │
└──────────────────────────────────────┘
```

Mapping stati Google → interno: vedere doc Google Batch API. `EXPIRED` = oltre 48h senza completion → trattato come `FAILED` con refund automatico.

**Schema `_batch_jobs.json`** (record):
```json
{
  "monitor_token": "Vk9sZ3Y3a0...",
  "client_id": "abm_cid_xyz",
  "job_id": "abc123",
  "google_batch_id": "batches/proj/abc...",
  "book_title": "Il nome della rosa",
  "email": "user@example.com",
  "voice_id": "gemini:flash25:Charon",
  "model_key": "flash25",
  "language": "it",
  "output_format": "m4b",
  "chunks_total": 100,
  "estimated_input_tokens": 125000,
  "selected_chapters": [1,2,3],
  "ai_opt_enabled": true,
  "submitted_at": "2026-05-21T12:30:00Z",
  "cancel_window_expires_at": "2026-05-21T12:35:00Z",
  "estimated_completion_at": "2026-05-22T12:30:00Z",
  "status": "processing",
  "progress_pct": 47,
  "chunks_done": 47,
  "chunks_failed": 0,
  "download_url": null,
  "audio_output_path": null,
  "payment_token": "pp_xyz...",
  "payment_type": "paypal",
  "payment_amount_eur": 6.50,
  "refunded_at": null,
  "refund_voucher_code": null,
  "failure_reason": null,
  "completed_at": null,
  "expires_at": "2026-05-24T12:30:00Z"
}
```

**Schema `_batch_queue_state.json`**:
```json
{
  "flash25": {
    "tokens_in_queue": 380000,
    "active_batch_count": 3,
    "updated_at": "2026-05-21T12:30:00Z"
  },
  "flash31": {
    "tokens_in_queue": 95000,
    "active_batch_count": 1,
    "updated_at": "2026-05-21T12:30:00Z"
  }
}
```

Lo stato si aggiorna:
- **+tokens** al submit (`batch_engine.submit_batch`).
- **−tokens** alla transizione `PROCESSING→{SUCCESS|FAILED|CANCELLED}` (Google libera la coda al termine effettivo).
- Reconciliation periodico: ogni N giri del poller, listano i batch attivi su Google e riallineano il contatore locale (drift recovery).

---

## 8. UI changes (dettaglio)

### 8.1 Pannello "Stima costo" (audio settings)

```
┌──────────────────────────────────────────────────┐
│  Costo stimato: 10.00 €          [💰 Risparmia ▼]│  ← bottone visibile solo
│  Audio: 8h 30m                                   │     se voice Premium +
│  ─────────────────────                           │     capacity OK
│  Voce: gemini:flash25:Charon                     │
└──────────────────────────────────────────────────┘
```

Click "Risparmia" → popup:
```
┌────────────────────────────────────────────────────────┐
│  Risparmia il 40% con la generazione batch             │
│                                                        │
│  ✓ Sconto: 10.00 € → 6.00 €                            │
│  ✓ Attesa fino a 24 ore (in media molto meno)          │
│  ✓ Ricevi una mail con un link per monitorare il lavoro│
│  ✓ Cancellabile entro 5 minuti dall'avvio              │
│                                                        │
│  L'elaborazione avviene in background. Puoi chiudere   │
│  la finestra: ti avvisiamo per email quando l'audio    │
│  è pronto.                                             │
│                                                        │
│              [ Annulla ]  [ Aderisci ]                 │
└────────────────────────────────────────────────────────┘
```

Aderisci → popup chiude, bottone diventa `[💰 Risparmia ✓ ATTIVO]` (highlight verde), stima si aggiorna.
Annulla → popup chiude, nessuna modifica.

### 8.2 Pannello "Riepilogo" wizard

```
┌──────────────────────────────────────────────────┐
│  Riepilogo scelte                                │
│  ─────────────────                               │
│  Voce:           gemini:flash25:Charon           │
│  Velocità:       +0%                             │
│  Ottimizzazione: Attiva                          │
│  Output:         M4B con cover                   │
│  Capitoli:       Tutti (47)                      │
│  Modalità:       [🕐 BATCH — sconto 40%]         │  ← badge condizionale
│  Costo:          6.00 €                          │
└──────────────────────────────────────────────────┘
```

### 8.3 Modale email pre-launch

Trigger: click "Avvia generazione" con batch=true.
```
┌────────────────────────────────────────────────────┐
│  Inserisci la tua email                            │
│                                                    │
│  La generazione batch può richiedere fino a 24h.   │
│  Ti invieremo un link per monitorare il lavoro     │
│  e un secondo link per scaricare l'audio quando    │
│  sarà pronto.                                      │
│                                                    │
│  [_______________________________]                 │
│                                                    │
│              [ Annulla ]  [ Avvia ]                │
└────────────────────────────────────────────────────┘
```

Validazione email regex base; se invalida, errore inline.

### 8.4 Stato post-launch

Dopo POST `/api/batch/launch` success, il pannello `#progress-section` viene rimpiazzato da:
```
┌────────────────────────────────────────────────────┐
│  ✓ Processo in modalità batch avviato              │
│                                                    │
│  Clicca qui per monitorare l'avanzamento e per     │
│  scaricare l'audio al termine:                     │
│                                                    │
│  → https://app.example/batch/Vk9sZ3Y3a0...         │
│                                                    │
│  Lo stesso link è stato inviato a user@example.com │
└────────────────────────────────────────────────────┘
```

Il link è `target="_blank"`. Nessuna progress bar, nessun box email, nessun pulsante "Annulla" diretto (la cancel si fa dalla monitoring page).

### 8.5 Monitoring page (`/batch/<token>`)

```
┌──────────────────────────────────────────────────────┐
│  AudioBook-Maker                                     │
│                                                      │
│  Libro: Il nome della rosa                           │
│  Voce: gemini:flash25:Charon                         │
│                                                      │
│  Stato: [🔄 ELABORAZIONE IN CORSO]                   │
│  Avanzamento: ████████░░░░░░░░ 47%                   │
│  Chunk completati: 47 / 100                          │
│                                                      │
│  Avviato: 21/05/2026 14:30                           │
│  Completamento stimato: 22/05/2026 ~14:30            │
│                                                      │
│  ⏱  Aggiornamento avanzamento lavori tra 7 minuti... │
│                                                      │
│  [ Cancella ]   ← visibile solo entro 5 min          │
└──────────────────────────────────────────────────────┘
```

A fine processo (`status=completed`):
```
│  Stato: [✓ COMPLETATO]                               │
│                                                      │
│  [ 📥 Scarica audio (M4B, 245 MB) ]                  │
```

Su `status=failed`:
```
│  Stato: [✗ FALLITO]                                  │
│  Motivo: <reason>                                    │
│  ← Rimborso applicato. Voucher BONUS-XYZ inviato     │
│    alla tua email.                                   │
```

JS: setInterval ogni 10 min `fetch('/api/batch/status/<token>')`, countdown visivo decrementa ogni secondo.

---

## 9. Background poller

**Thread**: `batch_engine.batch_poller_loop()` lanciato a startup da `audiobook_app.py` se `ABM_GEMINI_BATCH_ENABLED=true`.

**Ciclo**:
```python
def batch_poller_loop():
    while not _shutdown_event.is_set():
        try:
            records = _load_pending_batches()
            for rec in records:
                if rec["status"] in ("queued", "processing"):
                    new_state = poll_batch(rec)
                    if new_state["status"] == "succeeded":
                        download_and_assemble(rec)
                        send_complete_email(rec)
                        rec["status"] = "completed"
                    elif new_state["status"] in ("failed", "expired"):
                        refund_batch(rec["monitor_token"], reason=new_state.get("reason"))
                        send_failure_email(rec)
                        rec["status"] = "failed"
                    _save_record(rec)
                    _update_queue_state()
            _cleanup_expired_records()
        except Exception as e:
            print(f"[batch_poller] error: {e}")
        _shutdown_event.wait(POLL_INTERVAL_MIN * 60)
```

**Reconciliation**: ogni N giri (es. N=6, cioè ogni ora), il poller chiama `batches.list()` su Google per riconciliare `_batch_queue_state.json` con lo stato reale (drift recovery se thread era down al momento di un completion).

**Crash recovery**: a startup, `batch_engine.start_poller_thread()` esegue prima un reconciliation pass per allineare lo stato locale con Google.

**Anti-zombie**: record con `submitted_at < now - MAX_AGE_HOURS` (default 72h) senza completion → forzato a `failed` con refund.

---

## 10. Pricing formula

### 10.1 Sync (esistente, baseline)
```
user_price_eur_sync =
  ((input_tokens * INPUT_USD_PER_MTOK + output_tokens * OUTPUT_USD_PER_MTOK) / 1e6)
  * USD_EUR_RATE
  * (1 + MARGIN_PERCENT/100)
  + PAYPAL_FIXED_FEE
  + price * (PAYPAL_PERCENT_FEE/100)
```

### 10.2 Batch (nuovo)
```
google_cost_usd_batch = google_cost_usd_sync * 0.5    # sconto Google 50%
user_price_eur_batch = user_price_eur_sync * (1 - DISCOUNT_PERCENT/100)
                     = user_price_eur_sync * 0.6        # con D1=40%
```

**Nota margine effettivo**: il nostro costo cala del 50%, il prezzo utente cala del 40% → margine relativo aumenta di 10pp rispetto al sync. Coerente con D1.

### 10.3 LLM (ottimizzazione testo)
Lo step LLM **non è scontato** in modalità batch (non passa da Google Batch API, è un provider LLM separato). `combined_estimate` con `batch=true` applica sconto **solo** sulla quota Gemini.

---

## 11. Capacity check logic

```python
def get_queue_capacity(voice_id: str, estimated_book_tokens: int) -> dict:
    if not voice_id.startswith("gemini:"):
        return {"available": False, "reason": "voice_not_eligible"}

    model_key = voice_id.split(":")[1]  # "flash25" or "flash31"
    cap = ENV[f"ABM_GEMINI_BATCH_QUEUE_MAX_TOKENS_{model_key.upper()}"]
    safety = ENV["ABM_GEMINI_BATCH_QUEUE_SAFETY_PERCENT"] / 100
    effective_cap = cap * (1 - safety)   # es. 4M * 0.80 = 3.2M

    state = _load_queue_state()
    tokens_used = state.get(model_key, {}).get("tokens_in_queue", 0)
    free = effective_cap - tokens_used

    if estimated_book_tokens > effective_cap:
        return {"available": False, "reason": "book_too_large_for_batch",
                "estimated_book_tokens": estimated_book_tokens,
                "queue_cap": effective_cap}

    if estimated_book_tokens > free:
        # stima retry: tempo medio completion + 10min margine
        return {"available": False, "reason": "queue_full",
                "retry_after_minutes": 30,
                "estimated_book_tokens": estimated_book_tokens,
                "free_tokens_in_queue": int(free)}

    # check per-user cap
    client_id = _get_client_id_from_request()
    pending = _count_pending_batches_for_client(client_id)
    if pending >= ENV["ABM_GEMINI_BATCH_PER_USER_MAX_PENDING"]:
        return {"available": False, "reason": "user_quota_exceeded"}

    return {"available": True,
            "free_tokens_in_queue": int(free),
            "estimated_book_tokens": estimated_book_tokens,
            "model_key": model_key,
            "discount_percent": ENV["ABM_GEMINI_BATCH_DISCOUNT_PERCENT"]}
```

**Race condition**: due richieste concorrenti che superano insieme la capienza. Mitigazione: in `/api/batch/launch`, ri-eseguire il capacity check **dopo** aver acquisito un lock sul file `_batch_queue_state.json` (`filelock` o `fcntl`/`msvcrt`). Se al secondo check non c'è più capienza → 409 con `reason=queue_full_race`, frontend mostra "spiacenti, la coda si è riempita mentre confermavi. Riprova fra qualche minuto o procedi in modalità sincrona".

---

## 12. Error handling & refund

| Evento | Stato batch | Refund | Email |
|---|---|---|---|
| Submit fallisce (Google API error) | mai creato | refund completo (pagamento non consumato) | nessuna (utente vede errore inline) |
| `QUEUED` → cancel utente entro finestra | `cancelled` | refund completo asimmetrico | email cancel confirmation |
| `PROCESSING` → user prova cancel | rifiutato | nessuno | nessuna |
| `FAILED` da Google | `failed` | refund completo asimmetrico | failure email + voucher (se PayPal) |
| `EXPIRED` (>72h senza completion) | `failed` | refund completo asimmetrico | failure email + voucher |
| `SUCCEEDED` ma chunks_failed > MAX_FAILED_RATIO | `partial` | refund **parziale** (% chunks falliti) | warning email con audio parziale + voucher partial |
| `SUCCEEDED` clean | `completed` | nessuno | completion email con download link |

**Refund asimmetrico** (riusa `payment.py`):
- Voucher payment → ripristina saldo voucher silenzioso.
- PayPal payment → genera nuovo voucher bonus +10% del valore, codice inviato in failure email.

---

## 13. Env vars (sezione completa)

| Nome | Default | Scope | Descrizione |
|---|---|---|---|
| `ABM_GEMINI_BATCH_ENABLED` | `false` | startup | Master switch. Se false, endpoint `/api/batch/*` rispondono 404 e thread poller non parte. |
| `ABM_GEMINI_BATCH_DISCOUNT_PERCENT` | `40` | runtime | % sconto applicato all'utente sul prezzo Gemini sync. |
| `ABM_GEMINI_BATCH_QUEUE_MAX_TOKENS_FLASH25` | `4000000` | runtime | Cap token-in-queue su 2.5 Flash TTS (Tier 3). |
| `ABM_GEMINI_BATCH_QUEUE_MAX_TOKENS_FLASH31` | `1000000` | runtime | Cap token-in-queue su 3.1 Flash TTS. **Default conservativo da verificare al momento dell'unlock Tier 3** (vedi §1). Se la dashboard mostrerà 4M, alzare l'env var di conseguenza. |
| `ABM_GEMINI_BATCH_QUEUE_SAFETY_PERCENT` | `20` | runtime | % di buffer riservato sotto il cap effettivo. |
| `ABM_GEMINI_BATCH_POLL_INTERVAL_MIN` | `10` | runtime | Frequenza polling stato batch da parte del thread. |
| `ABM_GEMINI_BATCH_MONITOR_REFRESH_MIN` | `10` | runtime | Frequenza refresh lato monitoring page (countdown UI). |
| `ABM_GEMINI_BATCH_CANCEL_WINDOW_MIN` | `5` | runtime | Minuti di finestra cancellazione dopo submit. |
| `ABM_GEMINI_BATCH_MAX_AGE_HOURS` | `72` | runtime | Record batch più vecchi vengono forzati a `failed` + refund. |
| `ABM_GEMINI_BATCH_PER_USER_MAX_PENDING` | `2` | runtime | Cap anti-abuso: max batch pendenti per `abm_cid`. |
| `ABM_GEMINI_BATCH_RECONCILE_EVERY_N_POLLS` | `6` | runtime | Frequenza reconciliation con Google `batches.list()`. |

---

## 14. Sicurezza & privacy

- **Monitor token**: 32 byte random URL-safe (es. `secrets.token_urlsafe(32)`). Non riutilizzato fra job. Scade dopo `MAX_AGE_HOURS`.
- **Email**: validata regex, mai loggata in chiaro (hash SHA-256 in log per debug audit). Conservata in `_batch_jobs.json` finché record non scade.
- **GDPR**: record batch scaduti vengono purged dal cleanup ogni 24h. Email rimossa con il record.
- **Rate limit**: capacity check per IP a max 30 req/min (anti-probe). Launch endpoint a max 3 req/min per client_id.
- **Audit**: ogni evento batch logged in `gemini_cost_audit.py` con purpose=`batch_gemini`.

---

## 15. Test plan (high-level)

| Categoria | Test |
|---|---|
| **Unit** | `batch_engine.submit_batch` mock Google, verifica JSONL ben formato. `get_queue_capacity` con stati edge (full / book-too-large / per-user-cap). Pricing batch matches discount formula. |
| **Integration** | Full flow su mock Google: submit → poll → success → assemble → email. Idem per failure path + refund. |
| **Race conditions** | Due `/api/batch/launch` concorrenti su capienza marginale: solo uno deve passare, l'altro 409. |
| **Crash recovery** | Stop processo durante PROCESSING, restart → reconciliation legge stato da Google e aggiorna. |
| **UI** | Bottone "Risparmia" compare/scompare al cambio voce / al cambio job size. Popup + recalc estimate. Email modal validation. Post-launch state. Monitoring page polling + countdown. |
| **i18n** | Tutte le nuove chiavi presenti in 6 lingue. `test_i18n_completeness` esteso. |
| **Email** | Mock SMTP, verifica template 3 lingue almeno (IT/EN/FR). Link monitor + download correttamente populated. |
| **Money critical stress** | (estende `test_money_critical_stress`) cancel-during-window, failure-mid-processing, partial-success refund. |

---

## 16. Out of scope (esplicito)

- **Anteprime in batch**: mai. R4.
- **Engine edge / google in batch**: solo Gemini Premium. Edge è gratis, Google TTS non ha batch API equivalente nel nostro flusso.
- **Resubmit automatico** su failure: l'utente è notificato, decide se rilanciare manualmente in sync con il refund.
- **Multiple voice/multi-language per batch**: stesse regole del sync (una voce per job).
- **Notifica push browser**: solo email (no service worker, no WebSocket dedicato).
- **Storico batch dell'utente**: nessuna lista accessibile dall'app; il monitor token è il solo accesso. (Future enhancement possibile, fuori scope qui.)
- **API esterna per terzi**: gli endpoint `/api/batch/*` sono per la SPA, non documentati pubblicamente.

---

## 17. Decomposizione implementativa suggerita (preview per writing-plans)

L'implementazione si presta a 4 stream paralleli + 1 integration:

1. **Backend engine**: `batch_engine.py`, estensione `gemini_tts.py`, storage files, thread.
2. **Backend API**: nuovi endpoint in `audiobook_app.py`, estensione `combined_estimate`, capacity logic.
3. **Frontend**: `app.js` + fragment, popup, recalc, post-launch state, monitoring page template.
4. **Email & i18n**: `email_service.py` template + nuove chiavi in 6 lingue.
5. **Integration & tests**: pipeline test end-to-end, money critical stress estensione, doc sync (3 file md).

Dettaglio sequenze, dipendenze, e blockers li definiamo in `writing-plans` quando si parte.

---

## 18. Decision log (post-spec, da aggiornare durante implementation)

| Data | Decisione | Note |
|---|---|---|
| 2026-05-21 | Spec parcheggiata fino a Tier 3 unlock | D1-D10 confermati dall'utente. |
| - | - | - |

---

**Fine spec.**
