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
| G4 | Latenza p95 non peggiore di Vertex a parità di concorrenza | **chiuso** | 28/08/2026 | A/B sul percorso di produzione, §10.4 |
| G5 | Nessun errore `2017` su un libro intero dopo il fix del chunking | **aperto, bloccante** | — | il fix non è ancora implementato |

**G4 — chiuso il 28/08/2026.** L'A/B che mancava è stato eseguito con
`scripts/ab_latency_bench.py`, che cronometra `gemini_tts.synthesize()` — il
percorso vero della produzione, non un clone HTTP — alternando i due backend
a chunk alterni, così che una deriva della rete non si scarichi tutta su uno
dei due. Dieci chunk da 450 caratteri (il valore di produzione), italiano,
voce Zephyr, zero errori e zero retry su entrambi i lati:

| | Cloudflare | Vertex |
|---|---|---|
| mediana per chiamata | 15,57 s | 17,14 s |
| **p95** | **20,53 s** | **32,86 s** |
| min – max | 13,26 – 20,53 s | 11,66 – 32,86 s |
| totale su 10 chunk | 160,6 s | 183,9 s |

Cloudflare non è peggiore di Vertex ed è più regolare: il p95 di Vertex è
gonfiato da un singolo campione a 32,9 s, mentre Cloudflare non produce
outlier confrontabili. Il criterio è soddisfatto. Numeri, limiti della misura
(n=10, concorrenza 1) e conseguenze operative in §10.4 della spec.

**G5 — chiuso il 2026-08-28, con esito diverso da quello atteso.** Il piano
`docs/superpowers/plans/2026-08-26-tts-chunking-degenerate-fix.md` partiva da
una premessa che si è rivelata falsa: che un capitolo titolato con un
frammento quasi solo numerale (`XIV.`, `Cap. 12`) producesse un **buco muto**
nell'audiolibro. Il backend Cloudflare rifiuta davvero quel chunk per
moderazione contenuti con codice `2017`, e in modo deterministico — ma dal
**v3.35.0** quel rifiuto non lascia silenzio: `generate_chunk_pcm_gemini`
instrada il chunk a una voce edge-tts dello stesso genere e accento, che lo
narra, e il chunk **non conta come fallito** (`tts_split.py`, ramo
`if fallback_lang:`; `fallback_lang` è sempre valorizzato dal chiamante in
`generation_engine.py` via `_audit_language`).

Il rimedio pianificato — fondere il frammento col chunk vicino — è stato
implementato, misurato e **rimosso**: su 6000 input casuali (italiano e
cinese, cap 60-2000 caratteri, byte-cap 200-1800) non cambiava l'esito in
nemmeno un caso. Lo splitter fa già greedy packing, quindi un frammento resta
isolato solo quando il vicino non ha spazio residuo, e in quel caso nemmeno la
fusione potrebbe rispettare i cap. Il comportamento reale è ora fissato da
`test/test_chunk_fragments.py`.

Resta quindi una **degradazione**, non un guasto: sui capitoli titolati a
numerale isolato si spendono tre tentativi Gemini e il titolo viene letto con
una voce diversa dal resto del libro. Non è una ragione per tenere spento
Cloudflare; è una cosa da ascoltare al primo libro reale.

> ## Riga netta: **ACCENSIONE AUTORIZZATA dopo il controllo di ascolto**
>
> G5 non blocca più. Resta **una** condizione, ed è di ascolto, non di log:
> una rigenerazione di controllo su un libro reale con titoli di capitolo
> numerali/brevi, backend Cloudflare attivo, in cui si verifica che
> 1. il testo dei titoli **si sente** (letto da Gemini o dalla voce di
>    ripiego: entrambi gli esiti vanno bene, un titolo muto no);
> 2. `failed_chunks` resta 0 — gli eventuali `2017` nei log sono attesi e
>    innocui **purché** seguiti dal recupero edge.
>
> Eseguito il controllo, annotare qui data e id del job e procedere alla §3.

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
3. **`ABM_CF_CREDIT_BALANCE_USD` allineato all'importo ricaricato**, *oppure*
   `ABM_CF_CREDIT_CHECK=0` se la ricarica automatica è attiva. Il credito
   Cloudflare è denominato **in dollari**: la variabile va dichiarata in USD,
   così la cifra del pannello e quella della dashboard del fornitore si
   confrontano a occhio. È il saldo che l'admin **dichiara** dopo la ricarica
   — non è leggibile via API Cloudflare (nessun endpoint di credito esiste;
   quelli di fatturazione rispondono `403` perché il token è volutamente
   ristretto). Impostarla all'importo netto della ricarica: il credito si
   compra pagando anche la commissione del 5% (`ABM_CF_CREDIT_TOPUP_FEE`),
   quindi il saldo disponibile per le chiamate è l'importo ricaricato, non
   l'importo speso in fattura. Con `0` (default) il pre-allarme sul credito
   resta disabilitato — non lasciarla a zero dopo l'accensione.

   **Alternativa consigliata se il pannello Cloudflare ha la ricarica
   automatica a soglia:** impostare `ABM_CF_CREDIT_CHECK=0` e ignorare il
   saldo dichiarato. Con la ricarica automatica il credito si rialza da solo,
   quindi un saldo dichiarato a mano invecchia dal giorno dopo e il residuo
   stimato diventa un numero plausibile e falso. A controllo spento il
   pannello mostra la **spesa cumulata** al posto del residuo, e la
   contabilità resta intatta: si continua a sapere quanto costa Cloudflare,
   si smette solo di sorvegliare quanto ne resta. Il nome vecchio
   `ABM_CF_CREDIT_BALANCE_EUR` è ancora onorato (convertito al cambio, con un
   avviso a stdout), ma va sostituito alla prima occasione utile.

