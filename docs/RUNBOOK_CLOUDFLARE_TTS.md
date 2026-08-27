# Runbook: accensione e rollback del backend TTS Cloudflare

Procedura operativa per l'esercente che gestisce il server di produzione
(systemd, Bash). Riguarda esclusivamente il modello `flash31` (Gemini 3.1
Flash TTS): `flash25` (Gemini 2.5 Flash TTS, il modello economico del
listino) **non è ospitato su Cloudflare** — nessun candidato TTS 2.5
risponde diversamente da `404 Model not found` — e resta su Vertex in modo
permanente, con le sue tariffe Google e il suo margine, qualunque cosa
succeda in questo runbook.

Il codice del backend Cloudflare è già in produzione ma **dormiente**:
nessun ambiente imposta `ABM_GEMINI_BACKEND=cloudflare` e il valore di
default `auto` non seleziona mai Cloudflare (serve un opt-in esplicito).
Finché questo runbook non viene eseguito, il comportamento del servizio è
identico a oggi.

---

## 1. Stato dei criteri GO

Lo switch di produzione non va eseguito finché tutti e cinque i criteri
della spec (`docs/superpowers/specs/2026-08-26-cloudflare-tts-prod-backend-design.md`,
§10) non sono soddisfatti.

| # | Criterio | Esito | Data | Note |
|---|---|---|---|---|
| G1 | Costo Cloudflare riconciliato contro dashboard | **chiuso** | 26/08/2026 | scarto −0,39% |
| G2 | Parità voci: tutte le 30 voci di `GEMINI_VOICE_NAMES` disponibili su Cloudflare | **chiuso** | 26/08/2026 | 30/30 verificate, §10.1 della spec |
| G3 | Qualità indistinguibile da Vertex (A/B a orecchio) | **chiuso** | 26/08/2026 | giudizio dell'esercente, §10.2 |
| G4 | Latenza p95 non peggiore di Vertex a parità di concorrenza | **aperto, non bloccante** | — | vedi nota sotto |
| G5 | Nessun errore `2017` su un libro intero dopo il fix del chunking | **aperto, bloccante** | — | il fix non è ancora implementato |

**G4 — perché è aperto ma non blocca l'accensione.** Non esiste oggi una
misura di latenza per chiamata comparabile su Vertex (la produzione non la
registra), quindi il confronto diretto con i 30 campioni Cloudflare
(6,9–9,6 s a chiamata) sarebbe una misura finta. La decisione della spec
(§10.2) è di procedere comunque: la latenza per chiamata non è un criterio
di qualità del prodotto ma di durata del job, un eventuale rallentamento si
vede subito sui primi job reali, e il rollback è una variabile d'ambiente.
Diventa quindi sorveglianza nelle prime 24 ore (§5), non un blocco
all'accensione.

