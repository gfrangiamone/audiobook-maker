# Moderazione LLM dell'abuso della quota voci standard

Data: 2026-09-03
Stato: design approvato

> Sostituisce integralmente la versione precedente di questo file (strategia a
> corsia spot e multi-chiave, abbandonata dopo review): resta nella storia git,
> non è più il design di riferimento.

## Problema

La quota mensile di caratteri sulle voci standard (`free_tts_quota.py`, deployata
il 2026-09-01 con il commit `396534f`) non limita nulla. Due falle indipendenti,
entrambe misurate in produzione sul client `36e901e8-71d`:

1. **Il gate email è un click.** `QUOTA_GATE` non è un rifiuto: marca un job
   **accettato oltre quota**. Il modale frontend preriempie l'email da
   `localStorage.abm_v_email` e richiama `retryGeneration()` da solo: dalla
   seconda volta in poi il gate costa un click e ~2 secondi. Settembre 2026:
   **26 `QUOTA_BLOCK` → 26 `QUOTA_GATE`**, rapporto 1:1, nessun blocco effettivo.
   Contatore a **19.218.930 / 10.000.000** caratteri.
2. **La quota è per-cookie.** Un secondo cid `61991d18-e7c` è comparso dallo
   stesso IP **2 minuti e 20 secondi dopo** il primo `QUOTA_BLOCK`, con bucket
   azzerato. `_client_emails.json` mostra che i due cid hanno registrato due
   indirizzi distinti, su due provider gratuiti diversi: alla rotazione del
   cookie ha accompagnato un'email nuova, ripassando il gate da capo.

Impatto misurato: ~21M caratteri in 2,5 giorni contro un tetto di 10M/mese, 113
`GENERATE` su 2030 di tutto settembre (un client su 760 = 5,6% del traffico),
103 EPUB distinti, escalation da 2 a 47 libri/giorno, code in assembly fino a
506s, un job di 22.394s. Voce sempre `zh-CN-XiaoxiaoNeural` (standard,
gratuita): ricavo zero.

## Vincolo di progetto

Nessuna identità gratuita è difendibile: cookie, IP ed email gratuite sono tutti
rinnovabili in minuti, e questo utente lo ha dimostrato in 2'20". Qualunque
regola fissa per-identità è aggirabile per costruzione. L'obiettivo non è
impedire, è **rendere l'abuso poco redditizio** — e la valuta che un bot paga
davvero è il **lavoro accumulato**: se ogni rotazione di identità distrugge i job
del giorno, il throughput crolla.

Da qui la scelta di un **giudice, non una regola**: un LLM valuta il dossier
comportamentale del gruppo. L'atto di aggirare — la rotazione del cookie,
l'email nuova, il cambio di rete — diventa esso stesso una feature di abuso. Un
bot di massa non può più usare il suo strumento migliore senza innescare il
giudizio; resta aggirabile da un umano dedicato e paziente, e questo è il
compromesso dichiarato.

## Decisioni

| Aspetto | Scelta |
|---|---|
| Gruppo (dossier) | IP `/24` hashato (fallback: cid se IP assente). Raggruppa, non giudica |
| Granularità del verdetto | per **cid**: `scope=cids` (attore identificato) o `scope=group` (i cid sono lo stesso attore) |
| Dossier | feature aggregate per gruppo **con ripartizione per cid**, in `_abuse_dossiers.json`; nessun testo di libro |
| Segnali sospetti | S1 quota esaurita; S2 ≥2 cid distinti; S3 ≥5 `QUOTA_GATE`/24h; S4 ≥2,5M chars/24h |
| Trigger giudizio | ≥2 segnali distinti e nessun verdetto valido; **cid nuovo** in gruppo con verdetto `abuse` ⇒ rigiudizio |
| Giudice | DeepSeek, client riusato da `generation_engine` (pattern di `community_moderator`) |
| Kill automatica | solo `verdict=abuse` ∧ `confidence≥0.9` ∧ cid nello scope ∧ job senza pagamento incassato ∧ voce standard |
| Kill in corsa | flag `job["cancelled"]` esistente + marcatore `abuse_terminated`; terminale `cancelled` (mai `error`) |
| Job successivi | rifiuto 403 pre-claim con messaggio neutro, senza spiegare il perché |
| Work dir del job ucciso | **conservata** 24h (nessuno spostamento): il ripristino è un rilancio con riuso chunk |
| Digest | sezione «Casi di abuso» nel digest admin esistente (24h), con motivazioni |
| Fail-open | LLM giù o timeout = nessuna kill, caso nel digest come «non giudicato» |
| Privacy | al provider solo feature numeriche/categoriali; nessun IP, email o titolo in chiaro |

