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
| `ABM_MAX_CONCURRENT_GLOBAL` | `6` (tetto GLOBALE d'istanza di generazioni simultanee, tutti i client; `0` = illimitato). Superato, `/api/generate` e `/api/paypal_create_order_gemini` rispondono `429` con `error_code: server_busy` **prima** di chiedere qualunque pagamento | `audiobook_app.py` | 588 |
| `ABM_MAX_CONCURRENT_ASSEMBLY` | `max(1, cpu_count() - 1)` (encode FFmpeg finali ammessi in parallelo: PCM→AAC/MP3, MP3→M4B, ZIP). Non rifiuta job: li mette in coda | `assembly_queue.py` | 50 |
| `ABM_ASSEMBLY_WAIT_TIMEOUT_SEC` | `1800` (attesa massima di uno slot di assembly; scaduta, il job procede comunque senza slot) | `assembly_queue.py` | 37 |
| `ABM_ASSEMBLY_STARVE_SEC` | `900` (secondi in coda oltre i quali un job pesa quanto un PREMIUM: anti-starvation dei job gratuiti scavalcati dai pagati. `0` = priorita' pura, nessuna promozione) | `assembly_queue.py` | 87 |
| `ABM_MEM_LOG_INTERVAL_SEC` | `300` (intervallo della riga `[mem]` nel cleanup loop) | `audiobook_app.py` | 15013 |
| `ABM_MEM_WARN_AVAIL_MB` | `300` (sotto questa `MemAvailable` scatta WARN + evento `MEMORY_PRESSURE`) | `audiobook_app.py` | 15014 |
| `ABM_MEM_WARN_SWAP_PCT` | `80` (sopra questa percentuale di swap usata scatta WARN + evento `MEMORY_PRESSURE`) | `audiobook_app.py` | 15015 |
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
| `ABM_LLM_MIN_COST_EUR` | `1.0` (floor EUR sull'importo dovuto per l'ottimizzazione AI **standalone**, applicato solo quando la stima supera `ABM_LLM_FREE_THRESHOLD_EUR`; sotto soglia resta gratis; non si applica alla quota LLM dei pagamenti combinati con voci PREMIUM) | `payment.py` | 58–62 |
| `ABM_LLM_COST_USD_PER_MTOK` | `0.18` (Costo provider LLM per l'ottimizzazione AI del testo — parametro **unico blended in USD** per 1M token TOTALI prompt+completion; assorbe mix input/output e token in cache; convertito in EUR con `ABM_GEMINI_USD_EUR_RATE`; base costo audit /admin/audit-premium) | `payment.py` | 68–69 |
| `ABM_FREE_QUOTA_EUR_PER_MONTH` | `2.00` (quota gratuita cumulativa per client, € di listino non fatturato per mese solare, sulle voci PREMIUM; `0` disattiva la feature) | `free_quota.py` | 40 |
| `ABM_PREMIUM_MIN_COST_EUR` | `0.50` (importo minimo addebitato a un job PREMIUM quando la quota gratuita mensile è esaurita) | `free_quota.py` | 168 |
| `ABM_VOUCHER_EXPIRY_DAYS` | `180` (giorni validità buono rimborso, = 6 mesi) | `audiobook_app.py` | 110 |
| `ABM_VOUCHER_BONUS_PERCENT` | `10` (% maggiorazione buono vs pagamento originale) | `audiobook_app.py` | 111 |
| `ABM_PAYMENT_RETENTION_DAYS` | `730` (24 mesi retention dati pagamento GDPR/fiscale) | `audiobook_app.py` | 112 |
| `ABM_AUTO_REFUND_UNUSED_CAPTURES` | `true` (se un capture PayPal viene incassato ma MAI consumato — `used=False`, es. avvio traduzione non partito per redirect mobile — e il job viene smaltito, emette automaticamente un voucher di rimborso all'email del pagante. Se `false`: marca solo `needs_manual_refund` e lascia all'admin il rimborso PayPal manuale) | `payment.py` | 64–66 |
| `ABM_UNUSED_CAPTURE_MIN_AGE_SEC` | `1800` (30 min; età minima di un capture non consumato prima di considerarlo abbandonato per detection/alert/auto-refund — evita di toccare un capture appena fatto ancora in attesa che parta `/api/translate`) | `payment.py` | 70–71 |
| `ABM_PRICE_LOCK_TTL_SEC` | `1800` (30 min; validità del **price lock**: l'importo quotato alla creazione dell'ordine PayPal resta il dovuto alla conferma, invece del ricalcolo live. Serve perché la stima TTS PREMIUM dipende da una media mobile empirica (`gemini_tts_rate_log.json`) che si muove fra pagamento e conferma: una deriva > 0,05 € mandava in 402 `invalid_payment` un utente già pagante, lasciando la capture orfana fino al purge "stale analyzed" → rimborso manuale. Il lock è registrato per `order_id` insieme alla firma degli input di prezzo — voce, capitoli, velocità, lingua, AI on/off — e non si applica se uno di questi cambia. Oltre il TTL si torna al ricalcolo live. Incidente 21/08/2026, job `N-RUN2qrc2blK82lRX_NdA`: 5,86 € pagati vs 6,00 € pretesi 40 s dopo) | `audiobook_app.py` | 666 |
| `ABM_PAYPAL_UNFUNDED_PENDING_REASONS` | `ECHECK,TRANSACTION_APPROVED_AWAITING_FUNDING,INTERNATIONAL_WITHDRAWAL,RECEIVING_PREFERENCE_MANDATES_MANUAL_ACTION,UNILATERAL,VERIFICATION_REQUIRED` (CSV dei `status_details.reason` PayPal che, su una capture con status `PENDING`, indicano fondi **non trasferiti**: la capture viene rifiutata e il servizio non erogato. I `PENDING` con reason non in lista — es. `PENDING_REVIEW`, revisione antifrode — restano accettati e vengono loggati come `WARN capture PENDING accettata`) | `payment.py` | 277–291 |
| `ABM_JOB_RETENTION_SEC` | `64800` (18 ore, retention elaborazioni completate e token download per voci standard) | `audiobook_app.py` | 300 |
| `ABM_GEMINI_JOB_RETENTION_SEC` | `172800` (48 ore, retention estesa per job con voci PREMIUM/Gemini — token download e cleanup loop usano questo valore quando `voice` inizia per `gemini:` o il token ha `is_gemini=True`. **Protezione no-download**: se un job/token PREMIUM non risulta mai scaricato (`job["downloaded_at"]` e `token_info["downloaded_at"]` entrambi vuoti) la retention effettiva è raddoppiata via `GEMINI_NO_DOWNLOAD_RETENTION_MULTIPLIER=2`, default 96h — vedi `_effective_retention_for_job` / `_effective_retention_for_token_info` in `audiobook_app.py`) | `audiobook_app.py` | 301 |
| `ABM_RECOVER_ENABLED` | `1` (abilita il recupero al boot dei job **batch** interrotti da un riavvio/deploy; `0\|false\|no\|off` per disabilitare). Letto in `_recover_orphan_jobs()`. | `audiobook_app.py` | — |
| `ABM_RECOVER_MAX_ATTEMPTS` | `2` (tentativi di recupero per job prima del fallback = rimborso secondo policy + mail "interrotto" + `state=failed`). Il contatore è persistito su disco **prima** di rilanciare (crash-safe) e azzerato al primo capitolo completato di un job recuperato. | `audiobook_app.py` | — |
| Descrittore recover — campi lingua | `_build_job_descriptor()` persiste `lang`, `opt_lang`, `gen_lang`, `browser_lang`, `platform`, `gemini_accent`; `_reenqueue_orphan()` li ripristina nel job ricostruito. Senza, il recovery post-restart perdeva la lingua e `run_optimization` cadeva sul default hardcoded `"it"` (prompt LLM italiano su libro di altra lingua) e `_audit_language` degradava accento/rate-sample Gemini. Fix v3.35.0 (incidente `kd8XQj6WWdrZJt1_z0VMPQ`: prompt `it` su libro `es` dopo restart alle 12:15). | `audiobook_app.py` | — |

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
| `MAX_CONCURRENT_GLOBAL` | da `ABM_MAX_CONCURRENT_GLOBAL` (default `6`) | `audiobook_app.py` | 588 |
| `assembly_queue.MAX_CONCURRENT_ASSEMBLY` | da `ABM_MAX_CONCURRENT_ASSEMBLY` (default `max(1, cpu_count() - 1)`) | `assembly_queue.py` | 50 |
| `assembly_queue.PRIORITY_NORMAL` / `PRIORITY_PREMIUM` | `0` / `10` (peso in coda di assembly; premium = voce Gemini/Speechify o job con pagamento incassato, vedi `generation_engine._assembly_priority`) | `assembly_queue.py` | 82-83 |
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
- **Floor minimo** (`ABM_LLM_MIN_COST_EUR`, default €1): quando la stima supera la soglia gratuita, l'importo dovuto per l'ottimizzazione **standalone** è alzato ad almeno il minimo (`due = max(stima, ABM_LLM_MIN_COST_EUR)`). Il floor preserva il lato della soglia (un job free resta free) e vale per stima UI, ordine PayPal e consumo voucher. Non si applica alla quota LLM dei pagamenti combinati con voci PREMIUM. Implementazione: `payment._llm_apply_min_cost()`.
- **Sopra soglia**: l'utente deve utilizzare un buono (voucher) ottenuto tramite donazione al progetto. Il pagamento diretto PayPal nel frontend è stato disabilitato (v3.7.0) ma i route backend PayPal sono mantenuti per eventuale riattivazione futura.
- **Flusso PayPal (backend, disabilitato nel frontend)**: ordine creato con `intent=CAPTURE`, `currency_code=EUR`, `shipping_preference=NO_SHIPPING`, `user_action=PAY_NOW`, `Prefer: return=representation`; OAuth2 client_credentials con cache ~8h; capture idempotente (re-capture dello stesso `order_id` ritorna lo stesso `payment_token`).
- **Voucher refund (errore/cancel)**: se l'ottimizzazione fallisce o viene annullata dopo un pagamento con voucher, l'importo viene **ri-accreditato integralmente** sul voucher originale tramite `_voucher_refund()`. Se il pagamento era PayPal, viene emesso un nuovo buono pari all'importo pagato + `ABM_VOUCHER_BONUS_PERCENT`%.
- **Recovery avvio server**: `_recover_orphaned_voucher_charges()` eseguita allo startup controlla gli addebiti voucher delle ultime 2 ore; se il job_id non è più in memoria né tra i completati (`_paid_opt_done.json`), ri-accredita automaticamente l'importo. Copre il caso di crash/riavvio durante un'ottimizzazione a pagamento.
- **Saldo residuo (consumo parziale)**: ogni voucher ha un campo `remaining_eur` (inizializzato all'importo totale) che viene decrementato di `estimated_cost` ad ogni operazione. Il buono torna "USED" solo quando il saldo scende sotto 0.01 EUR; fino a quel momento conserva stato `PARTIAL` e può essere usato più volte fino a scadenza. Lo storico delle spese è in `uses[]` (`job_id`, `amount_eur`, `at`, `remaining_after`). Record legacy senza `remaining_eur` vengono letti in compat: `used=True` → residuo 0; altrimenti residuo = `amount_eur`. La revoca admin azzera `remaining_eur`.
- **Idempotenza capture**: `payment.capture_and_store_order(order_id)` acquisisce `_capture_lock` (global), verifica se il record esiste già (idempotency cache), altrimenti chiama PayPal API. 5+ thread concorrenti producono 1 sola chiamata API.
- **Amount reconciliation**: `_pending_orders` traccia in-memory `{order_id: amount_requested_eur, purpose, ts}` registrato in `_paypal_create_order`. Al capture, l'importo PayPal viene confrontato con il pending (tolerance 0.01 EUR); mismatch → `CaptureAmountMismatchError`. Difende contro tampering del cliente sull'importo. TTL pending: 1h (cleanup automatico).
- **Capture PENDING non finanziate (eCheck)**: una capture PayPal puo' tornare `status=PENDING`, cioè **denaro non ancora sul conto**. Poiché ABM eroga il servizio contestualmente al pagamento, i reason elencati in `ABM_PAYPAL_UNFUNDED_PENDING_REASONS` (default: `ECHECK` e affini) sollevano `payment.UnfundedCaptureError`: nessun `payment_token` emesso, HTTP 402 con `paypal_issue=UNFUNDED_PENDING` e `retryable=true` (il frontend riapre il checkout per un altro metodo). Il record resta in `_payments` con `pending_unfunded=True` — **non spendibile** come payment token, **non rimborsabile** in automatico e **non incassabile** da `settle_delivered_captures_for_job` (rimborsare o incassare denaro mai ricevuto sarebbe una seconda perdita) — visibile per la riconciliazione manuale. Incidente 2026-08: 4 eCheck respinti dalla banca del pagante dopo l'erogazione, €12,93 di servizio consegnato e mai incassato. Blocco complementare consigliato lato conto PayPal: *Impostazioni → Pagamenti → Preferenze di incasso → blocca pagamenti eCheck*.
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
| `ABM_TRANSLATE_COST_IN_EUR_PER_MTOK` | `0.28` (Costo LLM input EUR/1M token — base costo audit traduzioni) | `payment.py` | (dopo TRANSLATE_MIN_COST_EUR) |
| `ABM_TRANSLATE_COST_OUT_EUR_PER_MTOK` | `2.30` (Costo LLM output EUR/1M token — base costo audit traduzioni) | `payment.py` | (dopo TRANSLATE_MIN_COST_EUR) |

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
| `LLM_THINKING` | `False` | `ABM_LLM_THINKING` | `generation_engine.py` | 98 |
| `LLM_REASONING_EFFORT` | `none` | `ABM_LLM_REASONING_EFFORT` | `generation_engine.py` | 99 |
| `THINKING_OFF_BODY` | `{"thinking": {"type": "disabled"}}` | — (costante) | `generation_engine.py` | 130 |

> **Thinking sempre esplicito.** `llm_thinking_kwargs()` (`generation_engine.py:133`) traduce le due env in parametri di richiesta e non lascia mai decidere al provider: DeepSeek v4 (`v4-pro`/`v4-flash`) abilita il thinking **di default con effort `high`** se la richiesta non contiene né `thinking` né `reasoning_effort`.
> - `REASONING_EFFORT=none` + `THINKING=false` (default) → `extra_body={"thinking": {"type": "disabled"}}`
> - `THINKING=true` con effort `none` → `extra_body={"thinking": {"type": "enabled"}}`
> - `REASONING_EFFORT=low|high|max` → `reasoning_effort=<valore>` (senza `extra_body`: i due parametri sono mutuamente esclusivi). `medium` degrada a `high`, valori non riconosciuti → thinking disabilitato.
>
> Lo stesso opt-out è applicato alle chiamate one-shot che condividono il client: `detect_book_language()`, `community_translator`, `community_moderator`.
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
| `_EDGE_FALLBACK_VOICES` / `_EDGE_FALLBACK_DEFAULT` | Mappa lingua (2 lettere) → voce edge-tts standard (default `en-US-AriaNeural`) usata come **fallback quando un chunk Gemini viene rifiutato in modo definitivo** (content policy / safety su testi sensibili). Invece di scrivere silenzio, `generate_chunk_pcm_gemini(..., fallback_lang=...)` sintetizza il chunk con la voce edge, lo converte in PCM 24 kHz mono (`_mp3_to_pcm_24k` via ffmpeg) e lo concatena come i chunk Gemini. Chunk recuperato → **non conta come `failed_chunks`**, contatore `job["gemini_edge_fallback_chunks"]`, contabilità token/costo/rate-sample Gemini **saltata** (0 token reali). Quota/budget/kill-switch restano job-fatal senza fallback. Introdotto v3.35.0 (incidente `kd8XQj6WWdrZJt1_z0VMPQ`). | `tts_split.py` / `generation_engine.py` | — |

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

**Fix v3.43.3 (troncamento silenzioso dell'assembly PCM)**:

Incidente 2026-08-16 (job `9dmJT_I3lHSeD2Vwz0Bu1A`, audiolibro ~7 h consegnato troncato a 4h18m52s, capitolo 14 di 24 interrotto a metà). Nessun chunk TTS era fallito: `pcm_to_aac_m4b` è stato ucciso dal timeout fisso `subprocess.run(timeout=3600)`, il ripiego `pcm_to_mp3` dal proprio `timeout=600`, e in entrambi i casi il file parziale è rimasto sul disco. Il valore di ritorno di `pcm_to_mp3` non veniva letto (`generation_engine.py`), quindi il job è stato marcato `done` e l'MP3 monco spedito all'utente come audiolibro completo, poi offloadato su cold storage.

- **Sorveglianza dello stallo al posto del wall-clock** (`_run_ffmpeg_encode`): il processo viene campionato ogni 5 s e ucciso solo se l'output non cresce per `stall_timeout` (300 s). Un libro lungo ha quindi tutto il tempo che gli serve. Resta un tetto assoluto larghissimo (`max(7200 s, 4 × durata attesa)`) come rete di sicurezza. Lo `stderr` di ffmpeg va su file temporaneo, non su `PIPE`: senza `communicate()` una pipe piena bloccherebbe il processo.
- **Validazione della durata** (`_encoded_duration_ok`): il PCM raw non ha header, quindi la durata attesa è esattamente `byte / (sample_rate × channels × sample_width)` (`_pcm_expected_duration_sec`, delega a `pcm_size_to_seconds`). L'output viene misurato con `ffprobe` e scartato se è più corto del 2%. È l'unico invariante che distingue un encode interrotto da uno riuscito: un file troncato è perfettamente riproducibile e `returncode` resta 0. Se `ffprobe` non è disponibile la verifica viene saltata (skip sicuro).
- **Rimozione del parziale** (`_discard_failed_output`): ogni path di fallimento di `pcm_to_mp3`, `pcm_to_aac_m4b` e `_monitored_m4b_run` cancella l'output. Un file parziale lasciato sul disco viene altrimenti raccolto dai passi a valle (offload cold, rebuild kit, email di completamento) come se fosse il risultato buono.
- **Valori di ritorno onorati** (`generation_engine.py`): i quattro call site di `pcm_to_mp3` verificano l'esito. Nel modo per capitoli il fallimento solleva `_AssemblyError` → status `error` + rimborso integrale + messaggio utente dedicato; nel modo file singolo l'assenza del file fa scattare la guardia output già presente, con lo stesso effetto. In nessun caso viene consegnato un audio incompleto.
- **Test**: `test/test_pcm_encode_truncation.py` (22 casi) copre calcolo della durata attesa, rilevamento del troncamento, cancellazione del parziale su ogni encoder, watchdog di stallo (processo bloccato ucciso / processo lento ma vivo lasciato lavorare) e propagazione del returncode.

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
| Timeout conversione M4B (da MP3) | `3600` secondi | `audio_utils.py` | `_convert_mp3_to_m4b`; su timeout il parziale viene rimosso |
| Stallo massimo encode PCM | `300` secondi senza crescita dell'output | `audio_utils.py` | `_run_ffmpeg_encode(stall_timeout=300)`: finché ffmpeg scrive non viene interrotto |
| Tetto assoluto encode PCM | `max(7200 s, 4 × durata audio attesa)` | `audio_utils.py` | `_run_ffmpeg_encode(hard_timeout)`: rete di sicurezza, non un limite di durata |
| Tolleranza durata output | `2%` in difetto rispetto al PCM sorgente | `audio_utils.py` | `_encoded_duration_ok(tolerance=0.02)` |
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
| `MIN_TITLE_STRATEGY_COVERAGE` | `0.95` (copertura minima: una strategia di riconoscimento titoli che scarta >5% del testo estratto viene ignorata, si passa alla successiva) | `pdf_to_tts.py` | 200 |
| `CHAPTER_DIVIDER_RE` / `is_chapter_marker_line()` | Regex multilingua per marcatori di suddivisione su riga isolata ("Chapter 4", "Capitolo III"/"Parte prima", "Première partie", "Erstes Kapitel", "Глава 1", "अध्याय १", "第2章"…), keyword+numero e numero+keyword, cardinali/ordinali; lingue allineate ai prompt in `prompt_opt_AI/` (de/en/es/fr/hi/it/pt/ru/zh). **Definito in `epub_to_tts.py`** (modulo base) e riusato da `pdf_to_tts.py` (alias `_line_is_chapter_marker`) come terzo segnale titolo oltre a font-size e grassetto | `epub_to_tts.py` | 883 / 886 |
| Soglia ri-segmentazione EPUB | Costante inline `4`: se il parsing EPUB via TOC produce **< 4** capitoli di contenuto (escluse note/apparato), si ri-segmenta il testo per marcatori (`_resegment_chapters_by_markers`); con ≥ 4 ci si affida al TOC senza suddivisioni ulteriori. Non perde testo (sostituisce solo se produce più capitoli) | `epub_to_tts.py` | 1345 |

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
| `ABM_GEMINI_BACKEND` | `auto` | Selettore backend Gemini TTS: `vertex` \| `apikey` \| `cloudflare` \| `auto`. `auto` preferisce Vertex se config completa (project + credentials), altrimenti cade su API key; **`auto` non seleziona mai Cloudflare** (quel backend e' solo opt-in esplicito). `vertex` forza Vertex (richiede `ABM_GCP_PROJECT_ID` + `ABM_GOOGLE_CREDENTIALS_FILE`). `apikey` forza API key. `cloudflare` richiede `ABM_CF_ACCOUNT_ID` + `ABM_CF_API_TOKEN` e che il modello abbia un `id_cloudflare` in `GEMINI_MODELS`: un modello non ospitato su Cloudflare ricade su Vertex, non va in errore. Il circuit breaker persistito (vedi §7.9) ha **precedenza su questa variabile**: un modello scattato viene forzato su Vertex anche dopo un riavvio del processo. File: `gemini_tts.py:_resolve_backend`. |
| `ABM_CF_ACCOUNT_ID` | *(vuoto)* | Account ID Cloudflare per l'endpoint Workers AI `POST /client/v4/accounts/<id>/ai/run`. Assieme a `ABM_CF_API_TOKEN` abilita il backend `cloudflare`: se una delle due manca, `_resolve_backend` non seleziona mai Cloudflare e una call forzata fallisce con `kind="fatal"`. File: `gemini_transport.py:cloudflare_call` (257), `gemini_tts.py:_resolve_backend` (258). |
| `ABM_CF_API_TOKEN` | *(vuoto)* | API token Cloudflare, ristretto ai soli permessi Workers AI. **Solo variabile d'ambiente**: mai in UI, mai in log, mai serializzato negli header di un'eccezione di trasporto. **Il valore non va mai riportato in questa documentazione, nei log applicativi o in export/dump di configurazione** — solo il nome della variabile. File: `gemini_transport.py:cloudflare_call` (258), `gemini_tts.py:_resolve_backend` (259). |
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

Token audio output per secondo, per-modello con fallback globale. Usato da `estimate_output_tokens()` → `estimate_book_cost()`. Una sottostima di questo valore causa margine % a consuntivo inferiore al `MARGIN_PERCENT` configurato; una **sovrastima** gonfia il prezzo all'utente. Ricalibrazione: `= output_tokens_actual / audio_seconds_actual` dei record `completed` per quel modello in `/admin/audit-tts`.

| Variabile | Default |
|-----------|---------|
| `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND` | `25.0` (fallback globale) |
| `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH25` | `25.0` (misurato) |
| `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH31` | `25.0` (misurato — era `29.0`, vedi nota) |

Ordine di risoluzione: `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_<MODEL>` → `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND` → default hardcoded.

**Misura su audit reale (giu–ago 2026, 256 job `completed`)**: il rapporto `output_tokens_actual / audio_seconds_actual` vale **esattamente 25.0** per entrambi i modelli — su flash25 con cv 0.0%, su flash31 esattamente 25.0 in 122 job su 168 (l'eccesso residuo viene solo dai chunk ritentati, che pagano token già fatturati). Il valore è quindi una costante del formato audio, non una caratteristica del modello. Il precedente `29.0` su flash31 (e il `30` impostato in produzione) produceva un **+16–20% sistematico sul costo stimato**, con margine a consuntivo del 36,8% contro un target del 25%.

> **Attenzione operativa**: se in produzione è presente un override `ABM_GEMINI_AUDIO_TOKENS_PER_SECOND_FLASH31` diverso da `25`, il default corretto nel codice non ha alcun effetto. Verificare con `systemctl cat audiobook-maker`.

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
| `ABM_GEMINI_EARLY_ABORT_RATIO` | `0.30` (early-abort: durante la generazione Gemini, se la frazione di chunk silenziati sul campione processato supera questo valore, il job viene **interrotto subito** (non a fine libro) e instradato allo stesso path refund-qualità — `generation_engine._gemini_quality_refund` via eccezione `_GeminiQualityAbort`. Evita di macinare l'intero libro e bruciare token Gemini su un job già compromesso. Impostare `>1.0` per disabilitare. Vedi anche `ABM_GEMINI_EARLY_ABORT_MIN_CHUNKS`) |
| `ABM_GEMINI_EARLY_ABORT_MIN_CHUNKS` | `15` (campione minimo di chunk processati prima che l'early-abort possa scattare: evita aborti su rumore iniziale di libri corti) |
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

### 7.8 Backend Cloudflare — ledger locale del credito e pre-allarme (`tts_backend_state.py`)

Il credito Cloudflare AI Gateway è **prepagato** e non è leggibile via API (gli endpoint di fatturazione rispondono 403: il token è deliberatamente ristretto a Workers AI). Il saldo residuo è quindi una **stima**: `ABM_CF_CREDIT_BALANCE_EUR` è il saldo che l'admin dichiara dopo ogni ricarica, da cui `tts_backend_state.credit_left_eur()` sottrae la spesa cumulata nel ledger locale (`add_spend()`, chiave globale `_credit` nel file di stato — il credito è unico per l'account, non per modello).

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `ABM_CF_CREDIT_BALANCE_EUR` | `0` | Saldo Cloudflare dichiarato dall'admin dopo l'ultima ricarica. `0` (non dichiarato) disabilita il pre-allarme: evita rumore costante su installazioni che non usano Cloudflare o non hanno ancora eseguito la procedura di accensione. |
| `ABM_CF_CREDIT_ALERT_EUR` | `5` | Soglia di residuo stimato sotto cui scatta il pre-allarme sul credito. |

**API del modulo:** `add_spend(model_key, eur)`, `reset_spend()` (da chiamare alla ricarica: azzera il ledger e riarma l'allarme), `credit_left_eur()`, `credit_balance_eur()` (saldo dichiarato, pura: `0` = residuo non conoscibile), `credit_alert_threshold_eur()`, `credit_alert_pending()`, `claim_credit_alert()`, `mark_credit_alerted()`.

**Il riarmo dell'allarme deve restare raggiungibile senza failover.** `reset_spend()` è l'unica funzione che riporta `alerted` a `False`, e il ciclo normale del credito (residuo sotto soglia → email di pre-allarme → ricarica → topup) avviene con Cloudflare **ancora sano**, cioè senza alcun trip. Il suo unico innesco in console è quindi il pulsante **«Ho ricaricato il credito»** del pannello «Backend TTS» (`POST /admin/api/tts_backend {"action":"topup"}`), abilitato ogni volta che `ABM_GEMINI_BACKEND=cloudflare` e **indipendente da `tripped_at`**. Nella forma precedente era una casella accanto al pulsante di rientro, abilitato solo dopo un trip: l'allarme partiva una volta sola nella vita dell'installazione e il residuo mostrato in console restava sbagliato per sempre (saldo dichiarato rialzato, `spent_eur` che continuava ad accumulare dal ciclo precedente).

**Dove scatta davvero il pre-allarme.** Subito dopo ogni `add_spend()` riuscito, in `gemini_tts._maybe_alert_credit(model_key)` (chiamata da `synthesize()` solo quando il backend che ha eseguito è Cloudflare): è l'unico istante in cui il residuo stimato può essere sceso sotto soglia, e il backend è ancora sano — cioè c'è ancora tempo per ricaricare. La funzione verifica **prima** che un notifier sia registrato e **poi** chiama `claim_credit_alert()`, mai il contrario: senza notifier la `claim` brucerebbe in silenzio l'unica notifica disponibile. Il notifier è registrato in `audiobook_app` (`_on_cf_credit_alert` → `email_service.admin_notify_cf_credit_low`), email **dedicata** e distinta da quella di failover (`admin_notify_tts_backend_switch`), che invece annuncia un guasto già avvenuto. `claim_credit_alert()` resta invocata anche dal notifier di switch, ma **solo** per sopprimere l'email di pre-allarme separata quando lo switch la anticipa: il residuo mostrato nell'email di failover si legge sempre da `credit_left_eur()` (pura) quando c'è un saldo dichiarato, mai dall'esito della claim. Legarlo a quell'esito faceva sparire il numero proprio quando serve di più — credito già sotto soglia significa allarme già consumato, cioè claim `False`.

**Ispezione e consumo dell'allarme sono due funzioni diverse, e la distinzione non e' cosmetica.**

- `credit_alert_pending()` e' **puro**: nessuna mutazione, nessuna scrittura. Ritorna `True` finche' il residuo stimato e' sotto soglia e l'allarme non e' stato consumato. E' la funzione da usare per mostrare lo stato in una pagina admin o in una diagnostica: chiamarla N volte da' sempre lo stesso esito.
- `claim_credit_alert()` **consuma** l'allarme: check-and-set atomico sotto lock, ritorna `True` a **esattamente un** chiamante e persiste il flag. Va chiamata **solo** nel punto in cui l'email parte davvero, esattamente come `trip()`. Chiamarla per ispezione brucia l'unica notifica e nessuno riceve niente.

**Forma del file di stato.** Il file porta un marcatore esplicito `version: 2` al livello superiore; le voci per-modello del breaker stanno dentro `models`, il ledger del credito sotto `_credit`. I file scritti dalle versioni precedenti (forma piatta, senza marcatore) vengono migrati in lettura senza perdere trip. Il marcatore e' l'**unico** criterio di riconoscimento: `version` assente significa forma vecchia, `version` presente ma diversa da `2` significa dato illeggibile e attiva il fail-safe (ogni modello considerato scattato). Non si deduce mai il formato dalla forma dei dati: dedurlo aveva gia' prodotto una perdita silenziosa di trip.

### 7.9 Backend Cloudflare — failover automatico e circuit breaker (`tts_backend_state.py`)

Il passaggio Cloudflare → Vertex e' **automatico e a senso unico**: quando il backend Cloudflare si rivela non utilizzabile, il modello viene marcato come "scattato" su disco (`<ABM_DATA_DIR>/_tts_backend_state.json`) e da quel momento risolve a Vertex. Non esiste half-open, non esiste scadenza: il rientro su Cloudflare avviene **solo** dal pulsante in console admin (`reset()`), che deve anche invalidare la cache in-process `gemini_tts._BACKEND`, altrimenti il processo vivo continua a servire Vertex.

**Contratto del rientro (`POST /admin/api/tts_backend {"action":"reset"}`).** L'endpoint azzera il trip su disco e fa il **`pop`** della voce di cache di ogni `model_key` noto — mai un valore forzato, nemmeno sul modello target: il backend torna a essere deciso da `_resolve_backend` alla sintesi successiva, cioè dalla configurazione dichiarata e da `id_cloudflare`. Due guardie sull'ingresso, entrambe lato server perché il bottone disabilitato in console è scavalcabile da una chiamata diretta all'API: `model_key` non presente in `GEMINI_MODELS` → **400** (una chiave inventata materializzerebbe per sempre una voce spuria nel file di stato); `ABM_GEMINI_BACKEND != "cloudflare"` → **409** (con quella configurazione la sintesi non userà mai Cloudflare, quindi riarmare il breaker non cambia nulla e la console direbbe il falso). `model_key` è coerciuto a stringa prima di ogni confronto: dal corpo JSON può arrivare una lista o un dict, e un valore unhashable produrrebbe un **500** invece del 400 previsto.

**Contratto del topup (`POST /admin/api/tts_backend {"action":"topup"}`).** Azione **distinta** dal rientro: chiama `tts_backend_state.reset_spend()` e **non tocca il breaker** (nessun `reset()`, nessuna invalidazione di `gemini_tts._BACKEND`) — aver ricaricato il credito non dimostra che la causa del guasto sia stata risolta. Stesse due guardie del rientro, stesso `_log_activity` (`ADMIN_TTS_CREDIT_TOPUP`, con il residuo stimato **prima** dell'azzeramento: una forense sul credito deve poter ritrovare la spesa cancellata). Il campo `topup` dentro `action="reset"` (forma precedente) è stato rimosso e, se valorizzato a vero, è rifiutato con **400** invece di essere ignorato in silenzio: ignorarlo lascerebbe il ledger intatto facendo credere il contrario a chi ha appena ricaricato.

Il job in corso non viene interrotto: prosegue su Vertex **dal chunk corrente**, e il backend viene ricalcolato ad ogni tentativo di retry. All'ingresso di Vertex parte una email immediata all'admin: `trip()` e' un check-and-set atomico sotto lock e ritorna `True` a **esattamente un** chiamante, quindi la notifica non ha bisogno di un secondo meccanismo di deduplica.

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `ABM_CF_TRIP_FAILURES` | `3` | Fallimenti consecutivi dopo i quali un errore `retryable` / `rate_limited` fa scattare il breaker. Floor a 1; valore non numerico → default. Un successo azzera il contatore. Gli errori `backend_down` fanno scattare **subito**, ignorando la soglia; `fatal` e `content_rejected` non fanno scattare nulla (sono difetti della richiesta, non del backend). File: `gemini_tts.py:_cf_trip_failures` (376). |
| `ABM_CF_TIMEOUT_MS` | `60000` | Timeout HTTP (ms) delle call verso Workers AI. Floor a 1000; valore non numerico → default. Indipendente dai timeout Vertex (`ABM_GEMINI_HTTP_TIMEOUT_MS*`) perche' la latenza del gateway Cloudflare ha un profilo diverso. File: `gemini_tts.py:_cf_timeout_ms` (2117). |

**Lettura fail-safe dello stato.** File **assente** = installazione pulita, nessun modello scattato (trattarlo come scattato disabiliterebbe Cloudflare dal primo avvio e la feature non si accenderebbe mai). File **presente ma illeggibile** = ogni modello e' considerato scattato finche' l'admin non interviene. Una singola voce per-modello corrotta viene materializzata come trip concreto con `reason="state_entry_corrupt"`, limitato a quel modello.

**Sicurezza:** il campo `detail` passato a `trip()` viene persistito su disco e stampato su stdout **senza redazione** — non deve mai contenere header o token.

### 7.10 Backend Cloudflare — economia e pricing lato cliente (`gemini_tts.py`)

Il prezzo esposto all'utente per `flash31` può incorporare parte del risparmio che Cloudflare Workers AI offre rispetto al listino Google diretto. Questi parametri governano **quanto** risparmio, non **se** Cloudflare è il backend attivo in un dato momento: `_pricing_uses_cloudflare()` guarda `ABM_GEMINI_BACKEND` (la configurazione dichiarata), non lo stato del circuit breaker — decisione D1: il prezzo non deve oscillare sotto gli occhi dell'utente per un evento infrastrutturale (trip → failover su Vertex a metà job).

| Variabile | Default | Descrizione |
|-----------|---------|-------------|
| `ABM_GEMINI_31FLASH_CF_INPUT_USD_PER_MTOK` | `0.75` | Tariffa Cloudflare di listino (USD/1M token input) per `flash31`. Applicabile solo ai modelli con `id_cloudflare` popolato in `GEMINI_MODELS` — oggi solo `flash31` (`flash25` non è ospitato su Cloudflare, vedi nota in §7.1/`ABM_GEMINI_BACKEND`). File: `gemini_tts.py:172` (`GEMINI_MODELS["flash31"]["cf_input_usd_per_mtok"]`). |
| `ABM_GEMINI_31FLASH_CF_OUTPUT_USD_PER_MTOK` | `12.00` | Tariffa Cloudflare di listino (USD/1M token output) per `flash31`. File: `gemini_tts.py:173`. |
| `ABM_CF_CREDIT_TOPUP_FEE` | `0.05` | Commissione di ricarica del credito AI Gateway, come frazione (`0.05` = 5%). Il credito si paga comprandolo, non spendendolo: il costo reale per ABM è la tariffa nuda maggiorata di questa commissione (`_cf_effective(rate) = rate * (1 + fee)`), applicata solo al calcolo interno del margine — non è un costo separato in fattura. File: `gemini_tts.py:_cf_topup_fee` (666). |
| `ABM_GEMINI_CF_SAVING_TO_CUSTOMER_PCT` | `50.0` | Quota percentuale del risparmio Cloudflare (rispetto al costo Google puro) ceduta al cliente nel prezzo finale, clampata a `[0, 100]`. Formula in `pricing_rates()`: `tariffa_utente = google - (google - cf_effettivo) * share`. `0` → listino esposto identico a oggi (Google puro, il risparmio resta interno); `100` → tutto il risparmio va al cliente. File: `gemini_tts.py:cf_saving_share` (671). |

---

## 8. Speechify TTS (Simba-3.2, voci PREMIUM inglese) (`speechify_tts.py`)

Engine TTS PREMIUM aggiuntivo, disponibile **solo per lingua inglese**. Modello fisso `simba-3.2` (costante interna `MODEL_ID`, `speechify_tts.py:88`), etichetta UI "Simba (English)" — nessun nome provider esposto nella UI utente. Audio nativo PCM 48000 Hz mono 16-bit. Il pagamento premium vive nella stessa "tasca" di Gemini (`job["payment"]`) e si rimborsa via `_refund_gemini_payment` / `_refund_payment_on_orphan`.

### 8.1 Configurazione (env)

| Variabile | Descrizione | Default | Sorgente |
|-----------|-------------|---------|----------|
| `ABM_SPEECHIFY_API_KEY` | API key Speechify. Se vuota l'engine è disabilitato (`is_available()` → False: voci Simba assenti dal catalogo, stime/pagamenti Premium rispondono 503). Solo variabile d'ambiente, mai esposta in UI o log. | *(vuoto)* | `speechify_tts.py` `api_key()` (139) |
| `ABM_SPEECHIFY_MAX_CONCURRENCY` | Concorrenza API **globale** (limite abbonamento): numero massimo di chiamate simultanee verso l'API Speechify su **tutti** i job del processo. Floor a 1. | `3` | `speechify_tts.py` `max_concurrency()` (149) |
| `ABM_SPEECHIFY_PER_JOB_CONCURRENCY` | Chiamate API simultanee per **singolo** job. Floor a 1. Se il gate globale è saturo, il job attende in modo trasparente ("in attesa") senza fallire. | `1` | `speechify_tts.py` `per_job_concurrency()` (154) |
| `ABM_SPEECHIFY_COST_USD_PER_MCHAR` | Costo USD per 1M caratteri (listino provider). Accetta virgola decimale. | `11.18` | `speechify_tts.py` `cost_usd_per_mchar()` (158) |
| `ABM_SPEECHIFY_MARGIN_PERCENT` | Ricarico % (margine netto operatore) applicato sul costo per determinare il prezzo utente. Accetta virgola decimale. | `60` | `speechify_tts.py` `margin_percent()` (162) |
| `ABM_SPEECHIFY_FREE_THRESHOLD_EUR` | Soglia gratuità: sotto questo prezzo la voce PREMIUM è offerta senza pagamento. | `0.50` | `speechify_tts.py` `free_threshold_eur()` (166) |
| `ABM_MAX_SPEECHIFY_TEXT_CHARS` | Cap caratteri testo per job con voce Speechify. Default = `ABM_MAX_GEMINI_TEXT_CHARS` (`800000`). Selezione via `_max_text_chars_for_voice(voice)` quando `voice` inizia per `speechify:`. | `800000` | `audiobook_app.py` `MAX_SPEECHIFY_TEXT_CHARS` (419) |
| `ABM_SPEECHIFY_CHUNK_CHARS` | Cap caratteri **testo** per chunk TTS. Clampato a `[200, 1850]` (`SAFE_MAX_CHUNK_CHARS`): il tetto garantisce che l'`input` SSML (testo + tag `build_ssml`) resti sotto il limite hard `2000` char dell'endpoint (oltre → HTTP 400 → chunk silenziato). Valori non validi → default. Usato da `tts_split._pick_chunk_max_chars` per le voci Speechify. | `1800` | `speechify_tts.py` `chunk_max_chars()` |
| `ABM_SPEECHIFY_USE_STREAM` | Sceglie l'endpoint API: `false` = non-streaming `/v1/audio/speech` (JSON con `audio_data` base64); `true` = streaming `/v1/audio/stream` (corpo audio grezzo). Booleano: `1/true/yes/on`. In streaming `billable_characters_count` non è disponibile → fallback a `len(text)` per il reconcile (il costo è comunque riservato sui caratteri di input). | `false` | `speechify_tts.py` `use_stream_api()` |

**Costanti condivise con Gemini** (stesse env per non divergere sui prezzi): tasso USD→EUR `ABM_GEMINI_USD_EUR_RATE` (`0.86`) e fee PayPal `ABM_GEMINI_PAYPAL_FIXED_FEE_EUR` (`0.34`) + `ABM_GEMINI_PAYPAL_PERCENT_FEE` (`3.4`). Vedi §7.2 e §7.4. Definite in `speechify_tts.py:170-179`.

### 8.2 Note operative

- Voice ID formato: `speechify:simba-3.2:<voiceId>` (es. `speechify:simba-3.2:harper_32`). 8 voci `_32`: 4 en-US (dominic/geffen/harper/wyatt) + 4 en-GB (beatrice/edmund/hugh/imogen). `speechify_tts.py:104`.
- 13 emozioni (`EMOTIONS`, `speechify_tts.py:98`): `angry, cheerful, sad, terrified, relaxed, fearful, surprised, calm, assertive, energetic, warm, direct, bright`. Nell'UI PREMIUM la combo "Emozione" sostituisce "Istruzioni di stile" quando il modello selezionato è Simba.
- Accento di lettura (en-US / en-GB) posizionato **sopra** la selezione voce; filtra le voci per locale.
- Su lingua inglese il modello PREMIUM di default è Simba-3.2 (preselezionato in `updModelsPremium()`, `static/js/app.js`).
- Chunk max: default `CHUNK_MAX_CHARS = 1800` (`speechify_tts.py`), sotto il limite ~2000 char/richiesta dell'endpoint. Override via `ABM_SPEECHIFY_CHUNK_CHARS` (clampato a `[200, 1850]` per non superare mai il limite hard dell'endpoint con l'overhead SSML).
- Endpoint API selezionabile via `ABM_SPEECHIFY_USE_STREAM` (default `false` = `/v1/audio/speech`; `true` = `/v1/audio/stream`). In streaming il corpo della risposta è audio WAV grezzo (`audio_format=wav`) e il download viene consumato dentro lo slot del gate per rispettare l'invariante di concorrenza.
- **Invariante concorrenza:** chiamate simultanee verso l'API ≤ `ABM_SPEECHIFY_MAX_CONCURRENCY` su tutti i job del processo; ogni job usa al più `ABM_SPEECHIFY_PER_JOB_CONCURRENCY` slot del gate globale.
- Cancel di un job con voce Speechify → refund **integrale** (`retained_eur=0.0`), nessuna retention parziale né consegna audio parziale (a differenza di Gemini).

---

## 9. Cold Storage S3 (tiering hot/cold)

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
| `ABM_OFFLOAD_QUIET_SEC` | Finestra di quiete (s): un output senza marker `.generation_complete` i cui file sono stati scritti da meno di N secondi è considerato in conversione e NON viene offloadato (gate anti race mid-write, vedi F1) | `180` | generation_engine.py, audiobook_app.py (`EVICT_REGEN_QUIET_SEC`, vedi F5) |

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
- **F5 — promozione del locale rigenerato dopo l'offload (2026-08).** Se il cold è PIÙ GRANDE del locale, il guard B (nessun overwrite, nessun evict) resta la regola, ma NON si applica quando il file locale è stato scritto DOPO il marker `.cloud_uploaded` (rigenerazione legittima, es. snapshot `.abm` ricostruito da `/api/download?type=abm`), è quiescente da almeno `ABM_OFFLOAD_QUIET_SEC` e supera il check strutturale locale (`_local_output_intact`: zip valido per `.abm`/`.zip`, atom `moov` per `.m4b`). In quel caso il locale è l'autoritativo: re-upload + evict. Senza questa eccezione un `.abm` rigenerato più piccolo di 1 byte bloccava l'eviction per sempre, con una riga di log a ogni sweep da 60s; i mismatch che restano sospetti sono ora loggati una sola volta per (file, coppia di dimensioni).

---

## 10. Versione (`version.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `__version__` | `"3.13.0"` | `version.py` | 7 |
| `__updated_date__` | Dinamico: `datetime.now().strftime("%Y-%m")` | `version.py` | 10 |

---

## 11. SEO Content (`seo_content.py`)

| Parametro | Valore | File | Riga |
|-----------|--------|------|------|
| `_URL_RE` | Regex compilata per rilevamento URL nel testo | `seo_content.py` | 31 |
| `_CONTENT` | Dict con contenuti SEO visibili per 6 lingue | `seo_content.py` | 43 |

---

## 12. Nuovi moduli (v3.8.0)

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

## 13. Community widget (v3.13.0)

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

## 14. Recupero job batch interrotti (`pending_jobs.py`)

I job **batch** (con email registrata) vivono solo in memoria; un riavvio/deploy li perderebbe. Per recuperarli, ogni job batch viene descritto in un file su `ABM_DATA_DIR`:

| File | Contenuto |
|------|-----------|
| `_pending_jobs.json` | Descrittori dei job batch in volo (id, phase `optimize\|generate`, attempts, state, input path, parametri TTS, notify_*, payment). Riusa `community_store.JsonStore`: write atomico tmp+rename, lock per file, backup `.bak`. |
| `_pending_jobs.json.bak` | Backup automatico della versione precedente |

Ciclo di vita del descrittore: **scritto** quando il job diventa batch (`/api/register_email`, submit batch di `/api/optimize`); **finalizzato/rimosso** quando la mail finale parte con successo (`_send_completion_email` e l'email optimize-only in `generation_engine.py`). Al boot, `_recover_orphan_jobs()` (thread one-shot in `_ensure_background_threads`) legge gli orfani, incrementa `attempts` su disco **prima** di rilanciare (crash-safe), ricostruisce il job ri-parsando l'input (riusa l'`.abm` ottimizzato se presente, saltando l'LLM) e respawna `run_optimization`/`run_generation`. Oltre `ABM_RECOVER_MAX_ATTEMPTS` tentativi → rimborso secondo policy esistente (voucher → riaccredito silenzioso; PayPal → nuovo voucher in mail) + mail "interrotto" + `state=failed`.

---

## 15. Push FCM (app mobile) (`push_service.py`)

Modulo `push_service.py` — notifiche push Firebase Cloud Messaging (HTTP v1) per l'app mobile.
Disabilitato se `ABM_FCM_CREDENTIALS_FILE` non è impostata; i fallimenti non sono mai bloccanti.

### 15.1 Variabile d'ambiente

| Variabile | Default | Descrizione | File | Riga |
|-----------|---------|-------------|------|------|
| `ABM_FCM_CREDENTIALS_FILE` | *(vuoto)* | Path del service-account JSON Firebase per le notifiche push FCM HTTP v1. Push disabilitate se vuota o file assente (`is_available()` ritorna `False`). | `push_service.py` | 14 |

### 15.2 Costanti interne (`push_service.py`)

| Parametro | Valore | File | Riga | Note |
|-----------|--------|------|------|------|
| `_SEND_RETRIES` | `3` | `push_service.py` | 16 | Tentativi invio push per token; backoff esponenziale `2**attempt` secondi tra tentativi (sleep solo tra retry, non prima del primo). |

### 15.3 Costanti interne (`audiobook_app.py`)

| Parametro | Valore | File | Riga | Note |
|-----------|--------|------|------|------|
| `_MAX_DEVICES_PER_CLIENT` | `5` | `audiobook_app.py` | 1382 | Device FCM massimi per client_id. I token registrati vengono mantenuti ordinati per recency: oltre `_MAX_DEVICES_PER_CLIENT` il più vecchio viene silenziosamente scartato. |
| `_FCM_TOKEN_RE` | `r"^[A-Za-z0-9_:\-\.~%]{10,4096}$"` | `audiobook_app.py` | 1383 | Regex di validazione formato token FCM. Richiesta fallisce con `400` se il token non corrisponde. |
| `_DEVICE_TOKENS_FILE` | `UPLOAD_DIR / "_device_tokens.json"` | `audiobook_app.py` | 1381 | File di persistenza dei token FCM registrati per client. Write atomico (tmp + rename). |
| `_MOBILE_CID_RE` | `r"^[A-Za-z0-9_-]{8,64}$"` | `audiobook_app.py` | 572 | Regex di validazione del `client_id` letto dall'header `X-ABM-Cid`. Il CID mobile è preferito rispetto al cookie `abm_cid` se presente e valido. |

### 15.4 Flusso operativo

- **Registrazione device**: `POST /api/device/register` — il client mobile invia `{fcm_token, job_ids[]}`. Il server valida il token (regex `_FCM_TOKEN_RE`), deduplica per `(token, cid)`, mantiene al massimo `_MAX_DEVICES_PER_CLIENT` entry per client, persiste su `_device_tokens.json`.
- **Identificazione client mobile**: header `X-ABM-Cid` (validato da `_MOBILE_CID_RE` a `audiobook_app.py:572`). Se presente e valido viene preferito al cookie `abm_cid`, così l'app mobile non dipende dalla gestione cookie del browser.
- **Invio notifiche**: `_push_job_event(job_id, event, title)` (`audiobook_app.py:1417`) — chiamata al completamento (`COMPLETE`) o all'errore (`ERROR`) di un job; chiama `push_service.send_push()` per ogni device del client. Token che restituiscono `unregistered` (HTTP 404 FCM) vengono rimossi automaticamente da `_device_tokens.json`.
- **Job del client**: `GET /api/my_jobs` — restituisce la lista dei job correnti associati al client_id (via header `X-ABM-Cid` o cookie), con stato e progresso. Usato dall'app mobile per aggiornare la UI al resume.

---

## 16. Telemetria di carico (`load_metrics.py`)

Modulo foglia (nessun import di moduli di progetto) che alimenta il pannello **Stats** di `/admin/log-activity`.
Campiona lo stato del processo e della macchina ogni `SAMPLE_SEC`, aggrega in bucket da `BUCKET_SEC` e scrive
in append su `ABM_DATA_DIR/load_metrics_YYYY-MM.jsonl` (una riga JSON per bucket chiuso).
Le durate (attesa in coda assembly, encode FFmpeg, durata job) sono in istogrammi logaritmici
`_BINS = (10, 30, 60, 120, 300, 600, 1200)` — 8 bin — da cui i percentili sono stimati per interpolazione lineare.

### 16.1 Variabili d'ambiente

| Variabile | Default | Descrizione | File | Riga |
|-----------|---------|-------------|------|------|
| `ABM_LOAD_METRICS_ENABLED` | `true` | Abilita il campionatore di carico. Se `false` il thread non parte e `/api/admin/load_stats` restituisce i soli bucket già su disco. | `load_metrics.py` | 37 |
| `ABM_LOAD_METRICS_SAMPLE_SEC` | `30` | Periodo di campionamento dei gauge (job in elaborazione, RAM, CPU, swap, disco, coda assembly). | `load_metrics.py` | 39 |
| `ABM_LOAD_METRICS_BUCKET_SEC` | `300` | Ampiezza del bucket di aggregazione (5 minuti): un bucket chiuso = una riga JSONL. | `load_metrics.py` | 40 |
| `ABM_LOAD_METRICS_RETENTION_MONTHS` | `4` | Mesi di file `load_metrics_YYYY-MM.jsonl` conservati; i più vecchi vengono rimossi da `purge()`. | `load_metrics.py` | 41 |

### 16.2 API del modulo

`configure(data_dir)` (chiamata in `_ensure_background_threads`), `sample(now=None, **gauges)`, `incr(counter, n=1, now=None)`,
`observe(hist, seconds, premium=False, now=None)`, `flush(now=None)`, `query(window, now=None, global_cap=0, assembly_slots=0)`,
`purge(now=None)`, `reset_for_tests()`.

`query()` accetta le finestre `24h`, `7d`, `28d`, `month` (default `24h` su valore non riconosciuto) e restituisce
`{meta, job, ffmpeg, machine, quality, reliability, timeline}`.

### 16.3 Punti di raccolta

| Sorgente | Cosa registra |
|----------|---------------|
| `audiobook_app._load_metrics_sampler` | Thread di campionamento (con supervisore `_load_metrics_supervisor`): job in elaborazione free/premium, job in RAM, slot assembly occupati/in coda, RAM/swap/RSS/CPU/iowait/load/thread/disco letti da `/proc` e `shutil.disk_usage`, età dell'heartbeat del cleanup loop. Fuori da Linux le metriche di macchina mancano e le card corrispondenti leggono zero. |
| `audiobook_app._assembly_metrics_observer` | Osservatore iniettato in `assembly_queue.set_observer()`: attesa in coda (`asm_wait`), durata encode (`enc`), timeout di coda (`asm_timeout`). |
| `audiobook_app._server_busy_response` | Contatori `rej_busy` / `rej_busy_p` (job rifiutati al raggiungimento di `ABM_MAX_CONCURRENT_GLOBAL`). |
| `generation_engine._set_job_status` | Alla terminazione di una generazione: durata job (`job`), esiti `done`/`err`/`cancel` (varianti `_p` per i premium), chunk TTS falliti. Il premium è deciso da `generation_engine.is_premium_job()`. |
| `audiobook_app` (varie) | `boot` (avvii processo), `cl_restart` (restart del cleanup loop), `memp` (memory pressure rilevata da `_log_memory_stats`). |

Endpoint admin: `GET /api/admin/load_stats?window=24h|7d|28d|month` (richiede autenticazione admin, `403` altrimenti).

---

## Link store app mobile (pagina /get-app)
- `ABM_PLAY_STORE_URL`: URL Play Store dell'app. Se vuoto, il bottone Play è
  mostrato ma disabilitato. Valore al rilascio:
  `https://play.google.com/store/apps/details?id=it.nextsw.audiobook_maker_mobile`.
- `ABM_APP_STORE_URL`: URL App Store (iOS). Se vuoto, il bottone Apple è mostrato
  ma disabilitato.

---

## Condivisione audiolibro (share app→app)
- `ABM_SHARE_TTL_SEC` (default 7200): durata della disponibilità di una share (120 min).
- `ABM_SHARE_MAX_BYTES` (default 524288000 = 500 MB): tetto dimensione file condivisibile (caso upload).
- `ABM_SHARE_UPLOAD_TTL_SEC` (default 3600): validità della presigned PUT URL.

---

## Riepilogo

| Categoria | Numero parametri |
|-----------|:---:|
| Variabili d'ambiente (`ABM_*`) | 24 |
| Configurazione Flask | 1 |
| Costanti applicative (`audiobook_app.py`) | 28 |
| Costanti parsing EPUB (`epub_to_tts.py`) | 12 |
| Costanti parsing PDF (`pdf_to_tts.py`) | 8 |
| Google Cloud TTS (`google_tts.py`) | 5 |
| Gemini TTS (`gemini_tts.py`) | 15 |
| Speechify TTS (`speechify_tts.py`) | 9 |
| Versione (`version.py`) | 2 |
| SEO Content (`seo_content.py`) | 2 |
| Nuovi moduli v3.8.0 | 6 |
| Push FCM app mobile (`push_service.py`) | 5 |
| Telemetria di carico (`load_metrics.py`) | 4 |
| **Totale** | **121** |
