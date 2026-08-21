# Migrazione produzione Audiobook Maker su nuovo server — Design

**Data:** 2026-08-21
**Stato:** approvato (design), piano operativo da scrivere
**Origine:** server di produzione saturo (disco 76%, RAM 4 GB con swap 512 MB esaurito)

## 1. Obiettivo

Spostare `audiobook-maker.com` dal server attuale a una macchina con il doppio di CPU, RAM
e disco, **senza perdere dati, job in retention, token di download, pagamenti o voucher**,
con downtime limitato alla finestra di freeze (~10-20 min) e con rollback disponibile.

## 2. Inventario dei due server (rilevato, non assunto)

| | Attuale `80.211.136.211` | Nuovo `80.211.137.33` |
|---|---|---|
| Hostname | MiniLinux | MiniLinux2 |
| OS / kernel | Ubuntu 24.04.4 LTS / 6.8.0-138 | Ubuntu 24.04 LTS / 6.8.0-36 |
| Virtualizzazione | KVM — OpenStack Nova | KVM — OpenStack Nova |
| CPU | 2 vCPU | 4 vCPU |
| RAM | 4 GB | 8 GB |
| Swap | 512 MB (file, **100% usato**) | **assente** |
| Disco | 40 GB — 76% pieno, 9 GB liberi | 80 GB — 72 GB liberi |
| Python / ffmpeg / nginx | 3.12.3 / 6.1.1 / 1.30.4 | da installare |
| Servizi | audiobook-maker, audiobook-maker-test, nginx, fail2ban, postfix, rsyslog, cron | nessuno |
| Dati | `/opt/audiobook-maker/data` = 23 GB | `/opt` vuoto |
| Certbot | audiobook-maker.com, test.audiobook-maker.com | — |
| Utenti | ubuntu (1000), backupuser (1001, rbash), frangiamone (1002) | — |
| Commit in prod | `d6a7992` | — |
| Connettività | SSH diretta vecchio → nuovo sulla 22: **OK** | — |

**DNS:** Aruba (`ns.abdns.biz/.eu/.info`), record A con TTL 21600s (6h).

## 3. Decisioni prese

| Tema | Decisione | Motivo |
|---|---|---|
| Strategia | Parallelo + switch DNS | Collaudo reale prima del cutover; rollback disponibile |
| Dati | Migrazione completa dei 23 GB | Job in retention e link di download attivi sopravvivono |
| Ambiente test | **Escluso** | Resta sul vecchio server finché lo si dismette |
| Utenti/cron/backup/fail2ban/postfix | Replicati | Continuità operativa |
| Hardening | Swap, cron disco riparato, journald | Fix di difetti noti, non copia 1:1 |
| Vecchio server | Rollback per 7 giorni, poi dismissione | Rete di sicurezza |
| Collaudo | hosts file sul PC dell'utente + certificati copiati | Flusso fedele, `ABM_BASE_URL` definitivo, zero impatto pubblico |
| Runtime Python | Replica fedele da `pip freeze` (no venv) | Versioni identiche a quelle collaudate; `deploy.yml` invariato |
| Momento del freeze | Su via libera esplicito dell'utente | Nessun cutover a sorpresa |

## 4. Fase 1 — Preparazione (nessun impatto sulla produzione)

1. Baseline: `apt update && apt upgrade`, pacchetti (python3-pip, git, nginx, certbot,
   python3-certbot-nginx, ufw, fail2ban, rsync, ffmpeg, postfix, sysstat), timezone e locale
   allineati al vecchio.
2. **Swap 4 GB** persistente in `/etc/fstab` + `vm.swappiness=10`.
3. Firewall ufw 22/80/443; fail2ban con la configurazione del vecchio.
4. `git clone` di `/opt/audiobook-maker` e checkout del commit **esattamente** pari a quello
   in prod (`d6a7992`), non `main` HEAD.
5. Runtime Python installato a partire dal `pip freeze` del vecchio; verifica di parità con
   diff dell'elenco pacchetti.
6. Utenti `ubuntu`, `backupuser` (rbash), `frangiamone` con relative `authorized_keys`,
   inclusa la chiave di deploy usata da GitHub Actions.
7. Segreti copiati **server-to-server**, mai attraverso la chat o il PC locale:
   `/etc/audiobook-maker/*.json` (service account Google) e
   `/etc/systemd/system/audiobook-maker.service.d/override.conf` (~60 variabili `ABM_*`).
