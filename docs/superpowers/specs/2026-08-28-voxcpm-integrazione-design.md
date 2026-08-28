# VoxCPM2 come quarto motore TTS: catalogo di voci inventate e clonazione della voce dell'utente

Design del 2026-08-28. Branch `VOXCPM`, worktree `.worktrees/VOXCPM`.

## 1. Obiettivo

Portare nel tab **Voci PREMIUM** un terzo modello, `VoxCPM2`, servito dal
worker RunPod serverless del repo `abm-voxcpm-worker`. Rispetto a Gemini e
Speechify Simba, VoxCPM offre una cosa in più e una in meno:

- **In più:** l'utente può far leggere il libro dalla **propria voce**, clonata
  da una registrazione di una ventina di secondi.
- **In meno:** non può esistere l'**anteprima di lettura del testo**. Ogni
  anteprima sarebbe un job separato che paga l'accensione del worker — circa
  180 secondi di attesa e il costo di un boot intero — per far ascoltare venti
  secondi di audio.

Al posto dell'anteprima l'utente ascolta il **campione di riferimento**: il
`.wav` da cui il clone parte. Per le voci di catalogo esiste già su disco; per
la voce dell'utente è la sua stessa registrazione, riascoltabile dentro la
procedura di cloning come verifica della qualità.

## 2. Perché l'anteprima non si può salvare

Misura del 2026-08-27 a worker caldo, stesso job sottomesso con 1 e con 8
chunk (`RIPRESA.md` del repo worker):

| Modalità | 1 chunk | 8 chunk |
|---|---|---|
| `reference` | 141,7 s\* | 3,5 s |
| `prompt` | 145,2 s\* | 2,9 s |
| `hifi` | 3,2 s | 3,4 s |

\* job che ha pagato l'accensione del worker.

Otto chunk costano quanto uno. **Il costo non sta nei caratteri, sta
nell'accensione.** Un'anteprima da 300 caratteri e un capitolo da 4.000
costano lo stesso, e l'anteprima non serve a nessuno se arriva tre minuti
dopo il clic. Questa asimmetria ritorna nel §9: cambia anche il modo giusto di
ritentare un capitolo fallito.

## 3. Decisioni prese

Tutte confermate in sede di brainstorming, 2026-08-28.

| # | Decisione |
|---|---|
| D1 | Perimetro: catalogo di voci inventate **e** voce clonata dall'utente, entrambi nella prima iterazione |
| D2 | La trascrizione del campione utente si ottiene con una **frase guidata** letta dal browser: nota per costruzione, niente ASR |
| D3 | La voce clonata resta sul server, legata al cookie `abm_cid` per la riproposta automatica e a un'**email** per il recupero da altro dispositivo e per la cancellazione |
| D4 | Tariffa **€/Mchar** con **costo minimo parametrico** quando si supera la soglia gratuita, sullo schema già in uso per l'ottimizzazione AI, più la quota mensile gratuita |
| D5 | `ACCENTO` e `CARATTERE` non spariscono: da manopole del motore diventano **filtri sul catalogo** |
| D6 | Label `Ascolta campione di riferimento`, non «anteprima» |
| D7 | `CARATTERE` filtra la lista voci; scelta la voce, il campo si allinea come etichetta. Nessuna bidirezionalità simmetrica (§5.3) |
| D8 | Clonazione offerta nelle **6 lingue dell'interfaccia**: IT, EN, FR, ES, DE, ZH |
| D9 | Il worker **sintetizza soltanto**; l'assemblaggio resta all'app |
| D10 | Il catalogo è una **variabile indipendente**: `voices.json` si legge a runtime, nessun elenco di voci è scritto nel codice o nelle traduzioni (§12.1) |

## 4. Fuori perimetro

- Modifiche al worker `abm-voxcpm-worker`. L'integrazione consuma le azioni
  `generate` e il contratto esistenti.
- Rigenerazione del catalogo per ottenere più caratteri per la stessa voce
  (vedi §5.3 e §15.1).