**G5 — perché è aperto e blocca l'accensione.** Il fix dei chunk degeneri
(piano `docs/superpowers/plans/2026-08-26-tts-chunking-degenerate-fix.md`)
**non è stato implementato**: il primo task del piano (`_is_degenerate_chunk`
in `tts_split.py`) risulta ancora da fare. Senza quel fix, un capitolo il
cui titolo è un frammento quasi solo numerale (es. `XIV.`, `Cap. 12`) genera
un chunk che il backend Cloudflare rifiuta per moderazione contenuti con
codice `2017` (vedi `gemini_tts.py`, commento a riga 2809: *"Percorso
Cloudflare (422 / codice 2017, spec §4.2)"*). Questo non è un rischio
statistico: è **deterministico**. Ogni libro con quella struttura di
titoli — e sono comuni — lo incontra allo stesso punto, ogni volta.
Accendere Cloudflare oggi significa consegnare un guasto certo a una classe
intera di libri, non un'eventualità rara da monitorare.

> ## Riga netta: **ACCENSIONE NON AUTORIZZATA**
>
> Resta non autorizzata finché non sono vere **entrambe** le condizioni:
> 1. il fix del chunking (piano sopra) è implementato e i suoi test passano;
> 2. è stata eseguita una rigenerazione di controllo su un libro reale con
>    titoli di capitolo numerali/brevi, backend Cloudflare attivo, **senza**
>    alcun errore `2017` nei log del job.
>
> Solo allora questa riga va aggiornata a **ACCENSIONE AUTORIZZATA**, con
> data e riferimento al job di controllo, e si può procedere alla §3.

---

## 2. Prerequisiti

Da completare **prima** di toccare l'unit systemd:

1. **Credito AI Gateway caricato.** Il credito Cloudflare è **prepagato**
   (con saldo a zero le chiamate falliscono): ricaricare un importo noto
   sul conto Cloudflare prima dell'accensione. Annotare l'importo esatto
   caricato (al netto della commissione, vedi punto 3) — serve al passo
   successivo.
2. **Token con soli permessi Workers AI.** Generare un API token Cloudflare
   ristretto a Workers AI (mai un token con permessi di fatturazione o più
   ampi). Il valore del token non va **mai** scritto in documentazione, log
   applicativi o export di configurazione — solo il nome della variabile
   (`ABM_CF_API_TOKEN`) va citato.
3. **`ABM_CF_CREDIT_BALANCE_EUR` allineato all'importo ricaricato.** Questa
   variabile è il saldo che l'admin **dichiara** dopo la ricarica — non è
   leggibile via API Cloudflare (nessun endpoint di credito esiste; quelli
   di fatturazione rispondono `403` perché il token è volutamente
   ristretto). Impostarla all'importo netto della ricarica: il credito si
   compra pagando anche la commissione del 5% (`ABM_CF_CREDIT_TOPUP_FEE`),
   quindi il saldo disponibile per le chiamate è l'importo ricaricato, non
   l'importo speso in fattura. Con `0` (default) il pre-allarme sul credito
   resta disabilitato — non lasciarla a zero dopo l'accensione.

---

## 3. Accensione

Variabili da aggiungere all'unit systemd (`Environment=` o
`EnvironmentFile=`, secondo la convenzione già in uso sul server):

```
ABM_GEMINI_BACKEND=cloudflare
ABM_CF_ACCOUNT_ID=<account id Cloudflare>
ABM_CF_API_TOKEN=<token con soli permessi Workers AI>
ABM_CF_CREDIT_BALANCE_EUR=<importo netto ricaricato, es. 50>
```

Poi:

```bash
sudo systemctl daemon-reload
sudo systemctl restart audiobook-maker
```

> **Trappola: le variabili `ABM_*` non sono ereditate dalla shell SSH.**
> Stanno nell'unit systemd, non nell'ambiente della shell interattiva. Un
> controllo con `echo $ABM_GEMINI_BACKEND` (o `grep ABM_ ...service` seguito
> da un test in shell) in una sessione SSH normale **non le vede** e porta a
> concludere — a torto — che non sono state impostate. Per verificare il
> valore realmente in uso dal processo, leggerlo da dove vive davvero:
> - `systemctl show audiobook-maker --property=Environment` (o il contenuto
>   dell'`EnvironmentFile`), oppure
> - l'ambiente reale del processo in esecuzione:
>   ```bash
>   tr '\0' '\n' < /proc/$(pgrep -f audiobook_app.py | head -1)/environ | grep ABM_
>   ```

---

## 4. Verifica post-accensione

Dopo il restart, in ordine:

1. **Log di risoluzione del backend.** Al primo chunk `flash31` sintetizzato
   dopo il riavvio, cercare nei log del servizio (journalctl o stdout
   redirect, a seconda della configurazione):

   ```
   [gemini-tts] Backend resolved (flash31): cloudflare
   ```

   Questa riga (`gemini_tts.py`, funzione `_resolve_backend`) viene emessa
   **una sola volta per chiave di cache**, non a ogni chunk: se il processo
   non ha ancora servito un job `flash31` dal riavvio, non comparirà finché
   non arriva la prima richiesta. Non è quindi anomalo non vederla subito
   dopo il restart — lo è non vederla dopo il primo job di prova del punto 3.

2. **Pannello «Backend TTS»** in `/admin/audit-premium` (titolo pagina
   "Admin - Audit Premium Services", richiede `X-Admin-Token`). Il pannello
   è sopra la barra delle schede e visibile sempre, indipendentemente dalla
   scheda selezionata. Deve mostrare, nel box in alto:
   - **SU CLOUDFLARE** (verde) · credito residuo stimato in €, se non c'è
     stato alcun trip;
   - se invece appare **SU VERTEX** (rosso) con dettaglio del trip, il
     failover è già scattato — passare direttamente alla §7.

3. **Job di prova breve.** Generare un audiolibro corto con voce
   `flash31` (Gemini 3.1 Flash) e verificarne il completamento normale.

4. **Confronto costo registrato vs dashboard Cloudflare.** Aprire
   Cloudflare → Workers & Pages → AI → Usage sulla stessa finestra
   temporale del job di prova, e confrontare con il costo registrato
   nell'Audit TTS (`/admin/audit-premium#tab-tts`, scheda «Audit TTS» — è
   anche la scheda di default della pagina).

   > **Trappola: il saldo cala dell'addebito, non del costo.** La
   > commissione di ricarica del 5% (`ABM_CF_CREDIT_TOPUP_FEE`) si paga
   > **comprando** il credito, non spendendolo: internamente il margine è
   > calcolato sulla tariffa maggiorata di quella commissione
   > (`_cf_effective(rate) = rate * (1 + fee)`), ma il consumo che
   > Cloudflare mostra in dashboard è l'addebito nudo sul saldo, senza la
   > commissione (già pagata a monte, alla ricarica). Confrontare la voce
   > sbagliata (costo interno maggiorato contro consumo dashboard nudo, o
   > viceversa) produce uno scarto sistematico di circa il 5% che sembra un
   > bug e non lo è.

