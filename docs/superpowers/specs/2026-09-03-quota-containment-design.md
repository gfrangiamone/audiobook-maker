# Contenimento dell'abuso della quota voci standard

Data: 2026-09-03
Stato: design approvato

## Problema

La quota mensile di caratteri sulle voci standard (`free_tts_quota.py`, deployata
il 2026-09-01 con il commit `396534f`) non limita nulla. Due falle indipendenti,
entrambe misurate in produzione sul client `36e901e8-71d`.

### 1. Il gate email è un click

`QUOTA_GATE` non è un rifiuto: marca un job **accettato oltre quota**
(`audiobook_app.py:11357`). Il rifiuto è `QUOTA_BLOCK`, un `402` che il frontend
converte in un modale. Ma `_handleTtsQuotaGate` (`static/js/app.js:4191`)
preriempie il campo email da `localStorage.abm_v_email`, e `_submitTtsQuotaGate`
chiama `retryGeneration()` da solo dopo `register_email`: dalla seconda volta in
poi il gate costa **un click e ~2 secondi**.

Settembre 2026, `36e901e8-71d`: **26 `QUOTA_BLOCK` → 26 `QUOTA_GATE`**, rapporto
1:1. Nessun blocco effettivo. Contatore a **19.218.930 / 10.000.000** caratteri.

### 2. La quota si azzera cambiando cookie

`_quota_client_id()` (`audiobook_app.py:732`) legge solo `abm_cid`. Dall'IP
`175.141.179.118`:

| client_id | primo evento | quota consumata |
|---|---|---|
| `36e901e8-71d` | 2026-08-08 | 19,2M |
| `61991d18-e7c` | **2026-09-02 15:12:07** | 1,75M (bucket nuovo) |

Il primo `QUOTA_BLOCK` di `36e901e8` è delle 15:09:47. Il secondo cookie nasce
**2 minuti e 20 secondi dopo**, e da lì i due vengono usati alternati nella stessa
sessione. Effetto collaterale: raddoppia anche `MAX_CONCURRENT_PER_CLIENT`, 2 → 4.

### Impatto misurato

