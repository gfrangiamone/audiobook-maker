# App mobile: login con magic link e area personale

Data: 2026-09-21. Repo interessati: `audiobook-maker-mobile` (quasi tutto) e
`AudioBook-Maker` (una riga nell'AASA). Contratto server di riferimento:
`2026-09-19-account-magic-link-design.md`.

## Obiettivo

L'app Flutter permette di accedere all'account AudioBook Maker con lo stesso
meccanismo del sito (email → link magico + codice a 6 cifre) e di consultare
l'area personale (storico audiolibri cross-device con download in libreria,
logout, cancellazione account). La tab «Voci campionate» del sito **non** è
riproposta nell'app: è legata al servizio premium di clonazione vocale, non
disponibile su mobile.

## Contratto server usato (già esistente)

Header su ogni richiesta: `X-ABM-Cid`, `X-ABM-Platform` e, da loggato,
`Authorization: Bearer <session_token>` (il Bearer ha precedenza sul cookie;
l'app non usa cookie). Nessun header `Origin`/`Referer`.

| Endpoint | Uso nell'app |
|---|---|
| `POST /api/auth/request {email, lang}` | invio link + codice. Risposta sempre neutra `200 {ok}`; `400 invalid_email`; `429 rate_limited` + `retry_after`; `404 account_disabled` |
| `POST /api/auth/verify {email, code, device_name}` oppure `{token, device_name}` | apre la sessione. `200 {ok, email, lang, plan, session_token}` (il `session_token` c'è solo con `X-ABM-Cid`); `401` con `error_code` ∈ `wrong, expired, locked, none` |
| `GET /api/auth/me` | `{logged_in, enabled, email?, lang?, plan?, sessions_count?}`, sempre 200 |
| `POST /api/auth/logout` | `200 {ok}` |
| `GET /api/account/jobs?p=N` | `{jobs[], total, page, per_page=50}`; `401 unauthorized` |
| `GET /api/account/progress?ids=a,b` (max 50) | `{jobs: {id: {status, pct, ...}}}` |
| `POST /api/account/delete_request` | invia link + codice di cancellazione all'email dell'account |
| `POST /api/account/delete_confirm {code}` | `200 {ok}`; `401 wrong/expired/locked/none` |

Riga di `/api/account/jobs`: `job_id, created_at (epoch), kind ∈ generate|
optimize|translate, book_title, output_format, status ∈ running|done|error|
cancelled, paid_eur, downloads[{kind ∈ page|m4b|abm|translated, url, expires_at}]`.

Vincoli noti: `/api/my_jobs` resta legato al cid (la tab Attività non cambia);
non esiste un endpoint che unisca i job anonimi all'account (solo l'adozione
al primo login e `POST /api/register_email` per singolo job); non esiste JSON
per la lista dispositivi (voce omessa nell'app).

## Modifica al server (repo AudioBook-Maker)

`apple_app_site_association` in `audiobook_app.py`: `paths` diventa
`["/t/*", "/s/*", "/auth/*"]`, con test aggiornato. `GET /auth/<token>` resta
com'è: non consuma il token, quindi l'app può intercettare il link e verificare
via `POST /api/auth/verify {token}`. Commit separato, senza toccare i file già
modificati nel working tree.

## Architettura app

### `lib/core/auth/`

- `AuthSession { email, lang, plan, sessionToken }` (immutabile, `fromJson`).
- `AuthStore`: persiste `sessionToken` + `email` in `flutter_secure_storage`
  (Keychain/Keystore). API: `read()`, `write(session)`, `clear()`.
- `AuthException { code }` con `code` ∈ `wrong, expired, locked, none,
  rate_limited (+retryAfter), account_disabled, unauthorized, invalid_email,
  generic`. Prodotta dal client a partire da `error_code`/status.
- `parseAuthPayload(String raw) → ({baseUrl, token})?` per i link
  `https://host[/path]/auth/<token>` (stesso stile di `parseTransferPayload`).
- `deviceName()`: modello del dispositivo (`device_info_plus` NON aggiunto:
  si usa `Platform.operatingSystem` + versione app, es. «Android · app 1.5.0»).

### `AbmApiClient`

- `sessionToken` settabile (`set sessionToken(String?)`): imposta/rimuove
  l'header `Authorization`.
- Nuovi metodi: `authRequest(email, lang)`, `authVerifyCode(email, code,
  deviceName)`, `authVerifyToken(token, deviceName)`, `authMe()`, `authLogout()`,
  `accountJobs(page)`, `accountProgress(ids)`, `accountDeleteRequest()`,
  `accountDeleteConfirm(code)`.
- Mappatura errori: 401 con `error_code` → `AuthException(code)`; 429 →
  `rate_limited`; 404 `account_disabled` → `account_disabled`; altro →
  `ApiException` come oggi.

### Provider (`lib/app/providers.dart`)

- `authStoreProvider`, `authProvider` (`StateNotifier<AuthState>`):
  `AuthState { status ∈ unknown|anonymous|loggedIn|disabled, email? }`.
  All'avvio legge lo store, se c'è un token chiama `/api/auth/me`: `logged_in`
  → `loggedIn`, `enabled:false` → `disabled`, altrimenti `anonymous` con store
  azzerato. Metodi: `requestCode`, `verifyCode`, `verifyToken`, `logout`,
  `invalidate()` (usato su 401 dagli endpoint account).
- `apiClientProvider` ora dipende anche dal token: quando cambia, il client
  viene ricreato con il Bearer. `PushSetup`/metriche non hanno bisogno del
  Bearer.

### UI

- **Drawer** (`app_drawer.dart`), sopra «Impostazioni»: anonimo → «Accedi»;
  loggato → «Area personale» con l'email come sottotitolo; `disabled` o server
  non configurato → nessuna voce.
- **`LoginScreen`** (`lib/app/account/login_screen.dart`), due passi:
  1. email + «Invia codice». Testo intro identico al sito (nessuna password,
     link + codice, ritrovi i tuoi audiolibri).
  2. «Abbiamo inviato un codice a {email}. Inseriscilo qui oppure apri il link
     nell'email (vale 10 minuti).», campo 6 cifre numerico, «Accedi», link
     «Richiedi un nuovo codice». Errori: `wrong` inline e si resta sul passo 2;
     `expired|locked|none` → messaggio e ritorno al passo 1; `rate_limited` →
     «Troppe richieste: riprova tra qualche minuto».
  Al successo: pop, snackbar «Connesso come {email}», apertura di
  `AccountScreen`.
- **Deep link** `/auth/<token>` (in `shell.dart`, dopo la normalizzazione
  `abm://`): `verifyToken` → snackbar «Connesso come …» + push di
  `AccountScreen`; errore → snackbar col messaggio mappato. Manifest Android:
  `pathPrefix="/auth/"`; iOS già coperto dal dominio associato.
- **`AccountScreen`** (`lib/app/account/account_screen.dart`):
  - header «Connesso come {email}»;
  - lista paginata (50) con «Carica altri»; riga: titolo (fallback job_id),
    data, tipo, badge stato, formato, «€ x,xx» se `paid_eur > 0`;
  - job `running`: barra di avanzamento aggiornata ogni 3 s via
    `accountProgress` (solo con la schermata visibile);
  - download: `m4b`/`abm` → «Scarica in libreria» tramite `DownloadService`
    (token estratto da `/dl/<token>/…`), chip «scade tra N h / scaduto»; `page`
    e `translated` → apertura nel browser con `url_launcher`;
  - stato vuoto: «Nessun audiolibro nel tuo account.»;
  - fondo: «Esci» (dialogo: «Verrai disconnesso su questo dispositivo…») e
    «Cancella account» (dialogo → `delete_request` → passo codice a 6 cifre →
    `delete_confirm` → sessione azzerata, pop, snackbar «Account cancellato»).
  - 401 in qualunque punto → `invalidate()` + ritorno al login.
- **Gate quota, variante email**: se loggato il campo email è precompilato con
  l'email dell'account e in sola lettura (il server risponde 409
  `logged_in_email_forced` a email diverse).

### i18n (template `app_it.arb`, poi en/de/es/fr/hi/zh)

Chiavi: `accountLogin`, `accountArea`, `accountSignedInAs({email})`,
`accountLoginIntro`, `accountEmailHint`, `accountSendCode`,
`accountCodeIntro({email})`, `accountCodeHint`, `accountVerify`,
`accountResendCode`, `accountErrWrong`, `accountErrExpired`, `accountErrLocked`,
`accountErrNone`, `accountErrRate`, `accountErrDisabled`, `accountErrGeneric`,
`accountJobsEmpty`, `accountKindGenerate`, `accountKindOptimize`,
`accountKindTranslate`, `accountStatusRunning`, `accountStatusDone`,
`accountStatusError`, `accountStatusCancelled`, `accountDownloadToLibrary`,
`accountOpenDownloadPage`, `accountDlExpiresIn({hours})`, `accountDlExpired`,
`accountLoadMore`, `accountLogout`, `accountLogoutTitle`, `accountLogoutBody`,
`accountLoggedOut`, `accountDelete`, `accountDeleteTitle`, `accountDeleteBody`,
`accountDeleteCodeIntro({email})`, `accountDeleteConfirm`, `accountDeleted`.
Testi italiani e inglesi ripresi da `i18n_data.js` e `account_pages.json` del
sito.

## Test

- Unità: `AuthException` da body/status, `parseAuthPayload`, `AuthStore` (con
  `FlutterSecureStorage` mock/in-memory), client (`DioAdapter`) per request,
  verify (codice/token, 401 wrong), me, logout, account jobs, progress,
  delete_confirm; `AuthNotifier` (avvio con token valido/non valido).
- Widget: `LoginScreen` (passo 1 → 2, `wrong` inline, `expired` torna al passo
  1, 429), `AccountScreen` (righe e badge, bottone download solo con m4b/abm,
  chip scadenza, flusso cancellazione), drawer (Accedi / Area personale /
  nascosto), shell deep link `/auth/<token>` → verify.
- README: changelog in «Stato» + checklist manuale (login con codice, login dal
  link sul telefono con build release, logout, cancellazione, download in
  libreria dall'area personale, gate quota da loggato con email bloccata).

## Fuori ambito

Lista dispositivi, «Voci campionate», unione dei job anonimi all'account,
crediti/voucher/piani (il server non li espone nell'area personale).
