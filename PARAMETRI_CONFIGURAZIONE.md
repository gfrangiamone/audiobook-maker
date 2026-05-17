# Parametri di Configurazione - Audiobook Maker

Raccolta completa di tutti i parametri di funzionamento dell'applicazione, con indicazione del valore attuale/default, del file sorgente e della riga.

---

## 1. Variabili d'ambiente (prefisso `ABM_`)

Parametri configurabili dall'esterno tramite variabili d'ambiente sul server.

| Parametro | Valore default | File | Riga |
|-----------|---------------|------|------|
| `ABM_DATA_DIR` | `"/var/lib/audiobook-maker/data"` | `audiobook_app.py` | 77 |
| `ABM_SMTP_HOST` | `""` (vuoto) | `audiobook_app.py` | 91 |
| `ABM_SMTP_PORT` | `587` | `audiobook_app.py` | 92 |
| `ABM_SMTP_USER` | `""` (vuoto) | `audiobook_app.py` | 93 |
| `ABM_SMTP_PASS` | `""` (vuoto) | `audiobook_app.py` | 94 |
| `ABM_SMTP_FROM` | `SMTP_USER` oppure `"noreply@audiobook-maker.com"` | `audiobook_app.py` | 95 |
| `ABM_BASE_URL` | `""` (vuoto, con rstrip di `/`) | `audiobook_app.py` | 96 |
| `ABM_ADMIN_EMAIL` | `""` (vuoto, se vuoto il digest admin e' disabilitato) | `audiobook_app.py` | 103 |
| `ABM_MAX_CONCURRENT_PER_CLIENT` | `2` | `audiobook_app.py` | 112 |
| `ABM_DEEPSEEK_API_KEY` | `""` (vuoto, se vuoto l'ottimizzazione testo AI è disabilitata) | `audiobook_app.py` | 63 |
| `ABM_DEEPSEEK_MODEL` | `"deepseek-chat"` | `audiobook_app.py` | 94 |
| `ABM_MAX_CONCURRENT_LLM_PER_CLIENT` | `1` | `audiobook_app.py` | 152 |
| `ABM_GOOGLE_CREDENTIALS_FILE` | `""` (vuoto, oppure path al file JSON service account Google Cloud) | `google_tts.py` | 69 |
| `GOOGLE_APPLICATION_CREDENTIALS` | `""` (alternativa standard Google SDK al parametro sopra) | `google_tts.py` | 70 |
| `ABM_GOOGLE_TTS_MONTHLY_LIMIT` | `1000000` (1M caratteri/mese, free tier Google Cloud TTS) | `google_tts.py` | 33 |
| `ABM_PAYPAL_CLIENT_ID` | `""` (PayPal REST API client ID per pagamenti LLM; con auto-strip whitespace) | `audiobook_app.py` | 104 |
| `ABM_PAYPAL_SECRET` | `""` (PayPal REST API secret; con auto-strip whitespace) | `audiobook_app.py` | 105 |
| `ABM_PAYPAL_MODE` | `"sandbox"` (sandbox\|live) | `audiobook_app.py` | 106 |
| `ABM_LLM_RATE_EUR_PER_MCHAR` | `1.10` (EUR per 1M char input, include markup + fee PayPal) | `audiobook_app.py` | 108 |
| `ABM_LLM_FREE_THRESHOLD_EUR` | `0.50` (EUR sotto i quali l'ottimizzazione è gratuita e liberamente testabile) | `audiobook_app.py` | 109 |
| `ABM_VOUCHER_EXPIRY_DAYS` | `180` (giorni validità buono rimborso, = 6 mesi) | `audiobook_app.py` | 110 |
| `ABM_VOUCHER_BONUS_PERCENT` | `10` (% maggiorazione buono vs pagamento originale) | `audiobook_app.py` | 111 |
| `ABM_PAYMENT_RETENTION_DAYS` | `730` (24 mesi retention dati pagamento GDPR/fiscale) | `audiobook_app.py` | 112 |
| `ABM_JOB_RETENTION_SEC` | `64800` (18 ore, retention elaborazioni completate e token download) | `audiobook_app.py` | 274 |

---

## 2. Configurazione Flask

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `MAX_CONTENT_LENGTH` | da `ABM_MAX_UPLOAD_MB` (default `50` MB) | `audiobook_app.py` | 163 |
| `ABM_MAX_TEXT_CHARS` | `1500000` (≈ 75-150 MB audio) | `audiobook_app.py` | 3604 |

---

## 3. Costanti applicative principali (`audiobook_app.py`)

### 3.1 Percorsi e directory

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `SCRIPT_DIR` | `Path(__file__).parent.resolve()` | `audiobook_app.py` | 33 |
| `UPLOAD_DIR` | `Path(_DATA_DIR)` (derivato da `ABM_DATA_DIR`) | `audiobook_app.py` | 78 |
| `_TOKENS_FILE` | `UPLOAD_DIR / "_download_tokens.json"` | `audiobook_app.py` | 157 |

### 3.2 Email e notifiche

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `SMTP_HOST` | da `ABM_SMTP_HOST` | `audiobook_app.py` | 91 |
| `SMTP_PORT` | da `ABM_SMTP_PORT` (int) | `audiobook_app.py` | 92 |
| `SMTP_USER` | da `ABM_SMTP_USER` | `audiobook_app.py` | 93 |
| `SMTP_PASS` | da `ABM_SMTP_PASS` | `audiobook_app.py` | 94 |
| `SMTP_FROM` | da `ABM_SMTP_FROM` o fallback | `audiobook_app.py` | 95 |
| `BASE_URL` | da `ABM_BASE_URL` (con rstrip) | `audiobook_app.py` | 96 |
| `EMAIL_FILE_RETENTION_SEC` | da `ABM_JOB_RETENTION_SEC` (default `64800` = 18 ore) | `audiobook_app.py` | 97 |
| `ADMIN_EMAIL` | da `ABM_ADMIN_EMAIL` | `audiobook_app.py` | 103 |
| `ADMIN_DIGEST_INTERVAL_SEC` | `86400` (24 ore) | `audiobook_app.py` | 104 |

### 3.3 Rate limiting e tracking client

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `MAX_CONCURRENT_PER_CLIENT` | da `ABM_MAX_CONCURRENT_PER_CLIENT` (default `2`) | `audiobook_app.py` | 112 |
| `MAX_CONCURRENT_LLM_PER_CLIENT` | da `ABM_MAX_CONCURRENT_LLM_PER_CLIENT` (default `1`) | `audiobook_app.py` | 152 |
| `_CLIENT_COOKIE_NAME` | `"abm_cid"` | `audiobook_app.py` | 115 |
| `_CLIENT_COOKIE_MAX_AGE` | `31536000` (1 anno in secondi) | `audiobook_app.py` | 116 |

### 3.6.1 PayPal (pagamenti ottimizzazione LLM)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `PAYPAL_API_BASE` | `https://api-m.sandbox.paypal.com` o `https://api-m.paypal.com` (auto da `ABM_PAYPAL_MODE`) | `audiobook_app.py` | 107 |
| `_paypal_token_cache` | Dict in-memory per cache OAuth2 token (`access_token`, `expires_at`) | `audiobook_app.py` | 115 |
| `_payments` | Dict in-memory `{order_id: {...}}` persistito su `_payments.json` | `audiobook_app.py` | — |
| `_vouchers` | Dict in-memory `{code: {...}}` persistito su `_vouchers.json` | `audiobook_app.py` | — |
| `_PAYMENTS_FILE` | `UPLOAD_DIR / "_payments.json"` | `audiobook_app.py` | 343 |
| `_VOUCHERS_FILE` | `UPLOAD_DIR / "_vouchers.json"` | `audiobook_app.py` | 344 |
| `_PAID_OPT_DONE_FILE` | `UPLOAD_DIR / "_paid_opt_done.json"` (tracking job pagati completati per recovery) | `audiobook_app.py` | 345 |

**Funzionamento pagamenti:**

- **Sotto soglia** (costo stimato ≤ `ABM_LLM_FREE_THRESHOLD_EUR`): l'ottimizzazione AI è **gratuita** e liberamente testabile (nessuna richiesta di pagamento).
- **Sopra soglia**: l'utente deve utilizzare un buono (voucher) ottenuto tramite donazione al progetto. Il pagamento diretto PayPal nel frontend è stato disabilitato (v3.7.0) ma i route backend PayPal sono mantenuti per eventuale riattivazione futura.
- **Flusso PayPal (backend, disabilitato nel frontend)**: ordine creato con `intent=CAPTURE`, `currency_code=EUR`, `shipping_preference=NO_SHIPPING`, `user_action=PAY_NOW`, `Prefer: return=representation`; OAuth2 client_credentials con cache ~8h; capture idempotente (re-capture dello stesso `order_id` ritorna lo stesso `payment_token`).
- **Voucher refund (errore/cancel)**: se l'ottimizzazione fallisce o viene annullata dopo un pagamento con voucher, l'importo viene **ri-accreditato integralmente** sul voucher originale tramite `_voucher_refund()`. Se il pagamento era PayPal, viene emesso un nuovo buono pari all'importo pagato + `ABM_VOUCHER_BONUS_PERCENT`%.
- **Recovery avvio server**: `_recover_orphaned_voucher_charges()` eseguita allo startup controlla gli addebiti voucher delle ultime 2 ore; se il job_id non è più in memoria né tra i completati (`_paid_opt_done.json`), ri-accredita automaticamente l'importo. Copre il caso di crash/riavvio durante un'ottimizzazione a pagamento.
- **Saldo residuo (consumo parziale)**: ogni voucher ha un campo `remaining_eur` (inizializzato all'importo totale) che viene decrementato di `estimated_cost` ad ogni operazione. Il buono torna "USED" solo quando il saldo scende sotto 0.01 EUR; fino a quel momento conserva stato `PARTIAL` e può essere usato più volte fino a scadenza. Lo storico delle spese è in `uses[]` (`job_id`, `amount_eur`, `at`, `remaining_after`). Record legacy senza `remaining_eur` vengono letti in compat: `used=True` → residuo 0; altrimenti residuo = `amount_eur`. La revoca admin azzera `remaining_eur`.
- **Idempotenza capture**: re-capture sullo stesso `order_id` ritorna il token esistente senza doppio addebito.
- **Ricevuta email**: inviata automaticamente post-capture al payer email PayPal.
- **GDPR**: dati pagamento conservati `ABM_PAYMENT_RETENTION_DAYS` giorni (default 24 mesi) per compliance fiscale.
- **Endpoint diagnostico**: `GET /api/paypal_debug_order/<order_id>` per ispezionare un ordine via API PayPal v2.

**Sicurezza voucher (hardening anti-forgery):**

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `VOUCHER_RL_PER_MIN` | `5` tentativi voucher_validate / IP / minuto | `audiobook_app.py` | ~350 |
| `VOUCHER_RL_PER_HOUR` | `30` tentativi voucher_validate / IP / ora | `audiobook_app.py` | ~351 |
| `VOUCHER_EMAIL_FAIL_LIMIT` | `10` fallimenti consecutivi per email prima del lockout | `audiobook_app.py` | ~352 |
| `VOUCHER_EMAIL_LOCKOUT_SEC` | `900` (15 min di lockout email) | `audiobook_app.py` | ~353 |

- **Rate limit**: `/api/voucher_validate` protetto da sliding window per IP e lockout temporaneo per email; oltre soglia risponde `429` con header `Retry-After`.
- **Log strutturato**: ogni tentativo genera un evento `VOUCHER_ATTEMPT` (o `VOUCHER_ATTEMPT_BLOCKED:<reason>`) nel log attività mensile, con IP, codice mascherato e outcome (`OK`, `NOT_FOUND`, `USED`, `EXPIRED`, `EMAIL_MISMATCH`, `MISSING_FIELDS`).
- **Schema voucher esteso**: ogni record ha `kind` (`refund` | `promo` | `gift`), `note` (≤500 char), `created_by` (`auto_refund` | `admin`). I voucher generati da CLI usano prefisso `PROMO-` o `GIFT-` per distinguerli a colpo d'occhio.
- **CLI amministrativa**: `scripts/admin_voucher.py` (zero superficie web) con sottocomandi `create`, `list`, `revoke`, `show`. Opera direttamente su `_vouchers.json` in `ABM_DATA_DIR` e logga ogni operazione in `voucher_admin.log`. Esempio: `python scripts/admin_voucher.py create --email user@ex.com --amount 2 --days 180 --kind promo --note "campagna lancio"`.
- **UI web admin** (`/admin/vouchers`): interfaccia grafica protetta da `ABM_ADMIN_TOKEN`. Se la env var è vuota l'endpoint risponde `404` (feature disabilitata). Il token viene validato lato server con `hmac.compare_digest` e trasmesso dal browser via header `X-Admin-Token` (memorizzato solo in `sessionStorage`). Operazioni esposte: creazione voucher (`POST /admin/api/vouchers`), elenco (`GET /admin/api/vouchers`), revoca (`POST /admin/api/vouchers/<code>/revoke`). Ogni operazione logga eventi `ADMIN_VOUCHER_CREATE:<kind>` / `ADMIN_VOUCHER_REVOKE`. `/admin/` è escluso da `robots.txt` (`noindex, nofollow` anche via header).

| Parametro env | Default | Scopo |
|---------------|---------|-------|
| `ABM_ADMIN_TOKEN` | *(vuoto → UI disabilitata)* | Token segreto per accedere a `/admin/vouchers` |
- **Gitignore**: `_vouchers.json`, `_payments.json`, `voucher_admin.log` esclusi esplicitamente da git per prevenire commit accidentali (in aggiunta a `data/`).

### 3.6 DeepSeek LLM (ottimizzazione testo per TTS)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `DEEPSEEK_API_BASE` | `"https://api.deepseek.com"` | `generation_engine.py` | 49 |
| `DEEPSEEK_MODEL` | `"deepseek-chat"` (configurabile via `ABM_DEEPSEEK_MODEL`) | `generation_engine.py` | 50 |
| `DEEPSEEK_THINKING` | `"false"` (configurabile via `ABM_DEEPSEEK_THINKING`) | `generation_engine.py` | 51 |
| `DEEPSEEK_REASONING_EFFORT` | `"none"` (configurabile via `ABM_DEEPSEEK_REASONING_EFFORT`: none, low, medium, high) | `generation_engine.py` | 52 |
| `DEEPSEEK_MAX_TOKENS` | `8192` | `generation_engine.py` | 53 |
| `DEEPSEEK_TEMPERATURE` | `0.3` | `generation_engine.py` | 54 |
| `DEEPSEEK_CHARS_PER_TOKEN` | `3.5` (stima per italiano) | `generation_engine.py` | 55 |
| `DEEPSEEK_MAX_INPUT_CHARS` | `~405.000` (calcolato da context 128K) | `generation_engine.py` | 60 |
| `_call_deepseek(max_retries)` | `4` tentativi con backoff esponenziale (1/2/4/8s) su errori transitori di rete (`ReadError`, `ConnectError`, `ConnectTimeout`, `ReadTimeout`, `RemoteProtocolError`, `APIConnectionError`, `APITimeoutError`) | `generation_engine.py` | 438 |
| `timeout` streaming DeepSeek | `120.0s` esplicito per evitare stall indefiniti | `generation_engine.py` | 451 |

### 3.4 Generazione audio

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CHUNK_MAX_CHARS` | `2000` (caratteri max per chunk TTS) | `tts_split.py` | 37 |
| `CHAPTER_SILENCE_SEC` | `3` (secondi di silenzio tra capitoli) | `generation_engine.py` | 78 |
| `_TTS_MIN_SENT_CHARS` | `80` (soglia minima di caratteri per frase inviata a edge-tts su voci Multilingual) | `tts_split.py` | 41 |
| `_TTS_MAX_SENT_CHARS` | `1500` (cap superiore di sicurezza per frase) | `tts_split.py` | 43 |

**Output M4B (v3.8.0+):**

A partire dalla v3.8.0, in modalità file unico (`single_file=True`) viene generato automaticamente anche un file `.m4b` con capitoli embedded, copertina e metadati, oltre all'MP3. Il file M4B utilizza codec AAC tramite `ffmpeg`. Se `ffmpeg` non è installato, l'MP3 viene comunque generato normalmente. Il pulsante "Scarica M4B" appare nell'UI solo se il file è disponibile.

**Fix v3.8.1**: timeout M4B aumentato a 3600s (audiolibri lunghi post-ottimizzazione AI), filtro capitoli zero-duration (ffprobe non disponibile), fallback cover art (`-c:v mjpeg`), reset `output_m4b` al ritorno ai capitoli, scan filesystem M4B nella pagina download email.

**Fix v3.8.2**:
- **Bitrate AAC adattivo** — `_get_audio_bitrate()` rileva tramite `ffprobe` il bitrate dell'MP3 sorgente (default edge-tts: 48 kbps) e lo usa per la codifica AAC, così il file M4B risulta di dimensioni sostanzialmente equivalenti alla somma degli MP3 originali. In precedenza il bitrate era fisso a 64kbps, rendendo il M4B ~33% più grande della sorgente.
- **Metadati titolo e autore**: aggiunto parametro `author` a `_convert_mp3_to_m4b`; scritti i tag `title`, `album` (= titolo), `artist` e `album_artist` (= autore) nel FFMETADATA1. Il file di metadati viene creato anche quando non ci sono chapter markers validi (in precedenza title/author non venivano scritti se ffprobe era assente). Aggiornati tutti i call site in `audiobook_app.py` e `generation_engine.py`.
- **Metadati estesi M4B**: aggiunti tag `date` (anno di pubblicazione, estratto da `dc:date` EPUB via `_extract_year_from_date`), `genre` (default `"Audiobook"`), `language` (codice ISO 639-2/B a livello **stream audio** via `-metadata:s:a:0`, mappato da ISO 639-1 via `_normalize_language_iso`), `comment`/`description` (troncati a 1000 char), `media_type=2` (iTunes `stik` atom → Apple Books classifica come "Audiobook"). Aggiunto campo `date: str` alla dataclass `BookInfo` in `epub_to_tts.py`.
- **Cover art ad alta risoluzione**: nuova funzione `_prepare_m4b_cover_path(job, title, author, work_dir)` che restituisce una cover 1400×1400 per l'embedding. Strategia: (1) riusa `job["cover_hires"]` se cached, (2) estrae dal sorgente EPUB via `_extract_cover_from_epub` a 1400×1400 quadrata, (3) fallback al `cover_thumb` esistente, (4) ultima risorsa: genera cover branded "Audiobook Maker" con titolo e autore via `_generate_fallback_cover` (richiede Pillow). Garantisce che **ogni M4B abbia sempre una copertina**, anche per PDF/TXT o EPUB senza cover.

**Fix v3.8.5 (UI fixes)**:
- **Layout più stretto**: ridotto `max-width` da 800px a 720px per `.app` (html_head.html) e `#seoContent` (seo_content.py), ripristinando margini laterali visibili.
- **Email readonly post-avvio ottimizzazione**: dopo la chiamata `/api/register_opt_email` il campo email diventa `readonly` con sfondo grigio; viene resettato alla riapertura del modal.
- **Icona FAQ corretta**: aggiunta classe `seo-section` ai singoli `<details>` delle FAQ per usare l'icona CSS customizzata invece del widget nativo del browser.

**Novità v3.10.0 (Analytics & Logging Overhaul)**:
- **Analisi Carico Orario**: introdotto un nuovo grafico a barre nella pagina `/logs` che mostra la distribuzione dei job nelle 24 ore.
- **Breakdown Linguistico**: il grafico orario suddivide i conteggi per lingua del browser (top 3 lingue + categoria "Other"), permettendo di analizzare la provenienza degli utenti.
- **Logging Chirurgico**: eliminati i log ridondanti della console (`/api/heartbeat`, `GET /api/job_status/`, `[google-tts] get_voices`) per una migliore leggibilità del server.
- **Tracciabilità Prompt**: il server ora logga esplicitamente quale file `.md` di prompt sta utilizzando per ogni sessione di ottimizzazione AI, insieme ai parametri del modello (Reasoning e Thinking).

**Novità v3.9.8 (Robust Chapter Selection AI)**:
- **Correzione Stima Costo**: risolto un problema per cui la stima dei caratteri e del costo dell'ottimizzazione AI poteva ignorare la selezione dei capitoli a causa di una formattazione non standard dei parametri. Ora il sistema utilizza `URLSearchParams` sul frontend e un parsing multi-formato sul backend per garantire la massima precisione.

**Novità v3.9.7 (Definitive Chapter Selection AI)**:
- **Stima Costo Precisa**: corretto il calcolo del costo nella fase di preventivo per l'ottimizzazione AI. Ora il sistema conta solo i caratteri dei capitoli effettivamente selezionati dall'utente.
- **Filtraggio Risultati**: al termine dell'ottimizzazione AI, il libro viene ora limitato permanentemente ai soli capitoli scelti. Questo garantisce che la successiva generazione audio e l'esportazione del progetto (.abm) includano esclusivamente i contenuti ottimizzati, evitando sprechi di risorse e discrepanze nel risultato finale.

**Novità v3.9.6 (Fix Chapter Selection AI)**:
- **Ottimizzazione Capitoli Selezionati**: corretto un bug per cui l'ottimizzazione AI ignorava la selezione dei capitoli e processava sempre l'intero libro. Ora il thread di ottimizzazione filtra correttamente i capitoli basandosi sugli indici selezionati dall'utente.

**Novità v3.9.5 (Remember Me Admin)**:
- **Persistenza Accesso**: aggiunta l'opzione "Rimani connesso (30 giorni)" nel gate di accesso ai log. Se selezionata, l'autenticazione viene salvata in `localStorage` con scadenza a 30 giorni, evitando di dover reinserire il token ad ogni sessione.

**Novità v3.9.4 (FAQ Update)**:
- **Esempio acronimi**: aggiornato il testo delle FAQ sull'ottimizzazione AI sostituendo l'esempio "ONU" con "W3C" ("W3C" → "W-tre-C") per illustrare meglio la gestione degli acronimi tecnici e della pronuncia lettera-per-lettera.

**Novità v3.9.3 (Extra Layout Compression)**:
- **Riduzione spazi**: ulteriore dimezzamento del margine sopra il disclaimer (da 16px a 8px) per massimizzare la visibilità dei controlli su schermi piccoli.

**Novità v3.9.2 (Layout Cleanup)**:
- **Header semplificato**: rimossa la tagline duplicata sotto il logo ("Convertitore Gratuito...") per pulizia visiva.
- **Riduzione spazi verticali**: ridotto il margine inferiore dell'header e lo spazio tra i pulsanti toolbar e il disclaimer per una UI più compatta, specialmente su mobile.

**Novità v3.9.1 (Rimozione Active Jobs)**:
- **Rimozione Monitor Active Jobs**: eliminata la funzionalità di monitoraggio "Active Jobs" (accessibile tramite i tre puntini in basso a destra) dalla home page. Questa funzionalità è ora sostituita e centralizzata nella pagina `/logs` protetta.

**Novità v3.9.0 (Log Protection & Progress)**:
- **Protezione /logs**: la pagina dei log è ora protetta da token. Se non autenticati, viene mostrato un "gate" per l'inserimento dell'Admin Token (memorizzato in `sessionStorage`).
- **Percentuale Avanzamento**: nei log, per i task in corso, viene ora mostrata la percentuale di avanzamento (%) calcolata in tempo reale se il job è presente in memoria.

**Fix v3.8.9 (marker FAQ)**:
- **Marker CSS corretto**: corretto escape della sequenza unicode `\\25B6` nel blocco CSS iniettato da `seo_content.py`. In precedenza, l'assenza del doppio backslash in Python causava la visualizzazione di testo spurio ("B6") invece dell'icona a triangolo.

**Fix v3.8.4 (syntax errors seo_content.py)**:
- **Virgolette ASCII in stringhe FAQ**: corretto syntax error in 6 righe (IT/EN/FR/ES/DE/ZH) dove le virgolette degli esempi acronimi (`"ONU"`, `"NASA"`) usavano lo stesso delimitatore `"` della stringa esterna. Risolto cambiando il delimitatore esterno in `'` per quelle righe.
- **Doppia virgola**: rimossa virgola duplicata `"),,` nella voce FAQ italiana.
- **F-string e stringhe multi-riga**: corretti 5 punti in cui stringhe/f-string su più righe usavano `"...\n"` con newline letterale invece di `\n` escaped (incompatibile con Python 3.12+ in alcuni contesti).

**Fix v3.8.3 (integrità M4B)**:
- **Validazione post-conversione**: nuova funzione `_validate_m4b_file(path)` in `audio_utils.py` che usa `ffprobe` per verificare, dopo ogni conversione M4B, che il container sia parsabile (`mp4/m4a/ipod/mov`), che esista almeno uno stream audio e che la durata sia > 0. Motivazione: `ffmpeg` può uscire con `returncode=0` lasciando un file troncato o senza stream audio in casi limite (disk pressure, OOM minore, buffer flush parziale, fallback cover non pulito). Senza questa validazione un M4B corrotto veniva considerato "OK" e offerto al download. Se ffprobe non è installato la validazione viene saltata (skip sicuro, mantiene compatibilità).
- **Cleanup file parziali**: se `_convert_mp3_to_m4b` fallisce (ffmpeg rc≠0, timeout, eccezione) o la validazione rileva corruzione, il file M4B parziale viene rimosso dal disco. Questo evita che un M4B corrotto venga ripescato dal filesystem scan (`/api/events/<job_id>` L4098-4102, pagina email `/dl/<token>` L4835+).
- **Pulizia M4B parziale prima dello ZIP (Chapter mode)**: aggiornati entrambi i call site (`audiobook_app.py` L2268+, `generation_engine.py` L1350+) per rimuovere esplicitamente l'M4B parziale da `output_dir` PRIMA di `shutil.make_archive`, se `output_m4b` non è stato impostato (conversione fallita o validazione negativa). Il `try/except/finally` garantisce anche la pulizia del `combined_mp3` temporaneo in ogni scenario.

**Verifica flusso "status=done"**: confermato strutturalmente corretto in tutti i 4 percorsi (`audiobook_app.py` single-file L2166 + chapter L2279 → `status="done"` L2334; `generation_engine.py` single-file L1256 + chapter L1359 → `status="done"` L1411). Anche `progress_current = progress_total` (100%) e `completed_at` sono impostati DOPO la conversione M4B. Il client frontend riceve `status='done'` via SSE solo dopo che `job["output_m4b"]` è stato aggiornato, e l'endpoint `/api/download_m4b/<job_id>` controlla `status != "done"` → `400 Not ready`.

| Parametro | Valore | File | Note |
|-----------|--------|------|------|
| Codec M4B | `aac`, bitrate adattivo (rilevato da ffprobe) | `audio_utils.py` | `_convert_mp3_to_m4b` + `_get_audio_bitrate` |
| Bitrate AAC default | `48k` (fallback se ffprobe non disponibile) | `audio_utils.py` | = default edge-tts (audio-24khz-48kbitrate-mono-mp3) |
| Formato container | `ipod` (M4B/M4A) | `audio_utils.py` | `-f ipod` ffmpeg |
| TIMEBASE capitoli | `1/1000` (millisecondi) | `audio_utils.py` | Standard iTunes/Apple Books |
| Codec cover art | `mjpeg` (con fallback senza cover) | `audio_utils.py` | Compatibile con container ipod |
| Timeout conversione M4B | `3600` secondi | `audio_utils.py` | Supporto audiolibri molto lunghi |
| Tag metadati globali | `title`, `album`, `artist`, `album_artist`, `date`, `genre`, `comment`, `description` | `audio_utils.py` | Scritti sempre quando disponibili |
| Tag stream audio | `language=ita/eng/fra...` (ISO 639-2/B) | `audio_utils.py` | `-metadata:s:a:0 language=...` (MP4 usa language per-stream) |
| Tag iTunes stik | `media_type=2` (Audiobook) | `audio_utils.py` | Apple Books classifica come audiolibro |
| Risoluzione cover M4B | `1400×1400` quadrata (JPEG q=2 MJPEG embedded) | `audio_utils.py` | `_prepare_m4b_cover_path` + `_extract_cover_from_epub` |
| Cover fallback branded | Generata automaticamente per PDF/TXT o EPUB senza cover | `audio_utils.py` | `_generate_fallback_cover`, richiede Pillow |

**Mitigazione drift linguistico voci Multilingual:**

Le voci edge-tts denominate *Multilingual* (es. `it-IT-GiuseppeMultilingualNeural`) usano un modello neurale con auto-detection della lingua per clausola: testi italiani con anglicismi isolati, acronimi o righe brevi possono essere letti parzialmente in inglese/spagnolo/portoghese. Mitigazione a due livelli:

1. **Runtime (`generate_chunk_mp3`)**: quando la voce selezionata contiene `multilingual` nel nome (case-insensitive), il chunk viene spezzato in frasi con `_split_sentences_for_tts`, sintetizzato frase per frase e riconcatenato via `_concatenate_mp3`. Contesti più corti → meno drift. Le voci monolingua (`it-IT-IsabellaNeural`, `DiegoNeural`, ecc.) non subiscono questo trattamento extra e proseguono con chiamata singola.
2. **Preprocessing LLM (`prompt_tts_optimization.md`, regola #14)**: il prompt DeepSeek include direttive anti-drift — acronimi lettera-per-lettera con punti separatori (`CEO` → `C.E.O.`), merge di righe molto corte, divieto di traduzione. Attivo automaticamente quando l'utente sceglie l'ottimizzazione AI del testo.

### 3.5 Voci e lingue

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `LANGUAGE_NAMES` | Dict di 60+ codici lingua -> nomi | `audiobook_app.py` | 555 |

### 3.6 Cleanup (pulizia automatica)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CLEANUP_GRACE_AFTER_DOWNLOAD_SEC` | `300` (5 min dopo download diretto) | `audiobook_app.py` | 3870 |
| `CLEANUP_HEARTBEAT_TIMEOUT_SEC` | `60` (heartbeat perso = browser chiuso) | `audiobook_app.py` | 3871 |
| `CLEANUP_INTERVAL_SEC` | `60` (check ogni 60 secondi) | `audiobook_app.py` | 3872 |
| `CLEANUP_ORPHAN_DIR_AGE_SEC` | `7200` (2 ore, cartelle orfane rimosse) | `audiobook_app.py` | 3873 |

**Retention per stato (stato job → politica di conservazione):**

- `analyzed` → 3 min dopo l'ultimo heartbeat (anteprima mai avviata)
- `optimizing` → cancellato se heartbeat perso per >60s (senza email) / tenuto in vita in batch (con email)
- `optimized` → **`EMAIL_FILE_RETENTION_SEC` (default 18h, configurabile via `ABM_JOB_RETENTION_SEC`) dal `opt_completed_at`**, indipendentemente dalla presenza di email registrata e dallo stato del browser. Garantisce che il bottone "Scarica progetto ottimizzato (.abm)" nell'UI continui a funzionare per il periodo configurato dalla fine dell'ottimizzazione AI, allineando lo scenario interactive a quello batch-email.
- `generating` → tenuto in vita se email registrata; heartbeat timeout 60s altrimenti
- `done` → 5 min dopo download diretto / `EMAIL_FILE_RETENTION_SEC` dall'invio email / 60s di heartbeat perso senza download
- `error` → 2 min di grazia per leggere il messaggio

### 3.7 SEO e template

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `_SEO_DATA` | Dict con dati SEO per 6 lingue (it, en, fr, es, de, zh) | `audiobook_app.py` | 3749 |
| `_SUPPORTED_LANGS` | `['it', 'en', 'fr', 'es', 'de', 'zh']` | `audiobook_app.py` | 3795 |
| `HTML_TEMPLATES` | Dict di template HTML pre-renderizzati per lingua | `audiobook_app.py` | 3799 |
| `HTML_TEMPLATE` | Fallback al template inglese | `audiobook_app.py` | 3809 |

---

## 4. Costanti di parsing EPUB (`epub_to_tts.py`)

### 4.1 Filtri HTML

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `TAGS_TO_REMOVE_WITH_CONTENT` | Set di 25 tag HTML scartati (script, style, nav, aside, footer, header, figcaption, figure, table, svg, math, code, pre, sup, sub, noscript, iframe, object, embed, canvas, form, input, select, textarea, button, map, area) | `epub_to_tts.py` | 48 |
| `BLOCK_TAGS` | Set di tag blocco: `p, div, h1-h6, li, blockquote, section, article, br, hr` | `epub_to_tts.py` | 57 |
| `HEADING_TAGS` | `{"h1", "h2", "h3", "h4", "h5", "h6"}` | `epub_to_tts.py` | 63 |

### 4.2 Filtri CSS e EPUB semantici

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CLASSES_TO_SKIP` | Set di 40+ pattern di classi CSS da escludere | `epub_to_tts.py` | 66 |
| `EPUB_TYPES_TO_SKIP` | Set di 30+ tipi semantici EPUB3 da escludere | `epub_to_tts.py` | 94 |

### 4.3 Filtri filename

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `NON_CONTENT_FILENAMES_EXACT` | Set di 15+ nomi file esatti da escludere (toc, nav, cover, colophon...) | `epub_to_tts.py` | 112 |
| `NON_CONTENT_FILENAMES_SUBSTR` | Set di 8 sottostringhe filename da escludere | `epub_to_tts.py` | 120 |

### 4.4 Pulizia testo

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `LINE_SKIP_PATTERNS` | Lista di 5 regex per righe da saltare (numeri pagina, separatori...) | `epub_to_tts.py` | 127 |
| `NOISE_PATTERNS` | Lista di 18 coppie (regex, sostituzione) per pulizia inline | `epub_to_tts.py` | 138 |
| `ABBREVIATIONS` | Dict di 50+ abbreviazioni -> espansione per TTS naturale | `epub_to_tts.py` | 180 |

### 4.5 Marker di pausa TTS

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CHAPTER_PAUSE` | `"\n\n...\n\n"` (pausa lunga tra capitoli) | `epub_to_tts.py` | 236 |
| `SECTION_PAUSE` | `"\n\n"` (pausa media tra sezioni) | `epub_to_tts.py` | 237 |

---

## 5. Costanti di parsing PDF (`pdf_to_tts.py`)

### 5.1 Soglie e margini

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `SMALL_TEXT_RATIO` | `0.85` (testo < 85% del body text = nota/didascalia, scartato) | `pdf_to_tts.py` | 110 |
| `HEADER_MARGIN_RATIO` | `0.08` (top 8% della pagina = header) | `pdf_to_tts.py` | 113 |
| `FOOTER_MARGIN_RATIO` | `0.08` (bottom 8% della pagina = footer) | `pdf_to_tts.py` | 114 |

### 5.2 Pattern di riconoscimento

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CAPTION_PATTERNS` | Lista di 6 regex multilingua per didascalie figure/tabelle | `pdf_to_tts.py` | 117 |
| `NON_CONTENT_TITLES` | Set di 80+ titoli di sezioni non-contenuto da escludere (multilingua) | `pdf_to_tts.py` | 141 |
| `FOOTNOTE_SUPERSCRIPT_RE` | Regex compilata per footnote nel testo | `pdf_to_tts.py` | 180 |
| `PAGE_NUMBER_RE` | Regex compilata: `r"^\s*[-—–]?\s*\d{1,4}\s*[-—–]?\s*$"` | `pdf_to_tts.py` | 185 |
| `MIN_REPEAT_FOR_HEADER` | `3` (minimo ripetizioni per header/footer statistico) | `pdf_to_tts.py` | 188 |

---

## 6. Google Cloud TTS (`google_tts.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `GOOGLE_TTS_MONTHLY_LIMIT` | `1000000` (da `ABM_GOOGLE_TTS_MONTHLY_LIMIT`) | `google_tts.py` | 33 |
| `VOICES_CACHE_TTL` | `3600` (1 ora, cache voci Google) | `google_tts.py` | 42 |
| `_usage_file_path` | `Path(data_dir) / "google_tts_usage.json"` | `google_tts.py` | 51 |
| `_MONITORING_STABILIZATION_LAG_SEC` | `900` (15 min, intervallo escluso dalle query Cloud Monitoring per usare solo metriche stabilizzate) | `google_tts.py` | 380 |
| `_MAX_CHARS_PER_REQUEST` | `2200` (bound massimo caratteri/richiesta TTS per sanity check, = `CHUNK_MAX_CHARS` + 10% tolleranza) | `google_tts.py` | 610 |

---

## 7. Gemini TTS (`gemini_tts.py`)

Modulo `gemini_tts.py` indipendente da Chirp3-HD. Usa SDK `google-genai`, account separato. Native output PCM 24kHz mono 16-bit → AAC per M4B diretto (niente MP3 intermedio).

### 7.1 Autenticazione

| Variabile | Default | Note |
|-----------|---------|------|
| `ABM_GEMINI_API_KEY` | *(vuoto)* | Se vuoto, Gemini TTS è disabilitato |
| `ABM_GEMINI_USE_VERTEX` | `false` | Se `true` usa Vertex AI (service account) |
| `ABM_GEMINI_VERTEX_CREDENTIALS_FILE` | *(vuoto)* | Path JSON service account (se Vertex) |

### 7.2 Costi Google (USD per 1M token)

Sovrascrivibili in caso di adeguamento listino Google.

| Variabile | Default |
|-----------|---------|
| `ABM_GEMINI_25FLASH_INPUT_USD_PER_MTOK` | `0.50` |
| `ABM_GEMINI_25FLASH_OUTPUT_USD_PER_MTOK` | `10.00` |
| `ABM_GEMINI_31FLASH_INPUT_USD_PER_MTOK` | `1.00` |
| `ABM_GEMINI_31FLASH_OUTPUT_USD_PER_MTOK` | `20.00` |
| `ABM_GEMINI_USD_EUR_RATE` | `0.86` |

### 7.3 Margini di vendita (% sul costo Google)

| Variabile | Default |
|-----------|---------|
| `ABM_GEMINI_25FLASH_MARGIN_PERCENT` | `35` |
| `ABM_GEMINI_31FLASH_MARGIN_PERCENT` | `25` |

### 7.4 PayPal fee compensation e soglia gratuità

| Variabile | Default |
|-----------|---------|
| `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR` | `0.34` |
| `ABM_GEMINI_PAYPAL_PERCENT_FEE` | `3.4` |
| `ABM_GEMINI_FREE_THRESHOLD_EUR` | `0.50` |

### 7.5 Limiti e anti-abuso

| Variabile | Default |
|-----------|---------|
| `ABM_GEMINI_PREVIEW_CAP_PER_DAY` | `5` (preview free per cookie, rolling 24h) |
| `ABM_GEMINI_MAX_BYTES_PER_CALL` | `4000` (cap UTF-8 per chiamata API) |
| `ABM_GEMINI_RATE_MODE` | `prompt` |

### 7.6 Note operative

- Voice ID formato: `gemini:<model_key>:<voice_name>` (es. `gemini:flash25:Zephyr`).
- Modelli supportati: `flash25` (Gemini 2.5 Flash TTS), `flash31` (Gemini 3.1 Flash TTS).
- 30 voci prebuilt × 2 modelli = 60 entry per lingua UI.
- Chunk max chars per lingua: 1500 per zh/ja/hi/ar, 2000 per le altre.
- Stato utilizzo persistito in `<ABM_DATA_DIR>/gemini_tts_usage.json`, preview cap in `gemini_tts_previews.json` (atomic write tmp+rename).

### 7.7 Audit log dei costi (`gemini_cost_audit.py`)

Per ogni generazione TTS Premium completata, fallita o cancellata, viene scritto un record JSONL nel file mensile `<ABM_DATA_DIR>/gemini_cost_audit_YYYY-MM.jsonl` (append-only, lock per scrittura).

**Campi record (18):**

| Campo | Descrizione |
|-------|-------------|
| `ts` | Timestamp ISO8601 UTC della scrittura |
| `job_id` | ID job applicativo |
| `client_id` | Cookie client (opaco) |
| `email` | Email associata al pagamento (vuota per free) |
| `language` | Lingua sintesi |
| `model_key` | `flash25` o `flash31` |
| `voice` | Nome voce |
| `chars_total` | Caratteri sintetizzati |
| `chunks_total` | Numero chunk inviati |
| `audio_seconds_estimated` | Stima ex-ante (rate model+lang) |
| `audio_seconds_actual` | Misurato (bytes PCM / (24000·2)) |
| `google_cost_eur_estimated` | Costo Google stimato ex-ante |
| `google_cost_eur_actual` | Costo Google effettivo (token in/out × tariffa) |
| `user_price_eur_charged` | Prezzo addebitato all'utente |
| `margin_percent` | Margine applicato (`ABM_GEMINI_<model>_MARGIN_PERCENT`) |
| `delta_eur` | `user_price - google_cost_actual` |
| `delta_pct` | `delta_eur / google_cost_actual × 100` |
| `outcome` | `completed` \| `failed_refunded` \| `cancelled_refunded` \| `recovered_refunded` |

**Retention:** manuale — i file sono piccoli (qualche KB/mese a regime). Ruotare/archiviare a discrezione admin.

**Parametri di tuning:** se `delta_pct_avg` si discosta sistematicamente (vedi `/admin/logs` → "Audit Gemini" → "Calcola parametri suggeriti"), valutare:
- aumento margin_percent del modello se delta negativo (`ABM_GEMINI_<model>_MARGIN_PERCENT`)
- riduzione tariffa utente se delta positivo eccessivo
- adeguamento del rapporto chars/secondi (tabella `_SEC_PER_KCHARS_BY_LANG` in `gemini_tts.py`) se la stima ex-ante diverge dalla realtà

**Persistenza job pagati unificata:** dalla v3.13.x, sia i pagamenti per Ottimizzazione testo AI sia quelli per voci Premium sono tracciati in `<ABM_DATA_DIR>/_paid_jobs_done.json` (campo `purpose`: `"llm"` o `"gemini"`). La migrazione del vecchio `_paid_opt_done.json` è automatica all'avvio (backup `.pre_unify_bak`).

---

## 8. Versione (`version.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `__version__` | `"3.13.0"` | `version.py` | 7 |
| `__updated_date__` | Dinamico: `datetime.now().strftime("%Y-%m")` | `version.py` | 10 |

---

## 9. SEO Content (`seo_content.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `_URL_RE` | Regex compilata per rilevamento URL nel testo | `seo_content.py` | 31 |
| `_CONTENT` | Dict con contenuti SEO visibili per 6 lingue | `seo_content.py` | 43 |

---

## 10. Nuovi moduli (v3.8.0)

### Architettura a moduli

A partire dalla v3.8.0, il codice è distribuito su più file per migliorare la manutenibilità:

| Modulo | Contenuto |
|--------|-----------|
| `audio_utils.py` | Utilities audio: concatenazione MP3, silenzio, cover, podcast RSS, **conversione M4B** (`_convert_mp3_to_m4b`) |
| `tts_split.py` | Splitting testo per TTS, generazione chunk via edge-tts/Google TTS, anti-drift Multilingual |
| `email_service.py` | SMTP, digest admin, ricevuta pagamento, buono rimborso |
| `payment.py` | Gestione voucher, PayPal OAuth2/capture, validazione rate-limited |
| `generation_engine.py` | Thread di ottimizzazione LLM e generazione TTS, `configure()`, `run_optimization`, `run_generation` |
| `community_store.py` | JSON store per widget community: news (`news.json`) e feedback utenti (`feedback.json`) su `ABM_DATA_DIR`. Atomic write tmp+rename, lock per file, backup `.bak` |

---

## 11. Community widget (v3.13.0)

Live Stats, News e Feedback aggiungono questi file su `ABM_DATA_DIR`:

| File | Contenuto |
|------|-----------|
| `news.json` | Lista news pubblicate dagli admin (tag, title, body, lang, banner, archived) |
| `news.json.bak` | Backup automatico della versione precedente |
| `feedback.json` | Feedback utenti pubblici (rating 1-5, name, comment, ip_hash) |
| `feedback.json.bak` | Backup automatico della versione precedente |

Gli IP raw degli autori dei feedback non vengono persistiti: viene salvato solo `sha256(salt + ip)[:16]`. Il salt è configurabile via `ABM_IP_SALT` (default fisso). Le statistiche live (`/api/community/stats/today` e `/month`) sono derivate dal log `activity_YYYY-MM.log` esistente, nessun nuovo file.

Endpoint pubblici: `/api/community/stats/today`, `/api/community/stats/month`, `/api/community/news` (GET), `/api/community/feedback` (GET, POST).
Endpoint admin (richiedono `X-Admin-Token` o `?token=...`): `/admin/community` (UI con tab News + Feedback), `/admin/api/news`, `/admin/api/news/<id>`, `/admin/api/news/list`, `/admin/api/feedback/list`, `/admin/api/feedback/<id>`.

Anti-spam feedback (in-memory, no DB): rate-limit `1/h, 5/24h` per IP-hash, honeypot `website` field, sanitize HTML server-side, cap lunghezze (name 80, comment 1000). Notifica email all'admin throttled a 30 min.

---

## Riepilogo

| Categoria | Numero parametri |
|-----------|:---:|
| Variabili d'ambiente (`ABM_*`) | 21 |
| Configurazione Flask | 1 |
| Costanti applicative (`audiobook_app.py`) | 28 |
| Costanti parsing EPUB (`epub_to_tts.py`) | 12 |
| Costanti parsing PDF (`pdf_to_tts.py`) | 8 |
| Google Cloud TTS (`google_tts.py`) | 5 |
| Gemini TTS (`gemini_tts.py`) | 15 |
| Versione (`version.py`) | 2 |
| SEO Content (`seo_content.py`) | 2 |
| Nuovi moduli v3.8.0 | 6 |
| **Totale** | **100** |
