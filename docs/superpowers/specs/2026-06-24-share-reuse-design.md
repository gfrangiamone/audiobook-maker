# Riuso della condivisione audiolibro — Design

Data: 2026-06-24
Stato: approvato

## Obiettivo

Quando l'utente ri-condivide lo **stesso** audiolibro a distanza di poco tempo,
il sistema oggi ricomincia da capo (per le share "ready" genera un nuovo
token/link; per le "upload" **ri-carica** il file). Invece, finché esiste ancora
una condivisione **viva** dello stesso file e il file è **recuperabile**, va
**riusata** quella condivisione — **stesso link**, con il **TTL resettato a 120
min** dal momento della nuova richiesta — senza nuovo upload né nuovo token.

## Decisioni approvate

- **Chiave di riuso uniforme**: `cid` + **fingerprint** del file. Il fingerprint
  è una stringa **opaca** calcolata dall'app e confrontata per uguaglianza dal
  backend (il backend non ne conosce l'algoritmo).
- **Fingerprint (app)**: veloce, basato su contenuto — `SHA-256(dimensione ‖
  primi 64KB ‖ ultimi 64KB)`; file < 128KB → hash dell'intero file. Legge pochi
  KB → istantaneo anche su file grandi.
- **Reset TTL** a `ABM_SHARE_TTL_SEC` (7200s = 120 min) ad ogni riuso, **senza
  cap** sul numero di reset.
- Il link riusato è **lo stesso** di prima (link già copiati restano validi con
  scadenza estesa).
- Se la share esiste ma il **file non è più recuperabile** → niente riuso, si
  procede con create fresco (ready/upload).

## Componenti

### App (`audiobook_maker_mobile`)
- Helper `shareFingerprint(File)` → `String` (SHA-256 di dimensione + primi/ultimi
  64KB; file piccoli → intero file). In `lib/core/api/` (puro, testabile).
- `AbmApiClient.shareCreate(...)` accetta e invia `fingerprint` nel body.
- `ShareService.prepare(...)` calcola il fingerprint dal file e lo passa a
  `shareCreate`. Nessun'altra modifica al flusso UI (la risposta `mode:"ready"`
  del riuso è già gestita → il link compare subito, niente upload).

### Backend (`AudioBook-Maker`, `/api/share/create` + `/api/share/finalize`)
- Helper `_share_file_recoverable(info)`: ready → `_resolve_ready_file` trova il
  file (anche cold storage); upload → `storage_backend.object_exists(s3_key)`.
- Helper `_find_reusable_share(cid, fingerprint, now)`: primo token vivo dello
  stesso `cid` con `fingerprint` uguale, `kind in (ready, upload)`, file
  recuperabile; altrimenti `(None, None)`. `fingerprint` vuoto → nessun riuso.
- `create`: legge `fingerprint` dal body. **Prima** della logica ready/upload
  tenta il riuso: se trovato → `created_at=now`, `ttl_sec=ABM_SHARE_TTL_SEC`,
  salva, ritorna `{mode:"ready", share_token:<esistente>, link, ttl_sec}`.
  Altrimenti procede come ora **memorizzando `fingerprint`** sul token creato
  (ready e pending).
- `finalize`: porta `fingerprint` dal record `pending` al nuovo token `upload`.

## Flusso dati

```
ricondivido stesso audio
  → app calcola fingerprint → POST /api/share/create {job_id?, filename, fingerprint}
  → _find_reusable_share(cid, fingerprint): share viva + file recuperabile?
        sì → reset created_at + ttl_sec; ritorna stesso link (mode ready)   [no upload]
        no → logica attuale (ready se job online, else upload); salva fingerprint
```

## Casi limite

- Share trovata ma file non recuperabile (job scaduto/eliminato, oggetto R2
  sparito) → ignora il riuso, create fresco.
- `pending` (upload a metà) **non** riusabile (solo `ready`/`upload`).
- `fingerprint` assente nel body (vecchie app) → nessun riuso, comportamento
  identico a oggi (retrocompatibile).
- Più share vive con lo stesso fingerprint (residui pre-feature) → si riusa la
  prima trovata, resettandone il TTL.

## Testing

- Backend (`test/test_share_api.py`): riuso ready ritorna lo stesso `share_token`
  + `mode:"ready"` + resetta `created_at`/`ttl_sec`; riuso upload con
  `object_exists` True idem; nessun riuso se file non recuperabile; `fingerprint`
  memorizzato su create (ready+pending) e portato in finalize.
- App: `shareFingerprint` stabile per lo stesso contenuto e diverso al cambiare
  del contenuto; `shareCreate` inserisce `fingerprint` nel body.

## Fuori scope (YAGNI)

- Cap sul numero di reset TTL.
- Deduplica retroattiva di share esistenti senza fingerprint.
- Riuso cross-`cid` (la condivisione resta legata al client che l'ha creata).