8. Unit systemd installata ma **disabilitata e ferma**.

### Vincolo di isolamento (invariante)

Il servizio nuovo non deve **mai** girare in produzione contemporaneamente al vecchio con
la stessa data dir o lo stesso bucket R2: il cleanup loop di un processo cancellerebbe i
job dell'altro, sia in locale sia in cold storage. Un solo processo "vivo" per volta.

## 5. Fase 2 — Dati, certificati, collaudo

**Sincronizzazione (servizio nuovo fermo):**
- Passata 1 a caldo: `rsync -aHAX --numeric-ids` di `/opt/audiobook-maker/data` (23 GB) via
  SSH diretto vecchio → nuovo, con il vecchio in piena attività.
- Copia di `activity_*.log`, `/opt/backup`, script di ops, config nginx, `/etc/letsencrypt`
  (live + archive + renewal + options-ssl-nginx.conf + ssl-dhparams.pem), `/etc/audiobook-maker/`.
- Passata 2 delta durante il freeze (fase 3).

**Nginx + TLS:**
- Vhost `audiobook-maker.com` identico all'attuale: rate limit (`app_limit` 10r/s,
  `upload_limit` 3r/m), `client_max_body_size 200M` su `/api/analyze`, SSE su `/api/progress/`
  con `proxy_buffering off`, timeout 600s. **Senza** il vhost `test.`.
- Certificati copiati dal vecchio → il nuovo risponde subito con certificato valido.
  Il rinnovo certbot resta inerte finché il DNS punta altrove; verifica `--dry-run` al cutover.

**Collaudo isolato** (override temporaneo, sostituito al cutover):
- `ABM_DATA_DIR=/opt/audiobook-maker/data_collaudo` (vuota, separata dai 23 GB migrati);
- cold storage S3/R2 **disattivato** (nessuna scrittura né cancellazione sul bucket condiviso);
- resto identico alla produzione, `ABM_BASE_URL=https://audiobook-maker.com`.

L'utente punta `audiobook-maker.com` a `80.211.137.33` nel file hosts del proprio PC e collauda
dal browser: upload EPUB/PDF, ottimizzazione AI, anteprima voce, generazione standard e PREMIUM,
M4B, email di consegna, download.

**Vincolo:** nessun pagamento PayPal reale in collaudo — finirebbe in un `_payments.json`
destinato a essere buttato. Test con libro sotto soglia gratuita e voucher creato nella data
dir di collaudo. A collaudo concluso: servizio fermato, `data_collaudo` rimossa.

## 6. Fase 3 — Cutover

**T-7h:** TTL del record A di `audiobook-maker.com` e `www` abbassato da 21600s a **300s** su Aruba.

**T-0 — drenaggio, non attesa.** La produzione ha statisticamente 35-40 job vivi in ogni istante:
attendere che siano zero è impossibile. Il criterio è **zero job BLOCCANTI**, dove bloccante
significa "interromperlo distrugge lavoro pagato che il recovery non sa riprendere": qualunque
job Speechify (escluso da `chunk_reuse.REUSABLE_ENGINES`), i job PREMIUM non registrati in
`_pending_jobs.json` (solo i batch con email hanno un descrittore di recovery) e i job con
pagamento consumato e non concluso, anche senza chunk (ottimizzazione AI interattiva).
I job batch con motore `edge`/`gemini`/`google` ripartono dai chunk già sintetizzati, perché il
fingerprint di `chunk_reuse` è ancorato al contenuto e non ai path; gli interattivi free sono
perdita accettabile (il browser regge comunque solo ~30 s di interruzione SSE).

Il drenaggio si ottiene con `POST /api/admin/suspend`, che blocca i nuovi job **prima** del
preflight di pagamento lasciando attivi i download, e si misura con
`scripts/migration/migration_live_jobs.py` (exit code 2 finché ci sono bloccanti).
Il criterio di uscita è **due letture consecutive pulite con finestra di 25 minuti**: una
finestra stretta scambierebbe per morto un job PREMIUM in attesa di rate limit o in assembly
lungo, e una singola lettura può cadere nel buco fra due chunk. Il ciclo ricontrolla a ogni giro
anche che la sospensione sia ancora in piedi, perché `_suspend_new_jobs` vive in RAM e un
restart la azzera senza dirlo.
Poi report all'utente e **attesa del via libera esplicito**.