Totale reale dell'IP: **~21M caratteri in 2,5 giorni** contro un tetto di
10M/mese. 113 `GENERATE` su 2030 di tutto settembre — **un client su 760 = 5,6%
del traffico**. Escalation da 2 libri/giorno (8 agosto) a 47/giorno (1-2
settembre). Coda assembly: 15 encode osservati, attesa media 135s, quattro sopra
i 120s, **uno a 506s con 6 job accodati**. Un job ha girato 22.394s (6h12').

Voce sempre `zh-CN-XiaoxiaoNeural` (standard, gratuita): **ricavo zero**. Il costo
non è di provider ma di CPU, banda, storage e reputazione dell'endpoint edge-tts.

## Vincolo di progetto

Nessuna identità gratuita è difendibile: cookie, IP ed email gratuite sono tutti
rinnovabili in minuti, e questo utente lo ha dimostrato in 2'20". L'obiettivo non
è impedire, è **rendere l'abuso poco redditizio a costo nullo per gli altri 759
client**. Da qui la scelta di degradare anziché rifiutare.

Scartata esplicitamente la verifica email con codice oltre quota: l'attrito
colpirebbe i lettori legittimi (2 client su 760 hanno superato la quota a
settembre, lo 0,26%) e reggerebbe pochi minuti contro chi ha già rotato un cookie.
Resta disponibile come escalation futura.

## Decisioni

| Aspetto | Scelta |
|---|---|
| Chiave quota | massimo fra `cid`, `net` (IP /24 hashato), `mail` (email hashata) |
| Tetto `cid` e `mail` | `L` = `ABM_FREE_TTS_QUOTA_CHARS_PER_MONTH` (10M) |
| Tetto `net` | `3L` (`ABM_FREE_TTS_QUOTA_NET_MULTIPLIER`, tolleranza NAT) |
| Superamento | il job resta gratuito, entra in corsia spot |
| Freni corsia spot | concorrenza 1, riserva di capacità 2, cooldown 7200s |
| Gate email | **invariato**: la modalità batch è desiderabile, non è la leva |
| Esito del freno | `429 quota_throttled` con `retry_after_sec` |
| Privacy | nessun IP o email in chiaro su disco: solo `sha256(ABM_IP_SALT + valore)[:16]` |

Fuori ambito: le voci premium (già protette da `free_quota` a valore) e la
traduzione libri.

## Architettura

### 1. `free_tts_quota.py` — chiave multipla

Il modulo resta **foglia** (stdlib + `community_store.atomic_write_json`);
l'hashing entra qui con `hashlib`, non viene delegato ad `audiobook_app`, così
tutti i punti di enforcement condividono una sola normalizzazione.

```python
def identity_keys(client_id, ip, email):
    """['cid:<raw>', 'net:<h16>', 'mail:<h16>'] — solo le chiavi disponibili."""
```

- `net`: l'IP viene troncato al `/24` (IPv4) o al `/64` (IPv6) **prima**
  dell'hash. IP malformato o assente ⇒ chiave omessa.
- `mail`: lowercase + strip prima dell'hash. Assente ⇒ chiave omessa.
- `cid`: invariato rispetto a oggi, incluso il fallback `_anon`.

Il file `_free_tts_quota.json` non cambia schema: le tre chiavi convivono nello
stesso dizionario del mese, distinte dal prefisso. La compattazione a
`_KEEP_MONTHS = 3` resta invariata.

Firme aggiornate:

- `consume(keys, chars, job_id, gated=False)` — incrementa **tutte** le chiavi.
  L'idempotenza per `job_id` resta per-chiave: se una chiave ha già addebitato
  quel job, quella chiave non viene toccata (retry della stessa generazione).
- `decision(keys, chars, job_id=None)` — esaurita se **almeno una** chiave sfora
  il proprio tetto. Aggiunge al dizionario di ritorno `"key"` (la chiave che ha
  fatto scattare l'esito) e `"kind"` (`cid` | `net` | `mail`), per il log e per
  il messaggio all'utente.
- `refund(keys, job_id)` — storna su tutte le chiavi.
- `limit_for(kind)` — `3L` per `net`, `L` altrove.

Le vecchie firme a singolo `client_id` restano accettate (una stringa viene
promossa a lista di una chiave), così `used_chars()`, `job_charged()`,
`snapshot()` e `month_table()` continuano a funzionare come oggi — insieme ai
pannelli admin che li usano.

### 2. `audiobook_app.py` — corsia spot

`_quota_client_id()` resta la sorgente unica del `cid`. Accanto nasce
`_quota_identity(job)`, che restituisce le tre chiavi da `job["client_id"]`,
`job["client_ip"]` e `job["notify_email"]`.

I tre freni si applicano in `/api/generate`, **prima** del claim atomico dello
stato, solo quando `decision()` è esaurita e la voce non è premium:

1. **Concorrenza 1** — `ABM_QUOTA_THROTTLE_CONCURRENCY` (default 1) sostituisce
   `MAX_CONCURRENT_PER_CLIENT` per le identità oltre quota. Il conteggio dei job
   attivi passa dal `cid` all'identità: due cookie dallo stesso `/24` non fanno
   due slot.
2. **Riserva di capacità** — rifiuto se
   `_active_generating_total_unlocked() >= MAX_CONCURRENT_GLOBAL - ABM_QUOTA_THROTTLE_RESERVE`
   (default 2). A macchina carica gli ultimi due slot restano ai client in quota;
   a macchina scarica il job parte subito.
3. **Distanziamento** — rifiuto se l'ultimo avvio oltre quota della stessa
   identità è più recente di `ABM_QUOTA_THROTTLE_COOLDOWN_SEC` (default 7200).
   Gli ultimi avvii stanno in una mappa in memoria `{key: monotonic}`, potata
   alla scadenza: un riavvio del processo regala un giro, che è accettabile e
   preferibile a un altro file di stato da mantenere coerente.

Tutti e tre rispondono:

```json
{"error": "...", "error_code": "quota_throttled", "retry_after_sec": 6840,
 "reason": "cooldown" | "capacity" | "concurrency"}
```

con `429` e header `Retry-After`. Il job torna a `analyzed`/`optimized` come già
fanno gli altri rami di rifiuto, e — invariante da rispettare — **nessun freno
può scattare dopo il consumo della quota o dopo un pagamento incassato**: tutti e
tre stanno a monte del punto di consumo, che resta l'unico punto di partenza
certa.

`ABM_QUOTA_THROTTLE_ENABLE=0` calcola e logga la decisione senza applicarla
(modalità osservazione, vedi Rollout).

### 3. `assembly_queue.py` — priorità

Nuovo livello `PRIORITY_THROTTLED = -10` accanto a `PRIORITY_NORMAL = 0` e
`PRIORITY_PREMIUM = 10`. Il modulo dichiara già livelli numerici «per gradazioni
future»: la meccanica della coda non cambia. L'anti-starvation resta quella
esistente — dopo `ABM_ASSEMBLY_STARVE_SEC` (900s) il waiter guadagna
`+PRIORITY_PREMIUM` (`assembly_queue.py:143`) — e su un throttled porta `-10` a
`0`, cioè alla pari con i job normali, mai sopra. Nessun job resta fermo
indefinitamente e nessun throttled scavalca un pagante.
`generation_engine._assembly_priority` restituisce il nuovo livello quando il job
porta il marcatore `job["_quota_throttled"]`.

### 4. Osservabilità e interruttore

- **Activity log**: nuova operazione `QUOTA_THROTTLE`, accanto a `QUOTA_GATE` e
  `QUOTA_BLOCK`, con il `reason` nel campo file. `user_stats.power_users` la
  conta in `throttle_24h`.
- **Digest admin**: due righe di allerta nuove — un'identità sopra `2×` la quota
  (`ABM_ADMIN_QUOTA_ALERT_MULTIPLIER`), e `≥2` cid distinti che generano dallo
  stesso `/24` nel mese. Il caso del 02/09 sarebbe arrivato al digest successivo
  invece che dopo 21M caratteri.
- **Blocklist**: `_blocklist.json` nella data dir, `{key: {reason, until, ts}}`
  con `key` in forma `cid:` o `net:`. Controllata in `/api/analyze` e
  `/api/generate` → `403 blocked`. Gestione dal pannello utenti di
  `/admin/log-activity`, con l'auth esistente (header `X-Admin-Token` o cookie
  `abm_admin_session`; **mai** il token in query string).

### 5. Frontend

Il modale della quota resta quello. Si aggiunge il ramo `quota_throttled` nei due
punti che oggi gestiscono `free_tts_quota_exhausted` (`static/js/app.js:3194` e
`3625`), con una nuova chiave i18n in `i18n_data.js` e nei 7 file `i18n/*.json`:

> «Oltre il limite mensile i libri vengono elaborati con la capacità disponibile.
> Prossimo avvio possibile fra circa {0}.»

Nessun nome di provider nel testo, coerentemente con la convenzione UI del
progetto.

## Effetto atteso

Sul comportamento osservato: da **47 libri/giorno a ~12**, concentrati nelle ore
scariche. Spariscono le code da 6 job che oggi fanno attendere 506s gli altri
client. Nessun client in quota vede alcuna differenza — solo un miglioramento
delle attese in coda assembly.

## Gestione errori

| Situazione | Comportamento |
|---|---|
| `_free_tts_quota.json` corrotto o illeggibile | `decision()` ritorna `allowed` (fail-open, come oggi): la quota non deve mai bloccare il servizio |
| `ABM_IP_SALT` non impostato | default `abm-default-salt-v1`, come il resto dell'app |
| IP assente o malformato | chiave `net` omessa, le altre due decidono |
| Blocklist illeggibile | fail-open, nessun 403 |
| `MAX_CONCURRENT_GLOBAL = 0` (illimitato) | freno 2 disattivato, gli altri due restano |

## Test

Nuovi file in `test/`:

- `test_free_tts_quota_multikey.py` — chiavi generate correttamente (incluso
  `/24` e `/64`); `consume` incrementa tutte le chiavi; idempotenza per-chiave sul
  `job_id`; `decision` esaurita quando sfora **solo** `net`; tetto `3L` su `net`;
  `refund` storna ovunque; retrocompatibilità della firma a stringa.
- `test_quota_throttle.py` — i tre freni scattano e restituiscono `429`
  `quota_throttled` con il `reason` giusto; il job torna in `analyzed`; nessun
  freno scatta per voce premium o pagamento incassato; nessun freno scatta dopo
  il consumo della quota; `ABM_QUOTA_THROTTLE_ENABLE=0` logga senza applicare.
- `test_quota_blocklist.py` — `403` su cid e su net, scadenza onorata, fail-open.

I test esistenti `test_free_tts_quota.py` e `test_free_tts_quota_gate.py` devono
passare **invariati**: il gate email non cambia comportamento.

## Rollout

1. **Osservazione** — deploy con `ABM_QUOTA_THROTTLE_ENABLE=0`. La decisione
   multi-chiave viene calcolata e scritta a log (`QUOTA_THROTTLE` con
   `reason=observe`) ma non applicata. Due giorni bastano per contare quanti
   client innocenti la chiave `net` intercetterebbe.
2. **Accensione** — `ABM_QUOTA_THROTTLE_ENABLE=1` se i falsi positivi da NAT sono
   accettabili; altrimenti si alza prima `ABM_FREE_TTS_QUOTA_NET_MULTIPLIER`.
3. **Blocklist** — resta la leva manuale per i casi che sfuggono comunque.

## File toccati

`free_tts_quota.py`, `audiobook_app.py`, `assembly_queue.py`,
`generation_engine.py`, `user_stats.py`, `email_service.py`,
`static/js/app.js`, `templates/_fragments/i18n_data.js`, `i18n/*.json`,
`md_files/PARAMETRI_CONFIGURAZIONE.md`, più i tre nuovi file di test.

## Nuove variabili d'ambiente

| Variabile | Descrizione | Default |
|---|---|---|
| `ABM_FREE_TTS_QUOTA_NET_MULTIPLIER` | Moltiplicatore del tetto sulla chiave `net` (tolleranza NAT) | `3` |
| `ABM_QUOTA_THROTTLE_ENABLE` | `0` = sola osservazione (calcola e logga, non applica) | `1` |
| `ABM_QUOTA_THROTTLE_CONCURRENCY` | Job contemporanei per identità oltre quota | `1` |
| `ABM_QUOTA_THROTTLE_RESERVE` | Slot globali riservati ai client in quota | `2` |
| `ABM_QUOTA_THROTTLE_COOLDOWN_SEC` | Distanza minima fra due avvii oltre quota | `7200` |
| `ABM_ADMIN_QUOTA_ALERT_MULTIPLIER` | Soglia di allerta nel digest, in multipli della quota | `2` |
