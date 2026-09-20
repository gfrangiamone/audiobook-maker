# Account utente con magic link e storico dei job — Blocco 1

**Data:** 2026-09-19
**Branch:** `gestione-utenti`
**Stato:** design approvato, pronto per il piano di implementazione

## Contesto

Primo blocco del piano "account + abbonamento". I blocchi successivi
(gestione delle voci campionate da account, voucher acquistabili a scalare,
abbonamenti con spazio riservato, integrazione con le app) si appoggiano
alle strutture introdotte qui. Questo blocco consegna:

- account identificato dalla sola **email**, login senza password
  (magic link + codice a 6 cifre nella stessa email), sessione lunga
  scorrevole con logout e "esci da tutti i dispositivi";
- **storico dei job** dell'account con download dei file ancora disponibili;
- **notifica forzata** all'email di login per ogni job avviato da loggato;
- cancellazione account self-service (GDPR art. 17);
- primo uso di **SQLite** nel progetto.

Il login resta **opzionale**: chi non accede usa il sito come oggi.

## Decisioni fissate

| Tema | Decisione |
|---|---|
| Identità | email normalizzata (`strip().lower()`); il cookie `abm_cid` non prova nulla |
| Adozione retroattiva | solo prove certe: job in `_payments.json` (email + `job_id`) e voci campionate con `owner_email` in `_voice_clones.json`. Nessuna inferenza da `_client_emails.json` |
| Storico | ogni job registrato (anche senza file), badge "scaduto" quando i file non ci sono più |
| Retention record storico | 24 mesi per account free; indefinita con piano attivo; alla disdetta, dopo il grace period, torna alla regola dei 24 mesi contati dalla data del job |
| Interfaccia | login/logout in un modal della SPA; storico su pagina server-side `/account` |
| Sessione | 90 giorni **scorrevoli**, revoca immediata lato server |
| App mobile | Bearer accettato sugli endpoint auth/account; verifica a codice senza pagina di conferma |
| Cancellazione | self-service, confermata con lo stesso meccanismo del login |
| Notifica da loggato | **automatica**: ogni job va in modalità email sull'email di login, esente da heartbeat, campo email nascosto |
| Storage | SQLite (`db.py`, `ABM_DATA_DIR/abm.db`); activity log **non** migrato in questo blocco |

## Nota sul branch `ABM_DB`

Esiste un branch `ABM_DB` (worktree `.worktrees/ABM_DB`, 2026-07-02, mai
mergiato) che ha già portato activity log e audit Gemini su SQLite con un
modulo `db.py` e il file `abm.db`. Questo blocco **riusa gli stessi nomi**
e adotta un versioning per nome di migrazione (tabella `schema_migrations`)
invece dell'intero `PRAGMA user_version`, così le migrazioni "accounts" e
"activity" convivono qualunque sia l'ordine di merge. Il follow-up
sull'activity log non è una nuova spec: è il rebase e il collaudo di
`ABM_DB` su `main`.

## Architettura

### `db.py` — bordo unico verso SQLite (modulo foglia)

- `init(data_dir)`: apre/crea `abm.db`, `PRAGMA journal_mode=WAL`,
  `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`;
  connessione unica `check_same_thread=False` protetta da `RLock` di
  processo (prod a processo singolo). Idempotente.
- Migrazioni: lista ordinata `(name, sql)`; `schema_migrations(name TEXT
  PRIMARY KEY, applied_at INTEGER)`; ogni migrazione non ancora registrata
  viene applicata in transazione.
- `tx()`: context manager che prende il lock, apre una transazione,
  `commit` a fine blocco, `rollback` su eccezione.
- `backup_to(path)`: copia consistente via `sqlite3.Connection.backup`
  (corretta sotto WAL) per `scripts/backup_ABM.sh` e per la replica su R2.
- Contratto: nessuna eccezione raggiunge i thread di generazione. I
  chiamanti che scrivono lo storico incapsulano in `try/except` e loggano.

### `accounts.py` — core account (modulo foglia, solo stdlib + `db`)

Nessun import da Flask o da `audiobook_app`. Riceve il necessario via
`configure(...)` (percorsi di `_payments.json` e `_voice_clones.json`,
funzione di log attività, salt IP).