**Freeze (~10-20 min):**
1. `systemctl stop` + `disable` + `mask` di `audiobook-maker` sul vecchio (deve restare giù
   anche dopo un riavvio della macchina), e sospensione del cron `abm-cleanup-stale` **sul
   vecchio**: cancella job dir per mtime e nei sette giorni di rollback eroderebbe la copia di
   rollback stessa.
2. Nginx del vecchio diventa un **proxy verso il nuovo** per chi arriva prima della propagazione
   DNS: il vhost viene sostituito per intero con un unico `location /` (il file di produzione ne
   ha sei con `proxy_pass`, e lasciarne indietro anche uno significa 502 su upload o SSE), con
   una pagina di manutenzione servita via `error_page 502 503 504` per la finestra in cui il
   nuovo servizio non è ancora acceso. Il nuovo va autorizzato con `set_real_ip_from` dell'IP
   vecchio, altrimenti il rate limit tratta tutto il traffico proxato come un unico client.
3. Sul nuovo, a servizio ancora fermo, `scripts/migration/migration_recover_prep.py --apply`
   ripulisce il registro orfani (job già consegnati, input mancante, tentativi da azzerare)
   prima che `_recover_orphan_jobs()` rilanci tutto al boot. Due esiti sono cancelli: zero job
   con "input mancante" (chiuderebbero senza rimborso né email) e un numero di job con evento di
   consegna nell'ordine delle decine di migliaia (se gli activity log mancano la funzione
   risponde "nessuno" senza errore, e al boot partono email duplicate). Da qui in avanti nessun
   altro rsync: ripeterlo riporterebbe il registro sporco.
4. rsync delta della data dir, degli `activity_*.log` e dei JSON di stato
   (`_download_tokens.json`, `_payments.json`, `_vouchers.json`, `google_tts_usage.json`,
   `_pending_jobs.json`, `_client_emails.json`).
5. Verifica di integrità: conteggio job, dimensione totale, checksum dei JSON critici,
   validazione sintattica di ciascun JSON.
6. Sul nuovo: rimozione dell'override di collaudo → data dir reale, **R2 riattivato**,
   segreti esposti ruotati (`ABM_S3_SECRET_KEY`, `ABM_ADMIN_TOKEN`) e **provati** con
   `scripts/verify_r2.py` prima dell'avvio — `is_enabled()` controlla solo che le variabili non
   siano vuote, quindi un typo nella chiave supererebbe l'avvio e si manifesterebbe al primo
   download cold di un utente. Poi servizio `enable` + `start`, con osservazione del recovery dei
   job interrotti e verifica che il riuso dei chunk sia attivo.
7. Smoke test locale: `curl` su `127.0.0.1:5601`, download da un token preesistente e da un
   token **cold** (job già evicted): è l'unico che dimostra insieme chiave nuova e integrità dei
   dati migrati. Le vecchie chiavi R2 si revocano solo dopo.
8. Switch DNS su Aruba: A `audiobook-maker.com` e `www` → `80.211.137.33`.
9. Rimozione della riga dal file hosts e verifica dal browser reale.
10. Ripristino del cron `abm-cleanup-stale` **sul nuovo**, dopo averne riletto il criterio di
    cancellazione e averlo provato a vuoto: i dati appena migrati portano gli mtime originali
    preservati da `rsync -aHAX`. Quello sul vecchio resta sospeso fino alla dismissione.
11. A T+2h: riconciliazione dei job interrotti (recuperati, rimborsati automaticamente, oppure
    da rimborsare a mano).

**Dopo lo switch:** `certbot renew --dry-run`, TTL riportato a 3600s (non 21600, per non
zavorrare un eventuale rollback).

**Secret GitHub Actions:** `SERVER_HOST` deve passare a `80.211.137.33` prima del primo push
su `main`, altrimenti il deploy colpisce il vecchio server.

## 7. Fase 4 — Hardening e verifiche

