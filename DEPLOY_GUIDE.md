# 🚀 Guida: GitHub + Deploy Automatico

## Come funziona

```
Push tag v1.2.3 → GitHub Actions → Test → Backup → Deploy sul server
```

Il deploy avviene **solo** quando crei un tag di release (es. `v1.0.0`).
Se i test falliscono, il deploy non parte. Se il servizio non si avvia dopo il deploy, viene eseguito un rollback automatico dal backup.

---

## 1. Crea il repository GitHub

```bash
# Sul tuo PC locale
cd /path/to/audiobook-maker

git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin git@github.com:TUO-USERNAME/audiobook-maker.git
git push -u origin main
```

Assicurati che nel repo ci siano:
- `audiobook_app.py`
- `requirements.txt`
- `tests/test_app.py`
- `.github/workflows/deploy.yml`
- `.gitignore`

---

## 2. Prepara il server

Esegui lo script di setup **una sola volta** come root:

```bash
sudo bash scripts/setup_server.sh
```

Lo script:
- Crea un utente `deploy` dedicato
- Genera una chiave SSH per i deploy
- Configura i permessi sudoers necessari
- Clona il repo in `/opt/audiobook-maker`
- Crea il servizio systemd
- Mostra la chiave privata da copiare su GitHub

---

## 3. Configura i segreti su GitHub

Vai su **GitHub → Settings → Secrets and variables → Actions** e aggiungi:

| Segreto | Valore |
|---------|--------|
| `SERVER_HOST` | IP del tuo server (es. `203.0.113.50`) |
| `SERVER_USER` | `deploy` |
| `SSH_PRIVATE_KEY` | Contenuto della chiave privata (output dello script) |
| `SERVER_PORT` | `22` (opzionale, se diverso) |

---

## 4. Come fare un deploy

Il deploy si attiva creando un **tag con versione semantica**:

```bash
# Dopo aver committato le modifiche
git add .
git commit -m "Fix: corretto bug URL duplicato nel feed"
git push

# Quando sei pronto per il deploy:
git tag v1.0.0
git push origin v1.0.0
```

Oppure crea una **Release** dalla UI di GitHub (che crea il tag automaticamente).

### Convenzione versioni

- `v1.0.0` → prima release
- `v1.0.1` → bugfix
- `v1.1.0` → nuova funzionalità
- `v2.0.0` → cambiamenti importanti

---

## 5. Cosa succede ad ogni deploy

```
1. ✅ TEST    — pytest esegue i test su GitHub
2. 📦 BACKUP — crea backup tar.gz sul server (ultimi 5)
3. ⬇️ PULL   — git checkout del tag
4. 📋 PIP    — aggiorna dipendenze se cambiate
5. 🔄 RESTART — riavvia il servizio systemd
6. ❤️ CHECK  — verifica che il servizio sia attivo
7. ↩️ ROLLBACK — se il servizio non parte, ripristina il backup
```

---

## 6. Struttura del progetto

```
audiobook-maker/
├── .github/
│   └── workflows/
│       └── deploy.yml          ← Pipeline CI/CD
├── tests/
│   ├── conftest.py
│   └── test_app.py             ← Test automatici
├── scripts/
│   └── setup_server.sh         ← Setup iniziale server
├── audiobook_app.py            ← App principale
├── requirements.txt            ← Dipendenze Python
├── .gitignore
└── README.md
```

---

## 7. Comandi utili

```bash
# Vedere lo stato del deploy
# → Vai su GitHub → Actions → vedrai lo stato di ogni deploy

# Vedere i log del servizio sul server
sudo journalctl -u audiobook-maker -f

# Rollback manuale a una versione precedente
ssh deploy@TUO-SERVER
cd /opt/audiobook-maker
sudo git checkout tags/v1.0.0 -f
sudo systemctl restart audiobook-maker

# Vedere i backup disponibili
ls -la /opt/backups/audiobook/

# Ripristinare un backup manualmente
sudo tar -xzf /opt/backups/audiobook/backup_v1.0.0_20240101_120000.tar.gz -C /opt/
sudo systemctl restart audiobook-maker
```

---

## 8. Configurazione Nginx

Se non hai già Nginx configurato, ecco un blocco base:

```nginx
server {
    listen 80;
    server_name tuo-dominio.com;

    # Redirect HTTP → HTTPS (se hai SSL)
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl;
    server_name tuo-dominio.com;

    ssl_certificate     /etc/letsencrypt/live/tuo-dominio.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tuo-dominio.com/privkey.pem;

    client_max_body_size 200M;    # Per upload EPUB grandi

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Timeout lunghi per la generazione audio
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

---

## Note

- I **test** girano su GitHub (gratis per repo pubblici, 2000 min/mese per privati).
- I **backup** vengono salvati sul server in `/opt/backups/audiobook/` (ultimi 5 mantenuti).
- Se il deploy fallisce il **rollback è automatico**: ripristina il backup e riavvia.
- La cartella `data/` (file generati a runtime) è esclusa da git e dai backup.
- Per monitorare i deploy: GitHub → repository → tab **Actions**.