- Uso dell'azione `assemble` del worker (D9).
- Clonazione nelle lingue oltre le sei dell'interfaccia.
- Le 50 voci reali di `data/catalogo`, eliminate dal progetto il 2026-08-28.

## 5. Il pannello Impostazioni audio

### 5.1 Il principio

Con Gemini e Simba i menù sono manopole del motore: si compone una richiesta.
Con VoxCPM sono **filtri su un catalogo**: si restringe un elenco. L'utente
vede la stessa griglia e fa gli stessi gesti; cambia solo cosa succede dietro.
Non serve un layout dedicato e i tre motori restano confrontabili a colpo
d'occhio.

### 5.2 Campo per campo

| Campo | Con VoxCPM | Sorgente |
|---|---|---|
| LINGUA | resta, col conteggio voci | `voices.json` → `language.code` |
| MODELLO | si aggiunge `VoxCPM2 · La tua voce` | costante client |
| ACCENTO | **filtra la variante** (`en-GB/US/AU/IN`, `es-ES/MX/AR/CO`, i nove `zh-*`) | `language.locale` |
| VOCE | nome, genere e carattere sulla stessa riga | `name`, `gender`, `description.persona` |
| CARATTERE (ex EMOZIONE) | filtra la lista voci | `description.persona`, 10 valori |
| VELOCITÀ | invariato, −30%…+30% | `speed` del worker, 0,5–2,0 |
| ASCOLTA CAMPIONE | player del `.wav` di riferimento | `audio.file` |
| STIMA COSTO | invariato nella forma | `/api/combined_estimate` |

Il catalogo pubblicato (`data/voci_inventate/voices.json`) conta **383 voci**
su 30 lingue e 48 varianti, ognuna con `description.persona` valorizzata.

I dieci caratteri: `audiobook-slow`, `bright-lively`, `casual-drawl`,
`deep-adventure`, `grave-narrator`, `intimate`, `neutral-pro`, `poised-dry`,
`warm-young`, `weathered`. Le etichette mostrate all'utente sono le stringhe
già presenti nel catalogo (`description.role`, `description.axes`), tradotte
nelle sei lingue dell'interfaccia.

### 5.3 Perché VOCE e CARATTERE non sono simmetrici

Nel catalogo **ogni voce ha esattamente un carattere**: il carattere è inciso
nel campione da cui VoxCPM clona, non è una manopola applicabile dopo.
Non è una deduzione: è stato misurato, vedi §15.1. In italiano, 13 voci
per 11 caratteri:

```
audiobook-slow   Federica, Andrea      intimate        Giulia
warm-young       Martina, Stefano      bright-lively   Alessia
grave-narrator   Elena                 poised-dry      Chiara
neutral-pro      Lorenzo               deep-adventure  Davide
weathered        Riccardo              casual-drawl    Marco
warm-pro         Tommaso
```

Esempio illustrativo, fotografia al 2026-08-28: la generazione delle
voci è in corso e questi numeri cambieranno. Nessuna parte dell'app li
conosce — vedi D10 e §12.1. Quello che non cambia è la **forma**: un
carattere può avere più voci, una voce ha un carattere solo.

Quindi *carattere → voci* restringe davvero (a una o due voci), mentre
*voce → caratteri* restituisce sempre uno. Il secondo verso non è una scelta:
è un'etichetta, e va mostrato come tale. Un menù che finge di offrire
un'alternativa dove non c'è ne inventa una.

**Comportamento definito:** il menù CARATTERE filtra la lista VOCE. Alla
selezione di una voce, CARATTERE si allinea al valore di quella voce e resta
visibile come informazione. Nessuno dei due campi si svuota mai.

## 6. Il sottosistema «La mia voce»

### 6.1 Ingresso

Prima riga del menù VOCE: **🎙 La mia voce**. Se il cookie `abm_cid` ha già una
voce registrata e non scaduta, la riga è selezionabile e mostra la data di
creazione. Altrimenti apre la procedura.

