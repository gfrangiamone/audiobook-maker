# Collaudo manuale — Voci campionate

Da eseguire su un ambiente con microfono, browser reale e (per i casi che lo
richiedono) un worker VoxCPM raggiungibile, prima del rilascio. La suite
automatica copre markup, i18n, gating dei prezzi e i contratti delle API con
doppi finti: tutto ciò che segue verifica le cose che un doppio non può dire
— se il microfono si accende davvero, se l'audio generato suona con la voce
giusta, se due browser diversi si scambiano correttamente un codice-voce.

**Fuori da questo documento:** le voci di catalogo (VoxCPM2 "voci
inventate", Gemini, Simba) sono coperte da `docs/MANUAL_TESTS_VOXCPM.md`. Qui
si collauda solo il percorso "campiona la tua voce" (spec voci campionate,
piani 1-3).

## Prerequisiti

- App avviata con un backend TTS funzionante (per generare i brani di prova
  e gli audiolibri finali).
- Un worker VoxCPM raggiungibile e configurato (stesse variabili di
  `docs/MANUAL_TESTS_VOXCPM.md`), necessario per i casi che arrivano fino
  alla generazione dei brani di prova o dell'audiolibro.
- SMTP configurato (`ABM_SMTP_*`): molti casi dipendono da email realmente
  recapitate (codice-voce, conferma di claim, promemoria di scadenza,
  rimando codice).
- Un microfono funzionante e un browser con permesso di registrazione
  audio concedibile/revocabile.
- Due browser distinti (o due profili/sessioni separate con cookie
  `abm_cid` diversi) per i casi di claim/conferma multi-dispositivo.
- Un file audio di test in un formato non accettato (es. `.flac`) e uno di
  dimensione superiore al limite configurato, per i casi di rifiuto lato
  client.
- Un metodo di pagamento sandbox (PayPal sandbox) e un voucher valido.
- Un libro breve in almeno due lingue diverse (per il caso di mismatch
  lingua voce/libro).

Per ogni caso: eseguire i passi, confrontare con l'esito atteso, annotare
l'esito reale nella colonna finale (OK / KO + nota).

## Casi di collaudo

| Id | Caso | Passi | Esito atteso | Esito |
|----|------|-------|---------------|-------|
| VC-01 | Visibilità del bottone «Campiona la tua voce» | Apri il wizard con VoxCPM configurato e una lingua libro tra quelle offerte; poi ripeti con la feature disattivata (spegni il flag/endpoint lato server) | Bottone visibile con tooltip esplicativo solo nel primo caso; assente quando la feature è spenta | |
| VC-02 | Condizioni obbligatorie | Apri il modal di campionamento, arriva al pannello delle condizioni senza spuntare la casella di consenso, prova a premere «Avanti» | «Avanti» resta disabilitato finché la spunta non è messa | |
| VC-03 | Registrazione: indicatori e stop automatico | Premi «Registra», osserva pallino/indicatore di livello/timer mentre parli; continua a parlare oltre 25 secondi senza fermarti manualmente | La registrazione si ferma automaticamente a 25 secondi; timer e livello aggiornati in tempo reale durante tutta la registrazione | |
| VC-04 | Scarto per ogni motivo raggiungibile | Genera deliberatamente ciascun caso: registrazione troppo corta (pochi secondi), troppo lunga (oltre soglia), rumore di fondo forte, lettura di una frase diversa da quella richiesta, upload di un formato non supportato | Ogni caso mostra un messaggio di scarto specifico e comprensibile, nella lingua UI attiva, senza gergo tecnico | |
| VC-05 | Rifiuto lato client su upload | Prova a caricare un file `.flac` (o altro formato non in whitelist); prova a caricare un file audio valido ma oltre il limite di dimensione configurato | Entrambi i file sono rifiutati subito lato client, senza round-trip al server, con messaggio chiaro | |
| VC-06 | Campione accettato | Registra (o carica) un campione valido che superi tutti i controlli | Compare un player per riascoltare il campione, con i bottoni «Rifaccio» e «Va bene, avanti» | |
| VC-07 | Validazione email | Nel pannello email, inserisci due email diverse nei due campi; poi correggi con un'email sintatticamente non valida | Errore di mancata corrispondenza nel primo caso, errore di formato non valido nel secondo; «Avanti» bloccato in entrambi | |
| VC-08 | Pagamento PayPal sandbox | Completa il flusso fino al pagamento, paga con un account PayPal sandbox | Pagamento va a buon fine, il codice-voce è mostrato una sola volta a schermo (e arriva anche via email) | |
| VC-09 | Pagamento voucher | Ripeti il pagamento usando un voucher valido invece di PayPal | Il voucher viene consumato e il flusso prosegue come nel caso PayPal | |
| VC-10 | Prezzo gratuito | Ripeti con un costo che ricade sotto la soglia gratuita | Nessun modal di pagamento: si passa direttamente alla generazione dei brani di prova | |
| VC-11 | Attesa demo e ripresa | Dopo il pagamento, osserva la barra/messaggio di attesa fino all'arrivo dei due brani via SSE; poi chiudi la scheda a metà attesa e riapri l'app | I brani arrivano entro pochi minuti; alla riapertura compare il banner «Riprendi il campionamento» che riporta al pannello corretto | |
| VC-12 | Rigenerazione dei brani | Premi «Rigenera» sui brani di prova più volte, fino a esaurire il contatore | Il contatore delle rigenerazioni rimaste decrementa a ogni uso; a zero il bottone «Rigenera» si disabilita | |
| VC-13 | Approvazione della voce | Premi «Approva» su una coppia di brani soddisfacenti; poi genera un audiolibro scegliendo questa voce dalla combo | La voce compare nella combo sotto «Le tue voci», preselezionata; l'audiolibro generato ha i tag `abm_voice`/`abm_voice_id` coerenti con una voce utente | |
| VC-14 | Rifiuto e rimborso | Premi «Rifiuta», conferma nel dialogo inline di conferma | La voce viene eliminata, il pagamento (se presente) viene rimborsato secondo il metodo usato, la voce sparisce da «Le tue voci» | |
| VC-15 | Demo fallite | Simula un fallimento nella generazione dei brani (es. worker non raggiungibile durante l'attesa) | Compare un messaggio di fallimento con «Riprova» e l'opzione «Rifiuta» per chiedere il rimborso | |
| VC-16 | Ripresa dal link email | Apri il link `/vc/<token>/resume` ricevuto via email in un nuovo browser/sessione | La pagina reindirizza all'app con `?vc=<clone_id>` in query, il modal si apre automaticamente sul pannello corretto, la query string viene rimossa dall'URL dopo l'apertura | |
| VC-17 | Claim da un secondo dispositivo | Su un secondo browser, apri «Aggiungi con codice-voce», inserisci il codice-voce ricevuto dal proprietario; il proprietario riceve un'email con un codice di conferma e lo comunica (fuori banda) al secondo browser, che lo inserisce | Lo stato passa a "in attesa di conferma", poi a conferma avvenuta la voce compare nella lista del secondo browser con un'etichetta generica (non l'identità del proprietario); «Rimuovi da questo dispositivo» agisce solo sulla copia locale del secondo browser | |
| VC-18 | Eliminazione vista dal dispositivo secondario | Con la voce condivisa come in VC-17, il proprietario la elimina dal link di gestione nell'email | Sul secondo browser: un tentativo di generazione con quella voce mostra l'errore dedicato di voce non più autorizzata/non trovata, e la combo delle voci si aggiorna rimuovendola | |
| VC-19 | Mismatch lingua voce/libro | Genera un audiolibro in una lingua diversa da quella della voce campionata | Errore dedicato che segnala l'incompatibilità di lingua, senza avviare la generazione | |
| VC-20 | Limite di «Rimanda l'email» | Come proprietario, premi «Rimanda l'email con il codice» tre volte, poi un quarto | Le prime tre vanno a buon fine (email recapitata); alla quarta compare un messaggio di limite raggiunto | |
| VC-21 | Cambio lingua UI a modal aperto | Con il modal di campionamento aperto su un pannello qualsiasi, cambia la lingua dell'interfaccia dal selettore globale | Tutte le etichette del modal (titoli, bottoni, messaggi di errore visibili) cambiano nella nuova lingua; nessuna chiave grezza (`vc_...`) visibile a schermo | |
| VC-22 | Regressione sui flussi premium esistenti | Ripeti un acquisto di voce premium Gemini con voucher e con PayPal, senza toccare le voci campionate | Il modal di pagamento e il flusso di generazione premium restano invariati rispetto a prima dell'introduzione delle voci campionate | |
| VC-23 | Sezione privacy | Apri la pagina privacy in IT e in EN | La sezione «9. Voci campionate» / «9. Sampled voices» è presente e leggibile; la numerazione delle sezioni è coerente da 1 a 11 in entrambe le lingue | |
| VC-24 | Percorso end-to-end con worker raggiungibile | Con un worker VoxCPM realmente raggiungibile: registra un campione reale, caricalo, paga, attendi l'arrivo dei brani via SSE, ascoltali, approva | L'intero percorso (upload campione → pagamento → attesa SSE → demo → approvazione) si completa senza errori e i brani ascoltati usano davvero la voce registrata | |
| VC-25 | Apertura diretta con `?vc=<clone_id>` in URL | Con una voce in stato intermedio (es. campione registrato in attesa di pagamento, o demo pronte), apri l'app con `?vc=<clone_id>` incollato manualmente in URL (non tramite il link email) | Il modal si apre automaticamente sul pannello coerente con lo stato salvato di quella voce; la query string viene rimossa dall'URL dopo l'apertura | |
| VC-26 | Claim/conferma end-to-end su due browser reali | Ripeti VC-17 usando due browser fisicamente distinti (non due tab dello stesso profilo) e attendendo la reale consegna delle email (codice-voce al richiedente, codice di conferma al proprietario) | Il flusso si completa solo dopo la conferma reale del proprietario; nessuna voce compare come "posseduta" sul secondo browser prima della conferma | |

## Cosa fare se qualcosa non torna

- Se il microfono non si attiva: controlla i permessi del browser per il
  sito (non solo il permesso di sistema) e riprova su una scheda in incognito
  per escludere estensioni che bloccano `getUserMedia`.
- Se le email non arrivano: verifica `ABM_SMTP_*` e i log SMTP prima di
  sospettare un bug applicativo — molti dei casi sopra dipendono da SMTP
  configurato correttamente.
- Se i brani di prova non arrivano mai mentre lo stato resta "in
  preparazione": guarda il log del worker VoxCPM come indicato in
  `docs/MANUAL_TESTS_VOXCPM.md` §7bis — la stessa distinzione fra motore
  compromesso e coda satura vale anche qui.
- Non annotare mai id di voce, codici-voce, codici di conferma o email reali
  in questo documento o nei suoi esiti: usa sempre placeholder come
  `<clone_id>`, `<voice_code>`, `<confirm_code>`.
