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
escalation da 2 a 47 libri/giorno, code in assembly fino a 506s, un job di
22.394s. Voce sempre `zh-CN-XiaoxiaoNeural` (standard, gratuita): ricavo zero.

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
| Identità | gruppo = IP `/24` hashato (fallback: cid se IP assente) — raggruppatore del dossier, non gate |
| Dossier | feature aggregate per gruppo in `_abuse_dossiers.json`, nessun testo di libro |
| Segnali sospetti | S1 quota esaurita; S2 ≥2 cid distinti; S3 ≥5 `QUOTA_GATE`/24h; S4 ≥2,5M chars/24h |
| Trigger giudizio | ≥2 segnali distinti nel dossier e nessun verdetto valido |
| Giudice | DeepSeek, client riusato da `generation_engine` (pattern di `community_moderator`) |
| Kill automatica | solo `verdict=abuse` ∧ `confidence≥0.9` ∧ job senza pagamento incassato ∧ voce standard |
| Kill in corsa | stop del thread (meccanica heartbeat esistente), status `error`, niente refund |
| Job successivi del gruppo | rifiuto 403 pre-claim con messaggio neutro, senza spiegare il perché |
| Quarantena | file del job in `data/quarantine/<job_id>/` per 24h, ripristino dall'admin |
| Digest | sezione «Casi di abuso» nel digest giornaliero esistente, con motivazioni |
| Fail-open | LLM giù o timeout = nessuna kill, caso nel digest come «non giudicato» |
| Privacy | al provider solo feature numeriche/categoriali; nessun IP, email o titolo in chiaro |

Fuori ambito: voci premium e traduzione libri (mai uccidere un pagante), pannello
admin dedicato (il digest + blocklist bastano; rimandabile).

## Architettura

### 1. `abuse_watch.py` — nuovo modulo foglia

Stdlib + JSON con lock, sul modello di `free_tts_quota`. Il giudizio LLM è una
funzione sincrona `judge(summary)` che riceve il client dal `configure()` di
`audiobook_app`, come fa `community_moderator`.

API del modulo:

- `group_key(ip)` — `net:<sha256(ABM_IP_SALT + ip/24)[:16]>`; IP malformato o
  assente ⇒ `cid:<raw>`.
- `record_event(group, kind, data)` — `kind` ∈ `{generate, quota_gate,
  quota_block, email}`. Aggiorna il dossier: conteggi, chars cumulati, cid
  distinti, email distinte, distribuzione voci (top 3), lingua dominante,
  timestamps degli ultimi 10 eventi. Retention dossier: 60 giorni.
- `signals_for(group)` — booleani S1-S4 ricalcolati sul dossier. S4 è il segnale
  che la rotazione non elude: ruotare il cookie prima di esaurire la quota
  lascia intatti S1-S3, ma il volume del gruppo resta.
- `needs_judgement(group)` — ≥2 segnali distinti e nessun verdetto valido.
- `set_verdict(group, verdict)` / `verdict_for(group)` — verdetto persistito nel
  dossier: `{verdict, confidence, reason, ts}`. TTL `ABM_ABUSE_VERDICT_TTL_DAYS`
  (14); rivalutazione se il gruppo genera dopo il TTL o se gli eventi crescono
  del 25% post-verdetto. `verdict=clean` ⇒ nessuna kill, rigiudizio solo se
  compare un segnale nuovo.
- `quarantine_job(job_id, group, verdict)` — sposta i file del job (non copia) e
  scrive `verdict.json` accanto. `restore_job(job_id)` riporta i file e il job
  allo stato pre-kill (senza refund: il job non era pagato). `purge_expired()`
  rimuove oltre `ABM_ABUSE_QUARANTINE_HOURS`.

**Prompt del giudice** (costruito solo con feature, mai con testo utente):
istruzioni di conservatorismo esplicite — «in dubbio, non uccidere» — output
JSON `{verdict: abuse|clean|inconclusive, confidence: 0-1, reason: str}`. Il
dossier è compatto (1-2K token): il costo per gruppo è nell'ordine dei
millesimi di euro, e con il verdetto cached sono una-due chiamate al giorno per
l'intera utenza sospetta.

Il criterio di giudizio è volume e velocità, non le identità: 8 libri in un mese
con due cookie (cambio device) è innocuo; 103 libri in 2,5 giorni con due cookie,
due email e una voce sola no. Il giudice decide sul dossier completo — è il
motivo per cui serve un giudice e non una regola fissa.

### 2. `audiobook_app.py` — punti di aggancio

- **`/api/generate` pre-claim**: se `verdict_for(group)` è `abuse` valido e il
  job non ha pagamento incassato né voce premium ⇒ `403` con
  `error_code: "job_terminated"` e `_log_activity(..., "QUOTA_ABUSE_BLOCK", ...)`.
  Il job resta in `analyzed`/`optimized` come gli altri rifiuti pre-claim.
- **Dopo `QUOTA_GATE`/`QUOTA_BLOCK` e dopo il claim del `GENERATE`**:
  `record_event(...)`, poi se `needs_judgement(group)` si accoda il gruppo al
  worker di giudizio.
- **Worker di giudizio** in `_ensure_background_threads()`: coda interna a
  giudice singolo, timeout HTTP 20s + 1 retry. Su verdetto `abuse` valido
  chiama il callback `on_abuse_verdict` per i job del gruppo **in corso**: stop
  del thread con la meccanica di cancellazione esistente, `job["status"]="error"`,
  `job["error_code"]="job_terminated"`, **nessun refund** (percorso dedicato,
  non passa da `finalize`), file in quarantena,
  `_log_activity(..., "QUOTA_ABUSE_KILL", ...)`. I job premium o pagati del
  gruppo vengono saltati.