### 6.2 La procedura

1. **Consenso.** Spunta esplicita — *è la mia voce e ho il diritto di usarla* —
   e informativa: dove va il campione, quanto resta, come si cancella.
2. **Frase guidata.** Testo di circa 20 secondi nella lingua di narrazione,
   mostrato a schermo. È la trascrizione che il worker userà come
   `prompt_text`: nota per costruzione, senza ASR e senza possibilità di
   disallineamento fra ciò che si sente e ciò che si dichiara.
3. **Registrazione** dal browser via `MediaRecorder`, con indicatore di
   livello.
4. **Verifica.** Riascolto del proprio file **più** il verdetto automatico del
   gate di qualità (§6.3). Il verdetto è un motivo leggibile, non un generico
   «riprova». Si può ripetere senza limiti oltre il rate limit del §10.
5. **Registrazione della voce.** Il campione entra normalizzato con le stesse
   misure delle voci di catalogo. Poi email con due link: *richiama la voce su
   un altro dispositivo* e *cancella la voce dal server*.

L'ascolto vive qui e solo qui: è verifica del materiale registrato, non
anteprima della sintesi. Il limite è dichiarato — l'utente verifica *cosa ha
registrato*, non *come VoxCPM lo renderà* (§15.2).

### 6.3 Il gate di qualità

`tools/voice_prompts/audio.py` del repo worker contiene già `measure()` e
`Gate`, la macchina che ha selezionato le 383 voci del catalogo. Va portata
lato server, non riscritta.

`measure()` restituisce: `snr_db`, `speech_ratio`, `bandwidth_hz`,
`longest_gap`, `lufs`, `peak_dbfs`, `clipping`, `f0_median`.

Soglie del `Gate`, ereditate: `min_snr_db = 22.0`, `speech_ratio` fra 0,55 e
0,98, `min_bandwidth_ratio = 0,78` rispetto a Nyquist del target.

Traduzione dei fallimenti in messaggi:

| Misura fuori soglia | Messaggio |
|---|---|
| `snr_db` basso | «Troppo rumore di fondo: prova in una stanza più silenziosa» |
| `speech_ratio` basso o `longest_gap` alto | «Troppe pause: leggi il testo di seguito» |
| `speech_ratio` alto | «Nessuna pausa rilevata: leggi con calma, senza correre» |
| `bandwidth_hz` bassa | «Il microfono taglia le frequenze alte: prova un altro dispositivo» |
| `clipping` o `peak_dbfs` alto | «Audio distorto: allontanati dal microfono o abbassa il guadagno» |

### 6.4 Normalizzazione e formato

`tools/voice_design/includi_voce_esterna.py` fa già esattamente questo:
prende un wav esterno, lo normalizza a 24 kHz con lo stesso guadagno e le
stesse misure del catalogo, e scrive la riga di manifest con il testo letto.
Va portato **da script a funzione** riusabile.

I 24 kHz non sono una perdita: è misurato che **il clone non eredita la banda
del riferimento**. I campioni di catalogo stanno a 24 kHz e la sintesi esce
comunque a 48 kHz.

Senza il testo la voce non è utilizzabile per il cloning — lo dichiara lo
script stesso. Con la frase guidata il testo c'è sempre, per costruzione.

### 6.5 Identità e ciclo di vita

| Aspetto | Scelta |
|---|---|
| Riproposta automatica | cookie `abm_cid`, come `free_quota` |
| Recupero cross-device | link firmato inviato per email |
| Cancellazione | secondo link nella stessa email, effetto immediato |
| Storage del campione | R2, sotto il tiering già esistente |
| Retention | parametrica, dichiarata nell'informativa (§13) |
| Voci per client | una sola; una nuova registrazione sostituisce la precedente |

La voce resta sul server e la usa **solo** il client che l'ha creata: il
riferimento è il token, non indicizzabile e non enumerabile.

### 6.6 Le frasi guidate