---

## 3. Accensione

Variabili da aggiungere all'unit systemd (`Environment=` o
`EnvironmentFile=`, secondo la convenzione già in uso sul server):

```
ABM_GEMINI_BACKEND=cloudflare
ABM_CF_ACCOUNT_ID=<account id Cloudflare>
ABM_CF_API_TOKEN=<token con soli permessi Workers AI>
ABM_CF_CREDIT_BALANCE_USD=<importo netto ricaricato in USD, es. 50>
```

Con la ricarica automatica attiva sul pannello Cloudflare, al posto della
riga del saldo:

```
ABM_CF_CREDIT_CHECK=0
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
- **Durata complessiva dei job lunghi.** G4 è chiuso (§1): a parità di
  chunk, Cloudflare gira come Vertex. La sorveglianza resta perché il
  criterio misura la singola chiamata, non il job: entrambi i backend
  generano a circa 1,5–1,7x il tempo reale, quindi un libro da 6 h di audio
  impegna ~3,5–4 h in ogni caso, e l'anomalia si riconosce solo confrontando
  con quella base — non con un'attesa. Un rallentamento marcato rispetto a
  prima dell'accensione è il segnale da cui partire; in caso di dubbio il
  rollback (§6) è immediato.
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
   (lasciare `ABM_CF_ACCOUNT_ID` / `ABM_CF_API_TOKEN` / `ABM_CF_CREDIT_BALANCE_USD`
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

Oggetto: `[ABM-ADMIN] Credito Cloudflare basso: <residuo> USD residui
(soglia <soglia>)`. Tutti gli importi dell'email sono in USD, la valuta in
cui Cloudflare denomina il credito: chi la legge di notte deve poterli
confrontare con la dashboard del fornitore senza rifare il cambio a mente.

Questa email **non** annuncia un failover: il TTS sta ancora girando su
Cloudflare e nessun job è in errore. Parte quando il residuo **stimato**
(`ABM_CF_CREDIT_BALANCE_USD` meno la spesa accumulata nel ledger locale)
scende sotto `ABM_CF_CREDIT_ALERT_USD`, subito dopo l'addebito che ha
attraversato la soglia. Arriva **una sola volta** per soglia
(`claim_credit_alert()` è atomica e consuma l'allarme); si riarma **solo**
con il topup, cioè il pulsante «Ho ricaricato il credito» del pannello
«Backend TTS», che azzera il ledger di spesa.

Che fare, nell'ordine:

1. Ricaricare il credito Cloudflare AI Gateway.
2. Riallineare `ABM_CF_CREDIT_BALANCE_USD` nell'unit systemd col nuovo saldo (in USD)
   (`daemon-reload` + `restart`).
3. **Premere «Ho ricaricato il credito»** nel pannello «Backend TTS»
   (`/admin/audit-premium`), con conferma. Azzera la spesa accumulata e
   riarma il pre-allarme per il ciclo successivo.

Nessun reset del breaker serve: non è scattato nulla — e infatti il pulsante
di rientro è disabilitato in questo scenario, mentre quello di topup è
**sempre** disponibile quando `ABM_GEMINI_BACKEND=cloudflare`, a prescindere
dai trip. È deliberato: il ciclo normale del credito non passa mai da un
failover, e legare il topup al rientro (com'era la vecchia casella accanto a
quel pulsante) faceva arrivare il pre-allarme **una volta sola nella vita
dell'installazione**.

Saltare il punto 3 non è innocuo: il saldo dichiarato sale mentre
`spent_usd` continua ad accumulare dal ciclo precedente, quindi il «credito
residuo» del pannello resta sottostimato per sempre e l'allarme non riparte
più. Saltare il punto 2 lascia invece il residuo sotto soglia: dopo il topup
il pre-allarme riscatterebbe quasi subito.

Se `ABM_CF_CREDIT_BALANCE_USD` è a `0` questa email non arriva mai — è il
motivo per cui il §2 punto 3 insiste sul non lasciarla a zero. **Non arriva
mai nemmeno con `ABM_CF_CREDIT_CHECK=0`**, e lì è voluto: con la ricarica
automatica attiva l'esaurimento lo gestisce il fornitore. In quel caso
l'intero §6 non si applica — nessuna email di pre-allarme, nessun topup da
premere, e il pannello mostra la spesa cumulata invece del residuo. Le due
configurazioni non vanno confuse: il saldo a `0` dice «non so quanto credito
ho», l'interruttore dice «non voglio che venga sorvegliato», e davanti a un
pannello muto la differenza distingue una dimenticanza da una scelta.

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
3. **Aggiorna `ABM_CF_CREDIT_BALANCE_USD`** nell'unit systemd con il nuovo
   importo netto ricaricato (in USD) — passo da saltare se
   `ABM_CF_CREDIT_CHECK=0` — poi:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl restart audiobook-maker
   ```
   I pulsanti del pannello (punti 4 e 5) non aggiornano questa variabile.
4. **Topup dal pannello** «Backend TTS» (`/admin/audit-premium`): pulsante
   **«Ho ricaricato il credito»**, da premere se si è appena ricaricato.
   Azzera il ledger locale di spesa e riarma il pre-allarme; senza, il
   residuo continuerebbe a essere calcolato sulla spesa pre-ricarica. È
   un'azione **distinta dal rientro** e non tocca il breaker: chiede conferma
   esplicita, ed è irreversibile.
5. **Rientro dal pannello**: pulsante «Riporta su Cloudflare», anch'esso con
   conferma esplicita.

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
