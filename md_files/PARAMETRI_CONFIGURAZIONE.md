# Parametri di Configurazione - Audiobook Maker

Raccolta completa di tutti i parametri di funzionamento dell'applicazione, con indicazione del valore attuale/default, del file sorgente e della riga.

---

## 1. Variabili d'ambiente (prefisso `ABM_`)

Parametri configurabili dall'esterno tramite variabili d'ambiente sul server.

| Parametro | Valore default | File | Riga |
|-----------|---------------|------|------|
| `ABM_DATA_DIR` | `"/var/lib/audiobook-maker/data"` | `audiobook_app.py` | 77 |
| `ABM_PORT` | `5601` (porta di bind di `app.run`, utile per affiancare istanze separate sullo stesso host — es. test vs prod) | `audiobook_app.py` | 8341 |
| `ABM_DEBUG` | `0` (Werkzeug debugger + auto-reload; valori truthy: `1`/`true`/`yes`/`on`). In produzione **deve** restare disattivato | `audiobook_app.py` | 8342 |
| `ABM_SMTP_HOST` | `""` (vuoto) | `audiobook_app.py` | 91 |
| `ABM_SMTP_PORT` | `587` | `audiobook_app.py` | 92 |
| `ABM_SMTP_USER` | `""` (vuoto) | `audiobook_app.py` | 93 |
| `ABM_SMTP_PASS` | `""` (vuoto) | `audiobook_app.py` | 94 |
| `ABM_SMTP_FROM` | `SMTP_USER` oppure `"noreply@audiobook-maker.com"` | `audiobook_app.py` | 95 |
| `ABM_BASE_URL` | `""` (vuoto, con rstrip di `/`) | `audiobook_app.py` | 96 |
| `ABM_ADMIN_EMAIL` | `""` (vuoto, se vuoto il digest admin e' disabilitato) | `audiobook_app.py` | 103 |
| `ABM_MAX_CONCURRENT_PER_CLIENT` | `2` | `audiobook_app.py` | 112 |
| `ABM_LLM_API_KEY` | `""` (vuoto, se vuoto l'ottimizzazione testo AI è disabilitata) | `audiobook_app.py` | 104 |
| `ABM_LLM_MODEL` | `"deepseek-chat"` | `audiobook_app.py` | 105 |
| `ABM_MAX_CONCURRENT_LLM_PER_CLIENT` | `1` | `audiobook_app.py` | 152 |
| `ABM_GOOGLE_CREDENTIALS_FILE` | `""` (vuoto, oppure path al file JSON service account Google Cloud) — dal 2026-05-26 usato **anche** dal backend Vertex AI Gemini TTS (non più solo da Google Cloud TTS): un unico service account autentica entrambe le integrazioni quando `ABM_GEMINI_BACKEND` risolve a `vertex`. | `google_tts.py` | 69 |
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
| `ABM_JOB_RETENTION_SEC` | `64800` (18 ore, retention elaborazioni completate e token download per voci standard) | `audiobook_app.py` | 300 |
| `ABM_GEMINI_JOB_RETENTION_SEC` | `172800` (48 ore, retention estesa per job con voci PREMIUM/Gemini — token download e cleanup loop usano questo valore quando `voice` inizia per `gemini:` o il token ha `is_gemini=True`. **Protezione no-download**: se un job/token PREMIUM non risulta mai scaricato (`job["downloaded_at"]` e `token_info["downloaded_at"]` entrambi vuoti) la retention effettiva è raddoppiata via `GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER=2`, default 96h — vedi `_effective_retention_for_job` / `_effective_retention_for_token_info` in `audiobook_app.py`) | `audiobook_app.py` | 301 |
| `ABM_RECOVER_ENABLED` | `1` (abilita il recupero al boot dei job **batch** interrotti da un riavvio/deploy; `0\|false\|no\|off` per disabilitare). Letto in `_recover_orphan_jobs()`. | `audiobook_app.py` | — |
| `ABM_RECOVER_MAX_ATTEMPTS` | `2` (tentativi di recupero per job prima del fallback = rimborso secondo policy + mail "interrotto" + `state=failed`). Il contatore è persistito su disco **prima** di rilanciare (crash-safe) e azzerato al primo capitolo completato di un job recuperato. | `audiobook_app.py` | — |

---

## 2. Configurazione Flask

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `MAX_CONTENT_LENGTH` | da `ABM_MAX_UPLOAD_MB` (default `50` MB). Upload oltre il limite → `413` **JSON** `{"error":"file_too_large","max_mb":N}` via `@app.errorhandler(413)` (prima: pagina HTML Werkzeug → "JSON.parse: unexpected character" nel frontend). Il valore è anche iniettato nella pagina come `window.ABM_MAX_UPLOAD_MB` (`templates/index_page.py`, placeholder `__MAX_UPLOAD_MB__` in `html_tail.html`) per il pre-check dimensione file in `handleFile()` (`static/js/app.js`), che blocca l'upload lato client con messaggio i18n `err_file_too_large`. | `audiobook_app.py` | 231 |
| `ABM_MAX_TEXT_CHARS` | `1500000` (≈ 75-150 MB audio) — cap caratteri **standard** (edge-tts/Google) applicato ai capitoli **selezionati** in `/api/generate`, `/api/optimize` e `/api/optimize_estimate`; il libro viene analizzato e mostrato a prescindere dalla dimensione totale | `audiobook_app.py` | 308 |
| `ABM_MAX_GEMINI_TEXT_CHARS` | `800000` — cap caratteri **PREMIUM/Gemini**, più basso per allinearsi a costi/throughput Gemini TTS. Selezione via `_max_text_chars_for_voice(voice)` → applicato dagli stessi 3 endpoint quando `voice` inizia per `gemini:`. Il frontend riceve entrambi i cap nella risposta upload (`max_text_chars`, `max_gemini_text_chars`) e usa quello attivo in base al tab audio (Standard vs PREMIUM) per il controllo `tryGoToAudioSettings`. | `audiobook_app.py` | 309 |
| `ABM_LLM_OPT_GROWTH_TOLERANCE` | `0.05` (5%, accetta virgola decimale; clamp a ≥0) — tolleranza di crescita del testo dovuta all'**ottimizzazione AI**. Un libro entro il cap **prima** dell'ottimizzazione (precondizione garantita dal cap base in `/api/optimize` e `/api/optimize_estimate` sul testo originale) può superare il cap fino a questa frazione **dopo** l'espansione LLM ed essere comunque generato. Applicata via `_effective_max_text_chars(voice, job)` **solo** ai job `ai_optimized` nei check di generazione/pagamento (`/api/generate` cap generale + preflight Gemini, `/api/paypal_create_order_gemini`). Cap effettivo = `int(base × (1 + tolleranza))`. | `audiobook_app.py` | ~355 |

---

## 3. Costanti applicative principali (`audiobook_app.py`)

### 3.1 Percorsi e directory

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `SCRIPT_DIR` | `Path(__file__).parent.resolve()` | `audiobook_app.py` | 33 |
| `UPLOAD_DIR` | `Path(_DATA_DIR)` (derivato da `ABM_DATA_DIR`) | `audiobook_app.py` | 78 |
| `_TOKENS_FILE` | `UPLOAD_DIR / "_download_tokens.json"` | `audiobook_app.py` | 157 |
| `_CLIENT_EMAILS_FILE` | `UPLOAD_DIR / "_client_emails.json"` | `audiobook_app.py` | 894 |

### 3.2 Email e notifiche

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `SMTP_HOST` | da `ABM_SMTP_HOST` | `audiobook_app.py` | 91 |
| `SMTP_PORT` | da `ABM_SMTP_PORT` (int) | `audiobook_app.py` | 92 |
| `SMTP_USER` | da `ABM_SMTP_USER` | `audiobook_app.py` | 93 |
| `SMTP_PASS` | da `ABM_SMTP_PASS` | `audiobook_app.py` | 94 |
| `SMTP_FROM` | da `ABM_SMTP_FROM` o fallback | `audiobook_app.py` | 95 |
| `BASE_URL` | da `ABM_BASE_URL` (con rstrip) | `audiobook_app.py` | 96 |
| `EMAIL_FILE_RETENTION_SEC` | da `ABM_JOB_RETENTION_SEC` (default `64800` = 18 ore) — retention voci standard | `audiobook_app.py` | 300 |
| `GEMINI_FILE_RETENTION_SEC` | da `ABM_GEMINI_JOB_RETENTION_SEC` (default `172800` = 48 ore) — retention voci PREMIUM/Gemini | `audiobook_app.py` | 301 |
| `ADMIN_EMAIL` | da `ABM_ADMIN_EMAIL` | `audiobook_app.py` | 103 |
| `ADMIN_DIGEST_INTERVAL_SEC` | `86400` (24 ore) | `audiobook_app.py` | 104 |
| `_client_emails` | `{}` dict `client_id → email`, persistito in `_client_emails.json`. Popolato da `/api/register_email`, letto da `gen._send_completion_email` come fallback se `job["notify_email"]` è vuoto | `audiobook_app.py` | 896 |
| `_client_emails_lock` | `threading.Lock()` per accesso thread-safe alla mappa | `audiobook_app.py` | 897 |

### 3.2.1 Fallback email cross-job

Quando un job completa senza `notify_email` registrato (es. UI del campo email non mostrata per errore JS),
il sistema cerca una email precedentemente associata allo stesso `client_id` nel file
`_client_emails.json`. Se trovata, la usa come fallback e invia comunque la notifica.
Il meccanismo è **difensivo**: copre scenari di fallimento UI preservando il consenso
esplicito (solo email già confermate in precedenza dallo stesso client).

File: `audiobook_app.py` funzioni `_load_client_emails()`, `_save_client_emails()`, `_lookup_client_email()`.
Consumato in `generation_engine.py:_send_completion_email()` e `run_generation()`.

### 3.3 Rate limiting e tracking client

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `MAX_CONCURRENT_PER_CLIENT` | da `ABM_MAX_CONCURRENT_PER_CLIENT` (default `2`) | `audiobook_app.py` | 112 |
| `MAX_CONCURRENT_LLM_PER_CLIENT` | da `ABM_MAX_CONCURRENT_LLM_PER_CLIENT` (default `1`) | `audiobook_app.py` | 152 |
| `_CLIENT_COOKIE_NAME` | `"abm_cid"` | `audiobook_app.py` | 115 |
| `_CLIENT_COOKIE_MAX_AGE` | `31536000` (1 anno in secondi) | `audiobook_app.py` | 116 |
| `_ANALYZE_RL_PER_MIN` | `5` upload `/api/analyze` / IP / minuto (sliding window) | `audiobook_app.py` | — |
| `_ANALYZE_RL_PER_HOUR` | `30` upload `/api/analyze` / IP / ora | `audiobook_app.py` | — |
| `_PREVIEW_RL_PER_MIN` | `20` preview `/api/preview_audio` / IP / minuto | `audiobook_app.py` | — |
| `_PREVIEW_RL_PER_HOUR` | `200` preview `/api/preview_audio` / IP / ora | `audiobook_app.py` | — |

Override env var: `ABM_ANALYZE_RL_PER_MIN`, `ABM_ANALYZE_RL_PER_HOUR`, `ABM_PREVIEW_RL_PER_MIN`, `ABM_PREVIEW_RL_PER_HOUR`. Oltre soglia risponde `429` con `retry_after` in secondi.

### 3.3.1 Sicurezza applicativa (CSRF, HSTS, archivi, MIME)

| Parametro | Valore default | Env var | File | Riga |
|-----------|----------------|---------|------|------|
| `ZIP_MAX_ENTRY_UNCOMPRESSED` | `200` MB per entry uncompressed | `ABM_ZIP_MAX_ENTRY_MB` | `secure_archive.py` | 16 |
| `ZIP_MAX_TOTAL_UNCOMPRESSED` | `500` MB totale uncompressed | `ABM_ZIP_MAX_TOTAL_MB` | `secure_archive.py` | 18 |
| `ZIP_MAX_COMPRESSION_RATIO` | `200` (uncompressed/compressed) | `ABM_ZIP_MAX_RATIO` | `secure_archive.py` | 20 |

- **CSRF**: `_csrf_protect()` before_request hook valida `Origin`/`Referer` su ogni `POST/PUT/PATCH/DELETE`. Richieste cross-site da browser bloccate con `403`. Richieste senza `Origin` e senza `Referer` (curl, mobile app) passano (CSRF richiede browser+cookie).
- **HSTS**: header `Strict-Transport-Security: max-age=31536000; includeSubDomains` aggiunto da `add_security_headers()` solo se `request.is_secure` (richiede TLS termination corretto via `ProxyFix`).
- **Zip-safety**: `secure_archive.py` centralizza protezione zip-slip (`safe_zip_path`), zip-bomb (`check_zip_bomb`) e XXE (`safe_xml_fromstring` via `defusedxml`). Applicato a parsing EPUB (`epub_to_tts.py`, `audio_utils.py`) e ABM (`generation_engine.py`). Override soglie via env var sopra. Errori sollevano `ZipSafetyError`.
- **MIME validation upload**: `/api/analyze` legge i primi 8 byte del file salvato e valida magic bytes contro l'estensione dichiarata (EPUB/ABM → `PK\x03\x04`, PDF → `%PDF-`, TXT → no NUL byte tranne BOM UTF-16). Bypass extension blacklist + protezione storage abuse.
- **CSV injection export**: `_csv_safe(val)` prefissa con apostrofo (`'`) qualunque cella che inizi con `= + - @ \t \r` per neutralizzare formula execution in Excel/LibreOffice. Applicato in `/admin/log-activity/export` (sia CSV fallback sia XLSX) per i campi user-controllabili (filename, voice, browser_lang, client_id, client_ip, last_op, events, sid).
- **Atomic JSON write**: `_payments.json`, `_vouchers.json`, `_download_tokens.json` scritti via tmpfile + `fsync` + `os.replace()` per evitare file corrotti su crash a metà write.
- **Legacy job warning**: `_check_job_ownership()` logga `[SECURITY-WARN] Legacy job senza client_id` quando un job pre-enforcement viene acceduto. Permette monitor della coorte legacy in vista di future restrizioni.

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
- **Idempotenza capture**: `payment.capture_and_store_order(order_id)` acquisisce `_capture_lock` (global), verifica se il record esiste già (idempotency cache), altrimenti chiama PayPal API. 5+ thread concorrenti producono 1 sola chiamata API.
- **Amount reconciliation**: `_pending_orders` traccia in-memory `{order_id: amount_requested_eur, purpose, ts}` registrato in `_paypal_create_order`. Al capture, l'importo PayPal viene confrontato con il pending (tolerance 0.01 EUR); mismatch → `CaptureAmountMismatchError`. Difende contro tampering del cliente sull'importo. TTL pending: 1h (cleanup automatico).
- **PayPal mode mandatory**: `ABM_PAYPAL_MODE` (`sandbox` | `live`) **obbligatorio** se `ABM_PAYPAL_CLIENT_ID` è settato. Module-level `RuntimeError` al boot se mancante o invalido. Difende contro deploy accidentale in sandbox in produzione.
- **Refund bonus disabilitato su cancel volontario**: `generation_engine._refund_job_payment(reason=...)` passa `apply_bonus=(reason != "cancel")` a `_create_voucher`. Cancel volontario → rimborso 1:1, NON bonus. Bonus +10% riservato a fallimenti piattaforma (errore/eccezione) per evitare abuso "cancel per bonus".
- **Ricevuta email**: inviata automaticamente post-capture al payer email PayPal.
- **GDPR**: dati pagamento conservati `ABM_PAYMENT_RETENTION_DAYS` giorni (default 24 mesi) per compliance fiscale.
- **Endpoint diagnostico**: `GET /api/paypal_debug_order/<order_id>` per ispezionare un ordine via API PayPal v2.

**Sicurezza voucher (hardening anti-forgery):**

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `VOUCHER_RL_PER_MIN` | `5` tentativi voucher_validate / IP / minuto | `payment.py` | 108 |
| `VOUCHER_RL_PER_HOUR` | `30` tentativi voucher_validate / IP / ora | `payment.py` | 109 |
| `VOUCHER_EMAIL_FAIL_LIMIT` | `10` fallimenti consecutivi per email prima del lockout | `payment.py` | 110 |
| `VOUCHER_EMAIL_LOCKOUT_SEC` | `900` (15 min di lockout email) | `payment.py` | 111 |
| `ABM_VOUCHER_GLOBAL_PER_MIN` | `100` tentativi/min TOTALI sul processo (safety net distributed scan) | `payment.py` | 115 |
| `ABM_VOUCHER_GLOBAL_PER_HOUR` | `1000` tentativi/ora TOTALI sul processo | `payment.py` | 116 |

- **Rate limit**: `/api/voucher_validate` protetto da sliding window per IP, per email (lockout temporaneo) e globale (burst cap). Oltre soglia risponde `429` con header `Retry-After` e `reason` (`rate_limit_ip_minute` | `rate_limit_ip_hour` | `email_locked` | `rate_limit_global_minute` | `rate_limit_global_hour`).
- **Log strutturato**: ogni tentativo genera un evento `VOUCHER_ATTEMPT` (o `VOUCHER_ATTEMPT_BLOCKED:<reason>`) nel log attività mensile, con IP, codice mascherato e outcome (`OK`, `NOT_FOUND`, `USED`, `EXPIRED`, `EMAIL_MISMATCH`, `MISSING_FIELDS`).
- **Schema voucher esteso**: ogni record ha `kind` (`refund` | `promo` | `gift`), `note` (≤500 char), `created_by` (`auto_refund` | `admin`). I voucher generati da CLI usano prefisso `PROMO-` o `GIFT-` per distinguerli a colpo d'occhio.
- **CLI amministrativa**: `scripts/admin_voucher.py` (zero superficie web) con sottocomandi `create`, `list`, `revoke`, `show`. Opera direttamente su `_vouchers.json` in `ABM_DATA_DIR` e logga ogni operazione in `voucher_admin.log`. Esempio: `python scripts/admin_voucher.py create --email user@ex.com --amount 2 --days 180 --kind promo --note "campagna lancio"`.
- **UI web admin** (`/admin/vouchers`): interfaccia grafica protetta da `ABM_ADMIN_TOKEN`. Se la env var è vuota l'endpoint risponde `404` (feature disabilitata). Il token viene validato lato server con `hmac.compare_digest` e trasmesso dal browser via header `X-Admin-Token` (memorizzato solo in `sessionStorage`). Operazioni esposte: creazione voucher (`POST /admin/api/vouchers`), elenco (`GET /admin/api/vouchers`), revoca (`POST /admin/api/vouchers/<code>/revoke`). Ogni operazione logga eventi `ADMIN_VOUCHER_CREATE:<kind>` / `ADMIN_VOUCHER_REVOKE`. `/admin/` è escluso da `robots.txt` (`noindex, nofollow` anche via header).

| Parametro env | Default | Scopo |
|---------------|---------|-------|
| `ABM_ADMIN_TOKEN` | *(vuoto → UI disabilitata)* | Token segreto per accedere a `/admin/vouchers` |
- **Gitignore**: `_vouchers.json`, `_payments.json`, `voucher_admin.log` esclusi esplicitamente da git per prevenire commit accidentali (in aggiunta a `data/`).

### 3.6.2 Traduzione libro

Parametri per la funzionalità di traduzione del testo del libro in un'altra lingua, gestita da `translation_core.py` (libreria condivisa tra CLI e web app) e `payment.py` (calcolo costo).

**Tariffe (web app + CLI)**

| Parametro | Valore default | File | Riga |
|-----------|----------------|------|------|
| `ABM_TRANSLATE_COST` | `3.0` (EUR per 1M caratteri input traduzione; accetta virgola decimale) | `payment.py` | 54–55 |
| `ABM_TRANSLATE_MIN_COST` | `1.5` (floor EUR sul totale dovuto, applicato solo quando si paga; gratis sotto soglia `ABM_LLM_FREE_THRESHOLD_EUR`) | `payment.py` | 56–57 |

**Formula di pricing** (funzione `_estimate_translation_cost_eur` in `payment.py:75`):

```
raw = chars / 1M × ABM_TRANSLATE_COST
      (+ chars / 1M × ABM_LLM_RATE_EUR_PER_MCHAR  se ottimizzazione AI attiva)
se raw ≤ ABM_LLM_FREE_THRESHOLD_EUR → gratis (due = 0)
altrimenti due = max(raw, ABM_TRANSLATE_MIN_COST)
```

**Backend LLM (web app e CLI — `translation_core.py`)**

I parametri `ABM_TRANSLATE_*` hanno fallback sui corrispettivi `ABM_LLM_*`; se non impostati, usano i default sotto.

| Parametro | Valore default | Env var fallback | File | Riga |
|-----------|----------------|-----------------|------|------|
| `ABM_TRANSLATE_API_KEY` | *(vuoto)* | `ABM_LLM_API_KEY` | `translation_core.py` | 54–55 |
| `ABM_TRANSLATE_API_BASE` | `https://api.deepseek.com` | `ABM_LLM_API_BASE` | `translation_core.py` | 58–60 |
| `ABM_TRANSLATE_MODEL` | `deepseek-chat` | `ABM_LLM_MODEL` | `translation_core.py` | 63–64 |
| `ABM_TRANSLATE_BACKEND` | `auto` (`auto`\|`openai`\|`vertex`) — `auto` preferisce Vertex se `ABM_GCP_PROJECT_ID` + credentials disponibili, altrimenti OpenAI-compat | — | `translation_core.py` | 67–68 |
| `ABM_TRANSLATE_VERTEX_LOCATION` | `global` | — | `translation_core.py` | 79–80 |
| `ABM_TRANSLATE_CHUNK_CHARS` | `20000` (caratteri max per chunk di testo inviato all'LLM) | — | `translation_core.py` | 98–99 |
| `ABM_TRANSLATE_MAX_RETRIES` | `4` (tentativi per chunk con backoff esponenziale) | — | `translation_core.py` | 102–103 |
| `ABM_TRANSLATE_TEMPERATURE` | `0.3` | — | `translation_core.py` | 106–107 |
| `ABM_TRANSLATE_REQUEST_TIMEOUT_SEC` | `300` (secondi per chiamata LLM singola) | — | `translation_core.py` | 110–111 |

**Report costi (solo CLI — `scripts/translate_abm.py`)**

Variabili usate esclusivamente dal report di costo post-esecuzione del CLI (non influenzano il prezzo web app).

| Parametro | Valore default | File | Riga |
|-----------|----------------|------|------|
| `ABM_TRANSLATE_INPUT_USD_PER_MTOK` | `0.10` (USD / 1M token input — calibrato su gemini-2.5-flash-lite) | `scripts/translate_abm.py` | 37 |
| `ABM_TRANSLATE_OUTPUT_USD_PER_MTOK` | `0.40` (USD / 1M token output) | `scripts/translate_abm.py` | 38 |
| `ABM_TRANSLATE_USD_EUR_RATE` | `0.86` (tasso di conversione USD → EUR per il report) | `scripts/translate_abm.py` | 39 |

### 3.6 LLM (ottimizzazione testo per TTS) — engine-agnostic

Tutti i parametri sono `ABM_LLM_*` env-driven. Default tarati su DeepSeek-Chat (provider attuale) ma sostituibili senza modifiche al codice.

| Parametro | Valore default | Env var | File | Riga |
|-----------|----------------|---------|------|------|
| `LLM_API_KEY` | *(empty)* | `ABM_LLM_API_KEY` | `generation_engine.py` | 77 |
| `LLM_API_BASE` | `https://api.deepseek.com` | `ABM_LLM_API_BASE` | `generation_engine.py` | 78 |
| `LLM_MODEL` | `deepseek-chat` | `ABM_LLM_MODEL` | `generation_engine.py` | 79 |
| `LLM_THINKING` | `False` | `ABM_LLM_THINKING` | `generation_engine.py` | 82 |
| `LLM_REASONING_EFFORT` | `none` | `ABM_LLM_REASONING_EFFORT` | `generation_engine.py` | 83 |
| `LLM_TEMPERATURE` | `0.3` | `ABM_LLM_TEMPERATURE` | `generation_engine.py` | 84 |
| `LLM_MAX_TOKENS` | `65536` (~195k char/chunk) | `ABM_LLM_MAX_TOKENS` | `generation_engine.py` | 85 |
| `LLM_CHARS_PER_TOKEN` | `3.5` | `ABM_LLM_CHARS_PER_TOKEN` | `generation_engine.py` | 88 |
| `LLM_MAX_CONTEXT_TOKENS` | `1000000` | `ABM_LLM_MAX_CONTEXT_TOKENS` | `generation_engine.py` | 89 |
| `LLM_RESERVED_PROMPT_TOKENS` | `4000` | `ABM_LLM_RESERVED_PROMPT_TOKENS` | `generation_engine.py` | 90 |
| `LLM_OUTPUT_SAFETY_MARGIN` | `0.85` | `ABM_LLM_OUTPUT_SAFETY_MARGIN` | `generation_engine.py` | 91 |
| `LLM_REQUEST_TIMEOUT_SEC` | `120.0` | `ABM_LLM_REQUEST_TIMEOUT_SEC` | `generation_engine.py` | 94 |
| `LLM_MAX_RETRIES` | `4` (backoff esponenziale `2**attempt`) | `ABM_LLM_MAX_RETRIES` | `generation_engine.py` | 95 |
| `LLM_INTER_CHUNK_SLEEP_SEC` | `0.5` | `ABM_LLM_INTER_CHUNK_SLEEP_SEC` | `generation_engine.py` | 96 |
| `LLM_HEARTBEAT_TIMEOUT_SEC` | `60.0` (auto-cancel solo interactive) | `ABM_LLM_HEARTBEAT_TIMEOUT_SEC` | `generation_engine.py` | 97 |
| `LLM_TRIVIAL_INPUT_MIN_CHARS` | `80` (sotto soglia, o single-line < 2× senza punteggiatura terminale → pass-through, no LLM call. Antidoto a prompt-leak su input banali) | `ABM_LLM_TRIVIAL_INPUT_MIN_CHARS` | `generation_engine.py` | 100 |
| `LLM_LEAK_MAX_RETRIES` | `2` (retry anti-leak con `temperature` +0.1 per attempt capped 1.0, `reasoning_effort="none"`, thinking off. Budget indipendente da `LLM_MAX_RETRIES` transient. Esauriti → raise `_PromptLeakError` → fallback originale + audit JSONL) | `ABM_LLM_LEAK_MAX_RETRIES` | `generation_engine.py` | 101 |
| `LLM_RESERVED_OUTPUT_TOKENS` | derived = `LLM_MAX_TOKENS` | — | `generation_engine.py` | 100 |
| `LLM_MAX_INPUT_TOKENS` | derived = ~930k | — | `generation_engine.py` | 101 |
| `LLM_MAX_INPUT_CHARS` | derived = ~3.26M | — | `generation_engine.py` | 102 |
| `LLM_SAFE_OUTPUT_CHUNK` | derived = `MAX_TOKENS × CHARS_PER_TOKEN × SAFETY_MARGIN` ≈ 195k char | — | `generation_engine.py` | 106 |

Errori transient gestiti da retry: `ReadError`, `ConnectError`, `ConnectTimeout`, `ReadTimeout`, `RemoteProtocolError`, `APIConnectionError`, `APITimeoutError`.

### 3.4 Generazione audio

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `CHUNK_MAX_CHARS` | `2000` (caratteri max per chunk TTS) | `tts_split.py` | 38 |
| `ABM_EDGE_TTS_TIMEOUT` | `120` (secondi, timeout per singola chiamata edge-tts via `asyncio.wait_for` su `communicate.save()`. Necessario perché edge-tts non applica `receive_timeout` alla websocket — `ws_connect` aiohttp senza timeout: una connessione half-open lascerebbe il job sospeso per sempre senza errori, incidente 2026-06-11. Allo scadere: `TimeoutError` → retry/backoff esistente → fallback silenzio) | `tts_split.py` | 45 |
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
- `optimized` → **retention per-job dal `opt_completed_at`**: `EMAIL_FILE_RETENTION_SEC` (default 18h, `ABM_JOB_RETENTION_SEC`) per voci standard, `GEMINI_FILE_RETENTION_SEC` (default 48h, `ABM_GEMINI_JOB_RETENTION_SEC`) quando `job["voice"]` inizia per `gemini:`. Selezione via `_retention_for_job(job)`. Indipendente dalla presenza di email registrata e dallo stato del browser. Garantisce che il bottone "Scarica progetto ottimizzato (.abm)" nell'UI continui a funzionare per il periodo configurato dalla fine dell'ottimizzazione AI, allineando lo scenario interactive a quello batch-email.
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
| `ABM_GEMINI_API_KEY` | *(vuoto)* | Se vuoto e backend non risolve a Vertex, Gemini TTS è disabilitato. Usato dal backend `apikey` (e fallback in modalità `auto`). |
| `ABM_GEMINI_BACKEND` | `auto` | Selettore backend Gemini TTS: `vertex` \| `apikey` \| `auto`. `auto` preferisce Vertex se config completa (project + credentials), altrimenti cade su API key. `vertex` forza Vertex (richiede `ABM_GCP_PROJECT_ID` + `ABM_GOOGLE_CREDENTIALS_FILE`). `apikey` forza API key. File: `gemini_tts.py:_resolve_backend` (linea ~97). |
| `ABM_GCP_PROJECT_ID` | *(vuoto)* | ID progetto GCP che ospita le API Vertex AI e Cloud TTS. Richiesto se `ABM_GEMINI_BACKEND=vertex` (o auto-risolto a Vertex). Esempio: `audiobook-maker-496208`. File: `gemini_tts.py:_vertex_project`. |
| `ABM_VERTEX_LOCATION_FLASH25` | `global` | Region Vertex per il modello `gemini-2.5-flash-tts` (GA). Default `global`: routing automatico latency-aware. Pinnare `us-central1` se servono quote dedicate. File: `gemini_tts.py:_resolve_location` (`GEMINI_MODELS["flash25"]["location_vertex"]`). |
| `ABM_VERTEX_LOCATION_FLASH31` | `us-central1` | Region Vertex per `gemini-3.1-flash-tts-preview`. Solo `us-central1` supporta il modello preview (verificato 2026-05-26 via `models.list()`). File: `gemini_tts.py:_resolve_location` (`GEMINI_MODELS["flash31"]["location_vertex"]`). |
| `ABM_GEMINI_USE_VERTEX` | `false` | **DEPRECATED** (2026-05-26): sostituita da `ABM_GEMINI_BACKEND=vertex` + `ABM_GCP_PROJECT_ID` + `ABM_GOOGLE_CREDENTIALS_FILE`. Mantenuta per back-compat ma non più letta da `gemini_tts.py` dopo la migrazione Vertex (vedi `md_files/ttsgemini.md`). |
| `ABM_GEMINI_VERTEX_CREDENTIALS_FILE` | *(vuoto)* | **DEPRECATED** (2026-05-26): sostituita da `ABM_GOOGLE_CREDENTIALS_FILE` (unico path JSON service account per Vertex AI Gemini TTS + Google Cloud TTS). Mantenuta per back-compat ma non più letta da `gemini_tts.py` dopo la migrazione Vertex (vedi `md_files/ttsgemini.md`). |

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

### 7.4.1 Stima token audio (calibrazione margine)

Token audio output per secondo, per-modello con fallback globale. Usato da `estimate_output_tokens()` → `estimate_book_cost()`. Una sottostima di questo valore causa margine % a consuntivo inferiore al `MARGIN_PERCENT` configurato (il prezzo viene lockato su costo stimato, ma il costo reale è più alto). Ricalibrazione: `= output_tokens_actual / audio_seconds_actual` medio dei record `completed` per quel modello in `/admin/audit-tts`.

| Variabile | Default |
|-----------|---------|
| `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND` | `25.0` (fallback globale, conservativo) |
| `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH25` | `25.0` (da verificare con dati reali) |
| `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH31` | `29.0` (calibrato empiricamente) |

Ordine di risoluzione: `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_<MODEL>` → `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND` → default hardcoded.

### 7.5 Limiti e anti-abuso

| Variabile | Default |
|-----------|---------|
| `ABM_GEMINI_PREVIEW_CAP_PER_DAY` | `3` (preview free per cookie, rolling 24h) |
| `ABM_GEMINI_MAX_BYTES_PER_CALL` | `8000` (target qualita` UTF-8 sul **testo da sintetizzare** — soft cap: oltre questa soglia Gemini TTS degrada acusticamente; sopra soglia `synthesize()` logga warning ma procede. NB: i prefissi style/rate aggiunti internamente sono *direttive di prompt*, non testo audio, e non concorrono al conteggio) |
| `ABM_GEMINI_API_HARD_BYTES_CAP` | `8000` (hard cap UTF-8 sul **payload completo** testo+prefissi inviato all'API; sopra soglia `synthesize()` solleva `ValueError`. E` il vero limite tecnico API, distinto dal target qualita`) |
| `ABM_GEMINI_CHUNK_CHARS` | `700` (chunk size globale — chunk piccoli per stabilita` acustica, richiede Tier 2/3) |
| `ABM_GEMINI_MAX_CHUNK_CHARS_<LANG>` | override per lingua, vince su `ABM_GEMINI_CHUNK_CHARS` (es. `ABM_GEMINI_MAX_CHUNK_CHARS_IT=850`) |
| `ABM_GEMINI_TEMPERATURE` | `0.75` (temperature passata al modello — abbassa la deriva metallica sui chunk lunghi) |
| `ABM_GEMINI_INTER_CHUNK_GAP_MS` | `100` (silenzio PCM in ms inserito tra chunk consecutivi in concat. Default abbassato da 250 a 100 perche` i chunk Gemini hanno gia` trailing silence naturale che ora viene trimmato — sommare 250 ms creava pause percepibili di "qualche secondo" all'inizio del libro) |
| `ABM_GEMINI_TRIM_TAIL_MS` | `800` (cap massimo in ms di silenzio finale da rimuovere a ogni PCM chunk Gemini prima della concat — riduce le pause percepibili tra chunk consecutivi. `0` disabilita il trim. Implementazione: `audio_utils.trim_pcm_trailing_silence()`) |
| `ABM_GEMINI_TRIM_TAIL_THRESHOLD` | `200` (soglia ampiezza int16 assoluta sotto cui un sample e` considerato "silenzio" durante il trim; 200 ≈ -44 dB. Range 0-32767. Valori troppo alti rischiano di tagliare l'attacco/coda di parola) |
| `ABM_GEMINI_HTTP_TIMEOUT_MS` | `25000` (timeout HTTP in ms per le call su modello **`flash25`**; applicato per-call via `GenerateContentConfig.http_options=HttpOptions(timeout=...)`. Per preview il ThreadPoolExecutor timeout di 30s funge da secondo limite) |
| `ABM_GEMINI_HTTP_TIMEOUT_MS_FLASH31` | `60000` (timeout HTTP in ms per le call su modello **`flash31`** — `gemini-3.1-flash-tts-preview`. Piu` lento di flash25 lato Google: RPM cap 3/300 vs 10/750 + audio gen piu` lenta. Senza maggiorazione i chunk normali finiscono in 504 `DEADLINE_EXCEEDED`. Selezione automatica via `_http_timeout_ms(model_key)` in `gemini_tts.py:1161`) |
| `ABM_GEMINI_PREVIEW_TIMEOUT_SEC_FLASH31` | `65` (timeout in **secondi** del `ThreadPoolExecutor` wrapper in `/api/preview_audio` per modello `flash31`; vedi `audiobook_app.py:4934`. Deve essere ≥ HTTP timeout flash31 + buffer per non strozzare la call Google. flash25 resta hardcoded a 30s. Client JS legge il voice id e usa 70s sopra flash31 / 35s sopra flash25) |
| `ABM_GEMINI_RATE_MODE` | `prompt` |
| `ABM_GEMINI_MAX_FAILED_RATIO` | `0.05` (oltre questa frazione di chunk falliti il job va in `partial`) |
| `ABM_GEMINI_REFUND_FAILED_RATIO` | `0.0` (oltre questa frazione il job va in `error` con refund integrale — `0.0` = qualsiasi chunk silenziato innesca il refund; impostare `>1` per disabilitare) |
| `ABM_GEMINI_FORENSIC_RETENTION_DAYS` | `7` (giorni di retention forense della `work_dir` per i job Gemini falliti con refund — `kind` ∈ `quality`/`quota`/`budget`/`preflight`/`generic`. Marker JSON `.forensic_retain.json` scritto da `generation_engine._write_forensic_marker()` invocato in `_admin_alert_gemini_failure()` (linea ~1123); gate `audiobook_app._forensic_marker_protects()` (linea ~8956) applicato a `_cleanup_job` e ai tre branch orphan del cleanup loop. Sopravvive a restart del service. `0` = disabilita la retention forense (dir cancellata immediatamente al passaggio a `status=error`). La mail admin (`email_service._admin_notify_gemini_failure`) include link a `/admin/job/<job_id>/forensic.zip` — endpoint Flask `audiobook_app.admin_forensic_zip` che zippa on-the-fly la dir, gated da `ABM_ADMIN_TOKEN` via cookie HttpOnly o header `X-Admin-Token`) |
| `ABM_GEMINI_CANCEL_LOCK_PCT` | `70` (soglia % di progresso oltre cui il cancel volontario di un job PREMIUM viene rifiutato da `/api/cancel` con HTTP 409 `cancel_locked_progress` + campo `lock_pct`; vedi `audiobook_app.py:5717`. Range valido `(0..100)`; valori `<=0` o `>=100` disabilitano il lock. Il client `static/js/app.js` disabilita preventivamente il pulsante "Cancel" sopra la stessa soglia hardcoded `_GEMINI_CANCEL_LOCK_PCT_CLIENT=70`; allineare se si cambia il server) |

### 7.6 Note operative

- **Requisito**: Gemini Tier 2 o 3 (RPD elevato). Il default `ABM_GEMINI_CHUNK_CHARS=700` privilegia stabilita` acustica e prosodia uniforme sul numero di richieste; un libro medio genera centinaia di chunk e satura rapidamente i 100 RPD/modello del Tier 1.
- Voice ID formato: `gemini:<model_key>:<voice_name>` (es. `gemini:flash25:Zephyr`).
- Modelli supportati: `flash25` (Gemini 2.5 Flash TTS), `flash31` (Gemini 3.1 Flash TTS).
- 30 voci prebuilt × 2 modelli = 60 entry per lingua UI.
- Chunk max chars: `700` globale, override per lingua via `ABM_GEMINI_MAX_CHUNK_CHARS_<LANG>` (es. `ABM_GEMINI_MAX_CHUNK_CHARS_IT=850`).
- Quality tuning: `ABM_GEMINI_TEMPERATURE=0.75` riduce la deriva metallica, `ABM_GEMINI_INTER_CHUNK_GAP_MS=100` inserisce un micro-silenzio tra chunk consecutivi in PCM, e `ABM_GEMINI_TRIM_TAIL_MS=800` tronca il trailing silence naturale che ogni chunk Gemini porta con se` (la combinazione dei due elimina pause percepibili di "qualche secondo" tra chunk lasciando un boundary acustico naturale).
- Stato utilizzo persistito in `<ABM_DATA_DIR>/gemini_tts_usage.json`, preview cap in `gemini_tts_previews.json` (atomic write tmp+rename).
- **Kill-switch admin** persistito in `<ABM_DATA_DIR>/gemini_admin_state.json` (`{disabled, reason, updated_at}`). Quando `disabled=true`, `gemini_tts.is_available()` ritorna `False`: il pannello Voci PREMIUM scompare dalla UI utente, stime e pagamenti Premium rispondono 503. Toggle via `GET/POST /admin/api/gemini_kill_switch` o dalla pagina `/admin/audit-tts`. Stato ricaricato in `gemini_tts.init()` al boot.
- **Cancel volontario PREMIUM** (`generation_engine.py:2708+`): branch `_CancelledError` calcola `retained_eur` via `cancel_policy.compute_cancel_retention(google_cost, method, paid)` con floor = `provider_cost + fee_PayPal` (solo se metodo `paypal`). Esiti:
  - `retained > 0` → outcome audit `cancelled_partial`, refund parziale = `paid - retained`, MP3 parziale codificato dai `chunk_*.pcm` accumulati, token download creato, email `_send_gemini_cancelled_partial_email` (IT-only) inviata se email registrata e MP3 generato.
  - `retained == 0` → outcome audit `cancelled_refunded`, refund integrale, nessuna email custom (resta path legacy).
  - Refund PayPal → nuovo voucher bonus (codice in email); refund su voucher originale → riaccredito silenzioso.
  - Job campi popolati: `cancel_meta = {paid_eur, retained_eur, refund_eur, progress_pct, partial_audio_delivered}` + `partial_download_url` + `partial_download_token`. Esposti via SSE `/api/progress/<job_id>` (`audiobook_app.py:5643+`) per rendering UI client.
  - Soglia anti-abuso: oltre `ABM_GEMINI_CANCEL_LOCK_PCT` (default 70%) `/api/cancel` ritorna HTTP 409 con `lock_pct`, il client mostra modal informativo invece di cancellare.

### 7.7 Audit log dei costi (`gemini_cost_audit.py`)

Per ogni generazione TTS Premium completata, fallita o cancellata, viene scritto un record JSONL nel file mensile `<ABM_DATA_DIR>/gemini_cost_audit_YYYY-MM.jsonl` (append-only, lock per scrittura).

**Campi record (18 base + 5 condizionali su esito `cancelled_*`):**

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
| `outcome` | `completed` \| `failed_refunded` \| `cancelled_refunded` \| `cancelled_partial` \| `recovered_refunded` |
| `cancel_paid_eur` | (solo `cancelled_*`) Importo pagato dall'utente, copiato da `job["cancel_meta"]["paid_eur"]` |
| `cancel_retained_eur` | (solo `cancelled_*`) Trattenuto effettivo = costo provider + fee PayPal stimate (vedi `cancel_policy.compute_cancel_retention`) |
| `cancel_refund_eur` | (solo `cancelled_*`) Refund = `paid - retained` |
| `cancel_progress_pct` | (solo `cancelled_*`) % progresso al momento del cancel |
| `cancel_partial_audio_delivered` | (solo `cancelled_*`) Bool: MP3 parziale consegnato all'utente via token download |

**Retention:** manuale — i file sono piccoli (qualche KB/mese a regime). Ruotare/archiviare a discrezione admin.

**Parametri di tuning:** se `delta_pct_avg` si discosta sistematicamente (vedi `/admin/logs` → "Audit Gemini" → "Calcola parametri suggeriti"), valutare:
- aumento margin_percent del modello se delta negativo (`ABM_GEMINI_<model>_MARGIN_PERCENT`)
- riduzione tariffa utente se delta positivo eccessivo
- adeguamento del rapporto chars/secondi (tabella `_SEC_PER_KCHARS_BY_LANG` in `gemini_tts.py`) se la stima ex-ante diverge dalla realtà

**Persistenza job pagati unificata:** dalla v3.13.x, sia i pagamenti per Ottimizzazione testo AI sia quelli per voci Premium sono tracciati in `<ABM_DATA_DIR>/_paid_jobs_done.json` (campo `purpose`: `"llm"` o `"gemini"`). La migrazione del vecchio `_paid_opt_done.json` è automatica all'avvio (backup `.pre_unify_bak`).

---

## 8. Cold Storage S3 (tiering hot/cold)

| Variabile | Descrizione | Default | Sorgente |
|-----------|-------------|---------|----------|
| `ABM_S3_ENDPOINT` | Endpoint S3-compatible (Aruba/R2/B2). Vuoto = tiering disabilitato. | *(vuoto)* | storage_backend.py |
| `ABM_S3_ACCESS_KEY` | Access key ID | *(vuoto)* | storage_backend.py |
| `ABM_S3_SECRET_KEY` | Secret access key | *(vuoto)* | storage_backend.py |
| `ABM_S3_BUCKET` | Nome bucket | *(vuoto)* | storage_backend.py |
| `ABM_S3_REGION` | Region | `us-east-1` | storage_backend.py |
| `ABM_S3_KEY_PREFIX` | Prefisso di namespacing nel bucket | *(vuoto)* | storage_backend.py |
| `ABM_S3_PRESIGN_TTL_SEC` | Validità presigned URL (s) | `21600` (6h) | storage_backend.py |
| `ABM_HOT_WINDOW_SEC` | Finestra calda locale, voci standard (s) | `64800` (18h) | storage_tiering.py |
| `ABM_HOT_WINDOW_GEMINI_SEC` | Finestra calda locale, voci PREMIUM (s) | `172800` (48h) | storage_tiering.py |
| `ABM_OFFLOAD_QUIET_SEC` | Finestra di quiete (s): un output senza marker `.generation_complete` i cui file sono stati scritti da meno di N secondi è considerato in conversione e NON viene offloadato (gate anti race mid-write, vedi F1) | `180` | generation_engine.py |

**Default voluti:** la finestra calda parte uguale alla retention attuale (18h/48h),
così all'inizio i file vivono in locale esattamente come oggi; nessuna eviction
anticipata. Si restringe `ABM_HOT_WINDOW_*` man mano per liberare disco prima.

**Retention totale (disponibilità utente):** base `ABM_JOB_RETENTION_SEC` (18h) /
`ABM_GEMINI_JOB_RETENTION_SEC` (48h), **indipendente dal cold storage**. Il cold
S3 decide solo *dove* si serve il file (locale durante la finestra calda, presigned
URL dopo), non *quanto* resta disponibile: con S3 attivo o disattivo la finestra è
identica. (Nota storica: fino al 2026-06 esisteva un `COLD_RETENTION_MULTIPLIER=2`
che raddoppiava la retention con S3 attivo; rimosso per disaccoppiare il tiering
dalla durata.) **Unica eccezione**: la protezione no-download per voci PREMIUM
(`GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER=2`, audiobook_app.py): un job/token
PREMIUM mai scaricato vive **48h×2 = 96h**; voci standard e PREMIUM già scaricati
non vengono mai estesi. Il testo email di completamento (`retention_h`) mostra la
base (24h/48h prod), non l'estensione no-download (salvaguardia a valle, non promessa).

Con tiering attivo i file vivono in locale solo per la finestra calda; oltre,
sono serviti via redirect dal cold storage fino alla retention totale. Egress
addebitato dal provider (con presigned i byte vanno storage→utente).

**Architettura:** `storage_backend.py` (primitive S3 via boto3, multipart upload
automatico, presigned URL) è l'unico punto provider-specifico; `storage_tiering.py`
contiene la logica caldo/freddo (chiave = path relativo a ABM_DATA_DIR, finestra,
marker `.cloud_uploaded` e `.generation_complete`). Upload async dopo `done`;
evacuazione locale a fine finestra calda solo se l'oggetto è confermato su S3;
delete cold a fine retention totale (escluso per job sotto retention forense).

**Invarianti anti-corruzione cold (post-incidente 2026-06):**
- **F1 — offload gated sul completamento generazione.** Lo sweep `_reconcile_cold_offload` e `_offload_to_cloud` NON caricano un `output*` mentre la conversione M4B è in corso (un m4b mid-write non ha ancora l'atom `moov` finale). Gate: marker `.generation_complete` (scritto a COMPLETE dopo l'assemblaggio) **oppure**, per output pre-marker, nessuna scrittura sui file da almeno `ABM_OFFLOAD_QUIET_SEC`. Il reconcile salta inoltre i job ancora `generating`.
- **F3 — eviction copy-verify by size.** `_evict_hot_local` cancella il file locale solo se `storage_backend.object_size(key) == size(locale)`; un cold troncato (size diversa) esiste ma NON autorizza la cancellazione → ri-upload del locale completo, ri-verifica size, poi delete.

---

## 9. Versione (`version.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `__version__` | `"3.13.0"` | `version.py` | 7 |
| `__updated_date__` | Dinamico: `datetime.now().strftime("%Y-%m")` | `version.py` | 10 |

---

## 10. SEO Content (`seo_content.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `_URL_RE` | Regex compilata per rilevamento URL nel testo | `seo_content.py` | 31 |
| `_CONTENT` | Dict con contenuti SEO visibili per 6 lingue | `seo_content.py` | 43 |

---

## 11. Nuovi moduli (v3.8.0)

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

## 12. Community widget (v3.13.0)

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

## 13. Recupero job batch interrotti (`pending_jobs.py`)

I job **batch** (con email registrata) vivono solo in memoria; un riavvio/deploy li perderebbe. Per recuperarli, ogni job batch viene descritto in un file su `ABM_DATA_DIR`:

| File | Contenuto |
|------|-----------|
| `_pending_jobs.json` | Descrittori dei job batch in volo (id, phase `optimize\|generate`, attempts, state, input path, parametri TTS, notify_*, payment). Riusa `community_store.JsonStore`: write atomico tmp+rename, lock per file, backup `.bak`. |
| `_pending_jobs.json.bak` | Backup automatico della versione precedente |

Ciclo di vita del descrittore: **scritto** quando il job diventa batch (`/api/register_email`, submit batch di `/api/optimize`); **finalizzato/rimosso** quando la mail finale parte con successo (`_send_completion_email` e l'email optimize-only in `generation_engine.py`). Al boot, `_recover_orphan_jobs()` (thread one-shot in `_ensure_background_threads`) legge gli orfani, incrementa `attempts` su disco **prima** di rilanciare (crash-safe), ricostruisce il job ri-parsando l'input (riusa l'`.abm` ottimizzato se presente, saltando l'LLM) e respawna `run_optimization`/`run_generation`. Oltre `ABM_RECOVER_MAX_ATTEMPTS` tentativi → rimborso secondo policy esistente (voucher → riaccredito silenzioso; PayPal → nuovo voucher in mail) + mail "interrotto" + `state=failed`.

---

## Riepilogo

| Categoria | Numero parametri |
|-----------|:---:|
| Variabili d'ambiente (`ABM_*`) | 23 |
| Configurazione Flask | 1 |
| Costanti applicative (`audiobook_app.py`) | 28 |
| Costanti parsing EPUB (`epub_to_tts.py`) | 12 |
| Costanti parsing PDF (`pdf_to_tts.py`) | 8 |
| Google Cloud TTS (`google_tts.py`) | 5 |
| Gemini TTS (`gemini_tts.py`) | 15 |
| Versione (`version.py`) | 2 |
| SEO Content (`seo_content.py`) | 2 |
| Nuovi moduli v3.8.0 | 6 |
| **Totale** | **102** |