Un testo per ciascuna delle sei lingue dell'interfaccia, di circa 20 secondi
letti (~350–400 caratteri, la stessa taglia dei campioni di catalogo — la riga
`Stefano` del manifest è 372 caratteri per 19,52 s).

Requisiti del testo: prosa continua senza elenchi, senza numeri da sciogliere,
senza nomi propri difficili, con almeno due pause naturali di frase. Scritto e
riletto da chi parla la lingua: una frase mal scritta produce un clone
peggiore e nessuno se ne accorge dall'interno.

## 7. Il ponte verso RunPod

### 7.1 La differenza di forma

Gli altri tre motori generano **un chunk alla volta**, in sincrono, dentro
`run_generation()`. VoxCPM è un **job batch remoto**: si sottomette `/run` con
i chunk di un capitolo, si fa polling su `/status`, il worker scrive l'audio
su R2.

`voxcpm_book.py` (2.950 righe) è l'implementazione di riferimento già
collaudata: pianificazione dei chunk, classe `Runpod` con `/run` e polling,
`WorkerBloccato`, `WorkerRimbalzato`, `blocco_cloning()`, contabilità del
costo per job. Il nuovo `voxcpm_tts.py` ne è il **porting**, non una
riscrittura.

Nota dal client: non si usa `/runsync`, che risponde 200 senza `output`
quando il job supera il tempo della richiesta.

### 7.2 Il confine (D9)

**Il worker sintetizza. L'app assembla.**

Il worker restituisce l'audio dei chunk su R2. Da lì in poi vale la catena
esistente: `assembly_queue.py`, `chunk_reuse.py`, la copertina, i capitoli, i
quattro formati di uscita (MP3 singolo, ZIP dei capitoli, M4B, feed RSS del
podcast).

Il worker sa anche assemblare (azione `assemble`, M4B con capitoli, `speed`,
AAC), ma usarla significherebbe insegnargli copertina, ZIP e RSS — oppure
offrire con VoxCPM meno formati che con gli altri motori. VoxCPM deve essere
un quarto motore dentro una catena che non cambia.

### 7.3 Unità di lavoro

**Un job per capitolo**, come fa `voxcpm_book.py`. Il capitolo è già l'unità
di avanzamento della UI e del `chunk_reuse`; l'accensione si ammortizza sui
capitoli successivi finché il worker resta caldo.

### 7.4 Modalità di cloning

`hifi` per tutte le voci, di catalogo e dell'utente. È la decisione presa il
2026-08-27 dopo il test A/B a parità di voce, capitolo e seme: `hifi` e
`prompt` molto simili, `hifi` leggermente meglio come continuità; `reference`
decisamente peggio e inaccettabile. È anche il default di `--clone-mode` nel
client. Le tre modalità **costano uguale**: il divario dei primi riepiloghi
era l'accensione del worker, non la modalità.

`hifi` richiede `prompt_wav` e `prompt_text`. Per le voci di catalogo il testo
viene dal manifest; per la voce dell'utente è la frase guidata.

**Il canale che porta l'identità è `prompt_wav`, non `reference_wav`.**
Misurato il 2026-08-28 (§15.1): incrociando i due canali, il risultato
segue il prefisso e ignora il riferimento. Questo rende `prompt_text` un
requisito duro e non un accessorio — un campione senza la sua trascrizione
esatta resta fuori dal canale che conta, e la resa crolla a quella di
`reference`, già giudicata inaccettabile. È la ragione tecnica per cui D2
sceglie la frase guidata: la trascrizione è nota per costruzione, quindi
esatta per costruzione.

## 8. Costi, quota, pagamento

### 8.1 Ordine di applicazione

Invariante, nell'ordine:

```
1. quota mensile gratuita (free_quota, ABM_FREE_QUOTA_EUR_PER_MONTH, €2,00/mese per abm_cid)
2. sul residuo: se ≤ ABM_LLM_FREE_THRESHOLD_EUR (€0,50) → gratis, dovuto 0
3. altrimenti dovuto = max(residuo, ABM_VOXCPM_MIN_COST_EUR)
```

