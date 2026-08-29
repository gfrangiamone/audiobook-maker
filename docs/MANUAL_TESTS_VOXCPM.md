# Collaudo manuale — VoxCPM2, voci di catalogo

Da eseguire su GPU vera prima del rilascio. La suite automatica parla sempre
con un worker finto: tutto ciò che segue verifica le cose che un doppio non
può dire — come suona la voce, quanto costa davvero un boot, e se il libro
finito ha i capitoli al posto giusto.

**Fuori da questo documento:** registrazione della propria voce, gate di
qualità, recupero via email, cancellazione. Sono del piano 2 e non sono mai
state provate.

## Prerequisiti

- `ABM_VOXCPM_ENDPOINT_ID` e `ABM_VOXCPM_API_KEY` di un endpoint attivo.
- `ABM_VOXCPM_RATE_EUR_PER_MCHAR` e `ABM_VOXCPM_MIN_COST_EUR` ai valori
  commerciali decisi (§13 della spec: si fissano prima del deploy).
- `data/voci_inventate/` presente, con `voices.json` e i `.wav`.
- Un EPUB breve: tre o quattro capitoli, meno di 20.000 caratteri. Un libro
  lungo qui non aggiunge informazione e costa GPU.

## 1. Il motore compare, e solo se configurato

1. Avvia l'app, apri il wizard, vai al tab **Voci PREMIUM**.
2. Nel menù MODELLO c'è **VoxCPM2 · La tua voce**. → _atteso: sì_
3. Ferma l'app, svuota `ABM_VOXCPM_ENDPOINT_ID`, riavvia.
4. Il modello **non** compare, e gli altri tre funzionano. → _atteso: sì_
5. Rimetti l'endpoint e riavvia.

## 2. I filtri fanno quello che dicono

1. Scegli VoxCPM2. Compaiono ACCENTO, CARATTERE e il player del campione;
   spariscono istruzioni di stile ed emozione.
2. Cambia ACCENTO: la lista VOCE si restringe a quel locale.
3. Scegli un CARATTERE: la lista VOCE si restringe ancora.
4. Scegli una voce: CARATTERE mostra il carattere di quella voce.
5. Nessuno dei due menù resta mai vuoto. → _atteso: sì_
6. Premi play sul campione: si sente la voce, e il nome che si legge è quello
   della voce scelta.
7. Con il campione in riproduzione, cambia MODELLO (verso Simba o Gemini)
   oppure lascia il tab Voci PREMIUM: il player si ferma subito, non resta a
   suonare invisibile dietro la riga che è sparita. → _atteso: sì_

## 3. Il prezzo detto è il prezzo pagato

Questo è il punto in cui l'incidente del 402 Speechify si ripeterebbe, se
dovesse ripetersi.

1. Con la quota mensile **capiente**, annota il prezzo mostrato nella riga
   costo. → _atteso: gratis o l'importo di listino_
2. Avvia la generazione. Non deve comparire nessuna richiesta di pagamento
   che la stima non avesse annunciato. → _atteso: sì_
3. Esaurisci la quota (o abbassa `ABM_FREE_QUOTA_EUR_PER_MONTH`), ricarica,
   e rileggi la stima.
4. Il modale di pagamento chiede **lo stesso numero** che la riga costo
   mostrava. → _atteso: sì_

## 4. Un libro intero, dal caricamento all'M4B

1. Carica l'EPUB, scegli una voce VoxCPM, lascia la velocità a 0%.
2. Avvia. Il primo messaggio di avanzamento parla di accensione del motore.
   → _atteso: «Accensione del motore vocale, circa tre minuti…»_
3. Annota **quanto passa** prima del primo capitolo pronto. È il cold start:
   se supera i cinque minuti, va segnalato prima del rilascio.
4. A fine generazione scarica l'M4B e aprilo in un lettore con i capitoli.
5. Verifica, ascoltando:
   - la voce è quella del campione, non un'altra;
   - i marcatori di capitolo cadono all'inizio dei capitoli;
   - non ci sono tagli, doppioni o silenzi lunghi fra un chunk e l'altro;
   - il testo letto è tutto il testo, inizio e fine compresi.

## 5. La velocità

1. Rigenera lo stesso libro con la velocità a **−20%** e a **+20%**.
2. La lettura rallenta e accelera, e la voce **non** cambia timbro.
   → _atteso: sì (è `atempo`, non un cambio di frequenza)_
3. La durata dell'M4B si muove nella direzione giusta.

## 6. Il riuso non ricompra

1. Rigenera lo stesso libro, stessa voce, stessi capitoli.
2. I capitoli già fatti si riusano: nessun job nuovo, nessun costo nuovo.
   → _atteso: sì_
3. Cambia il testo di **un solo** capitolo e rigenera: si rifà quel capitolo
   e basta.
4. Il riuso VoxCPM è capitolo-atomico: un capitolo si riusa solo se il suo
   chunk di testa e tutte le sue code sono già su disco. Cancella a mano la
   coda di un capitolo dalla cartella di lavoro e rigenera: quel capitolo
   viene rifatto per intero, non a metà. → _atteso: sì_

## 7. L'audit dice la verità

1. Apri `/admin/audit-premium`.
2. I job VoxCPM ci sono, con `provider: voxcpm`. → _atteso: sì_
3. Il costo scritto corrisponde ai caratteri letti.
4. Cerca `AUDIT WARNING` nel log: non deve essercene nessuno per un libro
   sopra soglia. → _atteso: nessuno_
5. Nel filtro MODELLO della tab Audit TTS c'è la voce **VoxCPM v2
   (PREMIUM)**: selezionandola la tabella mostra solo i job di questo
   motore. → _atteso: sì_
6. Nel record JSONL del job compare `gpu_seconds`, coerente con la durata
   osservata della sintesi. → _atteso: sì_

## 8. Cosa fare se qualcosa non torna

Prima di toccare il codice, guarda il log del worker su RunPod: la
tassonomia degli errori (§9.4) distingue un motore compromesso — che si
ritenta — da una coda satura, che non si ritenta. I due si assomigliano nel
messaggio e non nella cura.
