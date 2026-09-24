# Activity log su DB relazionale — programma e fase 1 (facciata `activity_log.py`)

**Data:** 2026-09-24
**Branch:** `worktree-activity-db` (worktree `.claude/worktrees/activity-db`, base `main` 18a67a9 v3.69.0)
**Stato:** design approvato in sessione; fase 1 pronta per il piano di implementazione
**Sostituisce:** `docs/superpowers/specs/2026-07-02-abm-db-design.md` sul branch `ABM_DB` (mai mergiato,
675 commit indietro, `db.py` incompatibile con quello oggi in `main`). Da `ABM_DB` si possono
riprendere idee e test del backfill, non il codice.

## Problema

Il business log `activity_YYYY-MM.log` e' un file di testo mensile in `SCRIPT_DIR`
(`/opt/audiobook-maker`, **non** `ABM_DATA_DIR`), scritto da `_log_activity` e letto per scansione
completa da 8 punti del codice.

- **Crescita:** 1,4 MB (aprile) → 4,9 → 7,0 → 9,95 → 14,05 MB (agosto 2026, 85k righe), circa +40%/mese.
  Oltre il 55% delle righe sono `ANALYZE`, `GENERATE`, `COMPLETE`.
- **Costo di lettura:** ogni lettore riparsa l'intero mese: pannello admin a ogni apertura,
  `user_stats` circa 1 s per mese (con cache ad hoc su mtime/size), statistiche community ogni
  60 s/5 min, recovery su N mesi, digest dei power user, export.
- **RAM:** il set di dedup `_logged_sids_ops` cresce per tutto il mese e si ricostruisce da file a ogni avvio.
- **Posizione:** fuori dal tiering R2 e dai backup; va spostato a mano nelle migrazioni del server.
- **Due parser indipendenti:** `audiobook_app` (split per campi) e `user_stats.split_line` (split ancorato).

## Programma in 4 fasi

Ogni fase si rilascia da sola. Questa spec dettaglia la **fase 1**; le fasi 2–4 sono direzione e
punti di decisione, e avranno piano (e dove serve spec) propri.

| Fase | Contenuto | Comportamento in prod |
|---|---|---|
| 1 | Modulo foglia `activity_log.py`; tutti i lettori/scrittori passano da li'; correzioni C1–C3 | invariato salvo C1–C3 |
| 2 | `activity.db` (SQLite) in doppia scrittura, backfill, verifica di parita', spostamento in `ABM_DATA_DIR` | flag `ABM_ACTIVITY_DB` |
| 3 | Lettori sul DB; dedup via indice UNIQUE | letture indicizzate |
| 4 | File di testo: gzip e archivio su R2 a mese chiuso; retention del DB | — |

## Fase 1 — Design

### Approccio