**Il floor si applica al residuo, mai al lordo.** Un utente con quota ancora
capiente non deve vedersi chiedere il minimo per un importo che la quota
copre.

Sono due meccanismi distinti già presenti nel codice e vanno tenuti distinti:
la soglia con floor è di `payment.py` (ottimizzazione AI e traduzione); la
quota mensile è di `free_quota.py` (voci premium). VoxCPM è la prima
funzionalità che li usa entrambi.

### 8.2 Costanti nuove

Due sole, in `payment.py`, sullo schema di `LLM_MIN_COST_EUR` (€1,00) e
`TRANSLATE_MIN_COST_EUR` (€1,50):

- `ABM_VOXCPM_RATE_EUR_PER_MCHAR`
- `ABM_VOXCPM_MIN_COST_EUR`

La funzione `apply_min_cost` esistente si riusa, non si duplica.

### 8.3 Base di costo

Misurato su RTX 4090 il 2026-08-04: throughput 28,5x realtime su 11.919
caratteri e 51 chunk a concorrenza 16; **~$0,91 per milione di caratteri** a
$1,10/h di scheda. Per confronto, Speechify sta a $11,18 per milione.

Sotto le ~10-15 richieste in volo il batching continuo non si satura: i
capitoli corti costano proporzionalmente di più. Il floor del §8.1 esiste
anche per questo.

### 8.4 Audit del costo reale

Il worker rendiconta il costo effettivo job per job. Quel dato alimenta una
scheda VoxCPM in `/admin/audit-premium`, accanto a Gemini e Speechify, con la
stessa struttura di `gemini_cost_audit.py`: listino applicato all'utente
contro costo GPU reale.

## 9. Errori e degradi

### 9.1 Cold start

Circa 180 secondi per il pull dell'immagine, l'avvio e il warmup
(`torch.compile`; il solo caricamento modello + warmup è 37,3 s). Si assorbe:
la generazione è già asincrona con SSE e l'utente non guarda una barra ferma.
La stima di avanzamento del primo capitolo deve però dichiarare l'attesa
invece di fingere un progresso che non c'è.

### 9.2 Il retry costa un boot, non caratteri

**È l'inversione esatta rispetto agli altri tre motori.** Con Edge, Google e
Gemini un chunk fallito si ritenta e si pagano i caratteri. Con VoxCPM un
capitolo fallito ritentato a freddo paga un'accensione intera: la differenza
fra qualche centesimo e il costo di un boot.

Regola: **ritentare dentro lo stesso job finché il worker è caldo.** Il retry
a freddo è l'ultima risorsa, non la prima.

### 9.3 Motore compromesso

Il worker si autospegne quando il processo del server nanovllm cade — un OOM
lo uccide. La risposta va trattata come **ritentabile**, non come errore del
libro. La regola operativa nota: contare gli eventi «motore compromesso» prima
di dare la colpa alla VRAM.

### 9.4 Tabella dei fallimenti

| Condizione | Trattamento |
|---|---|
| `WorkerBloccato` (coda o timeout) | retry con backoff, poi fallimento del job con rimborso |
| `WorkerRimbalzato` | retry immediato, worker caldo |
| «motore compromesso» / OOM | ritentabile: nuovo job, non errore del libro |
| Endpoint non configurato | VoxCPM non compare fra i modelli, come già fa il tab premium con Gemini |
| Gate di qualità fallito | messaggio §6.3, la generazione non parte |
| Campione utente mancante o scaduto | si ricade sul catalogo, con avviso esplicito |

Le invarianti di rimborso esistenti (voucher ripristinato, ordine PayPal non
marcato) valgono immutate.

## 10. Sicurezza e abuso

La voce clonata è materiale da impersonificazione. La frase guidata letta dal
vivo alza l'asticella — richiede di leggere *quel* testo, non un file
qualunque — ma non la chiude.

