# Voci campionate: la voce dell'utente come voce di lettura

Data: 2026-09-09. Branch: `voci-campionate`. Stato: bozza per revisione.

Estende la spec `2026-08-28-voxcpm-integrazione-design.md`, §6, §10, §11, §15.2
(la "release 2" rinviata in §17.3). Dove questa spec e quella divergono vale
questa.

## 1. Scopo

L'utente registra un campione della propria voce di 15-18 secondi, paga una
tantum, ascolta due clip demo sintetizzate con la sua voce, e da quel momento
la voce compare in cima alla lista delle voci VoxCPM della sua lingua e
accento, su quel dispositivo e su ogni altro dispositivo che il proprietario
autorizza via email.

### 1.1 Dentro il perimetro

- Bottone «Campiona la tua voce» accanto al box di scelta voce, wizard a
  pannelli.
- Registrazione dal browser o upload di un file audio.
- Gate di qualità automatico, riascolto e approvazione del campione.
- Pagamento fisso `ABM_EUR_CLONED_VOICE` (default 5 €) via PayPal o voucher.
- Due clip demo generate con la voce dell'utente, fino a tre rigenerazioni.
- Codice-voce per il recupero su altri dispositivi, con conferma via email
  del proprietario. Più voci sullo stesso dispositivo (dono).
- Revoca dei dispositivi, cancellazione della voce, retention con rinnovo
  all'uso.
- Ripresa del wizard dopo qualunque interruzione, con o senza cookie.

### 1.2 Fuori perimetro

- Uso della voce clonata su motori diversi da VoxCPM.
- Uso della voce su libri in lingua o accento diversi da quelli dichiarati.
- Più voci per lo stesso proprietario (una sola voce attiva per email).
- Modifica del campione dopo la creazione (si cancella e si rifà).
- App mobile: il wizard è solo web. L'API resta neutra e l'app potrà usarla
  in seguito.

## 2. Decisioni

