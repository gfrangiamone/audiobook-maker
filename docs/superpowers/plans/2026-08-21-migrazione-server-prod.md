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

Dal PC (PowerShell, dalla cartella del repo). **Niente `-pw` e niente `-batch`**: la password
digitata al prompt di `pscp` non entra nella history di PowerShell, mentre `-pw "<password>"`
la lascerebbe in chiaro in `ConsoleHost_history.txt` (e in `Get-History`) per sempre.

```powershell
pscp scripts\migration\migration_live_jobs.py scripts\migration\migration_recover_prep.py root@80.211.136.211:/root/
```

Una sola copia dal PC, verso il **vecchio** server. Il secondo file viaggia poi da server a
server con la chiave `id_migrate` gia' autorizzata al Task 2, senza password in gioco:

```bash
scp -i /root/.ssh/id_migrate /root/migration_recover_prep.py root@80.211.137.33:/root/
ssh -i /root/.ssh/id_migrate root@80.211.137.33 'ls -l /root/migration_recover_prep.py'
```

> Se per qualunque motivo si e' usato `-pw`, ripulire subito la history del terminale:
>
> ```powershell
> Clear-History
> Remove-Item (Get-PSReadlineOption).HistorySavePath -ErrorAction SilentlyContinue
> ```
>
> e riaprire PowerShell.

`migration_live_jobs.py` è **sola lettura**: classifica i job vivi e restituisce exit code
`0` se non ci sono bloccanti, `2` se ce ne sono. `migration_recover_prep.py` gira **solo sul
nuovo server**, a servizio fermo (rifiuta di applicare modifiche se trova un processo vivo).

- [ ] **Step 3: Fotografia iniziale dei job vivi (nessun impatto)**

Sul vecchio server:

```bash
python3 /root/migration_live_jobs.py --data-dir /opt/audiobook-maker/data --window-min 25
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

`_suspend_new_jobs` è una variabile **in RAM**: un restart del servizio durante il drenaggio
(crash, OOM, riavvio manuale) la azzera **in silenzio** e i job nuovi ricominciano ad arrivare
proprio mentre si aspetta lo zero bloccanti. Per questo il ciclo dello Step 5 la ricontrolla a
ogni giro invece di darla per acquisita.

- [ ] **Step 5: Attendere due letture consecutive a zero job BLOCCANTI**

Il ciclo sorveglia tre cose insieme: i bloccanti, la sospensione (che può cadere da sola) e il
tempo trascorso (non deve restare appeso a tempo indefinito su una sessione plink).

```bash
PID=$(systemctl show audiobook-maker -p MainPID --value)
ADMIN_TOKEN=$(tr '\0' '\n' < /proc/$PID/environ | sed -n 's/^ABM_ADMIN_TOKEN=//p')

CLEAN=0
for i in $(seq 1 24); do        # 24 giri x 5 min = 2 h di tetto
  SUSP=$(curl -s http://127.0.0.1:5601/api/admin/suspend)
  case "$SUSP" in
    *true*) : ;;
    *) echo "!! SOSPENSIONE CADUTA ($SUSP) - la riattivo"
       curl -s -X POST http://127.0.0.1:5601/api/admin/suspend \
         -H "X-Admin-Token: $ADMIN_TOKEN" -H "Content-Type: application/json" \
         -d '{"suspend": true}' > /dev/null
       CLEAN=0 ;;
  esac
  if python3 /root/migration_live_jobs.py --data-dir /opt/audiobook-maker/data \
       --window-min 25 --quiet; then
    CLEAN=$((CLEAN + 1))
    echo "letta pulita $CLEAN/2"
    [ "$CLEAN" -ge 2 ] && break
  else
    CLEAN=0
  fi
  sleep 300
done
echo "uscito con CLEAN=$CLEAN dopo $i giri"
```

Tre scelte da non annacquare:

- **`--window-min 25`, non 10.** Un job Gemini in attesa di rate limit, o in assembly FFmpeg su
  un libro lungo, può non scrivere alcun file per oltre dieci minuti: con una finestra stretta
  sparisce dall'elenco e il classificatore dichiara "nessun bloccante" mentre il lavoro pagato è
  ancora vivo. La finestra larga costa qualche minuto di attesa in più e toglie il falso
  negativo. Nulla vieta di allargarla ancora (`--window-min 40`) se lo snapshot dello Step 3
  mostrava job Speechify lunghi.
- **Due letture consecutive.** Una singola lettura pulita può cadere nel buco fra la fine di un
  chunk e l'inizio del successivo. Il contatore riparte da zero a ogni lettura sporca **e** a
  ogni caduta della sospensione.
- **Tetto di 24 giri.** Se il ciclo esce con `CLEAN` diverso da `2`, il drenaggio **non** è
  riuscito: non proseguire.

Ogni tanto, per vedere il dettaglio, rieseguire lo script senza `--quiet`.

Se un bloccante resta tale oltre **60 minuti** (tipicamente un job Speechify lungo), fermarsi e
riportare la situazione all'utente: le opzioni sono attendere ancora oppure accettare la perdita
e rimborsare quel singolo job nello Step 24. Non decidere da soli.

- [ ] **Step 6: Snapshot forense dei job che verranno interrotti**

Prima di fermare il servizio, congelare l'elenco: serve allo Step 24 per verificare che nessuno
sia rimasto indietro.

```bash
STAMP=$(date +%Y%m%d-%H%M)
python3 /root/migration_live_jobs.py --data-dir /opt/audiobook-maker/data --window-min 25 \
  > /root/migration_snapshot_$STAMP.txt 2>&1