- Rate limit sulle registrazioni per `abm_cid` e per IP, sullo schema del rate
  limit già applicato a `/api/preview_audio`.
- Conservazione del campione per verifica a posteriori, con la retention del
  §13.
- Il token della voce non è enumerabile e non compare in URL pubblici.
- Nessuna esposizione della voce di un client ad altri client.

## 11. Privacy

Il campione vocale è dato personale, e i nomi del catalogo sono **inventati**:
`catalog_json.py` lo dichiara esplicitamente nelle note del catalogo, proprio
perché non identifichino nessuno. Le due cose vanno tenute separate anche
nell'informativa.

Per la voce dell'utente: finalità dichiarata, retention parametrica,
cancellazione con un clic dal link in email, nessuna condivisione, nessun uso
per addestramento.

## 12. Mappa dei moduli

**Nuovi:**

| File | Responsabilità |
|---|---|
| `voxcpm_tts.py` | catalogo, risoluzione voce, sottomissione job, polling, misure. Porting del cuore di `voxcpm_book.py` |
| `voice_clone.py` | procedura di cloning, gate di qualità, normalizzazione, storage, token, email |

**Toccati:**

| File | Modifica |
|---|---|
| `voice_utils.py` | `VOXCPM_VOICE_PREFIX`, `is_voxcpm_voice`. Modulo foglia: nessun import di progetto |
| `payment.py` | due costanti, riuso di `apply_min_cost` |
| `free_quota.py` | `is_voxcpm_voice` accanto a `is_speechify_voice` |
| `generation_engine.py` | ramo VoxCPM in `run_generation`, retention per job |
| `audiobook_app.py` | `/api/voices` esteso, endpoint del cloning, `/api/voice_sample`, `/api/combined_estimate` |
| `storage_tiering.py` | campioni vocali nel tiering |
| `static/js/app.js` | modello VoxCPM nel tab premium, filtro carattere, player campione, pannello cloning |
| `templates/_fragments/html_head.html` | pannello di cloning, player |
| `i18n/` | stringhe nelle 6 lingue |

**Non toccati:** il repo `abm-voxcpm-worker`.

### 12.1 Il catalogo è un dato (D10)

La cartella `data/voci_inventate/` — `voices.json` più i `.wav` dei
campioni — entra nel progetto `AudioBook-Maker` come **dato importato** dal
repo del worker, non come sorgente da mantenere qui.

La generazione delle voci è in corso e prosegue in parallelo a questa
implementazione: numero di voci, nomi, lingue e caratteri **cambieranno**.
Nessuna riga di codice, nessuna stringa di traduzione e nessun test può
dipendere da quali voci esistono. In concreto:

- l'elenco delle voci, delle lingue, degli accenti e dei caratteri si
  ricava **leggendo `voices.json`**, mai da una costante;
- i caratteri sono chiavi tecniche (`warm-pro`, `audiobook-slow`): l'app li
  traduce con un dizionario che, davanti a una chiave sconosciuta, ricade
  sulla chiave stessa invece di rompersi. Un carattere nuovo nel catalogo
  non deve richiedere un rilascio;
- i test usano un `voices.json` **di fixture**, non quello reale, così la
  suite non si rompe a ogni rigenerazione;
- una voce citata in un job salvato e poi sparita dal catalogo è un caso
  normale, non un errore: vedi la tabella dei fallimenti in §9.4.

Il percorso della cartella è configurabile (`ABM_VOXCPM_CATALOG_DIR`), così
aggiornare il catalogo è sostituire una cartella, non toccare il codice.

### 12.2 Formato degli identificatori

```
voxcpm:v2:<locale>/<Nome>     voce di catalogo, es. voxcpm:v2:it-IT/Stefano
voxcpm:mine:<token>            voce clonata dell'utente
```

Coerente con `gemini:<model>:<voice>` e `speechify:<model>:<voice>` già in uso,
così `is_voxcpm_voice` è un predicato di prefisso come gli altri.