Schema (migrazione `accounts_v1`):

```sql
CREATE TABLE accounts (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE,
    email_hash    TEXT NOT NULL,            -- voice_clone.email_hash(email)
    created_at    INTEGER NOT NULL,
    last_login_at INTEGER,
    lang          TEXT NOT NULL DEFAULT 'en',
    plan          TEXT NOT NULL DEFAULT 'free',
    plan_until    INTEGER,
    deleted_at    INTEGER
);
CREATE TABLE auth_codes (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    email       TEXT NOT NULL,
    token_hash  TEXT NOT NULL UNIQUE,       -- sha256 del token del link
    code_hash   TEXT NOT NULL,              -- sha256(email + ':' + codice)
    purpose     TEXT NOT NULL,              -- 'login' | 'delete'
    created_at  INTEGER NOT NULL,
    expires_at  INTEGER NOT NULL,
    attempts    INTEGER NOT NULL DEFAULT 0,
    consumed_at INTEGER,
    ip_hash     TEXT NOT NULL DEFAULT '',
    ua          TEXT NOT NULL DEFAULT ''
);
CREATE INDEX idx_auth_codes_email ON auth_codes(email, created_at);
CREATE TABLE sessions (
    id           TEXT PRIMARY KEY,          -- token opaco, 32 byte urlsafe
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    created_at   INTEGER NOT NULL,
    last_seen_at INTEGER NOT NULL,
    expires_at   INTEGER NOT NULL,
    device_name  TEXT NOT NULL DEFAULT '',
    ip_hash      TEXT NOT NULL DEFAULT '',
    revoked_at   INTEGER
);
CREATE INDEX idx_sessions_account ON sessions(account_id);
CREATE TABLE account_jobs (
    job_id         TEXT PRIMARY KEY,
    account_id     INTEGER NOT NULL REFERENCES accounts(id),
    created_at     INTEGER NOT NULL,
    kind           TEXT NOT NULL,           -- 'generate' | 'translate' | 'optimize'
    book_title     TEXT NOT NULL DEFAULT '',
    output_format  TEXT NOT NULL DEFAULT '',
    voice          TEXT NOT NULL DEFAULT '',
    lang           TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL DEFAULT 'running',
    paid_eur       REAL NOT NULL DEFAULT 0,
    download_token TEXT NOT NULL DEFAULT '',
    source         TEXT NOT NULL            -- 'forced' | 'payments'
);
CREATE INDEX idx_account_jobs_list ON account_jobs(account_id, created_at DESC);
```

`plan` e `plan_until` sono predisposti per il blocco abbonamenti; qui
restano `'free'`/`NULL`.

API principali di `accounts.py`:

- `request_code(email, purpose, lang, ip_hash, ua, now) -> (token, code) | None`
  — `None` se la finestra per-email (3 richieste / 10 min) è esaurita. Il
  chiamante spedisce l'email; il modulo non conosce SMTP.
- `verify(token=None, email=None, code=None, purpose='login', now) ->
  ('ok', account) | ('wrong'|'expired'|'locked'|'none', None)` — incrementa
  `attempts`, blocca al 6°, consuma (`consumed_at`) una sola volta; su
  `purpose='login'` crea l'account se manca, aggiorna `lang` e
  `last_login_at` e, se è il **primo login**,
  esegue l'adozione retroattiva.
- `open_session(account_id, device_name, ip_hash, now) -> session_token`.
- `resolve_session(token, now) -> account | None` — non revocata, non
  scaduta; se `last_seen_at` è più vecchio di 1 h aggiorna
  `last_seen_at` e `expires_at = now + SESSION_DAYS` (rinnovo scorrevole
  senza una scrittura per hit).
- `revoke_session(token)`, `revoke_all(account_id)`.
- `adopt_history(account)` — legge `_payments.json` e inserisce
  `account_jobs` con `source='payments'` per i record con la stessa email
  e un `job_id`; marca `account_id` nei record di `_voice_clones.json` con
  `owner_email` uguale (tramite `voice_clone.link_account(clone_id,
  account_id)`, funzione nuova che salva il solo campo). Idempotente
  (PK su `job_id`; il campo voce viene sovrascritto con lo stesso valore).