Fuori ambito: voci premium e traduzione libri (mai uccidere un pagante), pannello
admin dedicato (il digest + blocklist bastano; rimandabile).

## Architettura

### 1. `abuse_watch.py` — nuovo modulo foglia

Stdlib + JSON con lock, sul modello di `free_tts_quota`. Il giudizio LLM è una
funzione sincrona `judge(dossier)` che riceve il client dal `configure()` di
`audiobook_app`, come fa `community_moderator`.

API del modulo:

- `group_key(ip)` — `net:<sha256(ABM_IP_SALT + ip/24)[:16]>`; IP malformato o
  assente ⇒ `cid:<raw>`.
- `record_event(group, cid, kind, data)` — `kind` ∈ `{generate, quota_gate,
  quota_block, email}`. Aggiorna il dossier a due livelli: **per gruppo**
  (conteggi, chars cumulati, cid distinti, email distinte hashate, file distinti
  come hash del filename, distribuzione voci top 3, lingue, timestamps degli
  ultimi 20 eventi) e **per cid** (le stesse feature ristrette al singolo cid).
  Retention dossier: 60 giorni.
- `signals_for(group)` — booleani S1-S4 ricalcolati sul dossier. S4 è il segnale
  che la rotazione non elude: ruotare il cookie prima di esaurire la quota
  lascia intatti S1-S3, ma il volume del gruppo resta.
- `needs_judgement(group, cid)` — vero se ≥2 segnali distinti e nessun verdetto
  valido, **oppure** se `cid` non compare nello scope di un verdetto `abuse`
  valido (rotazione post-verdetto: il nuovo cid forza il rigiudizio — è la sola
  chiamata LLM extra che ogni rotazione costa).
- `set_verdict(group, verdict)` / `verdict_for(group)` — verdetto persistito:
  `{verdict, confidence, scope, cids, reason, ts}`. TTL
  `ABM_ABUSE_VERDICT_TTL_DAYS` (14); rivalutazione se gli eventi crescono del 25%
  post-verdetto. `verdict=clean` ⇒ nessuna kill, rigiudizio solo se compare un
  segnale nuovo.
- `is_blocked(group, cid)` — vero se esiste un verdetto `abuse` valido e `cid` è
  nello scope (`scope=group` ⇒ tutti i cid del dossier al momento del verdetto).
- `clear_verdict(group)` — usato dall'admin per il ripristino e dall'accensione
  (§Rollout).

**Prompt del giudice**, costruito solo con feature, mai con testo utente. Riceve
la ripartizione per cid e deve rispondere in JSON:
`{verdict: abuse|clean|inconclusive, confidence: 0-1, scope: cids|group,
cids: [...], reason: str}`. Istruzioni esplicite:

- conservatorismo — «in dubbio, `inconclusive`»;
- **marker di innocenza** enumerati: diversità di voci, lingue, orari ed email
  fra i cid è la firma di una rete condivisa (NAT domestico, CGNAT mobile), non
  di un attore singolo. Un `/24` mobile ospita migliaia di utenti: S2 e S4 vi
  scattano di routine e il giudice deve saperlo;
- `scope=group` solo se i cid condividono voce, lingua e pattern orario e le
  email compaiono a raffica dopo i blocchi; altrimenti `scope=cids` con i soli
  cid colpevoli.

Il criterio è volume e velocità, non le identità: 8 libri in un mese con due
cookie (cambio device) è innocuo; 103 file distinti in 2,5 giorni con due
cookie, due email e una voce sola no. Dossier compatto (1-3K token): costo per
gruppo nell'ordine dei millesimi di euro, una-due chiamate al giorno per
l'intera utenza sospetta, una in più per ogni rotazione.

### 2. `audiobook_app.py` — punti di aggancio

- **`/api/generate` pre-claim**: se `is_blocked(group, cid)` e il job non ha
  pagamento incassato né voce premium ⇒ `403` con
  `error_code: "job_terminated"` e `_log_activity(..., "QUOTA_ABUSE_BLOCK", ...)`.
  Il job resta in `analyzed`/`optimized` come gli altri rifiuti pre-claim.