## 13. Configurazione

Variabili nuove, tutte con default. Da riportare in
`md_files/PARAMETRI_CONFIGURAZIONE.md` come richiesto dal `CLAUDE.md`.

| Variabile | Default | Significato |
|---|---|---|
| `ABM_VOXCPM_ENDPOINT_ID` | — | endpoint RunPod; assente = motore nascosto |
| `ABM_VOXCPM_API_KEY` | — | chiave RunPod |
| `ABM_VOXCPM_CATALOG_DIR` | `data/voci_inventate` | cartella del catalogo importato (D10) |
| `ABM_VOXCPM_RATE_EUR_PER_MCHAR` | da fissare | listino all'utente |
| `ABM_VOXCPM_MIN_COST_EUR` | da fissare | floor sul residuo dopo la quota |
| `ABM_VOXCPM_CATALOG_PATH` | — | percorso di `voices.json` e dei campioni |
| `ABM_VOXCPM_CONCURRENCY` | 32 | chunk in volo per job |
| `ABM_VOICE_CLONE_ENABLED` | true | interruttore della clonazione |
| `ABM_VOICE_CLONE_RETENTION_DAYS` | da fissare | retention del campione |
| `ABM_VOICE_CLONE_MAX_PER_DAY` | da fissare | rate limit per `abm_cid` e IP |

I due valori di listino e la retention si fissano prima del deploy, non in
fase di implementazione: sono decisioni commerciali e legali.

## 14. Collaudo

**Unitari**, sullo schema dei test esistenti in `test/`:

- `is_voxcpm_voice` su input non-stringa, `None`, stringa vuota.
- Ordine quota → soglia → floor, con i tre casi: quota capiente, quota
  esaurita sotto soglia, quota esaurita sopra soglia. In particolare il caso
  che il floor **non** scatti quando la quota copre.
- Gate di qualità: un campione per ciascuno dei cinque motivi di rifiuto, e
  uno che passa.
- Normalizzazione: un wav esterno produce le stesse misure di una riga di
  catalogo.
- Filtro carattere: selezione di un carattere restringe la lista; selezione di
  una voce allinea il campo; nessuno dei due si svuota.
- `/api/voices` espone le voci VoxCPM con `persona` e percorso del campione.

**Con doppio del worker**, senza GPU:

- Job che ritorna «motore compromesso» → ritentabile, non errore del libro.
- `WorkerBloccato` → backoff, poi rimborso.
- Retry a caldo dentro lo stesso job.

**Manuale, su GPU vera** — prima del rilascio, in un documento sullo schema di
`docs/MANUAL_TESTS_GEMINI_PAYMENT.md`:

- Un libro breve con voce di catalogo, dal caricamento all'M4B.
- Registrazione guidata, gate, generazione con la propria voce.
- Recupero della voce da un secondo dispositivo con il link email.
- Cancellazione della voce e verifica che sparisca da entrambi i dispositivi.

Baseline della suite alla creazione del worktree, da `ac1ba45`: **1964
passati, 16 saltati**, nessun fallimento, 180 s. Ogni fallimento successivo è
imputabile a questo lavoro.

## 15. Punti aperti

### 15.1 Bidirezionalità voce/carattere — CHIUSO il 2026-08-28

L'ipotesi era che i due canali di `hifi` fossero separabili:
`reference_wav_b64` = *chi* parla, `prompt_wav_b64` + `prompt_text` = *come*.
Se lo fossero stati, la bidirezionalità sarebbe uscita gratis, incrociando
a runtime campioni già in catalogo. **Non lo sono.**

Misura su `it-IT`, quattro job, stesso seme (4242), stesso `cfg` (2,4),
stesso testo, stessa trascrizione: l'unica variabile era quale clip stesse
su quale canale. Similarità di speaker con embedding ECAPA-TDNN, coseno.

