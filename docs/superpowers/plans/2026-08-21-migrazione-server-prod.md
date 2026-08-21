# Migrazione produzione su nuovo server — Piano operativo

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** spostare `audiobook-maker.com` da `80.211.136.211` (2 vCPU / 4 GB / 40 GB) a `80.211.137.33` (4 vCPU / 8 GB / 80 GB) senza perdere dati, job, token, pagamenti o voucher, con freeze di ~10-20 minuti e rollback disponibile per 7 giorni.

**Architecture:** preparazione completa del nuovo server a produzione intatta; collaudo isolato (data dir separata, cold storage spento) via file hosts sul PC dell'utente; freeze breve con rsync delta e switch DNS su Aruba; vecchio server congelato ma vivo come rollback.

**Tech Stack:** Ubuntu 24.04, Python 3.12 di sistema (no venv), nginx + certbot, systemd, rsync su SSH, Cloudflare R2 (cold storage), DNS Aruba.

**Spec:** `docs/superpowers/specs/2026-08-21-migrazione-server-prod-design.md`

## Global Constraints

- **Un solo processo `audiobook_app.py` vivo per volta** fra i due server quando condividono data dir o bucket R2. Violare questo vincolo significa cancellazioni incrociate di job (locali e cold).
- **Codice:** il nuovo server parte dal commit **`d6a7992`**, non da `main` HEAD.
- **Segreti** (`override.conf`, service account Google, chiavi SSH): copiati **server-to-server**. Mai incollati in chat, mai salvati sul PC locale, mai scritti in questo piano.
- **Nessun push su `main`** durante tutta la migrazione: un push scatena il deploy di GitHub Actions sul server indicato dal secret `SERVER_HOST`.
- **`SERVER_HOST` su GitHub** viene aggiornato dall'utente, manualmente, dopo il cutover.
- **Ambiente test** (`audiobook-maker-test`, `test.audiobook-maker.com`): fuori scope, resta sul vecchio server.
- **Nessun pagamento PayPal reale durante il collaudo.**
- Ogni comando sul vecchio server è **non distruttivo** fino al Task 8 (freeze). Prima di allora: sola lettura e copia.
- Accesso: `plink`/`pscp` da Windows con utente `root` su entrambi i server (stessa password, nota all'operatore, mai scritta su file).

**Riferimenti host:**
- `OLD` = `80.211.136.211` (hostname `MiniLinux`)
- `NEW` = `80.211.137.33` (hostname `MiniLinux2`)

---

### Task 1: Baseline del nuovo server (pacchetti, timezone, swap, firewall)

**Files:**
- Create su NEW: `/swapfile`, `/etc/sysctl.d/99-abm-swap.conf`
- Modify su NEW: `/etc/fstab`

**Interfaces:**
- Consumes: niente (primo task).
- Produces: sistema con ffmpeg, python3, nginx, certbot, rsync, fail2ban, ufw installati; swap 4 GB attivo; timezone `Europe/Rome`.

- [x] **Step 1: Aggiornare il sistema e installare i pacchetti**

```bash
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get -y upgrade
DEBIAN_FRONTEND=noninteractive apt-get install -y \
  python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx \
  ufw fail2ban rsync ffmpeg postfix sysstat curl jq unzip pipx
```

Nota: l'installazione di `postfix` apre un dialogo di configurazione — con `DEBIAN_FRONTEND=noninteractive` viene scelto il default (`Internet Site`), coerente con il vecchio server (nessun relay, solo consegna locale per i cron).

- [x] **Step 2: Allineare timezone e verificare le versioni**

```bash
timedatectl set-timezone Europe/Rome
timedatectl | head -4
python3 -V
ffmpeg -version | head -1
nginx -v
```

Atteso: `Europe/Rome`, `Python 3.12.3`, `ffmpeg 6.1.1`, `nginx 1.30.x`. Se Python o ffmpeg differiscono in modo sostanziale (minor version diversa), **fermarsi e segnalare**: il runtime non sarebbe più equivalente a quello collaudato in produzione.

- [x] **Step 3: Creare lo swap da 4 GB**

Il vecchio server ha 512 MB di swap saturi al 100%; il nuovo non ne ha affatto. Senza swap, un picco di RAM provoca OOM-kill del servizio invece di un rallentamento.

```bash
fallocate -l 4G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
printf 'vm.swappiness=10\n' > /etc/sysctl.d/99-abm-swap.conf
sysctl -p /etc/sysctl.d/99-abm-swap.conf
```

- [x] **Step 4: Verificare lo swap**

```bash
swapon --show
free -h
```

Atteso: `/swapfile` da 4 GB, `Swap: 4.0Gi`. Verificare anche che `/etc/fstab` contenga la riga (un reboot senza di essa perderebbe lo swap silenziosamente).

- [x] **Step 5: Configurare il firewall**

```bash
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
ufw status verbose
```

Atteso: `Status: active`, tre regole ALLOW. **Verificare di non aver perso la sessione SSH** prima di proseguire (la 22 è aperta, quindi non dovrebbe accadere).

- [x] **Step 6: Configurare la retention di journald**

```bash
mkdir -p /etc/systemd/journald.conf.d
cat > /etc/systemd/journald.conf.d/retention.conf << 'EOF'
[Journal]
Storage=persistent
SystemMaxUse=4G
SystemKeepFree=2G
MaxRetentionSec=14day
MaxFileSec=1day
EOF
systemctl restart systemd-journald
journalctl --disk-usage
```

Atteso: journald riavviato senza errori.

---

### Task 2: Canale di trasferimento OLD → NEW

**Files:**
- Create su OLD: `~/.ssh/id_migrate`, `~/.ssh/id_migrate.pub`
- Modify su NEW: `/root/.ssh/authorized_keys`

**Interfaces:**
- Consumes: Task 1 (rsync installato su NEW).
- Produces: `ssh -i ~/.ssh/id_migrate root@80.211.137.33` funzionante dal vecchio server senza password. È il canale usato da tutti i task successivi per copiare dati e segreti.

- [x] **Step 1: Generare la chiave dedicata sul vecchio server**

```bash
ssh-keygen -t ed25519 -N '' -C 'migrate-2026-08' -f /root/.ssh/id_migrate
cat /root/.ssh/id_migrate.pub
```

- [x] **Step 2: Autorizzare la chiave sul nuovo server**

Copiare l'output di `id_migrate.pub` e, **sul nuovo server**:

```bash
mkdir -p /root/.ssh
chmod 700 /root/.ssh
echo '<CONTENUTO_ID_MIGRATE_PUB>' >> /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys
```

- [x] **Step 3: Verificare il canale dal vecchio server**

```bash
ssh -i /root/.ssh/id_migrate -o StrictHostKeyChecking=accept-new \
  root@80.211.137.33 'hostname; df -h / | tail -1'
```

Atteso: `MiniLinux2` e la riga del filesystem. Se chiede una password, la chiave non è stata autorizzata correttamente: **fermarsi**, non proseguire con password in chiaro negli script.

- [x] **Step 4: Misurare la banda disponibile fra i due server**

```bash
dd if=/dev/zero bs=1M count=512 2>/dev/null | \
  ssh -i /root/.ssh/id_migrate root@80.211.137.33 'cat > /tmp/bwtest; ls -l /tmp/bwtest; rm -f /tmp/bwtest'
```

Cronometrare: serve a stimare la durata del rsync dei 23 GB e, soprattutto, quella della passata delta durante il freeze. Annotare il throughput osservato.

---

### Task 3: Codice applicativo e runtime Python su NEW

**Files:**
- Create su NEW: `/opt/audiobook-maker` (clone git), `/root/pip_freeze_old.txt`
- Create su OLD: `/root/pip_freeze_old.txt`

**Interfaces:**
- Consumes: Task 2 (canale SSH).
- Produces: `/opt/audiobook-maker` al commit `d6a7992` con tutte le dipendenze Python installate alle stesse versioni della produzione.

- [x] **Step 1: Congelare l'elenco pacchetti del vecchio server**

Sul vecchio:

```bash
pip list --format=freeze > /root/pip_freeze_old.txt
wc -l /root/pip_freeze_old.txt
scp -i /root/.ssh/id_migrate /root/pip_freeze_old.txt root@80.211.137.33:/root/
```

Atteso: ~158 righe.

- [x] **Step 2: Clonare il repository sul nuovo server e allinearlo al commit di produzione**

```bash
git clone https://github.com/gfrangiamone/audiobook-maker.git /opt/audiobook-maker
cd /opt/audiobook-maker
git checkout d6a7992
git rev-parse --short HEAD
```

Atteso: `d6a7992`. Se il commit non esiste sul remoto, **fermarsi**: significa che la produzione gira su codice non pushato e va indagato prima di migrare.

- [x] **Step 3: Installare le dipendenze Python alle versioni di produzione**

```bash
pip install --break-system-packages -r /root/pip_freeze_old.txt 2>&1 | tail -20
```

Se alcuni pacchetti falliscono perché installati via apt sul vecchio (es. `python3-*` di sistema), installarli con apt e rilanciare. Non forzare versioni non disponibili: annotare ogni divergenza.

- [x] **Step 4: Verificare la parità delle dipendenze**

Sul nuovo:

```bash
pip list --format=freeze > /root/pip_freeze_new.txt
diff <(sort /root/pip_freeze_old.txt) <(sort /root/pip_freeze_new.txt) > /root/pip_diff.txt
wc -l /root/pip_diff.txt
cat /root/pip_diff.txt
```

Atteso: diff vuoto o limitato a pacchetti irrilevanti per l'app. Verificare esplicitamente che coincidano: `edge-tts 7.2.8`, `boto3 1.34.46`, `google-genai 2.3.0`, `google-cloud-texttospeech 2.36.0`, `PyMuPDF 1.27.2.2`, `Flask 3.1.3`, `EbookLib 0.20`, `openai 2.32.0`. **Qualsiasi differenza su questi otto è bloccante.**

- [x] **Step 5: Verificare che il codice compili**

**Non** usare `python3 -c "import audiobook_app"`: importare l'entry-point lo **riesegue** (incidente noto: doppio avvio del modulo con cleanup e recovery duplicati). Usare il solo controllo di sintassi:

```bash
cd /opt/audiobook-maker
python3 -m py_compile audiobook_app.py generation_engine.py audio_utils.py tts_split.py \
  epub_to_tts.py pdf_to_tts.py google_tts.py email_service.py payment.py assembly_queue.py
echo "compile OK"
```

Atteso: `compile OK` senza traceback. **Non lanciare l'app in questo task.**

---

### Task 4: Utenti, segreti, unit systemd (servizio ancora fermo)

**Files:**
- Create su NEW: utenti `ubuntu`/`backupuser`/`frangiamone`, `/etc/audiobook-maker/`, `/etc/systemd/system/audiobook-maker.service`, `/etc/systemd/system/audiobook-maker.service.d/override.conf`

**Interfaces:**
- Consumes: Task 2 (canale SSH), Task 3 (codice presente).
- Produces: servizio `audiobook-maker` installato, configurato con le ~60 variabili `ABM_*` della produzione, ma **disabilitato e fermo**.

- [x] **Step 1: Ricreare gli utenti sul nuovo server**

```bash
id ubuntu >/dev/null 2>&1 || useradd -m -s /bin/bash -u 1000 ubuntu
id backupuser >/dev/null 2>&1 || useradd -m -s /bin/rbash -u 1001 backupuser
id frangiamone >/dev/null 2>&1 || useradd -m -s /bin/bash -u 1002 frangiamone
awk -F: '$3>=1000 && $3<65000 {print $1, $3, $6, $7}' /etc/passwd
```

Atteso: i tre utenti con gli stessi UID del vecchio server (rilevanti perché `rsync --numeric-ids` preserverà gli owner numerici dei file).

- [x] **Step 2: Copiare le `authorized_keys` dal vecchio server**

Dal vecchio:

```bash
for U in root ubuntu backupuser frangiamone; do
  H=$(getent passwd "$U" | cut -d: -f6)
  [ -f "$H/.ssh/authorized_keys" ] && \
    ssh -i /root/.ssh/id_migrate root@80.211.137.33 "mkdir -p $H/.ssh && chmod 700 $H/.ssh" && \
    scp -i /root/.ssh/id_migrate "$H/.ssh/authorized_keys" "root@80.211.137.33:$H/.ssh/authorized_keys.from_old"
done
```

Sul nuovo, fondere senza perdere la chiave di migrazione:

```bash
for U in root ubuntu backupuser frangiamone; do
  H=$(getent passwd "$U" | cut -d: -f6)
  if [ -f "$H/.ssh/authorized_keys.from_old" ]; then
    cat "$H/.ssh/authorized_keys.from_old" >> "$H/.ssh/authorized_keys"
    sort -u "$H/.ssh/authorized_keys" -o "$H/.ssh/authorized_keys"
    rm -f "$H/.ssh/authorized_keys.from_old"
    chown -R "$U": "$H/.ssh"
    chmod 600 "$H/.ssh/authorized_keys"
  fi
done
grep -c . /root/.ssh/authorized_keys
```

**Verifica critica:** la chiave privata di deploy di GitHub Actions corrisponde a una chiave pubblica in `/root/.ssh/authorized_keys`. Se manca, dopo il cutover il deploy fallirà con `Permission denied`.

- [x] **Step 3: Copiare le credenziali Google**

Dal vecchio:

```bash
ssh -i /root/.ssh/id_migrate root@80.211.137.33 'mkdir -p /etc/audiobook-maker'
rsync -a -e "ssh -i /root/.ssh/id_migrate" /etc/audiobook-maker/ root@80.211.137.33:/etc/audiobook-maker/
```

Verificare inoltre dove punta davvero `ABM_GOOGLE_CREDENTIALS_FILE`: nell'env di produzione il percorso inizia per `/opt/a...`, quindi il file potrebbe stare **dentro `/opt/audiobook-maker`** (directory `credentials/`, non tracciata da git) e non in `/etc/audiobook-maker`. Dal vecchio:

```bash
tr '\0' '\n' < /proc/$(pgrep -f audiobook_app.py | head -1)/environ | grep -E 'CREDENTIALS|GOOGLE_APPLICATION'
ls -la /opt/audiobook-maker/credentials/ 2>/dev/null
```

Copiare il percorso realmente in uso:

```bash
rsync -a -e "ssh -i /root/.ssh/id_migrate" /opt/audiobook-maker/credentials/ \
  root@80.211.137.33:/opt/audiobook-maker/credentials/
```

- [x] **Step 4: Copiare unit systemd e override con le variabili d'ambiente**

Preparare prima la directory sul nuovo server (rsync su un percorso-file non la crea):

```bash
ssh -i /root/.ssh/id_migrate root@80.211.137.33 \
  'mkdir -p /etc/systemd/system/audiobook-maker.service.d'
```

Poi, dal vecchio:

```bash
rsync -a -e "ssh -i /root/.ssh/id_migrate" \
  /etc/systemd/system/audiobook-maker.service \
  root@80.211.137.33:/etc/systemd/system/audiobook-maker.service
rsync -a -e "ssh -i /root/.ssh/id_migrate" \
  /etc/systemd/system/audiobook-maker.service.d/override.conf \
  root@80.211.137.33:/etc/systemd/system/audiobook-maker.service.d/override.conf
```

(Non copiare `override.conf.bak`: è uno scarto storico.)

- [x] **Step 5: Verificare che le variabili siano arrivate integre**

Sul nuovo, **senza stampare i valori**:

```bash
grep -c '^Environment=' /etc/systemd/system/audiobook-maker.service.d/override.conf
grep -oE '^Environment="[A-Z_]+' /etc/systemd/system/audiobook-maker.service.d/override.conf | sed 's/Environment="//' | sort > /root/env_keys_new.txt
wc -l /root/env_keys_new.txt
```

Dal vecchio, confrontare l'elenco delle **chiavi** (non dei valori):

```bash
grep -oE '^Environment="[A-Z_]+' /etc/systemd/system/audiobook-maker.service.d/override.conf | sed 's/Environment="//' | sort > /root/env_keys_old.txt
scp -i /root/.ssh/id_migrate /root/env_keys_old.txt root@80.211.137.33:/root/
```

Sul nuovo:

```bash
diff /root/env_keys_old.txt /root/env_keys_new.txt && echo "ENV KEYS OK"
```

Atteso: `ENV KEYS OK`.

- [x] **Step 6: Ricaricare systemd lasciando il servizio fermo e disabilitato**

```bash
systemctl daemon-reload
systemctl disable audiobook-maker 2>/dev/null || true
systemctl is-active audiobook-maker || echo "fermo (corretto)"
systemctl is-enabled audiobook-maker || echo "disabilitato (corretto)"
```

Atteso: fermo e disabilitato. **Non avviare il servizio in questo task** — girerebbe sulla data dir reale e sul bucket R2 condiviso, in parallelo alla produzione.

---

### Task 5: Nginx, certificati TLS, cron e fail2ban

**Files:**
- Create su NEW: `/etc/nginx/sites-available/audiobook-maker`, symlink in `sites-enabled`, `/etc/letsencrypt/*`, `/etc/fail2ban/jail.local`, `/etc/fail2ban/jail.d/*`, `/etc/cron.d/abm-cleanup-stale`, crontab di root, `/opt/backup_ABM.sh`, `/opt/check_disk_space.sh`

**Interfaces:**
- Consumes: Task 1 (nginx, certbot, fail2ban installati), Task 2 (canale SSH).
- Produces: nginx che risponde in HTTPS con il certificato valido di `audiobook-maker.com`; cron e fail2ban allineati (con il bug del cron disco corretto).

- [x] **Step 1: Copiare configurazione nginx e certificati**

Dal vecchio:

```bash
rsync -a -e "ssh -i /root/.ssh/id_migrate" /etc/nginx/sites-available/audiobook-maker \
  root@80.211.137.33:/etc/nginx/sites-available/audiobook-maker
rsync -a -e "ssh -i /root/.ssh/id_migrate" /etc/nginx/nginx.conf \
  root@80.211.137.33:/root/nginx.conf.from_old
rsync -aL -e "ssh -i /root/.ssh/id_migrate" /etc/letsencrypt/ \
  root@80.211.137.33:/etc/letsencrypt/
```

Nota: `-L` risolve i symlink di `live/` in file reali. Dopo la copia, sul nuovo server `live/` conterrà file veri anziché link ad `archive/`: è sufficiente per servire il traffico, e al primo rinnovo certbot ricostruirà la struttura corretta.

Il vhost `test.audiobook-maker.com` **non** va copiato (fuori scope).

- [x] **Step 2: Confrontare `nginx.conf` globale e recepire le differenze**

```bash
diff /root/nginx.conf.from_old /etc/nginx/nginx.conf
```

Se il vecchio ha personalizzazioni (worker, `client_max_body_size` globale, gzip, log format), riportarle. Le `limit_req_zone` di `app_limit`/`upload_limit` stanno in cima al vhost del sito, quindi arrivano già con il file del Step 1.

- [x] **Step 3: Abilitare il sito e validare la configurazione**

```bash
ln -sf /etc/nginx/sites-available/audiobook-maker /etc/nginx/sites-enabled/audiobook-maker
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl reload nginx
```

Atteso: `syntax is ok` / `test is successful`. Se `nginx -t` lamenta certificati mancanti, verificare i percorsi in `ssl_certificate` rispetto a quanto copiato in `/etc/letsencrypt/live/audiobook-maker.com/`.

- [x] **Step 4: Verificare il certificato servito dal nuovo server**

Dal PC locale (PowerShell o bash), forzando la risoluzione senza toccare il DNS:

```bash
curl -sv --resolve audiobook-maker.com:443:80.211.137.33 https://audiobook-maker.com/ 2>&1 | grep -E "subject:|issuer:|expire|HTTP/"
```

Atteso: subject `CN=audiobook-maker.com`, issuer Let's Encrypt, data di scadenza valida. Il codice HTTP sarà 502 (backend fermo): **è corretto in questa fase**.

- [x] **Step 5: Copiare gli script di ops e correggere il cron del controllo disco**

Dal vecchio:

```bash
rsync -a -e "ssh -i /root/.ssh/id_migrate" /opt/backup_ABM.sh /opt/check_disk_space.sh \
  root@80.211.137.33:/opt/
rsync -a -e "ssh -i /root/.ssh/id_migrate" /etc/cron.d/abm-cleanup-stale \
  root@80.211.137.33:/etc/cron.d/abm-cleanup-stale
```

Sul nuovo, installare la crontab di root **con il percorso corretto** dello script disco (sul vecchio il cron invoca `/opt/check_disk.sh`, che non esiste: il controllo fallisce in silenzio da mesi):

```bash
cat > /root/crontab.abm << 'EOF'
0 1 * * * /opt/backup_ABM.sh >> /var/log/abm_backup.log 2>&1
30 3 * * * [ -n "$(find /opt/backup -maxdepth 1 -type f -mtime -10 -print -quit)" ] && find /opt/backup -maxdepth 1 -type f -mtime +10 -delete
0 */2 * * * /opt/check_disk_space.sh >> /var/log/disk_check.log 2>&1
EOF
crontab /root/crontab.abm
crontab -l
chmod +x /opt/backup_ABM.sh /opt/check_disk_space.sh
```

- [x] **Step 6: Verificare che lo script disco funzioni davvero**

```bash
bash /opt/check_disk_space.sh; echo "exit=$?"
```

Atteso: esecuzione senza errori (exit 0). Se lo script invia email, verificare che non fallisca per postfix non configurato; in tal caso annotare e proseguire — non è bloccante per il cutover.

- [x] **Step 7: Replicare fail2ban**

Dal vecchio:

```bash
rsync -a -e "ssh -i /root/.ssh/id_migrate" /etc/fail2ban/jail.local \
  root@80.211.137.33:/etc/fail2ban/jail.local
rsync -a -e "ssh -i /root/.ssh/id_migrate" /etc/fail2ban/jail.d/ \
  root@80.211.137.33:/etc/fail2ban/jail.d/
```

Sul nuovo:

```bash
systemctl enable --now fail2ban
fail2ban-client status
```

Atteso: jail `sshd` e `nginx-badbots` attive. La `ignoreip` include l'IP dell'ufficio: verificarlo, altrimenti un errore di digitazione della password può bannare l'operatore durante il cutover.

- [x] **Step 8: Verificare rsyslog**

```bash
systemctl is-active rsyslog
ls -la /var/log/syslog
```

Atteso: `active` e file presente. È la fonte forense principale (retention 3-4 settimane): senza rsyslog si perde la tracciabilità delle cancellazioni dei job.

---

### Task 6: Prima sincronizzazione dati (a produzione viva)

**Files:**
- Create su NEW: `/opt/audiobook-maker/data` (23 GB), `/opt/backup`, `activity_*.log`

**Interfaces:**
- Consumes: Task 2 (canale SSH), Task 3 (`/opt/audiobook-maker` esistente).
- Produces: copia completa dei dati di produzione al tempo T, da aggiornare con la passata delta del Task 8.

- [x] **Step 1: Verificare lo spazio disponibile sul nuovo server**

```bash
df -h /opt
du -sh /opt/audiobook-maker/data 2>/dev/null || echo "data non ancora presente"
```

Atteso: almeno 30 GB liberi su NEW (servono 23 GB più margine di crescita).

- [x] **Step 2: Lanciare la copia dei dati in sessione persistente**

Dal vecchio, dentro `screen`/`nohup` perché la copia dura a lungo:

```bash
nohup rsync -aHAX --numeric-ids --info=progress2 \
  -e "ssh -i /root/.ssh/id_migrate" \
  /opt/audiobook-maker/data/ root@80.211.137.33:/opt/audiobook-maker/data/ \
  > /root/rsync_data_pass1.log 2>&1 &
echo $!
```

- [x] **Step 3: Seguire l'avanzamento**

```bash
tail -f /root/rsync_data_pass1.log
```

Al termine, verificare che il log non contenga errori:

```bash
grep -iE "error|failed|denied" /root/rsync_data_pass1.log | head -20
tail -3 /root/rsync_data_pass1.log
```

- [x] **Step 4: Copiare log di attività, backup e script di ops**

```bash
rsync -a -e "ssh -i /root/.ssh/id_migrate" /opt/audiobook-maker/activity_*.log \
  root@80.211.137.33:/opt/audiobook-maker/
rsync -a -e "ssh -i /root/.ssh/id_migrate" /opt/backup/ \
  root@80.211.137.33:/opt/backup/
```

- [x] **Step 5: Confrontare i due lati**

Sul vecchio:

```bash
du -sh /opt/audiobook-maker/data
find /opt/audiobook-maker/data -maxdepth 1 -mindepth 1 -type d | wc -l
```

Sul nuovo, gli stessi due comandi. Atteso: dimensioni e conteggio job coerenti (la produzione è viva, quindi una piccola differenza è normale e verrà colmata dalla passata delta).

---

### Task 7: Collaudo isolato dal browser

**Files:**
- Create su NEW: `/etc/systemd/system/audiobook-maker.service.d/zz-collaudo.conf`, `/opt/audiobook-maker/data_collaudo`
- Modify sul PC dell'utente: `C:\Windows\System32\drivers\etc\hosts`

**Interfaces:**
- Consumes: Task 4 (servizio installato), Task 5 (nginx + TLS), Task 6 (dati presenti).
- Produces: conferma che il nuovo server esegue correttamente l'intero flusso applicativo. Al termine l'override di collaudo viene **rimosso** e `data_collaudo` cancellata.

- [x] **Step 1: Creare l'override di collaudo**

Il file `zz-collaudo.conf` viene letto **dopo** `override.conf` (ordine alfabetico), quindi le sue variabili vincono. Isola il collaudo dai dati reali e dal bucket R2 condiviso.

```bash
cat > /etc/systemd/system/audiobook-maker.service.d/zz-collaudo.conf << 'EOF'
[Service]
Environment="ABM_DATA_DIR=/opt/audiobook-maker/data_collaudo"
Environment="ABM_S3_ENDPOINT="
Environment="ABM_S3_ACCESS_KEY="
Environment="ABM_S3_SECRET_KEY="
Environment="ABM_S3_BUCKET="
EOF
mkdir -p /opt/audiobook-maker/data_collaudo
systemctl daemon-reload
```

- [x] **Step 2: Verificare l'isolamento PRIMA di avviare**

```bash
systemctl show audiobook-maker -p Environment | tr ' ' '\n' | grep -E 'ABM_DATA_DIR|ABM_S3_BUCKET|ABM_S3_ENDPOINT'
```

Atteso: `ABM_DATA_DIR=/opt/audiobook-maker/data_collaudo` e le variabili S3 **vuote**. Se `ABM_DATA_DIR` mostra ancora la data dir reale o `ABM_S3_BUCKET=audiobook-maker`, **non avviare**: il cleanup loop cancellerebbe job di produzione, in locale e su R2.

- [x] **Step 3: Avviare il servizio (senza abilitarlo al boot)**

```bash
systemctl start audiobook-maker
sleep 5
systemctl status audiobook-maker --no-pager | head -15
journalctl -u audiobook-maker -n 40 --no-pager
```

Nel log di avvio verificare le righe di configurazione: limite globale (`6`), slot di assembly, cold storage **disattivato**.

- [x] **Step 4: Smoke test locale**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5601/
curl -s http://127.0.0.1:5601/sitemap.xml | head -5
```

Atteso: `200` e sitemap valida.

- [x] **Step 5: Puntare il dominio al nuovo server sul PC dell'utente**

In PowerShell **come amministratore**:

```powershell
Add-Content -Path C:\Windows\System32\drivers\etc\hosts -Value "80.211.137.33 audiobook-maker.com www.audiobook-maker.com"
ipconfig /flushdns
Resolve-DnsName audiobook-maker.com -Type A | Select-Object Name, IPAddress
```

Atteso: `80.211.137.33`. Da questo momento **solo il PC dell'utente** vede il nuovo server; il resto del mondo continua a usare la produzione.

- [x] **Step 6: Collaudo funzionale dal browser (eseguito dall'utente)**

Percorso completo su `https://audiobook-maker.com`:

1. Upload di un EPUB e di un PDF → capitoli estratti, copertina, anteprima testo.
2. Ottimizzazione AI su un libro **sotto la soglia gratuita** (nessun pagamento).
3. Anteprima voce standard e anteprima voce PREMIUM.
4. Generazione completa formato M4B → download e riproduzione del file.
5. Generazione formato ZIP per capitoli.
6. Modalità email/batch → arrivo dell'email di consegna e funzionamento del link `/dl/<token>`.
7. Voucher: creazione via CLI admin nella data dir di collaudo e utilizzo.
8. Pagina admin (`/admin/vouchers`) e `/logs` con il token di amministrazione.

**Vincolo:** nessun pagamento PayPal reale — finirebbe in `_payments.json` della data dir di collaudo, che viene distrutta.

- [x] **Step 7: Controllare i log del collaudo**

```bash
journalctl -u audiobook-maker --since "1 hour ago" --no-pager | grep -iE "error|traceback|exception" | head -30
free -h
df -h /opt
```

Atteso: nessuna eccezione non gestita. Annotare eventuali warning.

- [x] **Step 8: Chiudere il collaudo e ripristinare l'isolamento**

```bash
systemctl stop audiobook-maker
rm -f /etc/systemd/system/audiobook-maker.service.d/zz-collaudo.conf
rm -rf /opt/audiobook-maker/data_collaudo
systemctl daemon-reload
systemctl show audiobook-maker -p Environment | tr ' ' '\n' | grep -E 'ABM_DATA_DIR|ABM_S3_BUCKET'
```

Atteso: `ABM_DATA_DIR=/opt/audiobook-maker/data` e `ABM_S3_BUCKET=audiobook-maker` (valori di produzione ripristinati), servizio **fermo**.

L'utente lascia per ora la riga nel file hosts: servirà per la verifica immediata dopo il cutover.

---

### Task 8: Cutover — drenaggio, freeze, ripresa dei job, switch DNS

**Files:**
- Create su OLD e NEW: `/root/migration_live_jobs.py`, `/root/migration_recover_prep.py`
- Create su OLD: `/etc/nginx/sites-available/audiobook-maker.cutover` (proxy verso il nuovo)
- Modify su OLD: stato dei servizi (`stop` + `disable` + `mask`), vhost nginx
- Modify su NEW: `/etc/nginx/nginx.conf` (`set_real_ip_from` del vecchio),
  `/etc/systemd/system/audiobook-maker.service.d/override.conf` (segreti ruotati),
  `/opt/audiobook-maker/data/_pending_jobs.json` (igiene del registro),
  `/etc/cron.d/abm-cleanup-stale` (ripristino)
- Modify su Aruba: record A di `audiobook-maker.com` e `www`

**Interfaces:**
- Consumes: Task 7 (collaudo superato), `scripts/migration/migration_live_jobs.py` e
  `scripts/migration/migration_recover_prep.py` (nel repo, già collaudati contro la produzione).
- Produces: produzione servita da `80.211.137.33` con i job batch interrotti ripresi dal punto
  in cui erano.

#### Perché serve un drenaggio (e non una semplice attesa)

La produzione ha statisticamente **~35-40 job vivi** in un istante qualsiasi: aspettare che siano
zero è impossibile. Il criterio non è "nessun job vivo" ma **"nessun job BLOCCANTE"**, dove:

| Categoria | Che cosa succede allo stop | Verdetto |
|---|---|---|
| Batch registrato (`_pending_jobs.json`) con motore `edge`/`gemini`/`google` | Al riavvio `_recover_orphan_jobs()` lo rilancia e `chunk_reuse` riparte dai chunk già sintetizzati (il fingerprint è ancorato al **contenuto**, non ai path: sopravvive alla migrazione) | **RECUPERABILE** |
| Interattivo `edge` non registrato | L'utente perde la sessione; nessun costo, nessun lavoro pagato | **SACRIFICABILE** |
| Qualunque job `speechify` | `REUSABLE_ENGINES` non include Speechify: il recovery **risintetizza da zero** e ri-paga l'intero job | **BLOCCANTE** |
| `gemini`/`google` non registrato | Nessun descrittore ⇒ nessun recovery: i chunk già pagati restano su disco senza che nessuno li riprenda | **BLOCCANTE** |
| Job con pagamento consumato e non concluso, anche **senza chunk** (ottimizzazione AI interattiva) | Nessun recovery: soldi incassati e lavoro perso | **BLOCCANTE** |

Il browser non aiuta: l'`EventSource` del frontend ritenta 5 volte con backoff lineare
(`app.js:3777` e `app.js:3975`), cioè ~30 s di tolleranza. Chi sta guardando la barra di
avanzamento la perde comunque; per questo l'unica cosa da proteggere è il **lavoro pagato**.

Il drenaggio si ottiene con il kill-switch già presente in `audiobook_app.py`: `POST
/api/admin/suspend` alza `_suspend_new_jobs`, che viene controllato in `/api/analyze`,
`/api/generate` (**prima** del preflight di pagamento, quindi nessuno paga per un job che verrà
rifiutato) e `/api/optimize`. I download e le pagine restano funzionanti.

- [ ] **Step 1: T-7h — abbassare il TTL su Aruba (eseguito dall'utente)**

Nel pannello DNS Aruba, per i record A `audiobook-maker.com` e `www`: TTL da 21600 a **300**.
Nessun altro cambiamento.

Verifica dopo qualche minuto:

```bash
dig +noall +answer audiobook-maker.com @8.8.8.8
```

Attendere che il TTL riportato sia ≤300 prima di procedere al freeze.

- [ ] **Step 2: Portare gli strumenti di migrazione sui due server**

Dal PC (PowerShell, dalla cartella del repo):

```powershell
pscp -batch -pw "<password root>" scripts\migration\migration_live_jobs.py root@80.211.136.211:/root/
pscp -batch -pw "<password root>" scripts\migration\migration_recover_prep.py root@80.211.137.33:/root/
```

`migration_live_jobs.py` è **sola lettura**: classifica i job vivi e restituisce exit code
`0` se non ci sono bloccanti, `2` se ce ne sono. `migration_recover_prep.py` gira **solo sul
nuovo server**, a servizio fermo (rifiuta di applicare modifiche se trova un processo vivo).

- [ ] **Step 3: Fotografia iniziale dei job vivi (nessun impatto)**

Sul vecchio server:

```bash
python3 /root/migration_live_jobs.py --data-dir /opt/audiobook-maker/data --window-min 10
```

Serve a sapere da dove si parte: quanti job vivi, quanti bloccanti, quanti recuperabili.
Se i bloccanti sono già zero il drenaggio sarà breve; se c'è un job Speechify da 500 chunk
appena partito, si tratta di attendere anche 30-40 minuti.

- [ ] **Step 4: Attivare il drenaggio (blocco dei nuovi job)**

Il token admin **non è nell'ambiente della shell SSH**: sta nell'unit systemd. Va letto dal
processo di produzione, che è quello con `MainPID` dell'unit `audiobook-maker` — **non** il
primo risultato di `pgrep`, che sul vecchio server è il servizio di *test* (`/opt/audiobook-maker-test`):

```bash
PID=$(systemctl show audiobook-maker -p MainPID --value)
ADMIN_TOKEN=$(tr '\0' '\n' < /proc/$PID/environ | sed -n 's/^ABM_ADMIN_TOKEN=//p')
[ -n "$ADMIN_TOKEN" ] && echo "token letto" || echo "TOKEN NON LETTO - fermarsi"

curl -s -X POST http://127.0.0.1:5601/api/admin/suspend \
  -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
  -d '{"suspend": true}'
```

Atteso: `{"suspended":true}`. Da questo momento upload, ottimizzazioni e generazioni nuove
ricevono `503 System under maintenance.`; i job in corso proseguono, i download funzionano.

**Non stampare il token.** Se serve rileggerlo, ripetere il comando: resta solo nella variabile
di shell della sessione.

- [ ] **Step 5: Attendere fino a zero job BLOCCANTI**

```bash
while true; do
  python3 /root/migration_live_jobs.py --data-dir /opt/audiobook-maker/data \
    --window-min 10 --quiet && break
  sleep 300
done
```

Il ciclo esce quando l'exit code è `0`. Ogni tanto, per vedere il dettaglio, rieseguire lo
script senza `--quiet`.

Se un bloccante resta tale oltre **60 minuti** (tipicamente un job Speechify lungo), fermarsi e
riportare la situazione all'utente: le opzioni sono attendere ancora oppure accettare la perdita
e rimborsare quel singolo job nello Step 24. Non decidere da soli.

- [ ] **Step 6: Snapshot forense dei job che verranno interrotti**

Prima di fermare il servizio, congelare l'elenco: serve allo Step 24 per verificare che nessuno
sia rimasto indietro.

```bash
STAMP=$(date +%Y%m%d-%H%M)
python3 /root/migration_live_jobs.py --data-dir /opt/audiobook-maker/data --window-min 15 \
  > /root/migration_snapshot_$STAMP.txt 2>&1
cp /opt/audiobook-maker/data/_pending_jobs.json /root/migration_pending_$STAMP.json
wc -l /root/migration_snapshot_$STAMP.txt
```

Copiarlo sul nuovo server (sopravvive alla dismissione del vecchio):

```bash
rsync -a -e "ssh -i /root/.ssh/id_migrate" /root/migration_snapshot_*.txt \
  /root/migration_pending_*.json root@80.211.137.33:/root/
```

- [ ] **Step 7: STOP — attendere il via libera esplicito dell'utente**

Riportare: numero di job vivi per categoria, bloccanti a zero, TTL propagato, esito del collaudo.
**Non proseguire** senza un "vai" esplicito. Da qui in avanti la produzione va giù.

- [ ] **Step 8: Fermare, disabilitare e mascherare il servizio sul vecchio server**

```bash
systemctl stop audiobook-maker
systemctl disable audiobook-maker
systemctl mask audiobook-maker
systemctl is-active audiobook-maker || echo "fermo"
systemctl is-enabled audiobook-maker
```

Atteso: `fermo` e `masked`. `disable` non basta: `mask` impedisce anche un avvio manuale o
per dipendenza. Se la macchina si riavviasse durante la finestra di rollback, un servizio
riattivato cancellerebbe i dati del nuovo server attraverso il bucket R2 condiviso — è
l'invariante "mai due processi vivi" del design.

Il servizio `audiobook-maker-test` resta **acceso**: usa una data dir diversa e non ha
credenziali R2 di produzione (verificarlo prima di lasciarlo su: `systemctl show
audiobook-maker-test -p MainPID --value`, poi `tr '\0' '\n' < /proc/<pid>/environ | grep -c
ABM_S3_BUCKET`; se il conteggio non è `0`, fermare anche il test).

- [ ] **Step 9: Trasformare il vecchio nginx in proxy verso il nuovo**

Meglio di una pagina 503: durante la propagazione DNS (5-15 minuti con TTL 300) chi arriva
ancora sul vecchio IP viene servito dal nuovo server, senza vedere disservizio.

```bash
cp /etc/nginx/sites-available/audiobook-maker /etc/nginx/sites-available/audiobook-maker.precutover
```

Nel `server` block HTTPS di `audiobook-maker.com`, sostituire il blocco `location / { proxy_pass
http://127.0.0.1:5601; ... }` con:

```
location / {
    proxy_pass https://80.211.137.33;
    proxy_ssl_server_name on;
    proxy_ssl_name audiobook-maker.com;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header CF-Connecting-IP $remote_addr;
    proxy_http_version 1.1;
    proxy_buffering off;
    proxy_read_timeout 600s;
    client_max_body_size 200M;
}
```

Le tre righe di header non sono decorative:

- `X-Forwarded-For $proxy_add_x_forwarded_for` accoda l'IP reale in testa alla catena.
  L'applicazione prende **sempre il primo valore** (`audiobook_app.py:840`), quindi il doppio
  hop non falsifica l'IP registrato nei log e nei rate limit applicativi.
- `CF-Connecting-IP $remote_addr` serve a nginx del **nuovo** server: il suo `real_ip_header` è
  `CF-Connecting-IP` (residuo di una configurazione Cloudflare, `nginx.conf:58`). Senza questo,
  `$binary_remote_addr` varrebbe `80.211.136.211` per **tutto** il traffico proxato e la
  `limit_req` da 10 r/s lo tratterebbe come un solo client, restituendo 503 a raffica.
  Il valore viene sovrascritto dal proxy, quindi non è falsificabile dal client.
- `proxy_ssl_name` fa presentare il SNI corretto: il certificato del nuovo server è quello di
  `audiobook-maker.com`, copiato al Task 5.

Poi:

```bash
nginx -t && systemctl reload nginx
```

La verifica funzionale si fa allo Step 18, quando il nuovo servizio è acceso.

- [ ] **Step 10: Autorizzare il vecchio server come proxy sul nuovo nginx**

Sul **nuovo** server, nel blocco `http` di `/etc/nginx/nginx.conf`, subito dopo l'ultimo
`set_real_ip_from` dei range Cloudflare:

```bash
cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.precutover
sed -i '/set_real_ip_from 2c0f:f248::\/32;/a\    set_real_ip_from 80.211.136.211;   # proxy temporaneo dal vecchio server (rimuovere alla dismissione)' /etc/nginx/nginx.conf
grep -n 'set_real_ip_from 80.211' /etc/nginx/nginx.conf
nginx -t && systemctl reload nginx
```

Atteso: una riga trovata, `nginx -t` OK. Questa riga va rimossa al Task 10, quando il vecchio
server viene dismesso: finché c'è, quell'IP è autorizzato a dichiarare l'IP dei client.

- [ ] **Step 11: Chiudere il collaudo (pre-condizione) ed eseguire la delta**

> Se il servizio di collaudo sul nuovo server fosse ancora in esecuzione, il suo cleanup loop
> lavorerebbe su una data dir che sta per diventare quella reale. Verificare **prima** della
> sincronizzazione:
>
> ```bash
> systemctl is-active audiobook-maker || echo "fermo"
> ls -d /opt/audiobook-maker/data_collaudo 2>/dev/null && echo "RESIDUO DA RIMUOVERE"
> test -f /etc/systemd/system/audiobook-maker.service.d/zz-collaudo.conf && echo "OVERRIDE COLLAUDO ANCORA PRESENTE"
> ```
>
> Atteso: `fermo` e nessuna delle due segnalazioni (chiuso al Task 7, Step 8).

Sul **vecchio** server:

```bash
rsync -aHAX --numeric-ids --delete --info=progress2 \
  -e "ssh -i /root/.ssh/id_migrate" \
  /opt/audiobook-maker/data/ root@80.211.137.33:/opt/audiobook-maker/data/ \
  2>&1 | tail -5
rsync -a -e "ssh -i /root/.ssh/id_migrate" /opt/audiobook-maker/activity_*.log \
  root@80.211.137.33:/opt/audiobook-maker/
```

`--delete` allinea esattamente i due lati: il nuovo server non deve conservare job che nel
frattempo la produzione ha cancellato per retention. La ricopia degli `activity_*.log`
(che stanno in `SCRIPT_DIR`, non nella data dir) sovrascrive anche gli eventi scritti durante
il collaudo: è voluta.

I chunk già sintetizzati viaggiano con la job dir, quindi il riuso al riavvio è possibile.

- [ ] **Step 12: Verificare l'integrità dei JSON di stato**

Sul vecchio:

```bash
cd /opt/audiobook-maker/data
md5sum *.json | sort -k2 > /tmp/json_md5.txt; cat /tmp/json_md5.txt
find . -maxdepth 1 -mindepth 1 -type d | wc -l
du -sh .
```

Sono **20** i file di stato (agosto 2026): `_client_emails`, `_device_tokens`, `_download_tokens`,
`_free_quota`, `_paid_jobs_done`, `_paid_opt_done`, `_payments`, `_pending_jobs`, `_share_tokens`,
`_transfer_tokens`, `_vouchers`, il service account, `feedback`, `gemini_admin_state`,
`gemini_tts_previews`, `gemini_tts_rate_log`, `gemini_tts_rpd`, `gemini_tts_usage`,
`google_tts_usage`, `news`. Vanno verificati **tutti**, non un sottoinsieme: `_transfer_tokens`
e `gemini_tts_rate_log` pesano da soli oltre 3 MB e reggono rispettivamente i trasferimenti
attivi e il price lock delle voci PREMIUM.

Sul nuovo, gli stessi comandi. Atteso: **md5 identici**, stesso conteggio job, stessa dimensione.
Poi validare la sintassi:

```bash
cd /opt/audiobook-maker/data
for f in *.json; do
  python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$f" 2>/dev/null \
    && echo "$f OK" || echo "$f CORROTTO"
done
```

Atteso: `OK` per ogni file. Un `CORROTTO` è **bloccante**: ricopiare il singolo file prima di
proseguire.

- [ ] **Step 13: Igiene del registro di recovery (sul nuovo, a servizio fermo)**

Al primo avvio `_recover_orphan_jobs()` rilancia **ogni** descrittore non `failed`. Dopo una
migrazione il registro contiene tre casi da trattare prima, altrimenti si producono email
duplicate, rimborsi indebiti o un ciclo di recovery interrotto a metà:

1. job **già consegnati** — `pending_jobs.finalize()` viene chiamato subito dopo l'invio
   dell'email; se lo stop cade nel mezzo, il descrittore sopravvive a un job completo e al boot
   verrebbe rigenerato da capo → `state='failed'`;
2. job con **input mancante** — `_reenqueue_orphan()` solleva `FileNotFoundError`, che risale e
   **interrompe il ciclo**, lasciando non recuperati tutti i descrittori successivi →
   `state='failed'`;
3. job al **cap tentativi** — oltre `ABM_RECOVER_MAX_ATTEMPTS` (default 2) scatta
   `_orphan_fallback()`: rimborso + email "interrotto" + failed. Un job interrotto **da noi**
   non deve consumare quel budget → `attempts=0`.

Prima in simulazione:

```bash
python3 /root/migration_recover_prep.py \
  --data-dir /opt/audiobook-maker/data \
  --script-dir /opt/audiobook-maker
```

Leggere l'elenco "DA RIPRENDERE AL BOOT" e il tempo stimato di recovery (2 s a job). Poi
applicare:

```bash
python3 /root/migration_recover_prep.py \
  --data-dir /opt/audiobook-maker/data \
  --script-dir /opt/audiobook-maker --apply
```

Atteso: `Scritto .../_pending_jobs.json (backup: ..._pending_jobs.json.premigration.bak)`.
Lo script rifiuta di applicare se trova un processo `audiobook_app.py` vivo.

- [ ] **Step 14: Verificare i limiti di capacità sul nuovo server**

I due valori sono già nell'override copiato al Task 4, ma vanno riletti prima di accendere:
il nuovo server riprenderà ~20 job in pochi secondi e non è il momento di scoprire un limite
diverso da quello della produzione.

```bash
grep -E 'ABM_MAX_CONCURRENT_(GLOBAL|ASSEMBLY)' \
  /etc/systemd/system/audiobook-maker.service.d/override.conf
```

Atteso **esattamente**: `ABM_MAX_CONCURRENT_GLOBAL=35` e `ABM_MAX_CONCURRENT_ASSEMBLY=2`.

`35` è il valore con cui **gira davvero** la produzione (letto da `/proc/<MainPID>/environ`),
non i `50` scritti nell'`override.conf` del vecchio server: quelle righe furono modificate dopo
l'ultimo restart e non sono mai entrate in vigore. Partire a 50 significherebbe accettare il
+43% di carico proprio mentre si riprendono i job interrotti. `2` slot di assembly, invece di
`cpu_count()-1 = 3`, tengono a bada gli encode FFmpeg finali: si sale a 3 dopo qualche giorno
di osservazione.

- [ ] **Step 15: Ruotare i segreti esposti**

Due valori sono transitati in chiaro nella chat di lavoro e vanno cambiati **prima** che il
nuovo server diventi pubblico:

- `ABM_S3_SECRET_KEY` — nuova coppia di chiavi dal pannello Cloudflare R2 (API token con
  permessi *Object Read & Write* sul solo bucket `audiobook-maker`);
- `ABM_ADMIN_TOKEN` — nuovo valore casuale, che protegge `/admin/*` e `/logs*`.

```bash
openssl rand -base64 24    # spunto per il nuovo ABM_ADMIN_TOKEN
nano /etc/systemd/system/audiobook-maker.service.d/override.conf
systemctl daemon-reload
```

Aggiornare anche l'`override.conf` del **vecchio** server con gli stessi valori: se si dovesse
tornare indietro nella finestra di rollback, deve poter parlare con R2. Le vecchie chiavi R2
si revocano dal pannello solo **dopo** la verifica dello Step 17.

- [ ] **Step 16: Avviare la produzione sul nuovo server e osservare il recovery**

Il DNS punta ancora al vecchio: si accende in condizioni controllate, con il solo traffico che
arriva dal proxy dello Step 9.

```bash
systemctl unmask audiobook-maker 2>/dev/null
systemctl enable audiobook-maker
systemctl start audiobook-maker
sleep 10
systemctl status audiobook-maker --no-pager | head -12
journalctl -u audiobook-maker -n 120 --no-pager | grep -iE "startup|recover|orphan|data dir|s3|cold|global|assembly"
```

Da verificare nel log di avvio:

| Voce | Atteso |
|---|---|
| data dir | `/opt/audiobook-maker/data` (**non** `data_collaudo`) |
| cold storage | R2 attivo, bucket `audiobook-maker` |
| limite globale | 35 |
| slot di assembly | 2 |
| recovery | un `[recover]` per ciascun job dell'elenco dello Step 13, ~2 s l'uno |
| suspend | assente: il kill-switch è in RAM e muore col processo vecchio |

Confermare che i nuovi job siano accettati:

```bash
curl -s http://127.0.0.1:5601/api/admin/suspend
```

Atteso: `{"suspended":false}`.

- [ ] **Step 17: Verificare che il riuso dei chunk stia funzionando**

È la prova che i job ripresi non stanno risintetizzando (e ri-pagando) da zero:

```bash
journalctl -u audiobook-maker --since "10 min ago" --no-pager \
  | grep -iE "riuso|reuse|chunk riusat|manifest" | head -20
```

Atteso: righe di riuso con un numero di chunk > 0 per i job batch ripresi. Se il riuso risulta
**zero ovunque**, fermarsi e indagare prima che i job PREMIUM ri-consumino budget: il sospetto
è un `plan_sha` diverso (piano di chunk ricostruito con parametri diversi da quelli originali —
tipicamente `ABM_GEMINI_CHUNK_CHARS`, che in produzione vale **450** e sta nell'unit systemd,
non nella shell).

```bash
PID=$(systemctl show audiobook-maker -p MainPID --value)
tr '\0' '\n' < /proc/$PID/environ | grep -E 'ABM_GEMINI_CHUNK_CHARS|ABM_RECOVER'
```

- [ ] **Step 18: Smoke test prima dello switch DNS**

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5601/
```

Dal **vecchio** server, verificare che il proxy dello Step 9 raggiunga il nuovo:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -k https://127.0.0.1/ -H "Host: audiobook-maker.com"
```

Atteso: `200` (non più `502`).

Dal PC dell'utente (che ha ancora la riga nel file hosts), aprire `https://audiobook-maker.com`
e verificare: home page, e soprattutto **un link di download generato prima del freeze**
(`/dl/<token>` da una vecchia email). È la prova che i dati sono migrati integri.

- [ ] **Step 19: Switch DNS su Aruba (eseguito dall'utente)**

Record A `audiobook-maker.com` e `www` → `80.211.137.33`.

```bash
dig +short audiobook-maker.com @8.8.8.8
dig +short audiobook-maker.com @1.1.1.1
```

Atteso: `80.211.137.33` su entrambi i resolver entro ~5 minuti.

- [ ] **Step 20: Rimuovere la riga dal file hosts e verificare dal DNS reale**

In PowerShell come amministratore:

```powershell
$p = "C:\Windows\System32\drivers\etc\hosts"
(Get-Content $p) | Where-Object { $_ -notmatch "audiobook-maker\.com" } | Set-Content $p
ipconfig /flushdns
Resolve-DnsName audiobook-maker.com -Type A | Select-Object Name, IPAddress
```

Atteso: `80.211.137.33` risolto dal DNS pubblico. Aprire il sito e verificare il lucchetto TLS.

Il proxy sul vecchio server **resta attivo** finché il traffico residuo non si azzera (controllo
la mattina dopo: `awk '{print $1}' /var/log/nginx/access.log | wc -l` sulle righe dell'ultima
ora). Va rimosso al Task 10 insieme alla riga `set_real_ip_from` dello Step 10.

- [ ] **Step 21: Ripristinare il cron di pulizia dei job stale**

Era stato sospeso al Task 5 perché `rsync -a` preserva gli mtime e il cron avrebbe cancellato
i dati migrati (cancella alla cieca le job dir con mtime > 25 h) prima del cutover. Ora che il
servizio è vivo e la retention applicativa è di nuovo l'unica autorità, va rimesso:

```bash
mv /root/abm-cleanup-stale.DEFERRED_UNTIL_CUTOVER /etc/cron.d/abm-cleanup-stale
chmod 644 /etc/cron.d/abm-cleanup-stale
chown root:root /etc/cron.d/abm-cleanup-stale
cat /etc/cron.d/abm-cleanup-stale
systemctl restart cron
ls -la /etc/cron.d/
```

Atteso: il file presente in `/etc/cron.d/` con permessi `644 root:root` (un cron file con
permessi diversi viene ignorato in silenzio).

- [ ] **Step 22: Verificare il rinnovo dei certificati dal nuovo IP**

```bash
certbot renew --dry-run 2>&1 | tail -15
systemctl list-timers | grep -i certbot
```

Atteso: `Congratulations, all simulated renewals succeeded`. Un fallimento qui va risolto
**subito**: il certificato scadrebbe entro 90 giorni senza preavviso. Finché il vecchio server
fa da proxy, la validazione HTTP-01 può passare da lui: rieseguire il dry-run anche dopo la
rimozione del proxy (Task 10).

- [ ] **Step 23: Riportare il TTL a 3600 (eseguito dall'utente)**

Non a 21600: un TTL di un'ora tiene rapido un eventuale rollback durante la finestra dei 7 giorni.

- [ ] **Step 24: Riconciliare i job interrotti**

A T+2h dallo start, con lo snapshot dello Step 6 alla mano:

```bash
python3 /root/migration_live_jobs.py --data-dir /opt/audiobook-maker/data --window-min 120
grep -c RECUPERABILE /root/migration_snapshot_*.txt
journalctl -u audiobook-maker --since "3 hours ago" --no-pager \
  | grep -iE "orphan|recover_failed|interrupted_restart|refund" | tail -30
```

Tre controlli:

1. **I recuperabili sono ripartiti?** Ogni job dell'elenco "DA RIPRENDERE AL BOOT" dello Step 13
   deve comparire nel log come ripreso, poi come consegnato oppure come `mark_failed` con
   rimborso. Un descrittore rimasto pendente e inattivo per ore va segnalato all'utente.
2. **I rimborsi automatici sono corretti?** `_orphan_fallback()` rimborsa con causale
   `recover_failed` e invia l'email "interrotto". Verificare che gli importi corrispondano e che
   nessun job **consegnato** sia stato rimborsato (sarebbe l'effetto dei descrittori sopravvissuti
   al finalize, che lo Step 13 dovrebbe aver già neutralizzato).
3. **I sacrificati non avevano pagamenti pendenti.** Per costruzione il classificatore lo
   esclude, ma è un controllo che costa poco:

```bash
python3 - <<'PY'
import json
d = "/opt/audiobook-maker/data/"
pay = json.load(open(d + "_payments.json"))
done = {r.get("job_id") for r in json.load(open(d + "_paid_jobs_done.json"))
        if isinstance(r, dict)}
pend = [(o, r.get("job_id"), r.get("amount_eur"), r.get("email"))
        for o, r in pay.items()
        if r.get("used") and r.get("job_id") and r.get("job_id") not in done]
print(len(pend), "pagamenti consumati senza record di completamento")
for row in pend[-10:]:
    print(row)
PY
```

Le righe più vecchie del cutover sono preesistenti (arretrato noto, vedi
`project_incident_unused_capture_false_positive`); vanno guardate solo quelle con timestamp
successivo al freeze. Qualunque riga nuova è un rimborso da fare a mano, con voucher
maggiorato del 10% se il pagamento era PayPal.

---

### Task 9: Verifiche post-cutover

**Files:** nessuno (sola verifica).

**Interfaces:**
- Consumes: Task 8 (produzione attiva sul nuovo server).
- Produces: conferma documentata che il servizio è pienamente operativo.

- [ ] **Step 1: Checklist funzionale (eseguita dall'utente sul sito pubblico)**

| # | Verifica | Esito atteso |
|---|---|---|
| 1 | Home page e cambio lingua | OK |
| 2 | Job standard end-to-end (EPUB → M4B) | file riproducibile |
| 3 | Job PREMIUM (voce Gemini) | file riproducibile |
| 4 | Email di consegna in modalità batch | ricevuta |
| 5 | Download da token **preesistente** al cutover | file scaricato |
| 6 | Download di un job già in cold storage | redirect presigned R2 funzionante |
| 7 | Pagamento PayPal reale di importo minimo | registrato in `_payments.json`, servizio erogato |
| 8 | Voucher esistente | accettato, saldo decrementato |
| 9 | `/admin/vouchers` e `/logs` | accessibili con token |
| 10 | `sitemap.xml`, `robots.txt`, hreflang | corretti |

- [ ] **Step 2: Verificare i thread di background**

```bash
journalctl -u audiobook-maker --since "30 min ago" --no-pager | grep -iE "cleanup|reconcile|hot-evict|digest" | tail -20
```

Atteso: attività del cleanup loop e del reconcile Google TTS. Il cleanup loop è già morto in silenzio in passato bloccando l'intera retention: la sua assenza dai log è un segnale d'allarme.

- [ ] **Step 3: Verificare che il log di attività continui a scrivere**

```bash
tail -5 /opt/audiobook-maker/activity_$(date +%Y-%m).log
```

Atteso: righe nuove relative ai job del post-cutover.

- [ ] **Step 4: Verificare risorse e cold storage**

```bash
free -h
df -h /opt
uptime
python3 /opt/audiobook-maker/scripts/verify_r2.py 2>/dev/null | tail -10 || echo "verifica R2 manuale"
```

- [ ] **Step 5: Verificare il backup notturno il giorno successivo**

```bash
ls -la /opt/backup | tail -5
tail -20 /var/log/abm_backup.log
```

Atteso: una directory di backup datata alla notte appena trascorsa, log senza errori.

- [ ] **Step 6: Osservazione a 48h**

```bash
free -h; swapon --show
df -h /opt
journalctl -u audiobook-maker --since "48 hours ago" --no-pager | grep -icE "traceback|exception"
uptime
```

Se lo swap resta pressoché inutilizzato e il carico regge, valutare l'aumento di `ABM_MAX_CONCURRENT_ASSEMBLY` da 2 a 3 e, separatamente, di `ABM_MAX_CONCURRENT_GLOBAL` da 6. **Un parametro per volta**, con 48h di osservazione fra un cambio e l'altro.

---

### Task 10: Chiusura — documentazione e dismissione del vecchio server

**Files:**
- Modify: `docs/FORENSICS_PLAYBOOK.md` (nuovo IP), `docs/superpowers/specs/2026-08-21-migrazione-server-prod-design.md` (esito)

**Interfaces:**
- Consumes: Task 9 (verifiche superate).
- Produces: documentazione allineata e vecchio server dismesso.

- [ ] **Step 1: Aggiornare il secret GitHub (eseguito dall'utente)**

`SERVER_HOST` → `80.211.137.33` nelle impostazioni del repository. Fino a quel momento **nessun push su `main`**.

- [ ] **Step 2: Verificare il deploy sul nuovo server**

Al primo push utile, controllare l'esito dell'Action e, sul nuovo server:

```bash
git -C /opt/audiobook-maker log -1 --oneline
systemctl status audiobook-maker --no-pager | head -5
```

Atteso: il commit pushato è quello attivo e il servizio è ripartito.

- [ ] **Step 3: Aggiornare la documentazione**

In `docs/FORENSICS_PLAYBOOK.md`, aggiornare la sezione di topologia con il nuovo IP, la nuova dotazione hardware (4 vCPU / 8 GB / 80 GB / swap 4 GB) e la nota che l'ambiente test non risiede più sulla stessa macchina.

- [ ] **Step 4: Commit della documentazione**

```bash
git add -f docs/FORENSICS_PLAYBOOK.md docs/superpowers/specs/2026-08-21-migrazione-server-prod-design.md
git commit -m "docs(ops): aggiorna topologia dopo la migrazione sul nuovo server"
```

Nessun push senza conferma esplicita dell'utente.

- [ ] **Step 5: Smontare il proxy temporaneo e le autorizzazioni collegate**

Quando il traffico sul vecchio IP è a zero (verificare sull'access log dell'ultima ora), il
proxy del Task 8, Step 9 non serve più e va rimosso insieme alla riga che lo autorizza a
dichiarare l'IP dei client:

```bash
# sul VECCHIO
awk -v t="$(date -d '1 hour ago' '+%d/%b/%Y:%H')" '$0 ~ t' /var/log/nginx/access.log | wc -l
cp /etc/nginx/sites-available/audiobook-maker.precutover /etc/nginx/sites-available/audiobook-maker
nginx -t && systemctl reload nginx

# sul NUOVO
sed -i '/set_real_ip_from 80.211.136.211;/d' /etc/nginx/nginx.conf
nginx -t && systemctl reload nginx
certbot renew --dry-run 2>&1 | tail -5
```

Il `certbot renew --dry-run` va rieseguito qui: finché il vecchio server faceva da proxy, una
validazione HTTP-01 poteva passare da lui e mascherare un problema di raggiungibilità diretta.

Revocare inoltre dal pannello Cloudflare R2 le **vecchie** chiavi sostituite al Task 8, Step 15,
dopo aver verificato che il nuovo server legge e scrive in cold storage senza errori.

- [ ] **Step 6: Dismissione del vecchio server (T+7 giorni)**

Prima di spegnere:

```bash
ls -la /opt/backup | tail -3
du -sh /opt/audiobook-maker/data
```

Verificare che non serva più nulla dal vecchio server (backup, `test.audiobook-maker.com`, log storici). Se l'ambiente test serve ancora, la dismissione va rinviata o il test va migrato con un piano dedicato.

Infine, decisione dell'utente sulla cancellazione della VM presso il provider.

---

## Appendice — Procedura di rollback

Valida nella finestra dei 7 giorni, ma realistica **solo nelle prime ore**: ogni job creato sul nuovo server dopo il cutover resterebbe orfano tornando indietro.

1. Fermare e disabilitare il servizio sul nuovo server:

```bash
systemctl stop audiobook-maker
systemctl disable audiobook-maker
```

2. Riportare i dati indietro **solo se sul nuovo server sono stati creati job che vanno salvati** (altrimenti saltare):

```bash
rsync -aHAX --numeric-ids -e "ssh -i /root/.ssh/id_migrate" \
  root@80.211.137.33:/opt/audiobook-maker/data/ /opt/audiobook-maker/data/
```

Da lanciare **dal vecchio server**, e senza `--delete`: si aggiunge, non si sovrascrive alla cieca.

3. Ripristinare il vhost del vecchio server (rimuovere il blocco `return 503;` reintroducendo il `location /` originale) e ricaricare nginx:

```bash
nginx -t && systemctl reload nginx
```

4. Riavviare il servizio sul vecchio server:

```bash
systemctl enable audiobook-maker
systemctl start audiobook-maker
journalctl -u audiobook-maker -n 40 --no-pager
```

5. Riportare i record A di `audiobook-maker.com` e `www` a `80.211.136.211` su Aruba (TTL 3600 → propagazione entro un'ora).

6. Verificare: home page, un download da token, i thread di background.

**Vincolo invariato:** al termine del rollback un solo servizio deve risultare attivo. Verificare esplicitamente che quello sul nuovo server sia fermo **e** disabilitato.

## Criteri di stop (validi in ogni task)

Fermarsi e chiedere all'utente se si verifica una di queste condizioni:

1. `pip` non riesce a installare una delle otto dipendenze critiche alla versione di produzione.
2. Il commit `d6a7992` non è presente sul remoto.
3. `nginx -t` fallisce e la causa non è evidente in un paio di tentativi.
4. Un JSON di stato risulta corrotto dopo la copia e la ricopia non lo risolve.
5. `systemctl show` mostra la data dir reale o il bucket R2 durante il collaudo.
6. `certbot renew --dry-run` fallisce dopo lo switch.
7. Il download di un token preesistente non funziona dopo il cutover.
8. Compaiono job attivi sul vecchio server al momento del freeze.

---

## Scostamenti registrati durante l'esecuzione (2026-08-21)

Fatti emersi in corso d'opera, non previsti dal piano originale. Ognuno è già stato gestito;
sono elencati perché cambiano l'inventario della spec o richiedono un'azione al cutover.

1. **`ABM_MAX_CONCURRENT_GLOBAL` è 35, non 6 — e l'`override.conf` del vecchio server dice 50.**
   La spec riportava i default del codice. Il valore con cui la produzione **gira davvero**,
   letto da `/proc/<MainPID>/environ`, è `35`: le righe dell'override furono modificate a `50`
   dopo l'ultimo restart e non sono mai entrate in vigore. `ABM_MAX_CONCURRENT_ASSEMBLY` è già
   pinnato a `2` in entrambi gli override. Sul nuovo server l'override è stato allineato al
   comportamento reale (`GLOBAL=35`), non alla lettera del file vecchio: partire a 50
   significherebbe accettare il +43% di carico proprio mentre si riprendono i job interrotti.
   Verifica al cutover: Task 8, Step 14.

2. **Credenziali Google — falso allarme.** L'env con `/opt/audiobook-maker-test/...` apparteneva
   al processo del servizio *test*, non alla produzione. La prod usa
   `/opt/audiobook-maker/credentials/vertex-sa.json` (md5 `42099af7…`, identico alla copia del
   test). Nessuna dipendenza dall'ambiente test.

3. **`nginx.conf` globale adottato dal vecchio server.** Il pacchetto nginx.org non include
   `sites-enabled/*` (usa solo `conf.d/`): senza il file del vecchio il vhost non verrebbe
   caricato. Il vecchio aggiunge anche il blocco Cloudflare `set_real_ip_from` +
   `real_ip_header CF-Connecting-IP`. Il file del pacchetto è conservato in
   `/etc/nginx/nginx.conf.pkg-default`.

4. **Filtro fail2ban `nginx-badbots` è custom**, non fa parte del pacchetto: va copiato
   `/etc/fail2ban/filter.d/nginx-badbots.conf` oltre alla jail, altrimenti fail2ban avvia
   la sola jail `sshd`.

5. **Cron `abm-cleanup-stale` sospeso fino al cutover.** Cancella ogni ora, alla cieca, ogni
   job dir con mtime > 25 h. Poiché `rsync -a` preserva gli mtime, se restasse attivo
   cancellerebbe i dati appena migrati *prima* del cutover. Spostato in
   `/root/abm-cleanup-stale.DEFERRED_UNTIL_CUTOVER`.
   **AZIONE AL CUTOVER:** ripristinarlo in `/etc/cron.d/` subito dopo lo start del servizio.

6. **Bucket R2 condiviso con l'ambiente test — verificato sicuro.** Prod e test usano lo stesso
   bucket `audiobook-maker` senza `ABM_S3_KEY_PREFIX`, ma il cold delete agisce solo su
   `delete_prefix("<job_id>/")` e `list_keys` non ha chiamanti: nessuno sweep globale, job id
   UUID, nessuna collisione. Il test può restare acceso sul vecchio server dopo il cutover.

7. **Secret key R2 esposta in chat** durante una lettura di env con mascheramento difettoso.
   **AZIONE RICHIESTA:** ruotare `ABM_S3_SECRET_KEY` dal pannello Cloudflare R2 e aggiornare
   l'`override.conf` di entrambi i server. Da fare al cutover, quando il servizio viene
   comunque riavviato (ruotarla prima significherebbe riavviare la produzione attuale).

8. **Voucher creati via CLI a servizio attivo vengono persi.** `payment.py` carica `_vouchers`
   in RAM all'avvio (`_load_vouchers`) e `_save_vouchers()` riscrive l'intero dizionario: un
   voucher creato con `scripts/admin_voucher.py` mentre il processo gira sparisce al primo
   salvataggio del servizio. Riscontrato in collaudo (il voucher `PROMO-NVNL-AP67-DL8C` è stato
   sovrascritto). **Vale anche per la produzione attuale:** i voucher, inclusi quelli di rimborso,
   vanno creati a servizio fermo, oppure dall'interfaccia admin. Difetto pre-esistente, fuori
   dallo scope della migrazione — da valutare separatamente.

9. **Esito del collaudo (2026-08-21, 17:42-18:15).** Superato: audiolibro free, PREMIUM Simba e
   PREMIUM Gemini 3.1 generati end-to-end, email di consegna ricevute, link `/dl/<token>`
   funzionanti. Zero eccezioni, zero chunk falliti (28/28, 1/1, 3/3), RAM di picco sotto 1 GB.
   Unico warning: `[preview] gemini_tts.record_rate_sample failed (non-fatal): Working outside
   of request context` — **pre-esistente** (248 occorrenze nel syslog di produzione), quindi le
   anteprime PREMIUM non alimentano `gemini_tts_rate_log.json` e il price lock si basa solo sui
   job veri. Non bloccante; da valutare separatamente. Collaudo chiuso: override rimosso,
   `data_collaudo` cancellata, env di produzione ripristinate, servizio fermo e `disabled`.


10. **La produzione ha sempre job attivi: il cutover non può "aspettare che finiscano".** Misura
    del 21/08/2026: **~35-40 job vivi** in un istante qualsiasi (batch registrati + interattivi).
    Il Task 8 è stato riscritto attorno a un criterio diverso — **zero job BLOCCANTI**, non zero
    job vivi — con due strumenti nuovi nel repo:
    `scripts/migration/migration_live_jobs.py` (classificatore read-only, exit code 2 finché
    c'è lavoro pagato a rischio) e `scripts/migration/migration_recover_prep.py` (igiene del
    registro orfani sul nuovo server, a servizio fermo). Il drenaggio usa il kill-switch già
    esistente `POST /api/admin/suspend`, che rifiuta i nuovi job **prima** del preflight di
    pagamento e lascia funzionare i download.
    Fondamento tecnico: `chunk_reuse` ancora il fingerprint al **contenuto** (`plan_sha` + voce
    e parametri), non ai path assoluti, quindi i chunk già sintetizzati sopravvivono alla
    migrazione; `REUSABLE_ENGINES` però **non include Speechify**, che quindi risintetizza (e
    ri-paga) da zero. Prima esecuzione in produzione: `vivi=40, BLOCCANTI=0, recuperabili=17,
    sacrificabili=23`; dry-run dell'igiene registro: 19 job da riprendere, nessuna anomalia.

11. **Trappola diagnostica: `pgrep -f audiobook_app.py | head -1` restituisce il servizio di
    *test*.** Sul vecchio server girano due istanze (`/opt/audiobook-maker-test/audiobook_app.py`,
    PID più basso, e la produzione). Leggere le env di produzione da quel PID porta a conclusioni
    sbagliate — è così che l'ambiente test era già stato scambiato per la prod (scostamento 2).
    Usare sempre `systemctl show audiobook-maker -p MainPID --value`.

12. **`ABM_ADMIN_TOKEN` esposto in chat** (stesso incidente di mascheramento della chiave R2,
    scostamento 7). **AZIONE RICHIESTA:** ruotarlo insieme a `ABM_S3_SECRET_KEY` al cutover
    (Task 8, Step 15) su entrambi i server. Protegge `/admin/*` e `/logs*`, cioè l'export dei
    log di attività e la gestione voucher.

13. **Il traffico proxato dal vecchio al nuovo va dichiarato a nginx.** Il `nginx.conf` di
    produzione usa `real_ip_header CF-Connecting-IP` con `set_real_ip_from` sui soli range
    Cloudflare (residuo storico: il DNS è Aruba e i record A puntano all'IP diretto). Durante
    la propagazione il vecchio server fa da proxy: senza `set_real_ip_from 80.211.136.211` sul
    nuovo e senza `proxy_set_header CF-Connecting-IP $remote_addr` sul vecchio, la `limit_req`
    da 10 r/s vedrebbe **un solo client** per tutto il traffico proxato e risponderebbe 503 a
    raffica. L'IP applicativo invece è già corretto per costruzione: il codice prende il primo
    valore di `X-Forwarded-For` (`audiobook_app.py:840`). Entrambe le righe vanno rimosse alla
    dismissione del vecchio server (Task 10).