**Fix noti applicati sul nuovo server:**
- Swap 4 GB (il vecchio thrashava con 512 MB — origine dell'incidente RAM del 21/08/2026).
- **Cron disco riparato**: oggi il cron invoca `/opt/check_disk.sh`, ma il file si chiama
  `check_disk_space.sh` → il controllo disco fallisce in silenzio da mesi.
- journald `persistent / 4G / 14day` fin dall'inizio.
- rsyslog verificato: deve duplicare lo stdout del servizio in `/var/log/syslog` (fonte
  forense principale, senza la quale si perde la tracciabilità delle cancellazioni).

**Capacità — cambiamento implicito da governare:**
- `ABM_MAX_CONCURRENT_ASSEMBLY` non è impostato: il default è `cpu_count()-1`, quindi passando
  da 2 a 4 vCPU passerebbe **da 1 a 3** encode FFmpeg finali in parallelo, automaticamente.
  Al cutover viene **pinnato a 2**, da alzare a 3 dopo qualche giorno di osservazione.
- `ABM_MAX_CONCURRENT_GLOBAL` viene pinnato a **35**, il valore con cui la produzione gira
  davvero (l'`override.conf` del vecchio dice 50, ma quelle righe non sono mai entrate in
  vigore dopo l'ultimo restart). Rivalutabile con 8 GB, ma dopo la migrazione, con dati alla mano.

**Checklist post-cutover:** servizio stabile · job standard end-to-end · job PREMIUM · email di
consegna · download da token **preesistente** (prova della migrazione dati) · download da cold
storage (presigned R2) · pagamento PayPal reale di piccolo importo verificato in `_payments.json` ·
voucher · pagina admin · sitemap/SEO · certbot dry-run · backup notturno verificato il giorno dopo ·
`activity_*.log` che continua a scrivere.

**Osservazione a 48h:** RAM/swap, disco, thread vivi (in particolare il cleanup loop, che muore
in silenzio e blocca la retention), log degli errori.

## 8. Rollback

Finestra di 7 giorni. Il vecchio server conserva codice e dati al momento del freeze: si ripunta
il DNS e si riavvia il servizio. Realistico solo nelle prime ore — dopo, i job creati sul nuovo
server sarebbero orfani e si corregge in avanti.

## 9. Rischi e mitigazioni

| Rischio | Mitigazione |
|---|---|
| Doppio processo attivo → cancellazioni incrociate su R2 | Servizio nuovo disabilitato fino al cutover; vecchio `disable` dopo il freeze; collaudo con R2 off |
| Propagazione DNS lenta | TTL a 300s con 7h di anticipo; il vecchio fa da proxy verso il nuovo |
| Finestra fra proxy acceso e servizio nuovo avviato (20-45 min) | `error_page 502 503 504 = @maint` sul proxy: pagina di manutenzione invece dell'errore nginx |
| `location` non proxati sul vecchio (upload, SSE) | Vhost sostituito per intero con un solo `location /` |
| Chiave R2 ruotata errata, scoperta dal primo utente | `scripts/verify_r2.py` prima dello start + download di un token cold prima dello switch DNS |
| Copia di rollback erosa dal cron del vecchio server | Cron `abm-cleanup-stale` sospeso sul vecchio per tutti i 7 giorni |
| Job chiusi senza rimborso da una delta rsync incompleta | Cancello "input mancante = 0" nell'igiene del registro, con verifica job per job |
| Lavoro pagato perso al freeze | Drenaggio con `/api/admin/suspend` fino a zero job BLOCCANTI (`migration_live_jobs.py`); i batch riprendono dai chunk grazie a `chunk_reuse` |
| Recovery al boot che duplica email o rimborsa job sani | `migration_recover_prep.py --apply` prima dello start: job consegnati e senza input a `failed`, tentativi azzerati |
| Deriva delle dipendenze Python | Installazione da `pip freeze` del vecchio + diff di verifica |
| Deploy su server sbagliato | `SERVER_HOST` aggiornato prima del primo push |
| Rinnovo certificati fallito dopo lo switch | `certbot renew --dry-run` subito dopo il cutover |
| Concorrenza assembly triplicata di colpo | `ABM_MAX_CONCURRENT_ASSEMBLY=2` pinnato al cutover |
| Segreti esposti | Copia server-to-server, mai in chat né su disco locale |

## 10. Fuori scope

- Migrazione di `audiobook-maker-test` / `test.audiobook-maker.com` (resta sul vecchio server).
- Passaggio a gunicorn o multi-worker.
- Modifiche a `deploy.yml` oltre al secret `SERVER_HOST`.
- Revisione dei parametri di retention e di pricing.
