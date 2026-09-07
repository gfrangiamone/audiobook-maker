# La barra VoxCPM smette di aspettare il capitolo: avanza per chunk

Design del 2026-09-07. Branch `VOXCPM`, worktree `.worktrees/VOXCPM`.
Coinvolge un secondo repository: `abm-voxcpm-worker` (immagine RunPod).

## 1. Obiettivo

Durante una generazione con voci VOXCPM2 la barra di avanzamento resta ferma
per minuti interi, e poi salta. Il motivo non è un difetto di rendering: il
dato «chunk fatto» **non esiste** lato ABM. L'unità di lavoro è il capitolo
(un job RunPod per capitolo, §7.3 del design d'integrazione), e l'unico
momento in cui ABM impara qualcosa è quando il job finisce.

Questo design apre un canale di avanzamento dal worker al server, così che la
barra si muova **al ritmo dei chunk che il motore chiude davvero** — non di una
stima, non di un'animazione.

## 2. Il difetto vero

### 2.1 Il worker sa, ma non lo dice

In `abm-voxcpm-worker/handler.py`, la coroutine `_one` (handler.py:877) chiude
un chunk alla volta: scrive `results[i] = y` (handler.py:889) oppure registra
la caduta in `caduti` (handler.py:908). Il contatore che serve alla barra è
quindi già lì, un incremento per riga. Non viene pubblicato da nessuna parte:
l'unica risposta del worker è il dizionario finale di `_action_generate`.

### 2.2 Il client scarta l'unica finestra utile

`voxcpm_tts._attendi_esito` (voxcpm_tts.py:623) sonda `/status` ogni
`ABM_VOXCPM_POLL_S` secondi (default 2,0). Legge `st.get("status")`, e di tutto
ciò che non è uno stato terminale usa una cosa sola:

```python
if t_run is None and stato == "IN_PROGRESS":
    t_run = clock()
```

Il resto del corpo della risposta viene ignorato. L'unico callback vivo durante
l'attesa è `on_queue`, che smette di essere chiamato **appena il job parte** —
cioè esattamente quando comincia il tempo lungo.

### 2.3 La barra avanza a scatti di capitolo

`generation_engine._voxcpm_pre_pass` (generation_engine.py:3358) muove la barra
in un punto solo, dentro il consumo delle future completate
(generation_engine.py:3524):

```python
job["progress_current"] = 2 + peso_barra * fatti_chunk
job["progress_message"] = (
    f"Sintesi vocale: {fatti_capitoli} di {len(gruppi)} "
    f"capitol{'o' if len(gruppi) == 1 else 'i'}")
```

`peso_barra` vale `_VOXCPM_PESO_BARRA = 9` (generation_engine.py:3355), e
`fatti_chunk` cresce di tutti i chunk del capitolo in un colpo solo. Con
`ABM_VOXCPM_JOBS=2` capitoli in volo e capitoli da diversi minuti, l'utente
vede due o tre aggiornamenti in un'ora di lavoro.

### 2.4 Il frontend non c'entra

`audiobook_app._progress_payload` calcola `pct = int(cur / tot * 100)` da
`progress_current`/`progress_total` e lo spinge in SSE; `static/js/app.js`
scrive la larghezza della barra. La catena a valle funziona: le manca il dato.

## 3. Decisioni prese

Tre scelte fatte con l'utente prima del design, che il resto del documento dà
per acquisite:

1. **Si tocca il worker e si ridistribuisce l'immagine.** Il progresso vero
   esiste solo lì; senza il deploy si potrebbe solo stimare, e una stima non è
   ciò che è stato chiesto.
2. **Il messaggio dice capitoli e frasi.** `Sintesi vocale: 3 di 12 capitoli
   (47 di 210 frasi)`: la barra si muove col numero fine, il testo conserva il
   riferimento al capitolo che l'utente già conosce.
3. **La coda del job ha la sua fetta e il suo messaggio.** I chunk generati non
   valgono il 100% del capitolo: dopo di loro restano i giri di rigenerazione
   delle code tagliate, l'upload su R2 e il download lato server. La barra non
   deve inchiodarsi su un capitolo apparentemente finito.

## 4. Il canale: `progress_update` di RunPod

L'SDK RunPod espone `runpod.serverless.progress_update(job, payload)`, che
associa al job in corso un payload arbitrario; il payload compare nelle
risposte `/status` mentre lo stato è `IN_PROGRESS`. È il canale ufficiale:
nessuna infrastruttura nuova, nessun costo per messaggio, nessuna chiave da
ripulire.

### 4.1 Quel che la sonda ha misurato

La sonda e' stata eseguita su job reali contro l'endpoint di produzione il
2026-09-07. Le risposte qui sotto non sono attese: sono misure.

**Il payload parziale arriva, sotto `output`.** Durante `IN_PROGRESS`,
`GET /v2/<endpoint>/status/<job_id>` restituisce esattamente cio' che il worker
ha pubblicato:

```
t+41.8s  IN_PROGRESS  {"output": {"chunks_done": 0, "chunks_total": 8,
                                  "phase": "generate"}, "status": "IN_PROGRESS"}
t+44.5s  IN_PROGRESS  {"output": {"chunks_done": 8, "chunks_total": 8,
                                  "phase": "verify"},   "status": "IN_PROGRESS"}
t+49.5s  IN_PROGRESS  {"output": {"chunks_done": 8, "chunks_total": 8,
                                  "phase": "deliver"},  "status": "IN_PROGRESS"}
```

Il piano B (§9) resta scritto ma non serve.

**La POST vuole l'`Authorization`, e nessuno lo dice.** `progress_update`
dell'SDK posta su `JOB_DONE_URL` attraverso una sessione aiohttp che porta gia'
`Authorization: <RUNPOD_AI_API_KEY>` (valore nudo, senza `Bearer`), messa li' da
`runpod/http_client.py::get_auth_header()`. Un pubblicatore che rifa' la POST a
mano senza quell'header riceve **401** e non pubblica niente: misurato, sei POST
rifiutate in silenzio, con la barra ferma e nessun errore visibile al chiamante.
Chi scrive il codice definitivo copi gli header dell'SDK, non solo l'URL.

**Il job non resta appeso.** Con il pubblicatore chiuso e atteso *prima* che la
risposta parta, tutte le corse sono finite `COMPLETED`. E' la difesa contro
runpod-python#250 (§9): un aggiornamento che arriva dopo il risultato riporta il
job a `IN_PROGRESS` e ce lo lascia, e per noi vorrebbe dire `tetto_exec`,
`VoxcpmBloccato`, capitolo rigenerato e GPU pagata due volte.

**Il thread pubblicatore non muore di fame.** In un job da ~130s ha fatto 60
giri regolari a passo di 2s: il ciclo che alimenta la GPU non lo soffoca, e non
serve nessun accorgimento sul GIL.

#### 4.1.1 I chunk chiudono a ondate, non a goccia

```
chunk chiusi a : 123.44  123.48 | 125.12  125.29 | 126.53  126.70 | 127.99  128.10
```

Otto chunk con `concurrency=2`: quattro ondate da due, a ~1,5s l'una dall'altra.
La granularita' vera dell'avanzamento e' **l'ondata, cioe' `concurrency`**, non
il singolo chunk. In produzione `ABM_VOXCPM_CONCURRENCY=24`, quindi un capitolo
da 30 chunk avanza in **due scatti**, non in trenta passi. La barra sara' molto
piu' informativa di adesso, ma non fluida: il design promette scatti piu' fitti
del capitolo, non una progressione continua.

#### 4.1.2 Il tratto piu' lungo non e' la generazione

Nella stessa corsa, il primo chunk si e' chiuso a **t+123s** su un job di
~130s: gli otto chunk sono usciti tutti negli ultimi cinque secondi. I 123
secondi precedenti sono l'avvio del motore su worker freddo — il log del worker
lo conferma (`pool pronto in 118.4s`).

Ne segue un vincolo che la §4.2 recepisce: **se il worker pubblica solo
`chunks_done/chunks_total`, su worker freddo l'utente vede la barra ferma a zero
per due minuti** — lo stesso difetto che questo lavoro deve togliere, spostato
di un livello. Il worker deve dichiarare la fase di avvio *prima* che esista un
solo chunk, e il messaggio deve dirla.

### 4.2 Forma del payload

```json
{"phase": "generate", "chunks_done": 47, "chunks_total": 96}
```

`phase` assume quattro valori, nell'ordine in cui il worker li attraversa:

| `phase`    | quando                                                   |
|------------|----------------------------------------------------------|
| `warmup`   | il motore si carica: nessun chunk esiste ancora           |
| `generate` | il ciclo che alimenta la GPU, un evento per chunk chiuso  |
| `verify`   | i giri di rigenerazione delle code tagliate               |
| `deliver`  | l'upload dell'audio su R2                                 |

`warmup` non e' un di piu': su worker freddo dura piu' di tutto il resto messo
insieme (§4.1.2), e va pubblicato appena il job viene preso in carico, prima
che il pool sia pronto. In quella fase `chunks_done` vale 0 e `chunks_total` e'
gia' noto, cosi' il client sa quante frasi arriveranno.

Il payload è additivo e autodescrittivo: un consumatore che non lo riconosce
lo ignora, e nulla di ciò che esiste oggi cambia forma.

## 5. Lato worker (`abm-voxcpm-worker/handler.py`)

**`_handle` passa il job intero.** Oggi `_action_generate(inp, str(job.get("id")
or ""))` (handler.py:1837) tiene solo l'id, perché serviva alla chiave S3.
`progress_update` vuole il dizionario del job: la firma diventa
`_action_generate(inp, job_id="", job=None)`, con `job` opzionale così i test in
`tools/` continuano a chiamarla con due argomenti.

**Un pubblicatore, tre regole.** Dentro `_action_generate` nasce una chiusura
`_pubblica(phase, done)`:

- **Non solleva mai.** Stessa politica di `_riga_costo` lato client: un
  avanzamento che si rompe non deve portarsi via un capitolo già pagato in GPU.
  L'eccezione si stampa una volta e la pubblicazione si spegne per il resto del
  job.
- **È strozzata.** Al più una pubblicazione ogni `VOXCPM_PROGRESS_MIN_S`
  secondi (default 1,0; `0` spegne del tutto la funzione). Con
  `ABM_VOXCPM_CONCURRENCY=24` i chunk chiudono a ondate, e senza freno una
  singola ondata genererebbe due dozzine di aggiornamenti indistinguibili.
  L'ultimo evento di ogni fase passa sempre, freno o no: è quello che porta il
  numero definitivo.
- **Si autodisattiva.** `getattr(runpod.serverless, "progress_update", None)`;
  se manca, `_pubblica` diventa un no-op. Un'immagine con un SDK più vecchio
  continua a funzionare esattamente come oggi.
- **Porta l'`Authorization` dell'SDK.** Se la pubblicazione non passa per
  `progress_update` ma rifa' la POST, deve copiare gli header di
  `runpod/http_client.py::get_auth_header()`: senza, l'endpoint risponde 401 e
  la barra resta ferma senza che nessuno se ne accorga (§4.1).

**Un thread, non le coroutine.** La sonda ha mostrato che pubblicare dal ciclo
di generazione non basta: un pubblicatore a passo fisso su un thread proprio ha
retto 60 giri in 130 secondi senza disturbare la GPU (§4.1), e soprattutto e'
l'unico modo di far uscire l'avanzamento durante il `warmup`, quando nessuna
coroutine di generazione e' ancora partita. Il thread legge un contatore e una
fase sotto lock e pubblica solo quando la riga cambia; `chiudi()` lo ferma e lo
**aspetta** prima che la risposta del job parta, che e' la difesa contro #250.

**I punti di chiamata.** Una pubblicazione `warmup` appena il job e' preso in
carico, prima del caricamento del pool: e' il tratto piu' lungo di tutti
(§4.1.2) e oggi e' completamente muto. Poi in `_one`, dopo `results[i] = y` e
dopo `caduti.append(i)` — un chunk caduto è comunque un chunk chiuso, e il
silenzio di un secondo che il worker mette al suo posto occupa la sua fetta di
capitolo come gli altri. Il contatore è un intero incrementato da coroutine dello stesso
event loop, mai da thread diversi: non serve altra sincronizzazione. Poi una
pubblicazione `verify` all'inizio dei giri di rigenerazione, e una `deliver`
prima dell'upload.

## 6. Lato client (`voxcpm_tts.py`)

**`_attendi_esito` guadagna `on_progress`.** Nel ramo non terminale, prima del
sonno annullabile:

```python
if on_progress is not None and stato == "IN_PROGRESS":
    _riga_avanzamento(on_progress, st.get("output"))
```

`_riga_avanzamento` consegna il dizionario **solo se** è un `dict` con
`chunks_total` intero maggiore di zero e `chunks_done` intero non negativo.
Qualunque altra forma — assente, `None`, lista, numeri assurdi — viene ignorata
in silenzio: è un worker di un'altra versione, non un errore da propagare. Come
`_riga_costo`, non solleva mai.

**Nessun parziale può essere scambiato per un esito.** L'uscita dal ciclo resta
governata dai soli stati terminali (`COMPLETED`, `FAILED`, `CANCELLED`,
`TIMED_OUT`). Questa è la regressione da temere in tutta la modifica, ed è il
primo test dell'elenco al §8.

**`run_job` e `synthesize_chapter` inoltrano.** Entrambe prendono `on_progress`
come parametro opzionale a sole parole chiave e lo passano a valle senza
interpretarlo. `synthesize_chapter` non ha nulla da dire sui ritentativi: un
capitolo rifatto a concorrenza ridotta ripubblica `chunks_done` da zero, e la
monotonia è responsabilità del chiamante (§7).

**Interruttore.** `ABM_VOXCPM_PROGRESS=0` fa sì che il client non passi mai
`on_progress`: la barra torna al comportamento di oggi senza toccare
l'immagine.

## 7. La barra (`generation_engine._voxcpm_pre_pass`)

### 7.1 Come si divide il peso

Il peso complessivo del capitolo non cambia: `9 * n` punti per un capitolo da
`n` chunk, come oggi. Cambia come li si spende:

- **90% ai chunk generati.** Un chunk chiuso vale `9 * 0,9 = 8,1` punti, e i
  punti si arrotondano a intero solo quando si scrive `progress_current`.
- **10% alla consegna.** Gli ultimi `0,9 * n` punti scattano quando la future
  del capitolo ritorna, cioè quando il PCM è davvero su disco.

Il totale `progress_total = total_chunks * (9 + 1) + 2` resta identico
(generation_engine.py:4952-4953), e l'assemblaggio continua a ripartire da
`2 + 9 * total_chunks` (generation_engine.py:4986). Le fette nuove stanno
dentro il budget di prima: nessun numero a valle cambia.

### 7.2 Due strutture e un lock

```python
consegnati = {}   # ci -> 9 * n, scritto a future completata
parziali   = {}   # ci -> punti dei chunk chiusi, scritto dai callback
fasi       = {}   # ci -> ultima phase vista, scritto dai callback
```

`progress_current = 2 + somma(consegnati) + somma(parziali dei capitoli non
ancora in consegnati)`.

**Chi scrive `ci`.** Il payload del worker non porta l'indice di capitolo, e non
deve: il capitolo è un concetto di ABM, non del worker. `_uno` costruisce quindi
una chiusura per il proprio capitolo — `lambda riga: _avanza(ci, len(indici),
riga)` — e la passa a `synthesize_chapter`. Ogni callback sa a quale capitolo
appartiene perché è stato creato per quello.

**Il denominatore è quello di ABM.** Il worker scarta i chunk vuoti prima di
generare (`chunks = [c for c in chunks if c and c.strip()]`), quindi il suo
`chunks_total` può essere più piccolo di `len(indici)`. La barra usa sempre
`len(indici)` come denominatore, e satura `chunks_done` a quel valore: il peso
del capitolo deve chiudere esattamente a `9 * n` a prescindere da quanti chunk
il worker abbia ritenuto validi.

**Monotonia.** `parziali[ci] = max(parziali.get(ci, 0), nuovo)`. Serve a due
casi reali: un capitolo rifatto da `synthesize_chapter` riparte da
`chunks_done = 0`, e la fase `verify` non porta un conteggio di chunk. Senza
questa regola la barra arretrerebbe, che è il difetto peggiore di una barra.

**Lock.** I callback arrivano dai thread del `ThreadPoolExecutor`
(`voxcpm_tts.jobs_in_flight()`, default 2), il consumo delle future gira sul
thread del job. Un `threading.Lock` avvolge sia l'aggiornamento delle due
strutture sia la riscrittura di `progress_current` e `progress_message`, così
la coppia numero/messaggio non può mai essere osservata mezza aggiornata.

### 7.3 Il messaggio

Il totale delle frasi è `sum(len(indici) for _, indici in gruppi)`, noto prima
di sottomettere il primo job: sono i chunk dei capitoli non riusabili, gli
stessi che la barra pesa.

```
Sintesi vocale: 3 di 12 capitoli (47 di 210 frasi)
```

Il conteggio delle frasi somma i chunk dei capitoli consegnati e i parziali di
quelli in volo — coerente per costruzione con i punti della barra, perché
entrambi leggono le stesse due strutture sotto lo stesso lock.

Quando **tutti** i capitoli in volo hanno smesso di generare, il testo diventa:

```
Sintesi vocale: 3 di 12 capitoli (rifinitura e consegna)
```

E finche' **tutti** i capitoli in volo sono in `warmup` — nessun chunk ancora
prodotto da nessuno — il testo dice quello che sta davvero succedendo:

```
Sintesi vocale: 3 di 12 capitoli (preparazione del motore vocale)
```

Non e' cosmesi: su worker freddo questa fase dura oltre due minuti (§4.1.2), ed
e' proprio il tratto in cui oggi l'utente non ha alcun segno di vita. Vale la
stessa regola di «tutti» della rifinitura, e per la stessa ragione: con due job
paralleli in fasi diverse, alternare i messaggi darebbe un lampeggio senza
informazione. La precedenza, quando le fasi si mescolano, e' al conteggio delle
frasi: appena **un** capitolo in volo genera, il messaggio torna a contarle.

«In volo» ha qui un significato preciso: i capitoli che hanno **un `ci` in
`fasi` e non ancora uno in `consegnati`**, cioè quelli per cui almeno un
avanzamento è arrivato e la future non è ancora tornata. I capitoli ancora in
coda al `ThreadPoolExecutor` non hanno una fase e non entrano nel giudizio; se
l'insieme è vuoto — nessun avanzamento ancora ricevuto, o worker vecchio — il
messaggio resta quello col conteggio frasi.

La condizione è «tutti» e non «almeno uno» di proposito: con due job paralleli,
uno in rifinitura e uno ancora in generazione, alternare i due messaggi darebbe
un lampeggio senza informazione.

Le stringhe restano in italiano, come quelle già presenti nella funzione e
asserite da `test/test_voxcpm_generation.py`. Allineare all'inglese tutti i
messaggi della barra è un lavoro a sé, fuori da questo design.

### 7.4 Il caso senza barra

`peso_barra = 0` (chiamanti che non passano `job`) continua a non toccare
niente: in quel caso `on_progress` non viene nemmeno costruito, e
`synthesize_chapter` riceve `None`.

## 8. Test

**ABM — `test/test_voxcpm_runpod.py`**

1. Una risposta `IN_PROGRESS` con `output` valido chiama `on_progress` col
   dizionario, **e il polling continua**: l'esito resta quello dello stato
   terminale successivo. È il test che protegge dalla regressione peggiore.
2. `output` assente, `None`, lista, o dizionario senza `chunks_total`: nessuna
   chiamata a `on_progress`, nessuna eccezione.
3. Un `on_progress` che solleva non fa fallire il job.
4. Senza `on_progress` il comportamento è quello di oggi.

**ABM — `test/test_voxcpm_generation.py`**

5. I callback parziali muovono `progress_current` senza che nessuna future sia
   ancora completata.
6. Un callback che regredisce (ritentativo, o `verify`) non abbassa
   `progress_current`.
7. A capitolo consegnato il contributo del capitolo è esattamente `9 * n`.
8. Il messaggio contiene capitoli e frasi nella forma del §7.3, e passa a
   «rifinitura e consegna» solo quando tutti i capitoli in volo hanno smesso di
   generare.
8bis. Con tutti i capitoli in volo in `warmup` il messaggio dice «preparazione
   del motore vocale»; appena **uno** genera, torna al conteggio delle frasi.
9. A fine pre-pass `progress_current` vale quello di oggi: la modifica non
   sposta il punto d'arrivo, solo la strada.
10. `peso_barra = 0` non scrive né `progress_current` né `progress_message`.
11. Un `chunks_done`/`chunks_total` più grande di `len(indici)` — worker che
    conta diversamente — non fa sforare il peso del capitolo oltre `9 * n`.
12. Senza mai un avanzamento (worker vecchio) barra e messaggio sono identici a
    quelli di oggi, capitolo per capitolo.

**Worker — `abm-voxcpm-worker/tools/test_progress.py` (nuovo, senza GPU)**

13. Con `progress_update` sostituita da un doppio, la sequenza delle fasi è
    `warmup` → `generate…` → `verify` → `deliver`.
13bis. La riga `warmup` esce **prima** che il pool sia pronto, non dopo: e' il
    tratto piu' lungo del job su worker freddo (§4.1.2), e un test che si
    limitasse all'ordine non lo distinguerebbe da una `warmup` pubblicata
    tardi.
14. Il freno rispetta `VOXCPM_PROGRESS_MIN_S`, e l'ultimo evento di ogni fase
    passa comunque.
15. `VOXCPM_PROGRESS_MIN_S=0` non pubblica nulla.
16. Un `progress_update` che solleva non fa fallire `_action_generate`, e il
    dizionario finale è identico a quello senza pubblicazione.
17. `chiudi()` aspetta il thread: dopo il ritorno nessuna pubblicazione puo'
    partire. E' il test che protegge da runpod-python#250, cioe' dal job che
    resta appeso e fa pagare la GPU due volte.

**Collaudo manuale** — una voce nuova in `docs/MANUAL_TESTS_VOXCPM.md`: libro
da almeno tre capitoli, barra osservata per l'intera sintesi, conteggio frasi
che cresce e non arretra mai, messaggio di preparazione visibile all'avvio a
freddo e messaggio di rifinitura visibile in fondo, e il valore a
fine sintesi che coincide con quello delle generazioni precedenti.

## 9. Compatibilità, deploy, piano B

**Nessuna finestra pericolosa.** Le due direzioni dello sfasamento di versione
degradano entrambe al comportamento attuale:

| worker  | ABM     | esito                                                                  |
|---------|---------|------------------------------------------------------------------------|
| vecchio | nuovo   | nessun `output` parziale, `on_progress` mai chiamata, barra come oggi   |
| nuovo   | vecchio | `progress_update` ignorata, `/status` terminale invariato               |

Il deploy dell'immagine può quindi precedere o seguire il rilascio di ABM in
qualunque ordine, e `ABM_VOXCPM_PROGRESS=0` è l'interruttore che riporta tutto
indietro senza toccare la GPU.

**Il piano B non serve.** La sonda (§4.1) ha misurato il payload parziale in
arrivo sotto `output`: si implementa il canale RunPod. Quel che segue resta
scritto solo come ricaduta, se un domani RunPod smettesse di rimandare indietro
gli aggiornamenti.

Il worker scriverebbe un piccolo JSON
su una chiave R2 (`voxcpm/<job_id>/progress.json`) ogni `VOXCPM_PROGRESS_MIN_S`
secondi, e il client lo rilegge fra un poll e l'altro. Stesso payload, stessa
barra, stessi test: cambia solo il trasporto. Costa una PUT ogni pochi secondi
per job e una chiave in più da cancellare in `_cancella_intermedio`, ed è per
questo la seconda scelta e non la prima.

## 10. File toccati

**`abm-voxcpm-worker`** — `handler.py` (`_handle`, `_action_generate`, `_one`),
`tools/test_progress.py` (nuovo).

**`AudioBook-Maker`** — `voxcpm_tts.py` (`run_job`, `_attendi_esito`,
`synthesize_chapter`), `generation_engine.py` (`_voxcpm_pre_pass`),
`test/test_voxcpm_runpod.py`, `test/test_voxcpm_generation.py`,
`docs/MANUAL_TESTS_VOXCPM.md`.

**Non toccati** — `static/js/app.js` e il payload SSE di `audiobook_app.py`:
la catena a valle di `progress_current`/`progress_total`/`progress_message`
funziona già, e questo design le cambia solo il ritmo con cui riceve i numeri.