cp /opt/audiobook-maker/data/_pending_jobs.json /root/migration_pending_$STAMP.json
date +%s > /root/migration_freeze_ts        # istante del freeze, in epoch: lo usa lo Step 24
wc -l /root/migration_snapshot_$STAMP.txt
cat /root/migration_freeze_ts
```

Copiare tutto sul nuovo server (sopravvive alla dismissione del vecchio):

```bash
rsync -a -e "ssh -i /root/.ssh/id_migrate" /root/migration_snapshot_*.txt \
  /root/migration_pending_*.json /root/migration_freeze_ts root@80.211.137.33:/root/
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

Va sospeso anche il **cron di pulizia dei job stale sul vecchio server**, per tutta la finestra
di rollback:

```bash
ls -la /etc/cron.d/ | grep -i abm
cat /etc/cron.d/abm-cleanup-stale
mv /etc/cron.d/abm-cleanup-stale /root/abm-cleanup-stale.OLD_SERVER_ROLLBACK
systemctl restart cron
ls /etc/cron.d/ | grep -i abm || echo "nessun cron ABM attivo sul vecchio"
```

Il servizio è masked, ma quel cron no: cancella alla cieca le job dir con mtime oltre le 25 ore
e nei sette giorni successivi **eroderebbe la copia di rollback**, cioè l'unica cosa per cui il
vecchio server resta acceso. Un rollback a T+3 giorni troverebbe dati già cancellati. Il file
va ripristinato solo se si torna davvero indietro, e comunque rimosso alla dismissione (Task 10).

- [ ] **Step 9: Trasformare il vecchio nginx in proxy verso il nuovo**

Durante la propagazione DNS (5-15 minuti con TTL 300) chi arriva ancora sul vecchio IP viene
servito dal nuovo server, senza vedere disservizio; una pagina di manutenzione resta come
fallback per la sola finestra in cui il nuovo servizio non è ancora acceso.

**Il vhost va sostituito per intero, non ritoccato.** Il file di produzione contiene più
`location` con `proxy_pass http://127.0.0.1:5601` — almeno `/`, `/api/analyze`
(`client_max_body_size 200M`) e `/api/progress/` (`proxy_buffering off`, timeout 600 s) —
e patchare solo `location /` lascerebbe gli altri puntati a un servizio ormai fermo: **upload e
SSE risponderebbero 502** proprio al traffico che si voleva salvare. Contarli prima, per sapere
quanti se ne stanno neutralizzando:

```bash
cp /etc/nginx/sites-available/audiobook-maker /etc/nginx/sites-available/audiobook-maker.precutover
grep -n "location\|proxy_pass\|ssl_certificate" /etc/nginx/sites-available/audiobook-maker
```

Annotare le due righe `ssl_certificate` / `ssl_certificate_key`: vanno riportate identiche nel
vhost di cutover (sotto sono scritte con il path standard Let's Encrypt; se il grep mostra path
diversi, valgono quelli del grep). La copia di riferimento nel repo
(`scripts/nginx-audiobook-maker.conf`) ha **sei** `location` nel server block HTTPS — `/`,
`= /.well-known/assetlinks.json`, `/api/analyze`, `/api/progress/`, `~ ^/api/download`,
`~ /\.` — e nessuna di queste regole va replicata nel proxy: le applica il nginx del **nuovo**
server, che le ha identiche. Qui serve l'opposto, un unico `location /` che non lasci scoperto
nulla.

Scrivere il nuovo vhost — un solo `location /` che raccoglie **tutto** il traffico, più una
pagina di manutenzione per la finestra in cui il nuovo servizio non è ancora acceso:

```bash
cat > /etc/nginx/sites-available/audiobook-maker <<'NGINX'
server {
    listen 80;
    listen [::]:80;
    server_name audiobook-maker.com www.audiobook-maker.com;
    location /.well-known/acme-challenge/ { root /var/www/html; }
    location / { return 301 https://$host$request_uri; }
}

server {
    listen 443 ssl;
    listen [::]:443 ssl ipv6only=on;
    server_name audiobook-maker.com www.audiobook-maker.com;

    ssl_certificate     /etc/letsencrypt/live/audiobook-maker.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/audiobook-maker.com/privkey.pem;

    client_max_body_size 200M;

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
        proxy_request_buffering off;
        proxy_connect_timeout 10s;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_intercept_errors on;
        error_page 502 503 504 = @maint;
    }

    location @maint {
        default_type text/html;
        add_header Retry-After 600 always;
        return 503 '<!doctype html><meta charset="utf-8"><title>Maintenance</title><style>body{font-family:system-ui,sans-serif;max-width:34rem;margin:20vh auto;padding:0 1.5rem;line-height:1.6;color:#222}h1{font-size:1.3rem}</style><h1>Scheduled maintenance</h1><p>Audiobook Maker is being moved to a new server. Downloads and new conversions will be back online within a few minutes.</p><p>Download links already sent by email remain valid.</p>';
    }
}
NGINX
nginx -t && systemctl reload nginx
curl -s -o /dev/null -w "%{http_code}\n" -k https://127.0.0.1/ -H "Host: audiobook-maker.com"
```

Atteso subito dopo il reload: **`503`** (il nuovo servizio non è ancora acceso, `@maint`
risponde al posto del 502 crudo di nginx). Diventerà `200` allo Step 18.