- **Digest giornaliero**: nuova sezione — gruppo, segnali, verdetto,
  confidence, reason, job uccisi in corsa, rifiuti 403 nelle 24h, quarantena
  attiva. Solo hash, mai IP o email in chiaro nel canale email. Se
  `ABM_ADMIN_EMAIL` è vuoto il kill automatico è disattivato (solo giudizio in
  log): nessuna azione distruttiva senza audit.
- **Cleanup loop**: purge della quarantena scaduta.

Il `403` non spiega mai il perché: il frontend mostra un messaggio neutro
(§4). Un messaggio esplicativo insegnerebbe al bot quali feature lo hanno
tradito.

### 3. Frontend

Gestione di `error_code === "job_terminated"` accanto ai rami di errore
esistenti, con chiave i18n in `i18n_data.js` e nei 7 file `i18n/*.json`:

> «Elaborazione interrotta. Se pensi che sia un errore, contattaci.»

Nessun nome di provider, nessun riferimento alla quota o alla moderazione.

### 4. Quota e gate esistenti

Restano **invariati**: `free_tts_quota.py` non cambia, nessuna multi-chiave,
nessuna corsia spot. Il superamento della quota non è più l'ultima parola: è il
segnale S1 che, con un secondo segnale, apre il giudizio.

## Effetto atteso

Sul caso misurato: il secondo cid compare 2'20" dopo il primo blocco ⇒ S2
scatta lo stesso giorno del superamento della quota ⇒ il giudizio parte il primo
giorno dell'escalation. Da lì i job del gruppo vengono rifiutati. Per continuare
il bot deve cambiare IP — e rigenerare i job persi. Ogni rotazione distrugge il
lavoro accumulato: è il costo che la quota e i freni non riuscivano a imporre.

Il giorno dopo, il digest consegna all'admin il gruppo e la motivazione: la
blocklist manuale resta la leva terminale per i casi che insistono.

## Gestione errori

| Situazione | Comportamento |
|---|---|
| LLM giù o timeout | fail-open: nessuna kill, caso nel digest come «non giudicato» |
| `confidence < 0.9` o `verdict=inconclusive` | nessuna kill, voce nel digest |
| Job con pagamento incassato o voce premium | mai ucciso, mai rifiutato |
| `ABM_ADMIN_EMAIL` vuoto | kill automatica disattivata, solo giudizio in log |
| `_abuse_dossiers.json` corrotto | fail-open, il dossier riparte da zero |
| IP assente | gruppo `cid:`, nessun errore |

## Test

Nuovi file in `test/`:

- `test_abuse_watch.py` — dossier: eventi aggregati, segnali S1/S2/S3, trigger
  al secondo segnale, nessun trigger al primo; verdetto persistito, TTL e
  rivalutazione; `clean` senza kill; quarantena, purge e restore.
- `test_abuse_generate_enforcement.py` — 403 `job_terminated` solo con verdetto
  `abuse` valido; mai su job pagato/premium; fail-open con dossier corrotto;
  kill in corsa: thread fermato, status `error`, nessun refund, file in
  quarantena.
- `test_abuse_judge.py` — prompt costruito solo da feature (nessun testo
  utente), parsing del verdetto JSON, fail-open su risposta malformata.

I test esistenti della quota (`test_free_tts_quota*.py`,
`test_free_quota_*.py`) devono passare **invariati**: la quota non cambia.

## Rollout

1. **Osservazione** — deploy con `ABM_ABUSE_LLM_ENABLE=0`: i dossier si
   popolano, i giudizi girano e finiscono in log e digest, nessuna kill. Serve a
   tarare la soglia di confidenza sui casi reali prima che qualunque azione
   distruttiva sia possibile.
2. **Accensione** — `ABM_ABUSE_LLM_ENABLE=1` quando i verdetti osservati sono
   in linea con il caso noto (nessun `abuse` su client legittimi).
3. **Blocklist** — resta la leva manuale per i gruppi confermati dal digest.

## File toccati

`abuse_watch.py` (nuovo), `audiobook_app.py`, `email_service.py`,
`user_stats.py` (op di log nei pannelli), `static/js/app.js`,
`templates/_fragments/i18n_data.js`, `i18n/*.json`,
`md_files/PARAMETRI_CONFIGURAZIONE.md`, più i tre nuovi file di test.

## Nuove variabili d'ambiente

| Variabile | Descrizione | Default |
|---|---|---|
| `ABM_ABUSE_LLM_ENABLE` | Interruttore del kill automatico (0 = solo giudizio in log e digest) | `0` |
| `ABM_ABUSE_LLM_CONFIDENCE` | Soglia minima di confidenza per la kill | `0.9` |
| `ABM_ABUSE_QUARANTINE_HOURS` | Retention dei file dei job uccisi, per il ripristino | `24` |
| `ABM_ABUSE_GATE_DAILY` | Soglia `QUOTA_GATE`/24h per il segnale S3 | `5` |
| `ABM_ABUSE_CHARS_DAILY` | Soglia caratteri/24h per il segnale S4 (quota/4) | `2500000` |
| `ABM_ABUSE_VERDICT_TTL_DAYS` | Validità del verdetto persistito | `14` |
