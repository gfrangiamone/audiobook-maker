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

**T-0:** verifica che non ci siano job in corso sul vecchio server (generazioni, ottimizzazioni
LLM, traduzioni); report all'utente e **attesa del via libera esplicito**.

**Freeze (~10-20 min):**
1. `systemctl stop` + `systemctl disable audiobook-maker` sul vecchio (deve restare giù anche
   dopo un riavvio della macchina).
2. Nginx del vecchio serve una pagina di manutenzione 503 per chi arriva prima della propagazione.
3. rsync delta della data dir, degli `activity_*.log` e dei JSON di stato
   (`_download_tokens.json`, `_payments.json`, `_vouchers.json`, `google_tts_usage.json`,
   `_pending_jobs.json`, `_client_emails.json`).
4. Verifica di integrità: conteggio job, dimensione totale, checksum dei JSON critici,
   validazione sintattica di ciascun JSON.
5. Sul nuovo: rimozione dell'override di collaudo → data dir reale, **R2 riattivato**,
   servizio `enable` + `start`.
6. Smoke test locale: `curl` su `127.0.0.1:5601`, download da un token preesistente.
7. Switch DNS su Aruba: A `audiobook-maker.com` e `www` → `80.211.137.33`.
8. Rimozione della riga dal file hosts e verifica dal browser reale.

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
- `ABM_MAX_CONCURRENT_GLOBAL` resta **6** (invariato): tarato per non saturare RAM+swap.
  Rivalutabile con 8 GB, ma dopo la migrazione, con dati alla mano.

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
| Propagazione DNS lenta | TTL a 300s con 7h di anticipo; pagina 503 sul vecchio |
| Job in corso persi al freeze | Verifica assenza job attivi prima del via libera |
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
