# App mobile AudioBook Maker (Android + iOS) — Design

**Data:** 2026-06-11
**Stato:** approvato in brainstorming, in attesa di piano implementativo
**Codice app:** repository Git separato (`audiobook-maker-mobile`). Questo documento vive nel repo backend perché ne specifica anche le modifiche.

## Obiettivo

App nativa Android + iOS, codebase unica **Flutter**, che:

1. Replica l'intero flusso di produzione del sito (upload → analisi → ottimizzazione AI → traduzione → TTS → consegna) sullo stesso backend Flask.
2. Gestisce una **cartella repository locale** scelta dall'utente, contenente i file audio (mp3/m4b) scaricati dall'app o copiati da altre app.
3. Offre un **player audiolibri** completo (copertina, capitoli, background, lock screen) sui file della cartella.
4. Riceve **notifiche push** (FCM) al completamento dei job, oltre all'email esistente.

## Decisioni chiave

| Tema | Decisione |
|------|-----------|
| Tecnologia | Flutter (Dart), Material 3, un solo codebase |
| Scope MVP | Parità completa col web + libreria locale + player. Escluso: `zip_rss`/podcast |
| Pagamenti | **Solo voucher** acquistati sul sito. Nessun IAP, nessun PayPal in-app, nessun link d'acquisto esterno (conformità store, zero commissioni) |
| Notifiche | Push FCM (Android + iOS via APNs) accanto all'email |
| Navigazione | 4 tab fisse: Libreria, Crea, Attività, Impostazioni + mini-player persistente |
| Player | Copertina grande, capitoli in bottom sheet |
| Codice | Repo separato; backend modificato solo in modo additivo |

## Architettura Flutter

```
lib/
├── api/          # AbmApiClient (dio): endpoint esistenti + nuovi; parser SSE
├── core/
│   ├── library/  # LibraryRepository: scansione cartella, indice SQLite (drift)
│   ├── player/   # PlayerService: just_audio + audio_service
│   ├── m4b/      # Parser Dart atom MP4: capitoli (chap/chpl), cover, metadata
│   └── jobs/     # JobsService: stato job remoti, polling/SSE, push FCM
└── ui/           # library/ player/ create/ settings/
```

- **Stato:** Riverpod.
- **Persistenza:** SQLite (drift) come *indice ricostruibile* (libreria, posizioni di ascolto, cronologia job); `shared_preferences` per le preferenze. I file audio stanno solo nella cartella repository.
- **i18n:** 7 lingue da subito; script di conversione `i18n/*.json` (sito) → ARB (Flutter).
- **Identità:** `abm_cid` generato dall'app (UUID persistente), inviato su ogni chiamata (header/cookie). Stesso modello di fiducia del web. Header `X-ABM-App-Version` per compatibilità futura.
- **Pacchetti chiave:** `dio`, `just_audio`, `audio_service`, `drift`, `firebase_messaging`, `connectivity_plus`, picker SAF/documents per piattaforma.

## Navigazione e schermate

4 tab fisse di pari importanza; mini-player sopra la tab bar quando c'è riproduzione attiva.

### Libreria
- Lista audiolibri della cartella repository: copertina, titolo, n. capitoli, durata, barra avanzamento, badge nuovo/in corso/finito.
- Pull-to-refresh = riscansione cartella. "+" = import file via picker.
- Tap → player. Long-press → dettaglio/elimina file.

### Player (copertina grande + bottom sheet capitoli)
- Baseline: play/pausa, seek, capitolo corrente, copertina, controlli lock screen/cuffie/auto (audio_service), ripresa dalla posizione salvata per file.
- MVP: velocità 0.5×–3×, sleep timer (N minuti o fine capitolo), salto avanti/indietro configurabile (±10/30s), chip "Capitoli" → bottom sheet con lista e durate.

### Crea (wizard, replica del flusso web)
1. **Sorgente:** file picker (EPUB/PDF/TXT/ABM), file dalla cartella repository, o share intent da altre app → upload multipart `POST /api/analyze` con progress.
2. **Analisi:** `BookInfo` — titolo, autore, copertina, capitoli selezionabili, anteprima testo.
3. **Ottimizzazione AI** (opzionale): costo dal backend; sotto soglia gratis; sopra → solo campo voucher. Avvio in modalità **batch** (push + email al termine). Include il passo opzionale di **traduzione** (stesso contratto API del web).
4. **Voce e formato:** lingua/voce con anteprima (`/api/preview_audio`), formato M4B (default) / MP3 / ZIP. `zip_rss` escluso dall'MVP.
5. **Generazione:** batch; job visibile in Attività.
6. **Consegna:** da push o da Attività → "Scarica nella libreria" → M4B/MP3 (+ ABM se presente) salvati nella cartella repository → appare in Libreria.

