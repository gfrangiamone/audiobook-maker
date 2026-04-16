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

---

## 2. Configurazione Flask

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `MAX_CONTENT_LENGTH` | `200 * 1024 * 1024` (200 MB) | `audiobook_app.py` | 73 |

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
| `EMAIL_FILE_RETENTION_SEC` | `86400` (24 ore) | `audiobook_app.py` | 97 |
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
| `_PAYMENTS_FILE` | `UPLOAD_DIR / "_payments.json"` | `audiobook_app.py` | 341 |
| `_VOUCHERS_FILE` | `UPLOAD_DIR / "_vouchers.json"` | `audiobook_app.py` | 342 |

**Funzionamento pagamenti:**

- **Sotto soglia** (costo stimato ≤ `ABM_LLM_FREE_THRESHOLD_EUR`): l'ottimizzazione AI è **gratuita** e liberamente testabile (nessuna richiesta di pagamento).
- **Sopra soglia**: l'utente deve pagare tramite PayPal (modalità `sandbox` o `live` in base a `ABM_PAYPAL_MODE`) oppure usare un buono emesso in precedenza.
- **Flusso PayPal**: ordine creato con `intent=CAPTURE`, `currency_code=EUR`, `shipping_preference=NO_SHIPPING`, `user_action=PAY_NOW`, `Prefer: return=representation`; OAuth2 client_credentials con cache ~8h; capture idempotente (re-capture dello stesso `order_id` ritorna lo stesso `payment_token`).
- **Voucher refund**: se l'ottimizzazione fallisce dopo un pagamento, viene emesso un buono pari all'importo pagato + `ABM_VOUCHER_BONUS_PERCENT`%, valido `ABM_VOUCHER_EXPIRY_DAYS` giorni, utilizzabile solo dall'email originale.
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
| `DEEPSEEK_API_BASE` | `"https://api.deepseek.com"` | `audiobook_app.py` | 64 |
| `DEEPSEEK_MODEL` | `"deepseek-chat"` (DeepSeek V3.2) | `audiobook_app.py` | 65 |
| `DEEPSEEK_MAX_TOKENS` | `8192` | `audiobook_app.py` | 66 |
| `DEEPSEEK_TEMPERATURE` | `0.3` | `audiobook_app.py` | 67 |
| `DEEPSEEK_CHARS_PER_TOKEN` | `3.5` (stima per italiano) | `audiobook_app.py` | 68 |
| `DEEPSEEK_MAX_INPUT_CHARS` | `~405.000` (calcolato da context 128K) | `audiobook_app.py` | 73 |
| `_call_deepseek(max_retries)` | `4` tentativi con backoff esponenziale (1/2/4/8s) su errori transitori di rete (`ReadError`, `ConnectError`, `ConnectTimeout`, `ReadTimeout`, `RemoteProtocolError`, `APIConnectionError`, `APITimeoutError`) | `audiobook_app.py` | 1279 |
| `timeout` streaming DeepSeek | `120.0s` esplicito per evitare stall indefiniti | `audiobook_app.py` | 1299 |

### 3.4 Generazione audio

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CHUNK_MAX_CHARS` | `2000` (caratteri max per chunk TTS) | `audiobook_app.py` | 627 |
| `CHAPTER_SILENCE_SEC` | `3` (secondi di silenzio tra capitoli) | `audiobook_app.py` | 1595 |
| `_TTS_MIN_SENT_CHARS` | `80` (soglia minima di caratteri per frase inviata a edge-tts su voci Multilingual; sotto questa soglia le frasi vengono accorpate alla successiva per dare contesto sufficiente al motore) | `audiobook_app.py` | ~1090 |
| `_TTS_MAX_SENT_CHARS` | `1500` (cap superiore di sicurezza per frase) | `audiobook_app.py` | ~1092 |

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
- `optimized` → **24h (`EMAIL_FILE_RETENTION_SEC`) dal `opt_completed_at`**, indipendentemente dalla presenza di email registrata e dallo stato del browser. Garantisce che il bottone "Scarica progetto ottimizzato (.abm)" nell'UI continui a funzionare per 24h dalla fine dell'ottimizzazione AI, allineando lo scenario interactive a quello batch-email.
- `generating` → tenuto in vita se email registrata; heartbeat timeout 60s altrimenti
- `done` → 5 min dopo download diretto / 24h dall'invio email / 60s di heartbeat perso senza download
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

## 7. Versione (`version.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `__version__` | `"3.5.1"` | `version.py` | 7 |
| `__updated_date__` | Dinamico: `datetime.now().strftime("%Y-%m")` | `version.py` | 10 |

---

## 8. SEO Content (`seo_content.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `_URL_RE` | Regex compilata per rilevamento URL nel testo | `seo_content.py` | 31 |
| `_CONTENT` | Dict con contenuti SEO visibili per 6 lingue | `seo_content.py` | 43 |

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
| Versione (`version.py`) | 2 |
| SEO Content (`seo_content.py`) | 2 |
| **Totale** | **79** |