- `record_job(account_id, job_id, kind, book_title, output_format, voice,
  lang, paid_eur, source)`, `update_status(job_id, status,
  download_token='')`, `attach_if_known(job_id, email, ...)` (scrive solo
  se l'account esiste già).
- `list_jobs(account_id, page, per_page=50) -> (rows, total)`.
- `delete_account(account_id, now)` — in una transazione: sessioni
  revocate, `account_jobs` cancellate, `deleted_at = now`, `email`
  sostituita da `deleted:<email_hash>` (la riga resta per l'audit; un
  nuovo login con la stessa email crea un account nuovo e ripete
  l'adozione), `account_id` rimosso dalle voci campionate.
- `purge_expired(now)` — vedi Retention.

Tutti i confronti di hash con `hmac.compare_digest`.

### `account_page.py` — pagina `/account` (server-side)

Stesso modello di `_render_dl_page` e delle pagine `/vc/...`: HTML
generato in Python, testi da `i18n/account_pages.json` (it/en/fr/es/de/zh/hi,
chiavi `account.*`), ogni valore proveniente dai dati passa per
`html.escape`. Lingua = `accounts.lang` con fallback `en`.

Contenuto: email, pulsanti "Esci", "Esci da tutti i dispositivi",
"Elimina account"; elenco job paginato server-side (`?p=N`, 50 per
pagina) con data, titolo, tipo, formato, voce (etichetta generica: mai il
nome del provider), esito, importo se pagato; per ogni job i pulsanti di
download risolti a render (vedi sotto); riga "N voci campionate collegate"
con link alla gestione attuale `/vc/...` (la gestione da account arriva
nel Blocco 2).

Senza sessione valida: redirect `302` a `/?login=1`; la SPA apre il modal
e, a login riuscito, torna a `/account`.

### Route in `audiobook_app.py`

Tutte sotto `ABM_ACCOUNT_ENABLE=1` e `_smtp_available()`; altrimenti `404`
(stesso gate `_vc_gate` delle voci campionate).

| Route | Comportamento |
|---|---|
| `POST /api/auth/request` `{email, lang, device_name?}` | rate limit IP via `_ip_rl_check` (5/min, 30/h) → `accounts.request_code` → email con link `/auth/<token>` **e** codice. Risposta sempre `{ok:true}` (nessuna enumerazione, SMTP giù compreso) |
| `GET /auth/<token>` | pagina "Conferma accesso" con email mascherata e pulsante. **Non consuma** il token (gli scanner di posta seguono i link) |
| `POST /api/auth/verify` `{token}` oppure `{email, code}` | `accounts.verify` → sessione; cookie `abm_session` (HttpOnly, Secure se https / `X-Forwarded-Proto`, SameSite=Lax, max-age 90 gg). Se la richiesta porta `X-ABM-Cid` (app) il body contiene anche `{session_token}` da usare come `Authorization: Bearer` |
| `POST /api/auth/logout` | revoca la sessione corrente, cancella il cookie |
| `POST /api/auth/logout_all` | revoca tutte le sessioni dell'account |
| `GET /api/auth/me` | `{logged_in, email, lang, plan, sessions_count}` o `{logged_in:false}`; **sempre 200** (la SPA lo chiama al boot) |
| `GET /account` | pagina storico |
| `GET /api/account/jobs?p=N` | stesso elenco in JSON: `{jobs:[{job_id, created_at, kind, book_title, output_format, status, paid_eur, downloads:[{kind, url, expires_at}]}], total, page}` |
| `POST /api/account/delete_request` | email con link/codice `purpose='delete'` |
| `POST /api/account/delete_confirm` `{token}` \| `{code}` | `accounts.delete_account` + email "account eliminato" |

`_current_account()`: Bearer ha precedenza sul cookie; entrambi portano lo
stesso token opaco; nessun JWT, revoca immediata. Il token non compare mai
in query string tranne che nel link `/auth/<token>`, consumato solo via
POST.

### Download dallo storico

I file restano autorizzati dai **token di download** esistenti: la riga
`account_jobs.download_token` punta al token in `_download_tokens`; se il
token è vivo si emettono le URL `/dl/<token>/<kind>` (già cold-aware:
redirect a presigned R2 dopo l'hot-evict). Token morto o file assenti su
entrambi i tier → badge "scaduto", nessun pulsante. Token a meno di 2 h
dalla scadenza → tempo residuo con `_effective_retention_for_token_info`.
Nessun archivio aggregato "scarica tutto" (incidente `download.zip`).

## Integrazione con i flussi esistenti

### Un solo punto di ingresso: `_apply_account_to_job(job, job_id, kind)`

Chiamato in `/api/generate`, `/api/optimize` (ramo combinato) e
`/api/translate` subito dopo la creazione del job. Se `_current_account()`
esiste:

1. forza `job["notify_email"] = account.email`, `notify_lang`,
   `email_registered = True`, `_auto_batch_notify = True`, marker
   `.email_sent` pending e descrittore in `pending_jobs` — lo stesso
   effetto di `_register_paid_job_batch` senza pagamento. Il corpo comune
   viene fattorizzato in `_arm_email_delivery(job, job_id, email, ...)`,
   chiamato da entrambe;
2. `accounts.record_job(..., source='forced', status='running')`.

`/api/register_email` (e `submitEmailLate`/`submitEmailLateTr` lato SPA)
con sessione attiva e email diversa → `409 logged_in_email_forced`: la
regola vale anche contro un client modificato.

### Job senza sessione ma con pagamento

`_register_paid_job_batch` chiama `accounts.attach_if_known(job_id, email,
...)`: riga `source='payments'` solo se l'account esiste già; altrimenti
nulla (sarà adottata al primo login da `_payments.json`). I batch gratuiti
via email di chi non ha account non lasciano traccia (solo prove certe).

### Stato del job

`generation_engine.configure(account_job_status_fn=...)`;
`_set_job_status` (già usato da `load_metrics`) chiama
`accounts.update_status(job_id, status)`. Alla creazione del token di
download il chiamante salva `download_token` nella riga.

Pagamento PayPal con email del pagatore diversa da quella dell'account: la
notifica resta forzata all'email dell'account; l'email PayPal finisce solo
in `_payments.json` come oggi.

### SPA (`static/js/app.js`, fragment `html_head.html`, `i18n_data.js`)

- Al boot `GET /api/auth/me`; header con "Accedi" oppure email abbreviata,
  link `/account`, "Esci".
- Modal login: email → `POST /api/auth/request` → schermata "controlla la
  posta" con campo codice a 6 cifre → `POST /api/auth/verify {email,
  code}`. Il link nell'email è la via alternativa. `?login=1` apre il modal
  e memorizza il ritorno a `/account`.
- Loggato: i box email (`notifyEmailLate`, `notifyEmailLateTr`,
  `payEmailNotice`, email del pagamento voucher) mostrano l'email di login
  in sola lettura con il testo "Le notifiche arrivano a …"; sparisce
  l'avviso "se chiudi la pagina viene annullato".
- La cache di `me` è invalidata su login/logout e a ogni
  `409 logged_in_email_forced`.

## Retention, cancellazione, backup

- `accounts.purge_expired(now)` una volta al giorno dal `_cleanup_loop`:
  elimina `account_jobs` con `created_at < now − HISTORY_MONTHS` per gli
  account con `plan='free'` o `plan_until < now − GRACE_DAYS`; elimina
  `auth_codes` scaduti da più di 24 h e `sessions` scadute o revocate da
  più di 30 giorni.
- Cancellazione account: vedi `delete_account`. `_payments.json` intatto
  (730 giorni fiscali).
- Backup: `scripts/backup_ABM.sh` include il dump di `db.backup_to`;
  replica su R2 del dump con lo stesso `_replica_loop`/`_backup_daily` di
  `_voice_clones.json` (mai il file vivo). Restore e query utili
  (`sqlite3 abm.db "select …"`) in `docs/FORENSICS_PLAYBOOK.md`; il CLI
  `sqlite3` va installato sul server.

## Configurazione (da aggiungere a `md_files/PARAMETRI_CONFIGURAZIONE.md`)

| Variabile | Descrizione | Default |
|---|---|---|
| `ABM_ACCOUNT_ENABLE` | interruttore dell'intera funzione (0 = header senza "Accedi", endpoint 404) | `1` |
| `ABM_ACCOUNT_SESSION_DAYS` | durata scorrevole della sessione | `90` |
| `ABM_ACCOUNT_CODE_TTL_MIN` | validità di link e codice | `10` |
| `ABM_ACCOUNT_CODE_MAX_ATTEMPTS` | tentativi di verifica per codice | `5` |
| `ABM_ACCOUNT_HISTORY_MONTHS` | retention dello storico per account free | `24` |
| `ABM_ACCOUNT_GRACE_DAYS` | grace period dopo la fine del piano prima della retention free | `90` |

## Log business

Eventi in `activity_*.log` via `_log_activity`, session id `acct-<hash8>`,
mai l'email in chiaro: `ACCOUNT_LOGIN`, `ACCOUNT_LOGOUT`,
`ACCOUNT_LOGOUT_ALL`, `ACCOUNT_DELETE`, `ACCOUNT_ADOPT` (numero di job
adottati nel campo filename).

## Sicurezza

- Token e codici salvati solo hashati; confronto in tempo costante.
- Risposte neutre su `request` (email sconosciuta, SMTP giù, rate limit
  per email raggiunto).
- Rate limit per IP con `_ip_rl_check`; per email 3 richieste / 10 min.
- Cookie HttpOnly + Secure + SameSite=Lax; POST JSON → CSRF coperto.
- `ip_hash = sha256(ABM_IP_SALT + ip)[:16]` come nel resto del progetto.
- `GET /auth/<token>` non ha effetti; la conferma è un POST.
- Nessun secondo canale di autorizzazione sui file: valgono i token di
  download esistenti.

## Test

- `test/test_db.py`: migrazioni idempotenti su `tmp_path`, `backup_to`
  produce un DB apribile, `tx()` serializza fra thread e fa rollback.
- `test/test_accounts.py` (core, DB su `tmp_path`): request→verify via
  token e via codice; scadenza; 6° tentativo bloccato; token consumato una
  sola volta; sessione scorrevole (rinnovo solo oltre 1 h); `revoke_all`;
  adozione da `_payments.json` e `_voice_clones.json` finti, idempotente;
  `purge_expired` 24 mesi vs piano attivo vs grace; `delete_account`.
- `test/test_account_routes.py` (Flask test client): risposta neutra;
  rate limit; flag del cookie; Bearer con `X-ABM-Cid`; `GET /auth/<token>`
  non consuma; `/account` redirect senza sessione; paginazione;
  `409 logged_in_email_forced`; `/api/generate` con sessione ⇒
  `notify_email` forzata e riga in `account_jobs`; `/api/auth/me` sempre
  200; `ABM_ACCOUNT_ENABLE=0` ⇒ 404.
- `test/test_app_js_account.py`: hook presenti nel bundle (`/api/auth/me`
  al boot, modal, campi email in sola lettura, `?login=1`).
- `test/test_account_page.py`: 7 lingue senza chiavi mancanti; `book_title`
  con `<script>` escapato.

## Sequenza di consegna

Commit locali sul branch `gestione-utenti`; nessun push senza conferma
esplicita; bump di versione a fine blocco.

1. `db.py` + test.
2. `accounts.py` + `voice_clone.link_account` + test.
3. Route auth/account, `account_page.py`, `i18n/account_pages.json`,
   email di login/cancellazione in `email_service` + test.
4. `_arm_email_delivery`, `_apply_account_to_job`, hook in
   `_set_job_status` e alla creazione del token, `409` su
   `/api/register_email` + test.
5. SPA: modal, header, campi email forzati, `?login=1` + test bundle.
6. `purge_expired` nel cleanup, `backup_ABM.sh`, replica R2, playbook,
   `PARAMETRI_CONFIGURAZIONE.md`.
7. Collaudo manuale in locale (SMTP reale o finto) prima di qualunque push.

## Fuori scope

- Gestione delle voci campionate da account (Blocco 2): qui solo il link
  `account_id` sul record voce.
- Voucher acquistabili, abbonamenti, spazio riservato, quota per piano.
- Migrazione dell'activity log su SQLite (rebase di `ABM_DB`).
- Uso dell'account come chiave di quota/anti-abuso (`free_quota`,
  `abuse_watch` restano su `client_id`).
- Modifiche alle app mobili: solo il contratto Bearer/JSON qui definito.
