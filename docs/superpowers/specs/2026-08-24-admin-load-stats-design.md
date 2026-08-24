# Pannello Stats admin — telemetria di carico

Data: 2026-08-24
Stato: design approvato, pronto per il piano di implementazione
Ambito: `/admin/log-activity` → modale `📊 Stats`

## 1. Problema

Il modale `Stats` mostra oggi la distribuzione oraria dei job per lingua TTS
(`audiobook_app.py:4137-4295`). È un dato di business già leggibile altrove
nella pagina e non dice nulla su come si comporta la macchina sotto carico.

Nessuna delle metriche che servono a valutare il carico è oggi persistita:

| Metrica | Fonte attuale | Persistita |
|---|---|---|
| Job in elaborazione (free/premium) | `jobs{}` in RAM, `status == "generating"` | no |
| Job rifiutati per carico massimo | `_server_busy_response` → `print()` (`audiobook_app.py:887`) | no, solo stdout |
| Job in fase ffmpeg | `assembly_queue.stats()` | no |
| Attesa coda ffmpeg | `Slot.waited_sec` → `print()` (`assembly_queue.py:255`) | no |
| RAM / swap | `_log_memory_stats()` (`audiobook_app.py:15288`), ogni 300 s → stdout | no, tranne il WARN → `MEMORY_PRESSURE` in activity log |
| CPU, iowait, load | — | mai campionata |
| Disco | — | mai campionato |

L'activity log (`activity_YYYY-MM.log`) è un log di **eventi di business**,
deduplicato per `(job_id, operazione)`: non può reggere serie temporali di
carico. Serve una sorgente dati nuova.

Il costo di questa cecità è documentato: freeze da esaurimento RAM+swap del
2026-08-21, disco al 100 % per il `_cleanup_loop` morto (17 h di invisibilità),
disco al 100 % per lo zip runaway da 28,5 GB. In tutti e tre i casi il segnale
esisteva ma non era registrato da nessuna parte.

## 2. Obiettivo

Sostituire il contenuto del modale `Stats` con un pannello di carico che, per
una finestra temporale selezionabile fra **24 ore / 7 giorni / 28 giorni / mese
corrente** (default 24 ore), mostri picchi e medie di carico distinguendo i job
**free** dai **premium**, più le metriche di salute della macchina.

Non obiettivi: alerting, notifiche, esportazione, dashboard esterne
(Prometheus/Grafana), storico retroattivo.

## 3. Vincolo accettato: nessun dato retroattivo

La raccolta parte al deploy. Al giorno 1 solo la finestra 24 h è significativa;
7 g dopo una settimana, 28 g e mese dopo un mese. Nessun backfill: le uniche
fonti retroattive (activity log, journald) coprono una frazione delle metriche
e introdurrebbero un parser usa-e-getta. Il pannello dichiara esplicitamente la
copertura parziale.

## 4. Architettura

Tre componenti nuovi più cinque punti di aggancio nel codice esistente.

```
   [ punti di aggancio ]                [ campionatore ]
   /api/generate (reject)                 thread 30 s
   assembly slot (wait/timeout)      legge /proc, jobs{}, assembly_queue
   fine run_generation (esito)                 |
   startup / cleanup supervisor                |
                \                              /
                 v                            v
              load_metrics.py  (modulo foglia, in-memory + flush)
                            |
                            v
        ABM_DATA_DIR/load_metrics_YYYY-MM.jsonl   (bucket 5 min)
                            |
                            v
        GET /api/admin/load_stats?window=...   (aggregazione)
                            |
                            v
              modale Stats  (card + timeline)
```

### 4.1 `load_metrics.py` — modulo foglia

Nuovo modulo, **nessun import di progetto** (regola anti-import-circolare,
CLAUDE.md §1), stesso stile di `assembly_queue.py`. Il nome `metrics_store.py`
è già occupato dal funnel app→web e resta invariato.

API pubblica:

| Funzione | Ruolo |
|---|---|
| `sample(**gauges)` | registra i valori istantanei nel bucket corrente; per ogni gauge tiene `min`, `max`, somma e conteggio |
| `incr(counter, n=1)` | incrementa un contatore del bucket corrente |
| `observe(hist_name, seconds, premium=False)` | inserisce una durata nell'istogramma a bin logaritmici, ramo free o premium |
| `flush()` | chiude e scrive su file i bucket il cui intervallo è concluso |
| `query(window)` | aggrega i bucket della finestra e restituisce il dizionario di risposta dell'API |
| `purge(max_months=4)` | cancella i file mensili oltre la retention |
| `configure(data_dir)` | inietta la directory dati allo startup |