Scelto l'approccio **A**: modulo foglia con API pubblica orientata alle query. Scartato **B**
(interfaccia `Backend` astratta gia' ora): con un solo implementatore l'interfaccia verrebbe
modellata sul file di testo (sessioni come ciclo Python vs `GROUP BY`, dedup come set vs `UNIQUE`),
e la fase 2 non ha due backend simmetrici ma un fan-out in scrittura piu' uno switch in lettura.
Le funzioni pubbliche di `activity_log.py` sono gia' l'interfaccia; il backend interno arriva in
fase 2 dietro di esse. Il vantaggio di B (test di contratto) si ottiene scrivendo i test della
fase 1 contro l'API pubblica, da parametrizzare in fase 2.
Scartato **C** (estrazione del solo parser): lascerebbe gli 8 lettori sparsi da toccare di nuovo in fase 3.

### Modulo `activity_log.py`

Modulo foglia, sola stdlib, nessun import dal progetto (convenzione 2 di CLAUDE.md).

```python
configure(log_dir)            # callable -> Path, risolta a ogni chiamata
```

`audiobook_app` lo configura all'avvio con `configure(log_dir=lambda: SCRIPT_DIR)`. La callable
risolta a ogni chiamata mantiene funzionanti i 22 file di test che fanno
`patch.object(audiobook_app, "SCRIPT_DIR", tmp)`. In fase 2 puntera' a `ABM_DATA_DIR`.

**Tipo dati**

```python
class Row(NamedTuple):
    job_id: str; ts: str; filename: str; op: str; client_id: str
    ip: str; voice: str; lang: str; platform: str
```

Stessi 9 campi e stesso ordine del formato su disco, che non cambia:
`<job_id> # <ts> # "<file>" # <op> # <cid> # <ip> # <voice> # <lang> # <platform>`.

**Scrittura**

- `log(job_id, filename, op, client_id="", ip="", voice="", lang="", platform="", epoch=None) -> None`
  — semantica di `_log_activity`. `_log_activity` resta come passaggio verso `log()` (firma
  invariata: `generation_engine` continua a riceverla via `configure()`).
- `init_dedup() -> None` — ricostruisce il set dal file del mese corrente; sostituisce `_init_log_dedup`.

**Parsing**

- `split_line(line) -> Row | None` — spostata da `user_stats` (split ancorato: 2 campi a sinistra,
  6 a destra, `#` tollerato nel titolo, righe storiche corte completate a destra). `user_stats`
  la reimporta per compatibilita'.

**Lettura**

- `months() -> list[str]` — mesi `YYYY-MM` disponibili, dal piu' recente; solo nomi validi.
- `month_rows(ym) -> Iterator[Row]`.
- `iter_rows(since, until=None, ops=None) -> Iterator[Row]` — attraversa i mesi coperti
  dall'intervallo `[since, until)`, filtra per `ops` (insieme di nomi esatti).
- `fingerprint(ym) -> tuple | None` — firma per invalidare le cache: oggi `(mtime, size)` del
  file, in fase 3 `max(id)` del DB. `None` se il mese non esiste.
- `delivered_ids(months=3) -> {"complete": set, "opt_complete": set}` — sostituisce
  `_delivered_job_ids`, con la stessa cache di 300 s.

**Fuori dal modulo:** le aggregazioni di dominio restano dove sono ma consumano `Row`:
`_parse_log_sessions` (pannello admin, export), `user_stats.parse_sessions`/`analyze`/`power_users`,
statistiche community.

**Fuori perimetro fase 1:** `scripts/migration/migration_recover_prep.py`, `backup_ABM.sh`,
`restore_ABM.sh` (autonomi, formato e posizione invariati); `FORENSICS_PLAYBOOK.md`.

### Cambi di comportamento dichiarati

La fase 1 e' un refactor. Uniche eccezioni, ciascuna con test dedicato:

- **C1 — Gli eventi con `job_id` vuoto non si deduplicano mai.** Oggi la chiave
  `("", "VOUCHER_ATTEMPT")` scarta in silenzio, nello stesso processo, ogni tentativo voucher
  successivo al primo; idem per `ADMIN_VOUCHER_*`, `TTS_BACKEND_*`, `ADMIN_*`. Ad agosto 2026:
  11 `VOUCHER_ATTEMPT`, circa uno per riavvio. Volume atteso piccolo; `VOUCHER_ATTEMPT` e' gia'
  limitato per IP a monte (`VOUCHER_ATTEMPT_BLOCKED:rate_limit_*`).
- **C2 — `init_dedup()` usa `split_line`.** Oggi `line.strip().split(" # ")` sfasa i campi sulle
  righe con `job_id` vuoto (la riga inizia con `" # "`) o con `#` nel titolo, e le chiavi
  ricostruite non coincidono con quelle scritte.
- **C3 — Gli eventi `M4B_*` portano il `job_id`.** `generation_engine._log_m4b_progress` legge
  `job.get("job_id")`, chiave assente nel dict `jobs[job_id]`: ad agosto tutti i 20
  `M4B_START`/`M4B_END` hanno `job_id` vuoto e non esiste alcun `M4B_PROGRESS`. Senza C3, C1
  produrrebbe una riga `M4B_PROGRESS` ogni 10 s per job. Correzione: firma
  `_log_m4b_progress(job_id, job, event, **fields)` nei 6 chiamanti (tutti dentro
  `run_generation`, dove `job_id` e' in scope); `M4B_PROGRESS` resta
  deduplicato per `(job_id, op)` come ogni evento con job. La copia
  `audiobook_app._log_m4b_progress`, senza chiamanti fuori dai test, viene rimossa;
  `test_m4b_progress.py` passa alla versione di `generation_engine`.

### Errori e concorrenza

- `log()` non solleva mai; su `OSError` la chiave non entra nel set (un nuovo tentativo riscrive).
- I lettori tollerano file assenti (iteratore vuoto) e righe malformate (`split_line` → `None`).
  Tutti aprono con `errors="replace"` (oggi `_parse_log_sessions` e `_parse_activity_lines` no:
  un byte non UTF-8 rompe il pannello admin).
- Un solo lock di modulo per scrittura e dedup (come `_log_lock`); azzeramento del set al cambio
  di mese invariato. I lettori non prendono il lock: l'append di una riga sotto i 4 KB e' atomico
  su Linux.

### Migrazione dei punti di chiamata

Un commit per punto, suite verde a ogni passo.

| # | Punto | Dopo |
|---|---|---|
| 1 | nuovo `activity_log.py` + test di contratto | — |
| 2 | `_log_activity`, `_init_log_dedup` (+ C1, C2) | passaggio verso `log()` / `init_dedup()` |
| 3 | `_log_m4b_progress` (C3) + rimozione della copia morta | `job_id` esplicito |
| 4 | `_delivered_job_ids` | `delivered_ids()` |
| 5 | `_parse_activity_lines` → `_stats_today_count`, `_stats_month_by_lang` | `iter_rows(since, ops={"COMPLETE","OPT_COMPLETE"})` |
| 6 | `_parse_log_sessions` (pannello admin + export) | `month_rows(ym)` |
| 7 | `user_stats.parse_sessions`/`analyze`/`power_users`, `api_admin_user_stats`, `_power_users_data` | righe + `ym`; cache con chiave `fingerprint(ym)` |
| 8 | navigazione mesi del pannello admin | `months()` |

Criterio di chiusura: in `audiobook_app.py` e `user_stats.py` nessun percorso `activity_*.log`
residuo (restano solo nomi di operazioni e commenti).

### Test

**Contratto** (`test/test_activity_log.py`, contro l'API pubblica, da parametrizzare in fase 2):

- andata e ritorno `log()` → `month_rows()`, anche con `#` nel titolo e `platform` vuoto;
- dedup: `(job_id, op)` scritto una volta; `epoch` diverse → due righe; `job_id` vuoto mai
  deduplicato (C1); `init_dedup()` su file preesistente con righe a `job_id` vuoto e `#` nel
  titolo → chiavi coincidenti (C2);
- `iter_rows`: attraversa due mesi, filtra per `ops` e intervallo, esclude le righe fuori intervallo;
- `delivered_ids` su N mesi, con cache;
- `months()` ordinati e limitati ai nomi validi; `fingerprint` cambia dopo un `log()`;
- file assente, righe malformate, byte non UTF-8: nessuna eccezione.

**C3:** gli eventi `M4B_*` scritti da `generation_engine` portano il `job_id` del job.

**Equivalenza:** su una copia dei log reali (aprile–settembre 2026), uscite identiche prima e
dopo per `_parse_log_sessions`, `user_stats.analyze`, `power_users` e statistiche community.
Script temporaneo nello scratchpad, non nel repo.

**Regressione:** restano verdi `test_log_activity_regen_dedup`, `test_activity_platform`,
`test_admin_logactivity_filters`, `test_power_users_digest`, `test_cold_download_log`,
`test_orphan_delivered_no_refund`; cambia solo la firma di `_log_m4b_progress` in
`test_m4b_progress` e `test_regression_double_module`. Baseline di
`main` 18a67a9: 3908 passati, 25 falliti preesistenti ed estranei (`abuse_judge`,
`voice_clone_replica`, `voxcpm_runpod`, `tts_backend_probe_state`, `admin_voice_xss`,
`audio_generation_tags`, `free_quota_generate_enforcement`): il numero non deve crescere.

## Fasi 2–4 — Direzione

### Fase 2 — `activity.db` in doppia scrittura

- File SQLite dedicato `activity.db` in `ABM_DATA_DIR`, **separato da `abm.db`**: `db.py` serializza
  tutto su un RLock di processo e il log (percorso caldo) non deve accodarsi alle transazioni account.
- Schema di partenza:

  ```sql
  events(id INTEGER PRIMARY KEY, ts INTEGER, job_id TEXT, op TEXT, op_arg TEXT,
         filename TEXT, client_id TEXT, ip TEXT, voice TEXT, detail TEXT,
         lang TEXT, platform TEXT, epoch INTEGER)
  INDEX (ts), (job_id), (op, ts), (client_id, ts)
  UNIQUE (job_id, op, IFNULL(epoch, -1)) WHERE job_id <> ''   -- regola C1
  ```

  `op_arg` separa i suffissi (`ADMIN_VOUCHER_CREATE:gift`); `detail` accoglie i payload oggi
  scritti in `voice` (`M4B_*`, e l'email di `ADMIN_VOUCHER_*`, cosi' isolata).
- Flag `ABM_ACTIVITY_DB=off|dual|db`: `dual` scrive su file e DB, legge dal file. Rollback senza deploy.
- Backfill idempotente dei mesi storici (idee e test da `ABM_DB/scripts/import_logs_to_db.py`);
  verifica di parita' dei conteggi per `op` e mese fra file e DB.
- Spostamento dei file da `SCRIPT_DIR` a `ABM_DATA_DIR`, con `backup_ABM.sh`, `restore_ABM.sh`,
  `migration_recover_prep.py` e `FORENSICS_PLAYBOOK.md` aggiornati insieme.
- Backup con `VACUUM INTO` o `sqlite3.backup`, mai copia del file con il WAL attivo.
- **Decisione:** scrittura sincrona con `busy_timeout` breve vs coda in memoria con thread di
  scrittura. Si decide misurando la latenza di `log()` in modo `dual`.

### Fase 3 — Lettori sul DB (`ABM_ACTIVITY_DB=db`)

- Cambia solo l'interno di `activity_log.py`: `iter_rows`/`month_rows` → `SELECT`; dedup →
  `INSERT OR IGNORE`, sparisce il set in RAM e la scansione all'avvio.
- Test di contratto della fase 1 parametrizzati su entrambi i backend.
- Opportunita': paginazione SQL del pannello admin; query trasversali fra mesi (ciclo di vita di
  job, client, IP); tabella `daily_rollup(day, op, lang, n)` per le statistiche community.

### Fase 4 — Destino del file di testo e retention

- Raccomandato: a mese chiuso gzip, copia su R2 (copy-before-delete, `docs/STORAGE_TIERING.md`),
  poi cancellazione locale. `scripts/activity_query.py` sostituisce il `grep` nelle indagini.
- Retention del DB: mesi oltre N esportati su R2, poi `DELETE` + `VACUUM` incrementale.
- **Decisione di business:** N mesi di retention; pseudonimizzazione di IP ed email dopo X mesi.

## Rischi

| Rischio | Mitigazione |
|---|---|
| Deploy su push a `main` senza gate ne' rollback | Fase 1 senza cambi di formato; fasi 2–3 dietro `ABM_ACTIVITY_DB` |
| Regressione sul percorso caldo di `log()` | `log()` non solleva mai; lock invariato; latenza misurata in fase 2 |
| Uscite dei lettori diverse dopo il refactor | Script di equivalenza sui log reali (fase 1) |
| C1 aumenta il volume di righe senza job | Volume misurato: decine/mese; C3 evita l'inondazione `M4B_PROGRESS` |
| Deriva fra file e DB in modo `dual` | Script di parita' per `op` e mese |
| Perdita del `grep` nelle indagini | File mantenuto fino alla fase 4; poi CLI di query e playbook aggiornato |
| Import circolari | `activity_log.py` foglia, configurato via `configure()` |