---

## 5. Cosa osservare nelle prime 24 ore

- **Email di switch.** Se arriva un'email con oggetto
  `[ABM-ADMIN] TTS flash31: switch automatico a Vertex (...)`, il failover
  è scattato: passare alla §7. Nessuna email = nessun failover, situazione
  normale.
- **Latenza percepita sui job lunghi** (G4, non chiuso). Non c'è una
  soglia numerica da verificare — non esiste un baseline Vertex comparabile
  — ma un rallentamento percepibile nella durata complessiva dei job
  rispetto a prima dell'accensione è il segnale da cui partire. In caso di
  dubbio, il rollback (§6) è immediato.
- **Credito residuo** nel pannello «Backend TTS» (`/admin/audit-premium`):
  deve scendere in modo coerente con il volume di job serviti, non a scatti
  improvvisi.
- **Errori `2017` nei log.** Anche con l'accensione autorizzata (fix del
  chunking implementato, §1), un `2017` isolato indica un caso limite non
  coperto dal fix: non è la classe intera di libri della §1, ma va comunque
  investigato prima che si ripeta.

---

## 6. Rollback

Per tornare a Vertex (non richiede alcuna diagnosi preventiva — è
reversibile in ogni momento):

1. Nell'unit systemd, riportare:
   ```
   ABM_GEMINI_BACKEND=vertex
   ```
   (lasciare `ABM_CF_ACCOUNT_ID` / `ABM_CF_API_TOKEN` / `ABM_CF_CREDIT_BALANCE_EUR`
   presenti non ha effetto: senza `cloudflare` come backend selezionato non
   vengono usate.)
2. ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart audiobook-maker
   ```
3. **Job in corso al momento del restart** seguono la sorte consueta di
   qualunque restart del servizio (non specifica di questo rollback):
   verificarne l'esito nell'activity log (`/admin/log-activity`) dopo il
   riavvio, invece di assumere che siano andati a buon fine o persi.
4. Il rollback **non richiede** di toccare lo stato del breaker
   (`tts_backend_state`): resettarlo è inutile perché **in questo scenario
   entrambi i percorsi portano comunque a Vertex** — con
   `ABM_GEMINI_BACKEND=vertex` la selezione dà Vertex sia che il breaker sia
   scattato sia che non lo sia.

   Attenzione a non generalizzare: **non** è vero che la selezione dipenda
   solo da `ABM_GEMINI_BACKEND`. Il breaker ha **precedenza** su quella
   variabile (`gemini_tts._resolve_backend`): un modello scattato resta su
   Vertex anche con `ABM_GEMINI_BACKEND=cloudflare`, e anche dopo un riavvio
   del processo. Simmetricamente, il reset dalla console admin **cambia
   davvero** il backend effettivo quando la configurazione dichiarata è
   `cloudflare` (con qualunque altra configurazione l'endpoint rifiuta il
   reset con `409`, proprio per non lasciar credere il contrario).

---

## 6bis. Pre-allarme credito: l'email che arriva *prima* del guasto

Oggetto: `[ABM-ADMIN] Credito Cloudflare basso: <residuo> EUR residui
(soglia <soglia>)`.

Questa email **non** annuncia un failover: il TTS sta ancora girando su
Cloudflare e nessun job è in errore. Parte quando il residuo **stimato**
(`ABM_CF_CREDIT_BALANCE_EUR` meno la spesa accumulata nel ledger locale)
scende sotto `ABM_CF_CREDIT_ALERT_EUR`, subito dopo l'addebito che ha
attraversato la soglia. Arriva **una sola volta** per soglia
(`claim_credit_alert()` è atomica e consuma l'allarme); si riarma solo dopo
un topup (casella «Ho ricaricato il credito» nel pannello «Backend TTS»,
che azzera il ledger).

Che fare: ricaricare il credito, riallineare `ABM_CF_CREDIT_BALANCE_EUR`
nell'unit systemd (`daemon-reload` + `restart`), spuntare la casella di
topup nel pannello. Nessun reset del breaker serve: non è scattato nulla.

Se `ABM_CF_CREDIT_BALANCE_EUR` è a `0` questa email non arriva mai — è il
motivo per cui il §2 punto 3 insiste sul non lasciarla a zero.

---

## 7. Failover: cosa fare quando arriva l'email

L'email (oggetto `[ABM-ADMIN] TTS flash31: switch automatico a Vertex
(<causa>)`) significa che il breaker è già scattato e il job in corso è
già proseguito su Vertex dal chunk corrente, senza interruzione. Non è
un'emergenza da instradare a mano — lo ha già fatto il codice. La
procedura:

1. **Diagnosi.** La causa più comune è credito Cloudflare esaurito
   (`2021 insufficient balance`, trattato come `backend_down`: scatta al
   primo fallimento, senza attendere soglia). Nel pannello «Backend TTS»
   compare una riga unica di dettaglio nel formato `Causa: <motivo> ·
   <dettaglio>` (non due campi separati) — leggerla per intero.
2. **Ricarica** il credito Cloudflare se la causa è esaurimento saldo.
3. **Aggiorna `ABM_CF_CREDIT_BALANCE_EUR`** nell'unit systemd con il nuovo
   importo netto ricaricato, poi:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart audiobook-maker
   ```
   Il rientro dal pannello (punto 4) da solo non aggiorna questa variabile.
4. **Rientro dal pannello** «Backend TTS» (`/admin/audit-premium`): pulsante
   «Riporta su Cloudflare», con la casella **«Ho ricaricato il credito
   (azzera il contatore di spesa)»** spuntata se si è appena ricaricato
   (azzera il ledger locale di spesa, altrimenti il pre-allarme continuerebbe
   a calcolare il residuo sulla spesa pre-ricarica). Il pulsante chiede
   conferma esplicita prima di procedere.

   > **Il rientro non va fatto prima di aver risolto la causa.** Se il
   > problema persiste (es. credito non ricaricato per davvero, o causa
   > diversa dal credito), il breaker riscatta alla primissima chiamata
   > successiva: ogni ricaduta di questo tipo costa un job (fallimento o
   > nuovo giro di failover a metà sintesi).

---

## 8. flash25 resta su Vertex, in modo permanente

Verificato il 26/08/2026 (spec, §10.3): Cloudflare non ospita alcuna
variante TTS di Gemini 2.5 — ogni id candidato (`gemini-2.5-flash-tts`,
`gemini-2.5-flash-preview-tts`, `gemini-2.5-flash-tts-preview`,
`gemini-2.5-pro-tts`) risponde `404 Model not found`. Solo
`gemini-3.1-flash-tts` (`flash31`) esiste su Cloudflare.

Conseguenza operativa: **accendere il backend Cloudflare con questo
runbook non sposta `flash25`.** Il modello economico del listino continua
a passare da Vertex, con le tariffe Google e il margine di sempre, sia
prima che dopo l'accensione — la risoluzione del backend è per modello, non
globale, e la tariffa mista non lo riguarda in alcun modo.