### Attività
- Lista job del client da `GET /api/my_jobs`: in corso (progress live via SSE, fallback polling), completati (download fino a scadenza retention, con countdown), falliti (messaggio; il rimborso voucher è invariante backend esistente).
- **Recovery automatico:** a ogni avvio app e ritorno in foreground, `my_jobs` ricostruisce lo stato e riaggancia il progress dei job attivi.

### Impostazioni
- Cartella repository (cambio cartella), lingua UI, gestione notifiche, info/versione.

## Repository locale

- **Onboarding al primo avvio:** scelta cartella.
  - **Android:** SAF `ACTION_OPEN_DOCUMENT_TREE`, permesso persistente; la cartella è scrivibile da altre app.
  - **iOS:** default = Documents dell'app esposta in File (`UIFileSharingEnabled` + `LSSupportsOpeningDocumentsInPlace`); alternativa: cartella esterna/iCloud via document picker con security-scoped bookmark (possibile ri-conferma occasionale).
- **Scansione:** avvio + pull-to-refresh. Nuovi mp3/m4b → metadati (ID3/MP4, copertina, capitoli m4b con parser Dart) → indice SQLite. File rimossi → voce rimossa; posizione di ascolto conservata 30 giorni per re-import.
- **Import:** share intent e "+" copiano il file nella cartella.
- **Download job:** salvataggio diretto nella cartella, nome `Titolo - Autore.ext` sanitizzato (stessa logica backend).

## Parser m4b (Dart)

Lettura atom MP4: capitoli QuickTime (`chap` track reference + testo) e Nero (`chpl`), cover (`covr`), metadata iTunes (`©nam`, `©ART`, …). Nessuna dipendenza FFmpeg lato app. Fixture di test binarie generate con FFmpeg dal backend (gli stessi m4b che il backend produce).

## Modifiche backend (additive, zero impatto SPA)

1. **`POST /api/device/register`** — `{fcm_token, platform, app_version}` associato al `abm_cid`. Persistenza `_device_tokens.json` (pattern JSON esistente). Rimozione token su risposta FCM "unregistered".
2. **`GET /api/my_jobs`** — job del `abm_cid` chiamante, combinando: `jobs` in-memory (attivi: status, fase, progress) + `_download_tokens.json` (completati entro retention: formati disponibili, scadenza). Robusto al riavvio server.
3. **Push FCM** — nuovo modulo `push_service.py` (pattern `email_service.py`, FCM HTTP v1 con service account). Invio al COMPLETE e all'ERROR accanto all'email. Fallimento push = solo log, mai bloccante.

Download con `Range` (resume su rete mobile): verificare/abilitare sugli endpoint di download file.

## Error handling e offline

| Scenario | Comportamento |
|----------|---------------|
| Offline totale | Libreria e player 100% funzionanti; Crea/Attività in stato "offline" con retry automatico (`connectivity_plus`) |
| Download interrotto | Resume con `Range` |
| Upload interrotto | Ripetibile (analisi idempotente) |
| SSE caduto | Fallback a polling REST 5s, ritorno a SSE quando possibile |
| Job fallito | Push + voce rossa in Attività; rimborso voucher lato backend (esistente) |
| File corrotto in cartella | try/catch per file: voce generica (nome file), scansione mai bloccata |
| Errori voucher | Già normalizzati dal backend, mostrati localizzati |

## Testing

- **Unit Dart:** parser m4b (fixture FFmpeg), AbmApiClient (mock HTTP), LibraryRepository (scansione/diff/posizioni).
- **Widget test:** wizard, libreria, player con PlayerService mockato.
- **Device reali (checklist manuale):** background audio, lock screen, push, SAF/Files — aree inaffidabili in emulatore.
- **Backend pytest:** `test/test_mobile_api.py` per i 3 interventi (stile test esistenti).

## Fuori scope MVP

- `zip_rss` / podcast RSS.
- Qualsiasi pagamento in-app (IAP, PayPal) o link d'acquisto.
- Streaming dal server (si scarica e si ascolta in locale).
- Sync posizioni multi-device.

## Rischi

| Rischio | Mitigazione |
|---------|-------------|
| Review store: app "companion" che cita voucher esterni | Wording neutro: campo "codice voucher" senza link/CTA d'acquisto; il free-tier (<€0.50) rende l'app utilizzabile senza pagare |
| Background limits (iOS sospende l'app durante job lunghi) | Tutta la produzione è batch lato server; l'app non deve restare viva |
| Security-scoped bookmark iOS perde validità | Default = Documents dell'app (sempre valida); cartella esterna come opzione avanzata |
| Capitoli m4b non standard (file di terzi) | Parser tollerante: senza capitoli il file si ascolta comunque come traccia unica |