Stato interno protetto da un unico `threading.Lock`. Tutte le funzioni di
scrittura sono best-effort: un errore non deve mai propagarsi al chiamante (il
punto di aggancio più caldo è dentro `run_generation`).

**Bin degli istogrammi** (8, logaritmici, condivisi da tutte le durate):

```
< 10 s | 10-30 s | 30-60 s | 1-2 min | 2-5 min | 5-10 min | 10-20 min | > 20 min
```

I percentili si ricavano per interpolazione lineare dentro il bin che contiene
il rango cercato — approccio standard degli histogram Prometheus. L'errore è
dell'ordine dell'ampiezza del bin: irrilevante per decidere se la coda ffmpeg
è sana, e l'alternativa (conservare i campioni grezzi) costerebbe un ordine di
grandezza in spazio.

### 4.2 Campionatore

Thread dedicato `_load_metrics_sampler`, avviato in `_ensure_background_threads()`
accanto agli altri, con lo stesso pattern supervisor di `_cleanup_supervisor`
(`audiobook_app.py:15379`): loop `try/except` che si riavvia su qualunque
eccezione.

**Perché un thread proprio e non un innesto nel `_cleanup_loop`**: il cleanup
fa lavoro pesante e a cadenza variabile (scan del disco, eviction, offload), e
soprattutto è già morto una volta in produzione. Una telemetria che muore
insieme al componente che dovrebbe sorvegliare non serve a niente.

Passo: **30 s**. Ogni giro raccoglie:

| Gauge | Sorgente | Note |
|---|---|---|
| `gen`, `gen_p` | `jobs{}` sotto `_jobs_lock`, `status == "generating"` | `_p` = premium |
| `jobs` | `len(jobs)` | job vivi in RAM |
| `asm_h`, `asm_q`, `asm_qp` | `assembly_queue.stats()` | slot occupati, in coda, in coda premium |
| `ram` | `/proc/meminfo` → `100 - MemAvailable/MemTotal` | % occupata |
| `swap` | `/proc/meminfo` | % usata |
| `rss` | `/proc/self/status` → `VmRSS` | MB |
| `threads` | `/proc/self/status` → `Threads` | |
| `cpu`, `iowait` | delta di `/proc/stat` fra due campioni | % |
| `load` | `/proc/loadavg` diviso `os.cpu_count()` | load per core |
| `disk` | `shutil.disk_usage(ABM_DATA_DIR)` | % occupata + GB liberi |
| `hb` | età in secondi dell'heartbeat del `_cleanup_loop` | vedi 4.4 |