`proxy_intercept_errors on` + `error_page 502 503 504` coprono la finestra fra questo step e lo
Step 16 — delta rsync, verifica dei 20 JSON, igiene del registro e rotazione dei segreti: nella
pratica **20-45 minuti** in cui il proxy punta a un servizio non ancora avviato. Senza la pagina
di manutenzione ogni visitatore vedrebbe l'errore nginx di default.

`proxy_request_buffering off` evita che il vecchio server accumuli su disco l'intero upload da
200 MB prima di inoltrarlo: ha 40 GB e li sta ancora tenendo tutti come copia di rollback.

Le tre righe di header non sono decorative:

- `X-Forwarded-For $proxy_add_x_forwarded_for` accoda l'IP reale in testa alla catena.
  L'applicazione prende **sempre il primo valore** (`audiobook_app.py:840`), quindi il doppio
  hop non falsifica l'IP registrato nei log e nei rate limit applicativi.
- `CF-Connecting-IP $remote_addr` serve a nginx del **nuovo** server: il suo `real_ip_header` è
  `CF-Connecting-IP` (`nginx.conf:58`). Senza questo, `$binary_remote_addr` varrebbe
  `80.211.136.211` per **tutto** il traffico proxato e la `limit_req` da 10 r/s lo tratterebbe
  come un solo client, restituendo 503 a raffica. Il valore viene sovrascritto dal proxy, quindi
  non è falsificabile dal client.
- `proxy_ssl_name` fa presentare il SNI corretto: il certificato del nuovo server è quello di
  `audiobook-maker.com`, copiato al Task 5.

