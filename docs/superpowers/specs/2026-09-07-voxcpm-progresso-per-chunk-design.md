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

### 4.1 La sonda che viene prima di tutto

**Il campo esatto in cui RunPod espone il payload parziale va confermato su un
job reale prima di scrivere il resto.** La sonda è un job `generate` da pochi
chunk, con una `progress_update` in `_one` e la stampa integrale delle
risposte `/status` lato client. Costa un'accensione di worker e qualche minuto.

Esito atteso: il payload sotto `output`. Se il payload non arriva affatto, si
ripiega sul **piano B** (§9) senza aver scritto né il plumbing del client né
quello della barra.

### 4.2 Forma del payload

```json
{"phase": "generate", "chunks_done": 47, "chunks_total": 96}
```

`phase` assume tre valori, nell'ordine in cui il worker li attraversa:

| `phase`    | quando                                                   |
|------------|----------------------------------------------------------|
| `generate` | il ciclo che alimenta la GPU, un evento per chunk chiuso  |
| `verify`   | i giri di rigenerazione delle code tagliate               |
| `deliver`  | l'upload dell'audio su R2                                 |

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

**I punti di chiamata.** In `_one`, dopo `results[i] = y` e dopo
`caduti.append(i)` — un chunk caduto è comunque un chunk chiuso, e il silenzio
di un secondo che il worker mette al suo posto occupa la sua fetta di capitolo
come gli altri. Il contatore è un intero incrementato da coroutine dello stesso
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
9. A fine pre-pass `progress_current` vale quello di oggi: la modifica non
   sposta il punto d'arrivo, solo la strada.
10. `peso_barra = 0` non scrive né `progress_current` né `progress_message`.
11. Un `chunks_done`/`chunks_total` più grande di `len(indici)` — worker che
    conta diversamente — non fa sforare il peso del capitolo oltre `9 * n`.
12. Senza mai un avanzamento (worker vecchio) barra e messaggio sono identici a
    quelli di oggi, capitolo per capitolo.

**Worker — `abm-voxcpm-worker/tools/test_progress.py` (nuovo, senza GPU)**

13. Con `progress_update` sostituita da un doppio, la sequenza delle fasi è
    `generate…` → `verify` → `deliver`.
14. Il freno rispetta `VOXCPM_PROGRESS_MIN_S`, e l'ultimo evento di ogni fase
    passa comunque.
15. `VOXCPM_PROGRESS_MIN_S=0` non pubblica nulla.
16. Un `progress_update` che solleva non fa fallire `_action_generate`, e il
    dizionario finale è identico a quello senza pubblicazione.

**Collaudo manuale** — una voce nuova in `docs/MANUAL_TESTS_VOXCPM.md`: libro
da almeno tre capitoli, barra osservata per l'intera sintesi, conteggio frasi
che cresce e non arretra mai, messaggio di rifinitura visibile, e il valore a
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

**Piano B, se la sonda del §4.1 dice di no.** Il worker scrive un piccolo JSON
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