- **Dopo `QUOTA_GATE`/`QUOTA_BLOCK` e dopo il claim del `GENERATE`**:
  `record_event(...)`, poi se `needs_judgement(group, cid)` si accoda il gruppo
  al worker di giudizio.
- **Worker di giudizio** in `_ensure_background_threads()`: coda interna a
  giudice singolo, timeout HTTP 20s + 1 retry. Su verdetto `abuse` valido, per
  ogni job del gruppo **in corso** con cid nello scope, senza pagamento e a voce
  standard: `job["abuse_terminated"]=True`, poi `job["cancelled"]=True`. Il
  resto lo fa la meccanica esistente: `_check_cancelled` (`generation_engine`)
  legge il flag prima del test `email_registered`, quindi ferma anche i job
  batch; il ramo `_CancelledError` esegue i refund (no-op su job non pagato) e
  chiude su terminale `cancelled`, che **non** storna la quota — `error` la
  stornerebbe (`_set_job_status`), e restituire i caratteri a chi viene ucciso
  per abuso riaprirebbe il bucket. `_log_activity(..., "QUOTA_ABUSE_KILL", ...)`.
- **Ramo `_CancelledError` di `run_generation`** — unica modifica in
  `generation_engine`: con `abuse_terminated` salta il `rmtree` della work_dir
  e posa `job["abuse_kept_until"]`. I `chunk_*.pcm` restano in posizione.
- **Progress SSE**: con `abuse_terminated` il payload riporta
  `error_code: "job_terminated"`, così il frontend distingue la kill dal cancel
  utente.
- **Digest admin** (24h, `ADMIN_DIGEST_INTERVAL_SEC`): nuova sezione — gruppo,
  segnali, verdetto, confidence, scope, reason, job uccisi in corsa, rifiuti 403
  nelle 24h, casi «non giudicati». Solo hash, mai IP o email in chiaro nel
  canale email. Se `ABM_ADMIN_EMAIL` è vuoto il kill automatico è disattivato
  (solo giudizio in log): nessuna azione distruttiva senza audit.
- **Cleanup loop**: rimuove le work_dir con `abuse_kept_until` scaduto
  (`ABM_ABUSE_KEEP_HOURS`, 24).
- **Ripristino** (`POST /admin/api/abuse/clear/<group>`, auth admin esistente):
  `clear_verdict(group)`. L'utente rilancia la generazione dal job in `analyzed`
  e il riuso dei chunk esistenti (v3.44.1) riparte da dove era. Nessun refund:
  il job non era pagato.

Il `403` non spiega mai il perché: il frontend mostra un messaggio neutro
(§3). Un messaggio esplicativo insegnerebbe al bot quali feature lo hanno
tradito.

### 3. Frontend

Gestione di `error_code === "job_terminated"` — sia nel `403` di `/api/generate`
sia nel payload del progress — accanto ai rami di errore esistenti, con chiave
i18n in `i18n_data.js` e nei 7 file `i18n/*.json`:

> «Elaborazione interrotta. Se pensi che sia un errore, contattaci.»

Nessun nome di provider, nessun riferimento alla quota o alla moderazione.

### 4. Quota e gate esistenti

Restano **invariati**: `free_tts_quota.py` non cambia, nessuna multi-chiave,
nessuna corsia spot. Il superamento della quota non è più l'ultima parola: è il
segnale S1 che, con un secondo segnale, apre il giudizio.

## Effetto atteso

Sul caso misurato: il secondo cid compare 2'20" dopo il primo blocco ⇒ S2
scatta lo stesso giorno del superamento della quota ⇒ il giudizio parte il primo
giorno dell'escalation. Da lì i job dei cid colpevoli vengono rifiutati. Per
continuare il bot deve cambiare IP — e rigenerare i job persi. Ogni rotazione
distrugge il lavoro accumulato: è il costo che la quota e i freni non riuscivano
a imporre.

Il giorno dopo, il digest consegna all'admin il gruppo e la motivazione: la
blocklist manuale resta la leva terminale per i casi che insistono.

Esenzione dichiarata: chi paga anche solo l'ottimizzazione AI (floor €1) è
esente da kill e 403. Coerente con «mai uccidere un pagante»; il prezzo
dell'esenzione è il floor, e un abuser che paga non è più a ricavo zero.