> **Cloudflare non è davanti al sito** (confermato dall'utente: il DNS è su Aruba e punta
> direttamente all'origine). Le direttive `set_real_ip_from` sui range Cloudflare e
> `real_ip_header CF-Connecting-IP` in `nginx.conf` sono un **residuo morto** e, finché restano,
> chiunque riesca a instradare traffico da uno di quei range può dichiarare l'IP che vuole,
> aggirando `limit_req` e falsificando i log. Non si tocca durante il cutover — cambiarlo qui
> significherebbe cambiare due variabili insieme — ma va rimosso al Task 10, insieme alla riga
> dello Step 10, sostituendo l'intero meccanismo con `real_ip_header X-Forwarded-For` limitato
> al solo IP del vecchio server finché il proxy è vivo.

La verifica funzionale completa si fa allo Step 18, quando il nuovo servizio è acceso.

- [ ] **Step 10: Autorizzare il vecchio server come proxy sul nuovo nginx**

Sul **nuovo** server, nel blocco `http` di `/etc/nginx/nginx.conf`, subito dopo l'ultimo
`set_real_ip_from` dei range Cloudflare:

```bash
cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.precutover
grep -c 'set_real_ip_from 2c0f:f248::/32;' /etc/nginx/nginx.conf
```

Atteso: **1**. Se fosse `0` il `sed` seguente non farebbe nulla in silenzio; se fosse `>1`
inserirebbe piu' righe. In entrambi i casi fermarsi e inserire la riga a mano dentro il blocco
`http`.

```bash
sed -i '/set_real_ip_from 2c0f:f248::\/32;/a\    set_real_ip_from 80.211.136.211;   # proxy temporaneo dal vecchio server (rimuovere alla dismissione)' /etc/nginx/nginx.conf
grep -n 'set_real_ip_from 80.211' /etc/nginx/nginx.conf
```

L'ancora e' un `set_real_ip_from` dei range Cloudflare, che nel file attuale sta dentro `http { … }`;
ma `sed` non conosce i blocchi, quindi la posizione va **verificata**, non data per scontata:
una direttiva `set_real_ip_from` fuori da `http`/`server`/`location` fa fallire `nginx -t`, e una
finita dentro un `server` sbagliato passerebbe il test senza avere effetto dove serve.

```bash
python3 - <<'PY'
import re
lines = open("/etc/nginx/nginx.conf", encoding="utf-8").read().splitlines()
target = [i + 1 for i, l in enumerate(lines) if "set_real_ip_from 80.211.136.211" in l]
print("riga inserita:", target)
ctx, ok = [], False
for i, l in enumerate(lines, 1):
    code = re.sub(r"#.*", "", l)
    if i in target:
        print("  contesto:", " > ".join(ctx) or "(livello top - ERRORE)")
        ok = (ctx == ["http"])
    for ch in code:
        if ch == "{":
            m = re.match(r"\s*([A-Za-z_]\S*)", code)
            ctx.append(m.group(1) if m else "?")
        elif ch == "}" and ctx:
            ctx.pop()
print("ESITO:", "OK - dentro http {}" if (len(target) == 1 and ok) else "ERRORE - correggere a mano")
PY
```

Atteso: `riga inserita: [N]` con un solo numero, `contesto: http` e `ESITO: OK - dentro http {}`.
Solo allora:

```bash
nginx -t && systemctl reload nginx
```

Atteso: `nginx -t` OK. Questa riga va rimossa al Task 10, quando il vecchio
server viene dismesso: finché c'è, quell'IP è autorizzato a dichiarare l'IP dei client.

- [ ] **Step 11: Chiudere il collaudo (pre-condizione) ed eseguire la delta**

> Se il servizio di collaudo sul nuovo server fosse ancora in esecuzione, il suo cleanup loop
> lavorerebbe su una data dir che sta per diventare quella reale. Verificare **prima** della
> sincronizzazione:
>
> ```bash
> # >>> NUOVO SERVER (80.211.137.33) <<<
> hostname -I | grep -q 80.211.137.33 || echo "!! SERVER SBAGLIATO - fermarsi"
> systemctl is-active audiobook-maker || echo "fermo"
> ls -d /opt/audiobook-maker/data_collaudo 2>/dev/null && echo "RESIDUO DA RIMUOVERE"
> test -f /etc/systemd/system/audiobook-maker.service.d/zz-collaudo.conf && echo "OVERRIDE COLLAUDO ANCORA PRESENTE"
> ```
>
> Atteso: `fermo` e nessuna delle due segnalazioni (chiuso al Task 7, Step 8).

Poi, e **solo** dopo aver visto quell'esito, la delta. Questi due comandi girano sul
**vecchio** server (80.211.136.211): eseguirli sul nuovo copierebbe i dati nella direzione
sbagliata, sovrascrivendo la produzione con la copia.

```bash
# >>> VECCHIO SERVER (80.211.136.211) <<<
hostname -I | grep -q 80.211.136.211 || echo "!! SERVER SBAGLIATO - fermarsi"
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

> **Questa è l'ultima sincronizzazione.** Lo Step 13 riscrive `_pending_jobs.json` sul nuovo
> server; qualunque `rsync` eseguito dopo — per esempio ritentando questo step perché lo Step 16
> è andato male — riporterebbe il registro sporco del vecchio, e al riavvio partirebbero
> rigenerazioni ed email duplicate per i job già consegnati. Regola: **ogni rsync successivo
> obbliga a rieseguire lo Step 13 prima dello Step 16.**

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
ls -la /opt/audiobook-maker/activity_*.log | tail -3
python3 /root/migration_recover_prep.py \
  --data-dir /opt/audiobook-maker/data \
  --script-dir /opt/audiobook-maker
```

Due righe dell'output sono **cancelli**, non informazioni:

1. **`activity log: N job con evento di consegna`.** `delivered_job_ids()` avvisa solo se la
   directory è illeggibile: se esiste ma non contiene alcun `activity_*.log` (rsync degli
   activity log dello Step 11 non eseguito, oppure `--script-dir` sbagliato) ritorna un insieme
   **vuoto senza dire nulla**, nessun job viene riconosciuto come già consegnato e al boot
   partono rigenerazioni ed email duplicate. `N` deve essere dell'ordine delle **decine di
   migliaia** (al collaudo di agosto 2026: `15671`). Un valore basso o nullo è **bloccante**:
   rifare la copia degli activity log e ripetere la simulazione.

2. **`input mancante -> failed: N`.** Ogni job in questo elenco viene chiuso senza
   rigenerazione, **senza rimborso e senza email**: è l'esito peggiore possibile, peggiore
   dell'interruzione. Il criterio è l'esistenza fisica di `input_path`/`abm_path`, quindi una
   delta rsync incompleta o interrotta si presenta esattamente così. Se `N` è diverso da **0**,
   **fermarsi** e verificare a mano ciascun job prima di applicare:

```bash
python3 - <<'PY'
import json, os
reg = json.load(open("/opt/audiobook-maker/data/_pending_jobs.json"))
for r in reg.get("items", []):
    if str(r.get("state")) == "failed":
        continue
    ip, ap = r.get("input_path") or "", r.get("abm_path") or ""
    if (ip and os.path.exists(ip)) or (ap and os.path.exists(ap)):
        continue
    print(r.get("id"), "| purpose:", r.get("purpose"), "| email:", bool(r.get("email")),
          "| input:", ip or "-", "| abm:", ap or "-")
PY
```

Per ciascuno: se il file esiste ancora **sul vecchio server** si tratta di una copia incompleta
— ripetere lo Step 11 (e poi di nuovo questo step). Se non esiste nemmeno lì, il job era già
orfano prima della migrazione: verificarlo nell'elenco dei pagamenti pendenti dello Step 24 e,
se risulta pagato, rimborsarlo a mano. Solo dopo si applica.

Leggere poi l'elenco "DA RIPRENDERE AL BOOT" e il tempo stimato di recovery (2 s a job).
Applicare:

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
si revocano dal pannello solo **dopo** la verifica dello Step 18.

**La nuova chiave va provata prima di accendere il servizio.** Un typo nella secret key non
impedisce l'avvio: `storage_backend.is_enabled()` guarda solo che le quattro variabili siano
non vuote, quindi il log di avvio direbbe comunque "R2 attivo" e il primo errore arriverebbe al
primo download cold di un utente vero. Il repo ha già lo strumento che esercita il modulo reale
(upload multipart, `object_exists`, presigned GET con nome accentato, delete):

```bash
cd /opt/audiobook-maker
systemctl show audiobook-maker -p Environment --value | tr ' ' '\n' \
  | grep '^ABM_S3_' > /root/r2check.env
set -a; . /root/r2check.env; set +a
python3 scripts/verify_r2.py
set +a; unset ABM_S3_SECRET_KEY ABM_S3_ACCESS_KEY
shred -u /root/r2check.env
```

Atteso: sette blocchi con `[PASS]` e la riga finale `RISULTATO: TUTTO OK`. Un fallimento qui è
**bloccante**: correggere l'`override.conf` (e ricordarsi del `systemctl daemon-reload`) prima
dello Step 16. Il file temporaneo con le credenziali va distrutto subito, come sopra.

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
journalctl -u audiobook-maker --since "30 min ago" --no-pager \
  | grep -iE "Chunk reuse" | head -20
```

**Un grep vuoto non è di per sé un allarme, e non è nemmeno una conferma.** La riga
`Chunk reuse: N/M chunk …` viene stampata solo quando `N > 0` (`generation_engine.py:4091`):
il silenzio copre tre casi diversi — riuso rotto, job non ancora arrivato alla sintesi, job
senza chunk pregressi. Va quindi confrontato con ciò che c'è **su disco**: elencare i job del
registro che hanno chunk già sintetizzati e verificare che ciascuno abbia la sua riga di riuso.

```bash
python3 - <<'PY' > /root/chunk_owners.txt
import json, glob, os
d = "/opt/audiobook-maker/data"
reg = json.load(open(os.path.join(d, "_pending_jobs.json")))
for r in reg.get("items", []):
    if str(r.get("state")) == "failed":
        continue
    j = str(r.get("id") or "")
    wd = os.path.join(d, j)
    n = len(glob.glob(wd + "/chunk_*.pcm")) + len(glob.glob(wd + "/chunk_*.mp3"))
    if n:
        print("%s %d" % (j, n))
PY
cat /root/chunk_owners.txt

while read -r J N; do
  if journalctl -u audiobook-maker --since "30 min ago" --no-pager | grep -q "\[$J\] Chunk reuse:"; then
    echo "OK       $J ($N chunk su disco)"
  elif journalctl -u audiobook-maker --since "30 min ago" --no-pager | grep -q "\[$J\]"; then
    echo "SOSPETTO $J ($N chunk su disco, il job è ripartito ma non ha riusato nulla)"
  else
    echo "attesa   $J ($N chunk su disco, sintesi non ancora iniziata)"
  fi
done < /root/chunk_owners.txt
```

Atteso: `OK` per ogni job già ripartito, `attesa` per quelli ancora in coda. Un solo
**`SOSPETTO`** basta a fermarsi, prima che i job PREMIUM ri-consumino budget: significa che il
fingerprint non combacia, cioè un `plan_sha` diverso (piano di chunk ricostruito con parametri
diversi da quelli originali — tipicamente `ABM_GEMINI_CHUNK_CHARS`, che in produzione vale
**450** e sta nell'unit systemd, non nella shell). Controllare anche gli errori di scansione,
che non sono fatali per il codice ma lo sono per noi:

```bash
journalctl -u audiobook-maker --since "30 min ago" --no-pager | grep -i "Chunk reuse scan error"
```

Atteso: nessuna riga.

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

Atteso: `200`. Finché il nuovo servizio non era acceso rispondeva `503` (la pagina `@maint`);
se risponde ancora `503` il proxy non sta raggiungendo il nuovo server — controllare
`/var/log/nginx/error.log` sul vecchio prima di andare avanti.

Dal PC dell'utente (che ha ancora la riga nel file hosts), aprire `https://audiobook-maker.com`
e verificare la home page.

Poi la prova che conta davvero, il **download di un job già passato a cold storage**: un token
recente è servito dal disco locale e non tocca R2, quindi non dimostrerebbe nulla sulla chiave
ruotata allo Step 15 né sull'integrità dei dati migrati. Sul nuovo server, individuare un token
i cui file locali non esistono più:

```bash
python3 - <<'PY'
import json, os, time
d = "/opt/audiobook-maker/data/"
toks = json.load(open(d + "_download_tokens.json"))
now = time.time()
found = 0
for tok, info in toks.items():
    if not isinstance(info, dict):
        continue
    age_h = (now - float(info.get("created_at", 0) or 0)) / 3600.0
    paths = [info.get(k) or "" for k in ("output_file", "output_zip")]
    paths = [p for p in paths if p]
    if not paths or any(os.path.exists(p) for p in paths):
        continue                      # ancora hot: non prova il cold storage
    print("%s  eta=%.0fh  %s" % (tok, age_h, os.path.basename(paths[0])))
    found += 1
    if found >= 3:
        break
if not found:
    print("NESSUN token cold trovato: usare un link vecchio da una email reale")
PY
```

Aprire uno di quei `https://audiobook-maker.com/dl/<token>` dal browser e **scaricare davvero il
file** (non fermarsi alla pagina): la consegna deve avvenire via redirect a un presigned URL R2.
Un `404` o un errore qui significa che i file cold non sono raggiungibili con la chiave nuova —
bloccante, e da risolvere **prima** dello switch DNS dello Step 19, non dopo.

Solo dopo questa verifica si possono revocare le vecchie chiavi R2 dal pannello Cloudflare.

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

Prima di riattivarlo, **rileggerlo**: è uno script che cancella directory, e i dati appena
migrati portano gli mtime originali preservati da `rsync -aHAX`. Basta un criterio più largo di
quello ricordato (per esempio un `find` senza filtro sul nome della job dir, o una soglia in
giorni anziché in ore) perché il primo giro cancelli lavoro ancora in retention.

```bash
cat /root/abm-cleanup-stale.DEFERRED_UNTIL_CUTOVER
```

Estrarre il comando `find` e provarlo **senza** l'azione distruttiva, contando cosa colpirebbe:

```bash
# esempio: se il cron esegue  find /opt/audiobook-maker/data -maxdepth 1 -type d -mmin +1500 -exec rm -rf {} +
find /opt/audiobook-maker/data -maxdepth 1 -mindepth 1 -type d -mmin +1500 | wc -l
find /opt/audiobook-maker/data -maxdepth 1 -mindepth 1 -type d -mmin +1500 | head -5
```

(sostituire il predicato con quello effettivamente presente nel file). Se il conteggio è
dell'ordine delle migliaia, o se fra i primi risultati compaiono job dell'elenco "DA RIPRENDERE
AL BOOT" dello Step 13, **non riattivare**: riportare all'utente e decidere insieme.

Se il criterio è quello atteso:

```bash
mv /root/abm-cleanup-stale.DEFERRED_UNTIL_CUTOVER /etc/cron.d/abm-cleanup-stale
chmod 644 /etc/cron.d/abm-cleanup-stale
chown root:root /etc/cron.d/abm-cleanup-stale
cat /etc/cron.d/abm-cleanup-stale
systemctl restart cron
ls -la /etc/cron.d/
```

Atteso: il file presente in `/etc/cron.d/` con permessi `644 root:root` (un cron file con
permessi diversi viene ignorato in silenzio; e un nome che contiene un punto viene ignorato
anch'esso — per questo il file sospeso sta in `/root` e non in `/etc/cron.d` con un suffisso).

Il gemello sul **vecchio** server resta invece sospeso (Step 8) per tutta la finestra di
rollback.

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

L'elenco grezzo dei pagamenti consumati senza record di completamento è **inutilizzabile così
com'è**: contiene un arretrato preesistente di mesi (vedi
`project_incident_unused_capture_false_positive`) e l'ordine del dizionario è quello di
inserimento, non quello temporale, quindi un `[-10:]` non seleziona affatto "gli ultimi dieci".
Vanno isolate le righe **successive al freeze**, e vanno stampate tutte:

```bash
FREEZE=$(cat /root/migration_freeze_ts)
date -d "@$FREEZE"                      # controllo: deve essere l'ora del freeze di oggi
python3 - "$FREEZE" <<'PY'
import json, sys, time
freeze = float(sys.argv[1])
d = "/opt/audiobook-maker/data/"
pay = json.load(open(d + "_payments.json"))
done = {r.get("job_id") for r in json.load(open(d + "_paid_jobs_done.json"))
        if isinstance(r, dict)}
rows = []
for o, r in pay.items():
    if not (r.get("used") and r.get("job_id")) or r["job_id"] in done:
        continue
    # used_at = istante del consumo; captured_at = ripiego per i record piu' vecchi
    ts = float(r.get("used_at") or r.get("captured_at") or 0)
    rows.append((ts, o, r["job_id"], r.get("amount_eur"), r.get("email")))
rows.sort()
recenti = [x for x in rows if x[0] >= freeze]
print(len(rows), "pagamenti consumati senza completamento in totale (arretrato incluso)")
print(len(recenti), "successivi al freeze -> DA VERIFICARE UNO A UNO:")
for ts, o, j, amt, em in recenti:
    print("  ", time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)), o, j, amt, em)
PY
```

Atteso: **zero** righe successive al freeze. Ognuna di quelle righe è un pagamento incassato per
un servizio che il cutover potrebbe non aver erogato: va verificata singolarmente (il job è stato
consegnato? esiste il file di output o un token di download?) e, se il servizio non è stato
erogato, rimborsata a mano — con voucher maggiorato del 10% se il pagamento era PayPal, con
riaccredito silenzioso sul voucher originale se era un voucher.

Un record con `ts = 0` (nessun `used_at` né `captured_at`) finisce fra i più vecchi e non fra i
recenti: se il totale cresce rispetto allo snapshot pre-freeze ma i "successivi al freeze" sono
zero, riguardare la lista completa senza filtro prima di archiviare il controllo.

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

Rimuovere anche il **residuo Cloudflare** in `nginx.conf` sul nuovo server: il sito non è dietro
Cloudflare (DNS Aruba diretto all'origine), quindi `real_ip_header CF-Connecting-IP` e i
`set_real_ip_from` sui range CF non proteggono nulla e lasciano a chiunque instradi traffico da
quei range la possibilità di dichiarare l'IP che vuole, aggirando `limit_req` e falsificando i
log applicativi. Con il proxy ormai smontato non c'è più alcun hop intermedio legittimo:

```bash
# sul NUOVO, dopo la rimozione della riga 80.211.136.211
cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.precf
sed -i '/set_real_ip_from/d; /real_ip_header/d; /real_ip_recursive/d' /etc/nginx/nginx.conf
nginx -t && systemctl reload nginx
tail -3 /var/log/nginx/access.log     # l'IP loggato deve essere quello reale del client
```

Verificare da un'altra rete (hotspot del telefono) che l'IP che compare nel log e in
`/logs` sia quello vero e non `127.0.0.1`.

Revocare inoltre dal pannello Cloudflare R2 le **vecchie** chiavi sostituite al Task 8, Step 15,
dopo aver verificato che il nuovo server legge e scrive in cold storage senza errori (Task 8,
Step 18).

Sul **vecchio** server, il cron `abm-cleanup-stale` sospeso al Task 8, Step 8 va lasciato dov'è
(`/root/abm-cleanup-stale.OLD_SERVER_ROLLBACK`) e sparisce con la macchina: non va rimesso in
`/etc/cron.d`.

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

3. Ripristinare il vhost originale del vecchio server (salvato al Task 8, Step 9) e ricaricare nginx:

```bash
cp /etc/nginx/sites-available/audiobook-maker.precutover /etc/nginx/sites-available/audiobook-maker
nginx -t && systemctl reload nginx
```

4. Riavviare il servizio sul vecchio server — che al Task 8, Step 8 era stato **masked**, non solo disabilitato:

```bash
systemctl unmask audiobook-maker
systemctl enable audiobook-maker
systemctl start audiobook-maker
journalctl -u audiobook-maker -n 40 --no-pager
```

4-bis. Ripristinare il cron di pulizia sospeso al Task 8, Step 8:

```bash
mv /root/abm-cleanup-stale.OLD_SERVER_ROLLBACK /etc/cron.d/abm-cleanup-stale
chmod 644 /etc/cron.d/abm-cleanup-stale
chown root:root /etc/cron.d/abm-cleanup-stale
systemctl restart cron
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
9. Il ciclo di drenaggio (Task 8, Step 5) esce senza due letture consecutive pulite, o la
   sospensione dei nuovi job cade più di una volta.
10. `migration_recover_prep.py` riporta un numero di job con evento di consegna basso o nullo,
    oppure un solo job in `input mancante -> failed`.
11. `scripts/verify_r2.py` non chiude con `RISULTATO: TUTTO OK` dopo la rotazione della chiave.
12. Il download di un token **cold** (Task 8, Step 18) fallisce.
13. Il `find` del cron di pulizia, provato a vuoto, colpirebbe migliaia di job dir o job
    dell'elenco di recovery.

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

14. **Revisione critica del Task 8 (2026-08-21, prima del via libera).** Rilettura completa dei
    24 step alla ricerca di punti deboli. Dieci difetti recepiti, tutti dentro il Task 8 e il
    Task 10:

    | # | Difetto | Dove è stato corretto |
    |---|---|---|
    | 1 | Il proxy sostituiva solo `location /`, ma il vhost ne ha **sei** con `proxy_pass`: upload (`/api/analyze`) e SSE (`/api/progress/`) sarebbero rimasti puntati al servizio fermo → 502 sul traffico ancora sul vecchio IP | Step 9: vhost di cutover riscritto per intero, un solo `location /` |
    | 2 | Fra l'accensione del proxy (Step 9) e l'avvio del nuovo servizio (Step 16) passano 20-45 minuti di **502 crudo** | Step 9: `proxy_intercept_errors` + `error_page 502 503 504 = @maint` con pagina di manutenzione |
    | 3 | `input mancante -> failed` chiude i job **senza rimborso e senza email**: una delta rsync incompleta si presenta esattamente così | Step 13: cancello a `N=0` + script che elenca i job e li confronta con il vecchio server |
    | 4 | `delivered_job_ids()` ritorna un insieme vuoto **senza errore** se gli activity log mancano → email duplicate al boot | Step 13: cancello sul numero di job con evento di consegna (atteso: decine di migliaia) |
    | 5 | `--window-min 10` dichiara "non vivo" un job PREMIUM fermo da 11 minuti (rate limit Gemini, assembly lungo) → falso negativo che autorizza il freeze | Step 5 e 6: finestra a **25 minuti**, due letture consecutive pulite, tetto di 24 giri |
    | 6 | `_suspend_new_jobs` è in RAM: un restart durante il drenaggio la azzera in silenzio | Step 5: il ciclo interroga `GET /api/admin/suspend` a ogni giro e la riattiva, azzerando il contatore |
    | 7 | Il cron di pulizia stale restava attivo sul **vecchio** server per i 7 giorni di rollback, erodendo la copia di rollback | Step 8: sospensione del cron sul vecchio; Task 10 Step 5 e appendice di rollback aggiornati |
    | 8 | Il cron veniva riattivato sul nuovo senza rileggere che cosa cancella, su dati con mtime originali preservati da rsync | Step 21: `cat` del file + prova a vuoto del `find` prima di riabilitarlo |
    | 9 | Nessuna prova reale di R2 dopo la rotazione della chiave: `is_enabled()` guarda solo che le variabili non siano vuote, quindi un typo passerebbe l'avvio | Step 15: `scripts/verify_r2.py` con le env dell'unit; Step 18: download di un token **cold** vero prima dello switch DNS |
    | 10 | Un rsync ripetuto dopo lo Step 13 riporterebbe il registro sporco → rigenerazioni ed email duplicate | Step 11: regola esplicita "ogni rsync successivo obbliga a rieseguire lo Step 13" |

    Chiarito inoltre che **Cloudflare non è davanti al sito**: le direttive `set_real_ip_from` /
    `real_ip_header CF-Connecting-IP` sono un residuo morto e, finché restano, chiunque instradi
    traffico da quei range può falsificare l'IP client aggirando `limit_req`. Restano invariate
    durante il cutover (servono al doppio hop, scostamento 13) e vengono rimosse insieme al proxy
    al Task 10, Step 5.

    Recepiti in un secondo giro anche i cinque difetti minori della stessa revisione:

    | # | Difetto | Dove è stato corretto |
    |---|---|---|
    | 11 | Il log `Chunk reuse:` è emesso solo quando il riuso è > 0 (`generation_engine.py:4091`): un grep vuoto non distingue "riuso rotto" da "sintesi non ancora iniziata" | Step 17: elenco dei job con chunk su disco, poi confronto job per job con il journal (`OK` / `SOSPETTO` / `attesa`) + controllo di `Chunk reuse scan error` |
    | 12 | Lo script dei pagamenti pendenti non filtrava per data e usava `pend[-10:]`, che sull'ordine di inserimento di un dizionario non seleziona "gli ultimi dieci" | Step 6: `date +%s > /root/migration_freeze_ts`; Step 24: filtro su `used_at`/`captured_at` ≥ freeze, ordinamento temporale, stampa integrale |
    | 13 | Il `sed -i` ancorato a un `set_real_ip_from` Cloudflare poteva inserire la riga fuori dal blocco `http` senza che il `grep -n` se ne accorgesse | Step 10: conteggio preventivo dell'ancora + parser dei blocchi che stampa il contesto della riga inserita (`ESITO: OK - dentro http {}`) |
    | 14 | `pscp -batch -pw "<password root>"` lasciava la password root nella history di PowerShell | Step 2: `pscp` senza `-pw`/`-batch` (password al prompt), una sola copia verso il vecchio server e propagazione al nuovo con la chiave `id_migrate`; istruzioni di pulizia della history |
    | 15 | Lo Step 11 mescolava comandi da eseguire sul nuovo server (pre-condizione) e sul vecchio (`rsync`), senza etichetta per comando | Step 11: intestazioni `>>> NUOVO SERVER <<<` / `>>> VECCHIO SERVER <<<` e verifica `hostname -I` prima di ciascun blocco |

15. **Analisi di sicurezza post-cutover (2026-08-24) — quattro interventi applicati, tre rimandati.**
    Ricognizione sul nuovo server rispetto alle minacce esterne. Applicato **senza toccare il
    servizio** (PID invariato, nessun riavvio):

    - **Range Cloudflare rimossi da `nginx.conf`** e `real_ip_header` passato da
      `CF-Connecting-IP` a `X-Forwarded-For`. Nessun CDN sta davanti a questo origin, quindi i
      22 range erano fidati a vuoto: chi usciva da un IP Cloudflare (un Worker sul piano
      gratuito basta) poteva dichiarare un `CF-Connecting-IP` arbitrario e falsificare l'IP del
      client in log, `limit_req` e ban fail2ban. Anticipa in parte il Task 10, Step 5; resta da
      rimuovere **solo** `set_real_ip_from 80.211.136.211` alla dismissione. Backup:
      `/etc/nginx/nginx.conf.bak-20260824-sec`. Verificato: uno spoof di prova non viene più
      creduto, il traffico proxato continua a risolvere l'IP reale via `X-Forwarded-For`.
    - **Permessi dei segreti**: `override.conf` e `credentials/vertex-sa.json` da `644` a `600`,
      data dir da `755` a `750`. Erano leggibili dai tre utenti con shell (`ubuntu`,
      `backupuser`, `frangiamone`) insieme a `_payments.json` e `_vouchers.json`.
    - **Jail fail2ban `abm-admin-auth`** sui `401` di `POST /admin/login` (5 tentativi / 10 min
      → ban 1 h). L'endpoint non ha lockout applicativo: l'unico freno era `limit_req` a 10 r/s,
      cioè nessuna rilevazione del tentativo. Come `nginx-badbots`, richiede `backend = polling`:
      il default in `jail.local` è `systemd` e la jail non leggerebbe alcun file.
    - **Drop-in `hardening.conf`** (`NoNewPrivileges`, `PrivateTmp`, `ProtectHome`,
      `ProtectSystem=full`): installato con `daemon-reload`, **entra in vigore al prossimo
      restart** (deploy o reboot). Validato prima dell'installazione con `systemd-run` su un
      probe che esegue le stesse operazioni dell'app (scrittura data dir, FFmpeg, lettura del
      service account, DNS + HTTPS): tutte ok. Conseguenza forense annotata in
      `docs/FORENSICS_PLAYBOOK.md`: i temporanei della sintesi migrano in
      `/tmp/systemd-private-*/tmp/` e spariscono a ogni stop.

    Rimandati per scelta dell'utente, con la relativa esposizione:

    - **Kernel `6.8.0-36` in esecuzione contro `6.8.0-138` installato**, riavvio pendente. Da
      accorpare alla dismissione del vecchio server (30/08).
    - **SSH con `PermitRootLogin yes` + `PasswordAuthentication yes`** verso internet (202
      tentativi falliti in 24 h da 58 IP, 44 IP bannati). Chiusura al Task 10, insieme al cambio
      della password root: caricare prima la chiave pubblica dell'operatore, altrimenti
      `PasswordAuthentication no` chiude fuori.
    - **Servizio come `root`**: l'hardening sopra riduce il danno di una RCE ma non cambia
      l'utente; il passaggio a utente non privilegiato richiede il re-chown della data dir.

    **Falso allarme chiuso: `81.56.92.38` (Free SAS, FR), 216 login root con password in 7
    giorni.** È la postazione dell'operatore con l'IP precedente, non un intruso. Prove: i due
    IP non si sovrappongono mai (`176.107.155.86` compare solo dal 24/08 09:18, l'ultima
    sessione dell'altro si chiude alle 08:38); `/root/.ssh/authorized_keys` e gli script
    `step*.sh`, `migration_*` in `/root` sono stati creati dentro quelle finestre e sono i
    nostri; nessuna persistenza sospetta (cron, unit systemd, utenti, SUID recenti, connessioni
    in uscita: tutto pulito). Il pattern — raffiche di 1-3 connessioni al minuto in orario di
    lavoro — è quello di `plink -batch`, non di un accesso umano ostile.