| # | Decisione |
|---|---|
| D1 | Il testo letto è una **frase guidata** per lingua, da `voice_clone_prompts.json`. Niente cifre, marchi, nomi propri. È il `prompt_text` che VoxCPM esige (§7.4 della spec VoxCPM). |
| D2 | La frase letta viene **salvata nel record della voce**. Cambiare il JSON vale solo per le registrazioni future. |
| D3 | Lingue offerte: **tutte le lingue attive del catalogo** che hanno una frase guidata. Lingua attiva senza frase = non offerta. Accento dichiarato dall'utente fra quelli attivi della lingua; non cambia il testo. |
| D4 | Genere dichiarato (♀/♂) prima della registrazione. Serve al raggruppamento in combo e, in hindi, a scegliere la variante della frase. |
| D5 | Formati accettati: **wav, mp3, webm/opus, ogg, m4a/mp4** (MediaRecorder non produce mp3). Tutto convertito a **wav mono 24 kHz** con ffmpeg. |
| D6 | Gate di qualità in due stadi: misure lato server (porting di `tools/voice_prompts/audio.py` del worker, numpy) più **verifica ASR sul server dell'app** (faster-whisper su CPU, CER contro la frase guidata) come anti-impersonificazione. Il worker GPU non viene acceso per questo. |
| D7 | Durata accettata dal gate: **12-20 s**; sotto o sopra si chiede di rifare. La finestra 15-18 è il target dichiarato all'utente. |
| D8 | Prezzo: `ABM_EUR_CLONED_VOICE`, default **5.00**, una tantum. I libri letti con la voce campione costano **come gli altri libri VoxCPM**: scritto nel pannello 1. |
| D9 | Pagamento **prima** delle demo. Se l'utente rifiuta il risultato finale, **rimborso in voucher** (importo pieno, con il bonus standard dei voucher di rimborso) e voce cancellata. |
| D10 | **Tre rigenerazioni** delle demo incluse. Alla quarta richiesta il bottone sparisce; restano approva o rifiuta. |
| D11 | **Codice-voce** (leggibile, per l'utente) e **token interno** (`voxcpm:mine:<token>`) sono due valori diversi, mappati server-side. Il token non compare mai in URL né in email. |
| D12 | Il legame dispositivo↔voce è **server-side**: la voce tiene la lista dei `abm_cid` autorizzati. Nessun cookie aggiuntivo. |
| D13 | Primo uso del codice su un nuovo dispositivo: **codice-conferma** a 6 cifre inviato al proprietario, valido 15 minuti, 5 tentativi. |
| D14 | Revoca di un dispositivo e cancellazione della voce: **link con token segreto** (`manage_token`, salvato nel record come i token di download) nell'email del proprietario. L'email invita a conservarla. |
| D15 | Retention `ABM_VOICE_CLONE_RETENTION_DAYS` (default 365) **rinnovata a ogni uso** (generazione o accesso da dispositivo). Avviso email 30 giorni prima della scadenza. |
| D16 | Dopo il pagamento il server è **autonomo**: genera le demo anche se il browser sparisce. La voce diventa **usabile solo dopo l'approvazione** esplicita delle demo (stato `ready`). |
| D17 | L'email inviata al pagamento è **lo strumento di ripresa** del wizard: contiene il codice-voce e un link con `resume_token` che riapre il wizard al punto giusto. |
| D18 | La voce clonata vale **solo per VoxCPM** e **solo se lingua e accento del libro coincidono** con quelli dichiarati. Negli altri casi non compare. |
| D19 | Il campione vive in `ABM_DATA_DIR/voices/<token>/`, **fuori dal tiering hot/cold dei job**, con copia su R2 sotto `voices/`. |
| D20 | Una voce per email. Una nuova registrazione dallo stesso proprietario è ammessa solo dopo cancellazione della precedente. |

## 3. Esperienza utente

### 3.1 Il bottone

A destra del box di scelta voce, visibile solo se VoxCPM è disponibile
(`_voxcpm.available`) e la lingua del libro ha una frase guidata:
«Campiona la tua voce», tooltip «Registra la tua voce per poter ottenere libri
letti con essa». Se il dispositivo ha già una voce per quella lingua, il
bottone diventa «Le tue voci» e apre il pannello di gestione (§3.7).

### 3.2 Pannello 1: condizioni

Testo in lingua UI:

- La registrazione è lecita solo con la **propria voce reale**.
- Il campione resta **privato**: lo usa solo il proprietario e i dispositivi
  che lui autorizza.
- Costo **una tantum** `ABM_EUR_CLONED_VOICE`. I libri letti con questa voce
  costano come gli altri libri VoxCPM.
- La voce resta sul dispositivo corrente e si recupera altrove con il
  **codice-voce** inviato per email; il primo uso su un dispositivo nuovo
  richiede un codice di conferma inviato al proprietario.
- Conservazione `ABM_VOICE_CLONE_RETENTION_DAYS` giorni rinnovati a ogni uso,
  cancellazione in qualunque momento dal link in email, nessun uso per
  addestramento, nessuna condivisione.

Spunta obbligatoria «È la mia voce e ho il diritto di usarla», bottone
«Continua».

### 3.3 Pannello 2: campione

1. Selettori: **lingua** (solo lingue con frase guidata, preselezionata la
   lingua del libro), **accento** (accenti attivi della lingua, preselezionato
   quello del libro), **genere** (♀/♂).
2. La **frase guidata** a schermo, grande, con l'indicazione «leggila di
   seguito, con calma, in 15-18 secondi».
3. Due modi: **Registra** (MediaRecorder, indicatore di livello, timer,
   stop automatico a 25 s) oppure **Carica file** (formati D5, max
   `ABM_VOICE_CLONE_MAX_UPLOAD_MB`, default 20).
4. Al termine il browser invia il file a `POST /api/voice_clone/sample`. Il
   server converte, misura (§5.2), risponde con esito e motivo.
5. Esito negativo: messaggio specifico (§5.3), si torna al punto 3. Nessun
   limite oltre il rate limit (§10).
6. Esito positivo: il server risponde con un `sample_id` pubblico e l'URL del
   **wav normalizzato** (quello che VoxCPM userà); player, bottoni «Va bene,
   avanti» e «Rifaccio».

Il campione approvato resta sul server in stato `sample_ok` per
`ABM_VOICE_CLONE_SAMPLE_TTL_H` ore, legato al `abm_cid`; un nuovo campione
dello stesso cid sostituisce il precedente (un solo draft per dispositivo).
Il `sample_id` è il futuro `id` della voce.

### 3.4 Pannello 3: pagamento, email, frasi demo

1. **Email** due volte, con controllo di uguaglianza lato client e server.
   Se l'email ha già una voce attiva: errore «hai già una voce campione;
   recuperala con il codice-voce o cancellala prima».
2. **Frasi demo**: la prima è fissa (la `opening` comune del catalogo per il
   locale); la seconda si sceglie fra i testi demo non comuni del catalogo per
   quel locale (dedup per testo). La lista la fornisce
   `GET /api/voice_clone/demo_texts?locale=`.
3. **Pagamento**: bottoni PayPal (`/api/paypal_create_order_voice_clone`) o
   voucher (`/api/voucher_validate` con `purpose=voice_clone`). Alla capture
   il client chiama `POST /api/voice_clone/commit` con payment token, email,
   frase demo scelta.
4. Il server: consuma il pagamento, crea la voce in stato `paid`, invia
   l'**email di pagamento** (§8.1), avvia la generazione demo. Risponde con
   `clone_id` pubblico e codice-voce.

### 3.5 Pannello 4: demo

Barra di attesa con SSE `GET /api/voice_clone/progress/<clone_id>`. Testo
onesto sull'attesa: «da uno a quattro minuti» (cold start del worker GPU). Al
termine due player, «Approva», «Rigenera» (con selettore della seconda frase,
contatore «rigenerazioni rimaste: N»), «Rifiuta e chiedi rimborso».

- **Approva**: stato `ready`, email finale (§8.3), chiusura wizard, combo
  voci ricaricata con la nuova voce in cima.
- **Rigenera**: nuovo job demo, stesso pannello.
- **Rifiuta**: conferma esplicita, poi rimborso in voucher (§7.4), voce
  cancellata, email di rimborso.

Se le demo falliscono (`demo_failed`) il pannello lo dice, propone «Riprova
più tardi» (non conta come rigenerazione) oppure «Rifiuta e chiedi
rimborso». Finché non c'è approvazione la voce non compare nella combo.

### 3.6 Ripresa del wizard

Al caricamento della pagina il client chiama `GET /api/voice_clone/mine`,
che restituisce le voci del dispositivo e l'eventuale procedura in sospeso
(`sample_ok`, `paid`, `demos_generating`, `demos_ready`, `demo_failed`).
Se c'è, un banner «Hai una voce campione in sospeso: riprendi» apre il
wizard al pannello giusto. Da un dispositivo senza cookie, il link di ripresa
dell'email (§8.1) autorizza il cid corrente e apre lo stesso pannello.

### 3.7 Gestione: «Le tue voci»

Elenco delle voci autorizzate sul dispositivo (nome «La tua voce» o «Voce di
<nome dichiarato>» per quelle ricevute in dono), lingua/accento, data,
scadenza. Azioni: «Aggiungi con codice-voce» (§6.4), «Rimuovi da questo
dispositivo» (solo il legame cid, la voce sopravvive), «Rimanda l'email con
il codice» (solo il proprietario, rate limited).

### 3.8 Nella combo voci

Nel modello VoxCPM, dopo la scelta dell'accento, le voci personali del
dispositivo con lingua e accento coincidenti stanno in un `optgroup` in testa
(«Le tue voci»), prima dei gruppi ♀/♂ del catalogo. Se ce n'è una sola ed è
la prima volta che la combo si popola dopo la creazione, è preselezionata.
Il player campione mostra le due demo approvate.

## 4. Frasi guidate

File `voice_clone_prompts.json` nella radice del progetto (tracciato in git):

```json
{
  "schema": "abm-voice-clone-prompts/1",
  "prompts": {
    "it": {"text": "Ogni mattina apro la finestra..."},
    "hi": {"text_by_gender": {"m": "...खोलता हूँ...", "f": "...खोलती हूँ..."}}
  }
}
```

- Chiave = codice lingua a due lettere, come `voices.json`.
- `text` oppure `text_by_gender` con `m` e `f`. Se `text_by_gender` manca
  una chiave, si ripiega su `text`; se manca tutto, la lingua non è offerta.
- Modulo `voice_clone_prompts.py` (foglia): `languages()`,
  `prompt_for(lang, gender)`. Ricarica il file se cambia l'mtime, così una
  modifica non richiede restart.
- **Invariante**: il record della voce salva `prompt_text` così com'era al
  momento della registrazione, più `prompt_version` (hash del testo). Il
  worker riceve sempre il testo del record, mai il file.
- Regola per le lingue future: attivare una lingua nel catalogo VoxCPM senza
  aggiungerne la frase non rompe nulla, la lingua semplicemente non compare
  nel wizard. Il test `test_voice_clone_prompts.py` segnala le lingue attive
  senza frase come warning, non come fallimento.

Le nove frasi approvate il 2026-09-09 (it, en, fr, es, de, nl, pt, hi m/f,
zh) entrano nel file alla prima implementazione.

## 5. Il campione

### 5.1 Conversione

`voice_clone_audio.py` (nuovo modulo, numpy + ffmpeg):

1. `ffprobe` sul file ricevuto: deve avere uno stream audio, durata 3-60 s
   (tetto largo, il gate stringe dopo), dimensione sotto il massimo.
2. `ffmpeg -i in -ac 1 -ar 24000 -sample_fmt s16 -af "highpass=f=60" out.wav`.
3. Taglio dei silenzi iniziale e finale oltre 300 ms, normalizzazione del
   guadagno alla stessa loudness dei campioni di catalogo (misure di
   `tools/voice_prompts/audio.py`: `lufs`, `peak_dbfs`).

### 5.2 Gate lato server

Porting di `measure()` e `Gate` dal repo worker (numpy puro, nessuna
dipendenza nuova oltre numpy, da aggiungere a `requirements.txt` perché oggi
è presente solo per via transitiva). Soglie ereditate: `min_snr_db 22`,
`speech_ratio` 0,55-0,98, `min_bandwidth_ratio 0,78` rispetto a Nyquist
(12 kHz a 24 kHz, quindi banda minima ~9,4 kHz). Più la durata D7.

### 5.3 Messaggi

| Misura | Chiave i18n | Testo (it) |
|---|---|---|
| durata < 12 s | `vc_gate_short` | Troppo breve: leggi tutta la frase, con calma |
| durata > 20 s | `vc_gate_long` | Troppo lunga: leggi la frase di seguito, senza pause lunghe |
| `snr_db` basso | `vc_gate_noise` | Troppo rumore di fondo: prova in una stanza più silenziosa |
| `speech_ratio` basso o `longest_gap` alto | `vc_gate_pauses` | Troppe pause: leggi il testo di seguito |
| `speech_ratio` alto | `vc_gate_nopause` | Nessuna pausa rilevata: leggi con calma, senza correre |
| `bandwidth_hz` bassa | `vc_gate_band` | Il microfono o il file tagliano le frequenze alte: prova un altro dispositivo o un file di qualità migliore |
| `clipping` / `peak_dbfs` alto | `vc_gate_clip` | Audio distorto: allontanati dal microfono o abbassa il guadagno |
| CER alto (§5.4) | `vc_gate_text` | Non riconosco la frase guidata: leggi esattamente il testo mostrato |

### 5.4 Verifica ASR sul server

Il volume atteso è basso (poche registrazioni al giorno) e un campione dura
al massimo 20 s: la trascrizione gira **sul server dell'app, su CPU**, con
`faster-whisper` (dipendenza nuova in `requirements.txt`, porta con sé
`ctranslate2`; nessuna GPU). Stesso motore e stessa metrica CER del
`verifica.py` del worker, così le soglie restano confrontabili.

`voice_clone_audio.check_transcript(wav_path, language, expected_text)
-> {"cer", "heard", "seconds"}`:

- modello `ABM_VOICE_CLONE_ASR_MODEL` (default `base`, int8), scaricato al
  primo uso in `ABM_DATA_DIR/whisper/` (circa 150 MB per `base`; `small`,
  circa 460 MB, se hindi e cinese risultassero inaffidabili in calibrazione);
- caricato **a richiesta** e scaricato dalla memoria dopo 10 minuti di
  inattività (impronta stimata 0,4-0,6 GB per `base`: va verificata contro
  la RAM libera di produzione prima del rilascio, vista la storia
  dell'esaurimento RAM);
- **una trascrizione alla volta** (lock di processo), tempo atteso 5-15 s
  per un campione di 20 s; il pannello mostra «verifica in corso»;
- eseguita in un thread, con timeout `ABM_VOICE_CLONE_ASR_TIMEOUT_SEC`
  (default 120).

Soglia `ABM_VOICE_CLONE_MAX_CER` (default 0.25, calibrata su prove reali
nelle nove lingue prima del rilascio). Sopra soglia il gate fallisce con
`vc_gate_text`. La verifica avviene dopo le misure acustiche (§5.2), così
un file rumoroso non occupa la CPU, e prima del riascolto. Se la
trascrizione va in errore o in timeout, il campione **non passa**: risposta
`vc_gate_asr_unavailable` («verifica momentaneamente non disponibile,
riprova fra qualche minuto»), niente stato `asr_pending`. Con
`ABM_VOICE_CLONE_ASR=0` la verifica è saltata (solo sviluppo).

Nessuna modifica al worker RunPod per questa feature.

### 5.5 Storage

```
ABM_DATA_DIR/voices/<token>/
  sample.wav          wav mono 24 kHz normalizzato (l'unico usato da VoxCPM)
  original.<ext>      file caricato, conservato per verifica a posteriori
  demo_common.wav     demo approvata, frase comune (48 kHz)
  demo_extra.wav      demo approvata, frase extra
  demo_try_<n>_*.wav  tentativi non approvati (cancellati all'approvazione)
```

Copia su R2 con chiave `voices/<token>/<file>` appena scritti (`sample.wav`
e `original` al commit, demo all'approvazione). Il prefisso `voices/` è
escluso da `storage_tiering` e da ogni sweep dei job. Se il locale manca (es.
nuovo server) il resolver scarica da R2 alla prima richiesta.

## 6. Identità e ciclo di vita

### 6.1 Il record

`_voice_clones.json` in `ABM_DATA_DIR`, via `community_store.JsonStore`
(lock, `.bak`, scrittura atomica). Un record per voce:

```json
{
  "id": "vc_9f3a...",                 "token": "<32 hex, segreto>",
  "voice_code": "AB7K-Q2MD-4H9X",     "state": "ready",
  "manage_token": "<32 hex, nei link di gestione/cancellazione>",
  "resume_token": {"value": "<32 hex>", "expires_at": ...},
  "owner_email": "...",               "owner_email_hash": "sha256",
  "lang": "it", "locale": "it-IT", "gender": "f",
  "prompt_text": "...", "prompt_version": "sha1:...",
  "sample": {"duration_s": 16.4, "lufs": -19.8, "snr_db": 31.2,
             "bandwidth_hz": 10800, "cer": 0.06, "original_ext": "webm"},
  "demo": {"common_text": "...", "extra_id": "memory", "extra_text": "...",
           "regen_used": 1, "regen_max": 3, "runpod_job_id": "..."},
  "payment": {"type": "paypal", "token": "<order_id>", "amount_eur": 5.0,
              "paid_at": 1789000000},
  "devices": [{"cid": "abcd1234efgh", "added_at": ..., "via": "creator|code|resume"}],
  "pending_confirm": {"cid": "...", "code_hash": "...", "expires_at": ..., "tries": 0},
  "created_at": ..., "ready_at": ..., "last_used_at": ..., "expires_at": ...,
  "archived": false, "deleted_at": null, "delete_reason": null
}
```

Indici in memoria all'avvio: `token → record`, `owner_email_hash → record`
(solo non cancellati), `voice_code → record`, `cid → [record]`,
`manage_token → record`, `resume_token → record`.

### 6.2 Codice-voce e token

- `token`: `secrets.token_hex(16)`. Id voce esposto alla generazione:
  `voxcpm:mine:<token>`. Non compare mai in URL, email, log business.
- `voice_code`: 12 caratteri da alfabeto senza ambiguità (no 0/O, 1/I/L),
  formattato a gruppi di 4. Univoco. È quello che l'utente scrive.
- `id` pubblico (`vc_...`): usato negli endpoint del wizard, senza potere
  da solo (ogni endpoint verifica il cid o un token di link).
- `manage_token` e `resume_token`: `secrets.token_hex(16)`, salvati nel
  record e messi solo nei link delle email (§8). Stesso schema dei token di
  download in `_download_tokens.json`: nessuna firma, nessuna chiave da
  gestire, revoca = cancellazione dal record. Il `resume_token` scade dopo
  30 giorni; il `manage_token` vive quanto la voce.

### 6.3 Dispositivi

`devices` è la lista dei `abm_cid` autorizzati. Il creatore entra con
`via: creator`. Un cid entra con `via: code` dopo la conferma (§6.4) o con
`via: resume` dal link di ripresa dell'email di pagamento (§8.1): quel link è
del proprietario, quindi vale come conferma.

Rimozione dal dispositivo: `POST /api/voice_clone/<id>/forget` (cid
corrente). Revoca da parte del proprietario: link di gestione nell'email
(§8.3), pagina `/vc/<manage_token>/devices` con l'elenco (data, via, ultimi
4 caratteri del cid) e un bottone di revoca per riga.

### 6.4 Recupero e dono con il codice

1. Su un dispositivo qualunque: «Aggiungi con codice-voce» →
   `POST /api/voice_clone/claim {voice_code}`.
2. Se il cid è già in `devices`: 200, fatto. Altrimenti il server genera un
   codice-conferma a 6 cifre, lo salva hashato in `pending_confirm` con
   scadenza 15 min, e lo invia **all'email del proprietario** (§8.2). Risposta
   202 «codice inviato al proprietario».
3. `POST /api/voice_clone/confirm {voice_code, confirm_code}`: 5 tentativi,
   poi `pending_confirm` annullato e 15 minuti di blocco per quel cid.
   Successo → cid aggiunto con `via: code`, email di avviso al proprietario
   con il link di revoca.

Un solo `pending_confirm` per voce alla volta: una nuova richiesta lo
sostituisce e invalida il codice precedente. Il dono è esattamente questo
flusso, fatto dal dispositivo del ricevente con il proprietario che legge il
codice dalla sua email.

### 6.5 Retention

`expires_at = last_used_at + ABM_VOICE_CLONE_RETENTION_DAYS`. `last_used_at`
si aggiorna a ogni generazione con la voce e a ogni `GET /api/voice_clone/mine`
che la restituisce. Il cleanup loop, una volta al giorno:

- 30 giorni prima della scadenza: email al proprietario (§8.4), una sola
  volta (`expiry_warned_at`).
- Alla scadenza: `state = expired`, file locali e R2 rimossi, record tenuto
  90 giorni con i soli metadati non biometrici, poi eliminato.

### 6.6 Cancellazione

Link `/vc/<manage_token>/delete` nell'email (§8.3) → pagina di conferma →
`state = deleted`,
file locali e R2 rimossi subito, email/cid rimossi dal record, resta la
traccia contabile (id, importo, date) per la retention dei pagamenti. Le
generazioni in corso con quella voce completano (il campione è già nel
payload); le successive vedono la voce sparita.

## 7. Pagamento

### 7.1 Prezzo

`payment.voice_clone_price_eur()` restituisce `ABM_EUR_CLONED_VOICE`
(default 5.00, accetta la virgola decimale come gli altri). Un solo posto,
usato dal wizard, dall'ordine PayPal e dal commit. Zero o negativo =
clonazione gratuita (utile in sviluppo): il pannello 3 salta il pagamento.

### 7.2 Flusso

- PayPal: `POST /api/paypal_create_order_voice_clone` →
  `_paypal_create_order(prezzo, "Voice sample - Audiobook Maker",
  custom_id="vc:" + sample_id)`. Capture con l'endpoint generico esistente.
- Voucher: `/api/voucher_validate` con `purpose=voice_clone`, `amount_eur`.
- Commit: `payment.consume_payment_token(token, prezzo, job_id="vc:"+id,
  purpose="voice_clone")` sotto lock, nello stesso passo che scrive il record
  `paid` (prima il consumo, poi la scrittura, con rollback del consumo se la
  scrittura fallisce). Doppio click: se esiste già una voce `paid` per quel
  `sample_id`, il secondo commit risponde 200 con la stessa voce senza
  consumare nulla.

### 7.3 Riconciliazione

Il job di riconciliazione esistente (`iter_unused_captures`) vede le capture
con `custom_id` `vc:*` non consumate dopo `ABM_UNUSED_CAPTURE_MIN_AGE_SEC` e
le rimborsa in voucher come oggi. La funzione `has_refund_for_job` funziona
con `job_id = "vc:" + id`.

### 7.4 Rimborso su rifiuto

`POST /api/voice_clone/<id>/reject` (solo cid autorizzato, solo da
`demos_ready` o `demo_failed`): `_create_voucher(email, amount, kind="refund",
origin_job_id="vc:"+id, note="voice clone rejected")`, email di rimborso con
il codice voucher (via PayPal) o riaccredito silenzioso sul voucher
originale (via voucher, come da policy esistente), voce in `state = refunded`
con file rimossi. Idempotente via `has_refund_for_job`.

### 7.5 Libri con la voce campione

Nessuna differenza di prezzo: `free_quota.decision`, soglie e floor VoxCPM
valgono come per le voci di catalogo. `is_premium_job` già classifica il
prefisso `voxcpm:`.

## 8. Email

Tutte in `email_service.py`, HTML inline come le altre, lingua = lingua UI al
momento della richiesta (salvata nel record come `ui_lang`).

Link nelle email: `/vc/<resume_token>/resume`, `/vc/<manage_token>/devices`,
`/vc/<manage_token>/delete`. Il token è cercato nell'indice del record
(§6.1): sconosciuto, scaduto, o voce `deleted`/`refunded`/`expired` → 404.
Nessuna firma, nessuna chiave segreta in configurazione.

### 8.1 Pagamento ricevuto (subito dopo il commit)

Oggetto «La tua voce campione: codice e ricevuta». Contiene: importo,
codice-voce in grande, «conserva questa email», link **Riprendi la
procedura** (valido 30 giorni, autorizza il cid che lo apre), riepilogo
condizioni, link cancellazione.

### 8.2 Codice di conferma (claim da nuovo dispositivo)

Oggetto «Conferma l'uso della tua voce su un nuovo dispositivo». Codice a 6
cifre, validità 15 minuti, «se non sei stato tu, ignora questa email: senza
il codice nessuno può usare la tua voce». Dopo la conferma: seconda email
«Nuovo dispositivo autorizzato» con link revoca.

### 8.3 Voce pronta (all'approvazione)

Oggetto «La tua voce campione è pronta». Codice-voce, condizioni d'uso,
retention e rinnovo, link **Gestisci dispositivi** e **Cancella la voce**
(con `manage_token`, senza scadenza; muoiono con la voce),
«conserva questa email».

### 8.4 Scadenza vicina (30 giorni prima)

Oggetto «La tua voce campione scade fra 30 giorni». Basta usarla o aprire
il link per rinnovarla.

### 8.5 Rimborso

Riusa il template voucher di rimborso esistente con causale «voce campione».

## 9. Integrazione con la generazione

| Punto | Modifica |
|---|---|
| `voice_clone.py` (nuovo) | `resolve(voice_id) → {wav_path, prompt_text}` per `voxcpm:mine:<token>`; scarica da R2 se il locale manca; `authorized(voice_id, cid)`; `mine(cid, lang, locale)`; tutta la macchina a stati. |
| `voxcpm_tts.clone_block` | se l'id è `mine`, chiede a `voice_clone.resolve` invece che al catalogo. Cache invariata (chiave = voice_id). |
| `/api/voices` | copia della cache per richiesta; aggiunge `_mine: [{id, name, lang, locale, gender, demo_urls, owner: true/false}]` per il cid corrente. La cache globale non viene più mutata. |
| `/api/generate`, `/api/preview`, stime | se la voce è `mine`: 403 `voice_not_authorized` se il cid non è in `devices`; 400 `voice_lang_mismatch` se lingua/accento del libro non coincidono; 410 `voice_gone` se lo stato non è `ready` (D16: usabile solo dopo l'approvazione). Poi `last_used_at` aggiornato. |
| `_friendly_voice_name` | già «La tua voce»; per le voci in dono «Voce di <nome>» non serve nell'audio: resta «La tua voce». |
| Tag `abm_voice` nei metadati audio | «user-voice», mai il token. |
| `output_reuse` | invariato: mai per VoxCPM. |
| Log business | `VOICE_CLONE_*` con `id` pubblico, mai token né email in chiaro. |
| `audio_cascade.js` | `_mine` filtrato per lingua/accento e messo in testa; premium già dedotto dal prefisso. |

## 10. Macchina a stati e recovery

```
sample_ok ──commit──> paid ──> demos_generating ──> demos_ready ──approve──> ready
   │ 24h                            │ N fallimenti        │ reject           │
   └─> (scartato)                   └──> demo_failed ─────┴──> refunded      ├─> expired
                                          │ retry                            └─> deleted
                                          └──> demos_generating
```

| Interruzione | Trattamento |
|---|---|
| Abbandono prima del pagamento | `sample_ok` scade dopo 24 h, file rimossi dal cleanup. Al rientro entro 24 h il wizard riprende dal pannello 3 (§3.6). |
| Crash fra capture PayPal e commit | capture non consumata → riconciliazione esistente → voucher (§7.3). |
| Crash fra consumo del pagamento e scrittura del record | il consumo avviene dentro la stessa sezione critica della scrittura; se la scrittura fallisce si rilascia il token (`_voucher_refund` / `used=False` sotto lock) e si risponde 500: l'utente riprova. |
| Browser chiuso in `paid` o `demos_generating` | il thread demo procede da solo (D16). Al rientro: banner di ripresa. Da altro dispositivo: link dell'email di pagamento. |
| Restart del server in `demos_generating` | all'avvio `voice_clone.recover()` rilancia i record in quello stato; se `runpod_job_id` è presente prova prima `/status` (il job può essere finito), altrimenti nuovo job. L'id RunPod è scritto nel record **prima** del submit del payload successivo. |
| Worker giù / rimbalzi / cold start lento | retry con backoff come `synthesize_chapter`; dopo `ABM_VOICE_CLONE_DEMO_RETRIES` (3) cicli → `demo_failed`, email «riprova più tardi» all'utente, notifica admin. Nessun rimborso immediato: il campione è valido e il «Riprova» dell'utente (che non consuma rigenerazioni) o il rilancio dal cleanup loop ogni 6 ore rimettono in coda le demo. Dopo 7 giorni in `demo_failed` senza esito: rimborso automatico (§7.4) e email. |
| `encode_voice` / sintesi fallisce sul campione (non sul worker) | `demo_failed` con `reason=sample_unusable`, rimborso automatico (§7.4) e email. |
| Email non recapitata | codice-voce mostrato a schermo a fine wizard e in «Le tue voci» per il proprietario; «Rimanda l'email» rate limited 3/giorno. |
| Cookie perso | codice-voce → conferma (§6.4). |
| Approvazione mai data | la voce resta `demos_ready` e **non** compare nella combo (D16). Il banner di ripresa (§3.6) riporta al pannello 4; email di sollecito dopo 24 ore e dopo 7 giorni («le tue demo sono pronte: ascoltale e approva»). Dopo 30 giorni in `demos_ready` senza azione: rimborso automatico (§7.4), voce `refunded`, email. |
| Due commit paralleli sullo stesso `sample_id` | lock per sample; il secondo vede `paid` e risponde con la stessa voce. |
| Due email uguali su due dispositivi contemporaneamente | indice `owner_email_hash` con check-and-set sotto lock: il secondo commit fallisce 409 `email_has_voice` **prima** di consumare il pagamento. |

## 11. Demo

- Un job RunPod `generate` con due chunk (frase comune, frase extra),
  `clone_block` dal campione, `output_format: pcm`, inline (sotto 60 s).
- PCM → wav 48 kHz con ffmpeg; nessun `atempo` (velocità 1.0).
- Tempo atteso: 20-40 s a worker caldo, 3-4 min a freddo. Costo interno
  trascurabile rispetto ai 5 € anche con tre rigenerazioni a freddo.
- Le rigenerazioni rispettano `regen_max`; il selettore della seconda frase
  vale solo per la rigenerazione.
- Il worker dovrà **contrassegnare** l'audio sintetico secondo AI Act art. 50
  quando quella marcatura sarà in pipeline: fuori perimetro qui, ma i demo e
  i libri con voce clonata seguiranno lo stesso meccanismo del catalogo.

## 12. Sicurezza e abuso

- Rate limit `POST /api/voice_clone/sample`: 10/ora per cid, 30/ora per IP
  (schema di `_feedback_check_rate`). `claim`: 5/ora per cid. `confirm`: 5
  tentativi per `pending_confirm`.
- La verifica ASR (§5.4) richiede di leggere proprio quella frase: un file
  di terzi non passa, salvo generazione sintetica mirata. Il campione
  originale è conservato per verifica a posteriori (§5.5).
- Nessun endpoint accetta il token interno: solo `id` pubblico più cid, o
  i token dei link email. Il `voice_code` da solo non dà accesso senza
  conferma.
- Log business e digest admin: sezione «Voci campionate» (create, pronte,
  rifiutate, rimborsate, claim confermati/falliti).
- Moderazione `abuse_watch`: nessun cambiamento, ma un cid bloccato non può
  creare né usare voci.

## 13. Privacy

Il campione è dato biometrico. Il pannello 1 è l'informativa; il consenso è
la spunta, con timestamp e `ui_lang` nel record. Finalità unica, retention
D15, cancellazione D14 con effetto immediato sui file, nessun addestramento.
La pagina privacy del sito riceve un paragrafo dedicato (fuori da questa
spec, ma prerequisito di rilascio).

## 14. Configurazione

| Variabile | Default | Significato |
|---|---|---|
| `ABM_VOICE_CLONE_ENABLED` | `1` | interruttore; con VoxCPM non disponibile la feature è comunque nascosta |
| `ABM_EUR_CLONED_VOICE` | `5.00` | prezzo una tantum; ≤ 0 = gratis |
| `ABM_VOICE_CLONE_RETENTION_DAYS` | `365` | retention rinnovata all'uso |
| `ABM_VOICE_CLONE_MAX_UPLOAD_MB` | `20` | tetto del file caricato |
| `ABM_VOICE_CLONE_MIN_SEC` / `_MAX_SEC` | `12` / `20` | finestra di durata del gate |
| `ABM_VOICE_CLONE_MAX_CER` | `0.25` | soglia della verifica ASR |
| `ABM_VOICE_CLONE_ASR` | `1` | `0` salta la verifica ASR (solo sviluppo) |
| `ABM_VOICE_CLONE_ASR_MODEL` | `base` | modello faster-whisper su CPU (`base` o `small`) |
| `ABM_VOICE_CLONE_ASR_TIMEOUT_SEC` | `120` | timeout della trascrizione |
| `ABM_VOICE_CLONE_REGEN_MAX` | `3` | rigenerazioni demo incluse |
| `ABM_VOICE_CLONE_DEMO_RETRIES` | `3` | cicli di retry prima di `demo_failed` |
| `ABM_VOICE_CLONE_SAMPLE_TTL_H` | `24` | vita di un campione non pagato |

Tutte documentate in `md_files/PARAMETRI_CONFIGURAZIONE.md` prima del push.

## 15. Moduli e file

| File | Ruolo |
|---|---|
| `voice_clone_prompts.py` + `voice_clone_prompts.json` | frasi guidate (§4) |
| `voice_clone_audio.py` | conversione, misure, gate, trascrizione whisper (§5.1-5.4) |
| `voice_clone.py` | store, macchina a stati, codici, dispositivi, token dei link, demo thread, recovery, retention (§6, §10, §11) |
| `voxcpm_tts.py` | `clone_block` per `mine`; `check_sample` client; job demo |
| `payment.py` | `voice_clone_price_eur()`, purpose `voice_clone` |
| `email_service.py` | le cinque email (§8) |
| `audiobook_app.py` | endpoint `/api/voice_clone/*`, `/api/paypal_create_order_voice_clone`, pagine `/vc/<sig>/...`, `_mine` in `/api/voices`, guardie in generate/preview, cleanup e recover all'avvio |
| `generation_engine.py` | `last_used_at` a fine job; tag audio |
| `static/js/voice_clone.js` (nuovo) + `app.js` + `audio_cascade.js` | wizard, ripresa, «Le tue voci», combo |
| `templates/_fragments/html_head.html` | bottone e markup del wizard |
| `templates/_fragments/i18n_data.js` + `i18n/*.json` | stringhe in 7 lingue |
| `requirements.txt` | `numpy` esplicito, `faster-whisper` |

## 16. Test

- `test_voice_clone_prompts.py`: parsing, varianti di genere, ricarica su
  mtime, lingue attive senza frase (warning).
- `test_voice_clone_audio.py`: fixture sintetiche (tono + rumore, clipping,
  banda tagliata, silenzi): un caso per ogni motivo di rifiuto e un caso
  che passa; conversione da webm/mp3 con ffmpeg (skip se assente).
- `test_voice_clone.py`: macchina a stati completa; commit idempotente;
  unicità email sotto concorrenza; claim/confirm con tentativi e scadenza;
  token dei link (validi, scaduti, sconosciuti); retention e avviso; cancellazione;
  recovery da `demos_generating` con e senza `runpod_job_id`; rimborso
  idempotente.
- `test_voice_clone_api.py`: endpoint con client Flask, cid, 403/400/410 in
  generate, `_mine` in `/api/voices`, cache non mutata.
- `test_voxcpm_tts.py`: `clone_block` con id `mine`.
- `test_voice_clone_audio.py` (ASR): `check_transcript` con modello mock;
  timeout → `vc_gate_asr_unavailable`.
- `test/js/voice_clone.test.js`: ordinamento combo, banner di ripresa,
  contatore rigenerazioni.
- Manuale (`docs/MANUAL_TESTS_VOCI_CAMPIONATE.md`): registrazione da
  Chrome/Firefox/Safari iOS, upload mp3 a 64 kbps (deve fallire per banda),
  claim da secondo browser, revoca, cancellazione, restart durante le demo.

## 17. Aperture note

- Soglia CER da calibrare su registrazioni reali nelle nove lingue prima del
  rilascio; whisper `base` su hindi e cinese va verificato (fallback `small`).
- RAM di produzione: misurare l'impronta di faster-whisper sul server prima
  del rilascio (§5.4).
- Marcatura AI Act art. 50 dell'audio sintetico: pipeline del worker, non di
  questa spec.
- Paragrafo privacy sul sito.
- L'app mobile potrà usare gli stessi endpoint con l'header `X-ABM-Cid`;
  il wizard nativo è un progetto a parte.