## Gestione errori

| Situazione | Comportamento |
|---|---|
| LLM giù, timeout o JSON malformato | fail-open: nessuna kill, caso nel digest come «non giudicato» |
| `confidence < 0.9` o `verdict=inconclusive` | nessuna kill, voce nel digest |
| Job con pagamento incassato o voce premium | mai ucciso, mai rifiutato |
| cid fuori dallo scope del verdetto | non toccato; se nuovo nel gruppo ⇒ rigiudizio |
| `ABM_ADMIN_EMAIL` vuoto | kill automatica disattivata, solo giudizio in log |
| `_abuse_dossiers.json` corrotto | fail-open, il dossier riparte da zero |
| IP assente | gruppo `cid:`, nessun errore |
| Work dir già rimossa alla kill | nessun errore, `abuse_kept_until` non posato |

## Test

Nuovi file in `test/`:

- `test_abuse_watch.py` — dossier a due livelli (gruppo e cid), `distinct_files`,
  segnali S1-S4, trigger al secondo segnale e non al primo; verdetto
  persistito, TTL e rivalutazione; `scope=cids` vs `scope=group` in
  `is_blocked`; cid nuovo ⇒ `needs_judgement`; `clean` senza kill;
  `clear_verdict`.
- `test_abuse_generate_enforcement.py` — 403 `job_terminated` solo con cid nello
  scope di un verdetto `abuse` valido; mai su job pagato/premium; fail-open con
  dossier corrotto; kill in corsa: flag posati, terminale `cancelled`, **quota
  non stornata**, work_dir conservata con `abuse_kept_until`; progress con
  `job_terminated`; cleanup rimuove la work_dir scaduta.
- `test_abuse_judge.py` — prompt costruito solo da feature (nessun testo
  utente, nessuna email o IP in chiaro), parsing del verdetto JSON con `scope`,
  fail-open su risposta malformata, kill disattivata con `ABM_ADMIN_EMAIL` vuoto
  o `ABM_ABUSE_KILL_ENABLE=0`.

I test esistenti della quota (`test_free_tts_quota*.py`,
`test_free_quota_*.py`) e del cancel (`test_cancel_endpoint_lock.py`) devono
passare **invariati**.

## Rollout

1. **Osservazione** — deploy con `ABM_ABUSE_KILL_ENABLE=0`: i dossier si
   popolano, i giudizi girano e finiscono in log e digest, nessuna kill né 403.
   In questa fase il TTL dei verdetti è forzato a 1 giorno: un prompt tarato
   male non lascia verdetti validi due settimane.
2. **Accensione** — `ABM_ABUSE_KILL_ENABLE=1` dopo aver letto i digest e
   verificato che nessun `abuse` colpisca client legittimi. All'accensione i
   verdetti maturati in osservazione vengono **azzerati** (`clear_verdict` su
   tutti al primo avvio con `1`): le kill partono solo da giudizi emessi con il
   prompt definitivo.
3. **Blocklist** — resta la leva manuale per i gruppi confermati dal digest.

## File toccati

`abuse_watch.py` (nuovo), `audiobook_app.py`, `generation_engine.py` (solo il
ramo `_CancelledError`), `email_service.py`, `user_stats.py` (op di log nei
pannelli), `static/js/app.js`, `templates/_fragments/i18n_data.js`,
`i18n/*.json`, `md_files/PARAMETRI_CONFIGURAZIONE.md`, più i tre nuovi file di
test.

## Nuove variabili d'ambiente

| Variabile | Descrizione | Default |
|---|---|---|
| `ABM_ABUSE_KILL_ENABLE` | Interruttore di kill e 403 (0 = solo giudizio in log e digest) | `0` |
| `ABM_ABUSE_LLM_CONFIDENCE` | Soglia minima di confidenza per la kill | `0.9` |
| `ABM_ABUSE_KEEP_HOURS` | Conservazione della work_dir dei job uccisi, per il ripristino | `24` |
| `ABM_ABUSE_GATE_DAILY` | Soglia `QUOTA_GATE`/24h per il segnale S3 | `5` |
| `ABM_ABUSE_CHARS_DAILY` | Soglia caratteri/24h per il segnale S4 (quota/4) | `2500000` |
| `ABM_ABUSE_VERDICT_TTL_DAYS` | Validità del verdetto persistito (1 in osservazione) | `14` |