| take | riferimento | prefisso | vs riferimento | vs prefisso |
|---|---|---|---|---|
| `T_A` | Tommaso | Andrea | **0,640** | **0,925** |
| `A_T` | Andrea | Tommaso | **0,712** | **0,928** |

Scala della metrica, misurata sugli stessi campioni: **pavimento 0,707**
(Tommaso contro Andrea, due voci diverse), **soffitto 0,92** (una voce col
proprio clone). Gli incroci non stanno nel mezzo: atterrano esattamente sul
soffitto del prefisso. `T_A` somiglia ad Andrea quanto Andrea somiglia a sé
stesso, e contro Tommaso fa 0,640 — *sotto il pavimento*.

La f0 concorda: `T_A` 122,8 Hz, identica ad `A_A` (Andrea), contro i 137 Hz
di Tommaso. Nemmeno l'andatura si separa: 11,04 s per `A_A`, `T_A` e `A_T`,
11,36 s per `T_T`, a parità di testo. Ascolto umano il 2026-08-28: `T_A` e
`A_A` sono la stessa persona.

**Conclusione.** Il prefisso porta tutto — identità e carattere insieme — e
il riferimento non lo corregge. Non esiste un canale «come» da incrociare.
Due conseguenze:

1. La bidirezionalità simmetrica resta **fuori portata a runtime**. D7 e
   §5.3 restano come sono. Ottenere «Tommaso lento da audiolibro» richiede
   di generarlo come campione: un asse in più nella generazione del
   catalogo, progetto a sé e fuori perimetro (§4).
2. Per «La mia voce», il campione dell'utente **deve** stare su
   `prompt_wav` con la trascrizione esatta. Vedi §7.4: rafforza D2 invece
   di metterla in discussione.

Limiti dichiarati: un seme, un testo, una coppia di voci, entrambe maschili
e vicine di timbro (137 contro 125 Hz). Lo scarto è però di 0,28, sopra il
soffitto da un lato e sotto il pavimento dall'altro: non è un margine che si
ribalta allargando il campione. Il ramo «stesso seme, descrizione diversa»
non è stato provato perché è il worker stesso a escluderlo: senza
riferimento il modello inventa una voce diversa a ogni chiamata.

### 15.2 Anteprima una tantum della voce clonata

L'utente verifica il materiale registrato, non la resa della sintesi. Si
potrebbe generare **una sola volta**, alla registrazione della voce, un
campione breve con una frase fissa, salvarlo e riusarlo per sempre: si paga un
boot una volta nella vita della voce, non a ogni cambio di impostazione.
Escluso da questa iterazione per scelta esplicita; resta la via più naturale
se emergesse che gli utenti si aspettano di sentirsi *sintetizzati* prima di
lanciare un libro.

### 15.3 Valori di listino

`ABM_VOXCPM_RATE_EUR_PER_MCHAR` e `ABM_VOXCPM_MIN_COST_EUR` non sono fissati.
Il costo reale è ~$0,91/Mchar contro gli $11,18 di Speechify: c'è spazio per
posizionare VoxCPM come la voce premium economica, ma è una decisione
commerciale.

### 15.4 Traffico dei chunk

Con D9 l'audio grezzo a 48 kHz transita da R2 al server prima
dell'assemblaggio. R2 è già nel percorso, ma il volume per libro va misurato
sul primo libro vero: se pesa, la compressione dei chunk in transito è
l'ottimizzazione ovvia, e non cambia il design.

### 15.5 Cadenza di aggiornamento del catalogo

La divergenza fra `manifest.csv` e `voices.json` è rientrata: al 2026-08-28
sono 361 righe contro 361 voci. La sorgente per l'app resta comunque
`voices.json` soltanto.

Quello che resta aperto è **procedurale, non tecnico**: con quale cadenza e
con quale comando la cartella `data/voci_inventate/` viene ri-importata dal
repo del worker ad `AudioBook-Maker`, e chi decide che un lotto di voci
nuove è pronto per la produzione. Per D10 questo non blocca
l'implementazione: il codice regge qualsiasi contenuto del file.