Fuori da Linux (`/proc` assente — l'ambiente di sviluppo Windows) le metriche
di macchina vengono semplicemente omesse dal campione: il modulo continua a
raccogliere job, code e contatori, e i test girano senza `/proc`.

Il campionatore chiama `flush()` a ogni giro e `purge()` una volta al giorno.

### 4.3 Punti di aggancio

| # | Dove | Chiamata |
|---|---|---|
| 1 | `_server_busy_response()` (`audiobook_app.py:887`) e il claim atomico in `/api/generate` (`audiobook_app.py:9657-9671`) | `incr("rej_busy")` o `incr("rej_busy_p")` secondo la classe del job |
| 2 | `generation_engine._acquire_assembly_slot()` (`generation_engine.py:3973`) | `observe("asm_wait", slot.waited_sec, premium)`; se `slot.timed_out` anche `incr("asm_timeout")` |
| 3 | rilascio dello slot di assembly | `observe("enc", durata_held)` — durata dell'encode, separata dall'attesa |
| 4 | chiusura di `run_generation` (successo, errore, cancellazione) | `observe("job", durata_totale, premium)`, `incr("done"/"err"/"cancel")`, `incr("chunk_fail", n)` |
| 5 | startup e `_cleanup_supervisor` | `incr("boot")`, `incr("cl_restart")` |
| 6 | ramo WARN di `_log_memory_stats()` (`audiobook_app.py:15321`) | `incr("memp")`, accanto all'evento `MEMORY_PRESSURE` gia' scritto in activity log |

La classe **premium** riusa `generation_engine._assembly_priority` — già la
definizione operativa nel sistema (voce Gemini/Speechify, oppure pagamento
incassato) — promossa a funzione pubblica `is_premium_job(job) -> bool`, con
`_assembly_priority` che la richiama. Una sola definizione, nessuna deriva.

### 4.4 Heartbeat del cleanup loop

`_cleanup_loop` aggiorna un timestamp globale a ogni giro completato. Il
campionatore registra `hb = now - ultimo_giro` come gauge: il suo **massimo**
nella finestra dice se il cleanup ha smesso di girare, che è esattamente il
segnale mancato per 17 ore nell'incidente del 2026-06-15.

## 5. Formato dati

File mensile `ABM_DATA_DIR/load_metrics_YYYY-MM.jsonl`, una riga JSON per
bucket chiuso di **5 minuti**, in append.

```json
{"t":1756000000,"n":10,
 "g":{"gen":[0,3,1.4],"gen_p":[0,2,0.8],"jobs":[5,12,8.1],
      "asm_h":[0,2,0.6],"asm_q":[0,5,1.1],"asm_qp":[0,2,0.3],
      "ram":[41,88,63.2],"swap":[0,12,2.1],"rss":[380,520,455],"threads":[22,31,25.0],
      "cpu":[3,97,44.0],"iowait":[0,31,4.2],"load":[0.2,3.8,1.1],
      "disk":[44,44,44.0],"disk_free_gb":[12.1,12.4,12.2],"hb":[0,35,12.0]},
 "c":{"rej_busy":2,"rej_busy_p":0,"asm_timeout":0,"boot":0,"cl_restart":0,
      "memp":0,"done":4,"done_p":1,"err":0,"err_p":0,"cancel":1,"chunk_fail":3},
 "h":{"asm_wait":[4,2,1,0,0,0,0,0],"asm_wait_p":[3,0,0,0,0,0,0,0],
      "enc":[1,3,2,0,0,0,0,0],"job":[0,0,1,2,1,0,0,0],"job_p":[0,0,0,1,0,0,0,0]}}
```

- `t` — epoch di inizio bucket, allineato a multipli di 300 s
- `n` — numero di campioni confluiti (10 attesi a 30 s di passo; meno se il
  processo è ripartito a metà bucket)
- `g` — gauge come `[min, max, media]`
- `c` — contatori sommati nel bucket
- `h` — istogrammi, 8 bin

Dimensione: ~600 byte per riga, 288 righe al giorno, **~5 MB al mese**.
Retention 4 mesi (copre la finestra 28 giorni più il mese corrente con
margine), purge nel campionatore.

Il file è testo per riga: durante un incidente è ispezionabile con `tail` e
`grep` direttamente sul server, coerentemente con `docs/FORENSICS_PLAYBOOK.md`.

**Perdita su restart**: il bucket in corso vive in RAM, quindi un riavvio
perde al massimo 5 minuti di campioni. Accettabile, e il riavvio stesso è
registrato dal contatore `boot` del bucket successivo.

**Perché non SQLite**: il progetto è dichiaratamente senza database (CLAUDE.md,
Architecture). Introdurne uno per una serie temporale da 5 MB al mese
aggiungerebbe un motore di persistenza, un file binario non ispezionabile a
mano durante un incidente, e un percorso di migrazione — a fronte di query che
su JSONL costano meno di 100 ms su 8.000 righe.

## 6. API

`GET /api/admin/load_stats?window=24h|7d|28d|month`

Protetta da `_admin_auth_ok(token)` come le altre route admin: 404 se
`ABM_ADMIN_TOKEN` è vuoto, come da convenzione esistente.

Risposta:

```json
{
  "meta": {"window":"24h","from":1755900000,"to":1755986400,
           "buckets":288,"coverage_pct":100,"first_sample_ts":1755100000},
  "job":  {...}, "ffmpeg": {...}, "machine": {...},
  "quality": {...}, "reliability": {...},
  "timeline": [{"t":...,"gen":2,"gen_p":1,"ram":71,"rej":0}, ...]
}
```

Metriche per sezione:

| Sezione | Contenuto |
|---|---|
| **job** | in elaborazione picco e media, free e premium separati · completati (free/premium) · rifiutati per carico massimo (free/premium) · % di tempo passato al tetto `ABM_MAX_CONCURRENT_GLOBAL` |
| **ffmpeg** | in assembly picco e media · attesa in coda media, p50, p95, free e premium separati · durata encode p50/p95 · timeout della coda · % di tempo con tutti gli slot occupati |
| **machine** | RAM picco e media % · swap picco % · RSS picco e media + trend MB/giorno (regressione lineare sulle medie dei bucket) · CPU picco e media % · iowait picco % · load per core picco · thread del processo picco · disco massimo % e GB liberi minimi |
| **quality** | durata job p50/p95 free vs premium · tasso di errore % · cancellazioni · chunk TTS falliti |
| **reliability** | restart del processo · restart del cleanup supervisor · età massima heartbeat cleanup · eventi `MEMORY_PRESSURE` |
| **timeline** | serie già ricampionata alla risoluzione della finestra (vedi 7) |

Il calcolo di `% di tempo in saturazione` usa il rapporto fra i bucket in cui
il massimo di `gen` ha toccato il tetto e il totale dei bucket della finestra:
è una stima al bucket, dichiarata come tale nel tooltip.

Le finestre `24h`, `7d`, `28d` sono scorrevoli a partire da adesso; `month` va
dal primo del mese corrente a ora. Una finestra a cavallo di due mesi legge due
file e concatena.

## 7. Interfaccia

Il modale `Stats` perde il grafico di distribuzione oraria per lingua e diventa:

1. **Selettore di finestra**: pulsanti `[24h] [7 giorni] [28 giorni] [Mese corrente]`,
   **24h preselezionato**. Il click fa il fetch on-demand dell'endpoint con
   uno spinner; l'apertura del modale non appesantisce il caricamento della
   pagina. Un pulsante di refresh ricarica la finestra corrente.
2. **Griglia di card**, raggruppate nelle cinque sezioni. Ogni card: valore
   principale in evidenza, picco e media sotto, badge `FREE` / `PREMIUM` dove
   la distinzione esiste. Colorazione a soglia (verde / ambra / rosso) su RAM,
   swap, disco, saturazione, timeout coda, età heartbeat.
3. **Timeline** della finestra selezionata: barre impilate free/premium del
   picco di job concorrenti per intervallo, linea sovrapposta del picco RAM %,
   marcatori rossi negli intervalli con rifiuti per carico.

   | Finestra | Intervallo | Barre |
   |---|---|---|
   | 24 h | 30 min | 48 |
   | 7 g | 4 h | 42 |
   | 28 g | 1 giorno | 28 |
   | Mese | 1 giorno | 28-31 |

4. **Banner di copertura**: `dati parziali — raccolta iniziata il <data>`,
   mostrato finché `coverage_pct < 100`.

Stile coerente con la pagina esistente (variabili CSS `--surface`, `--accent`,
`--green`, `--orange`, `--border` già definite); nessuna libreria esterna,
grafico in div come l'attuale.

L'etichetta del pulsante resta `📊 Stats`; il titolo del modale diventa
`📊 Carico sistema`.

## 8. Configurazione

Nuove variabili, tutte con default operativi sensati e da riportare in
`PARAMETRI_CONFIGURAZIONE.md`:

| Variabile | Descrizione | Default |
|---|---|---|
| `ABM_LOAD_METRICS_ENABLED` | abilita campionatore e pannello | `true` |
| `ABM_LOAD_METRICS_SAMPLE_SEC` | passo di campionamento | `30` |
| `ABM_LOAD_METRICS_BUCKET_SEC` | ampiezza del bucket | `300` |
| `ABM_LOAD_METRICS_RETENTION_MONTHS` | file mensili conservati | `4` |

## 9. Test

`test/test_load_metrics.py`, senza dipendenza da `/proc`:

- bucketing: campioni in bucket diversi non si mescolano; allineamento a 300 s
- aggregazione: `min`/`max`/media corrette su più bucket, gauge assenti in
  alcuni bucket non falsano la media
- istogrammi: percentili interpolati su casi noti, ramo free e premium separati
- finestra a cavallo di due file mensili
- retention: `purge()` elimina solo oltre soglia
- best-effort: `sample`/`incr`/`observe` non sollevano su directory non
  scrivibile
- degrado: assenza di `/proc` non impedisce la raccolta di job e contatori

`test/test_admin_load_stats.py`:

- 404 senza `ABM_ADMIN_TOKEN`, 401/redirect senza sessione admin valida
- risposta con storico vuoto: `coverage_pct = 0`, nessuna eccezione
- classificazione free/premium coerente con `is_premium_job`

## 10. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Il campionatore prende `_jobs_lock` ogni 30 s | una sola comprensione di lista sotto lock, come già fa `_log_memory_stats`; nessun I/O dentro il lock |
| Crescita non controllata dei file | bucket di dimensione fissa, retention a 4 mesi, purge giornaliero |
| Il thread del campionatore muore | pattern supervisor con riavvio, identico a `_cleanup_supervisor` |
| Un aggancio solleva dentro `run_generation` | tutte le chiamate a `load_metrics` sono racchiuse in `try/except` nel modulo stesso |
| Il pannello mostra dati fuorvianti finché la finestra non è coperta | banner di copertura esplicito con la data di inizio raccolta |
| Doppia definizione di "premium" | `is_premium_job()` unica, richiamata da `_assembly_priority` |

## 11. Fuori ambito

- Backfill retroattivo da activity log o journald
- Alerting o notifiche sulle soglie (il pannello è a consultazione)
- Esportazione delle metriche (Excel, Prometheus)
- Metriche per singolo job (già coperte dalle card dell'activity log)
