#!/bin/bash
###############################################################################
# Audiobook Maker - Restore completo da backup
# Ripristina l'intera applicazione su un server Ubuntu/Debian pulito.
#
# Usage: bash restore_ABM.sh /path/to/backup.tar.gz
#
# Prerequisiti:
#   - Server Ubuntu 24.04 con accesso root
#   - File di backup (.tar.gz) copiato sul server
#   - DNS di audiobook-maker.com puntato al nuovo IP
###############################################################################
set -e

if [ "$(id -u)" -ne 0 ]; then
    echo "ERRORE: esegui come root"
    exit 1
fi

if [ -z "$1" ]; then
    echo "Usage: bash restore_ABM.sh /path/to/backup.tar.gz"
    echo ""
    echo "Backup disponibili in /opt/backup/:"
    ls -lh /opt/backup/*.tar.gz 2>/dev/null || echo "  (nessun backup trovato)"
    exit 1
fi

BACKUP_ARCHIVE="$1"
if [ ! -f "$BACKUP_ARCHIVE" ]; then
    echo "ERRORE: file non trovato: $BACKUP_ARCHIVE"
    exit 1
fi

# Estrai backup in directory temporanea
RESTORE_TMP=$(mktemp -d)
echo "Estrazione backup in $RESTORE_TMP..."
tar -xzf "$BACKUP_ARCHIVE" -C "$RESTORE_TMP"
# Il contenuto e' in una sottocartella con il nome della data
BACKUP_DIR=$(find "$RESTORE_TMP" -maxdepth 1 -mindepth 1 -type d | head -1)
if [ -z "$BACKUP_DIR" ]; then
    echo "ERRORE: struttura backup non valida"
    rm -rf "$RESTORE_TMP"
    exit 1
fi

echo "=========================================="
echo " Audiobook Maker - Restore"
echo " Backup: $BACKUP_ARCHIVE"
echo " $(date)"
echo "=========================================="

# Mostra info del backup
if [ -f "$BACKUP_DIR/system_info.txt" ]; then
    echo ""
    echo "--- Info backup originale ---"
    cat "$BACKUP_DIR/system_info.txt"
    echo "-----------------------------"
    echo ""
fi

read -rp "Procedere con il ripristino? [y/N]: " CONFIRM
if [ "$CONFIRM" != "y" ] && [ "$CONFIRM" != "Y" ]; then
    echo "Restore annullato."
    rm -rf "$RESTORE_TMP"
    exit 0
fi

# ── 1. Installa pacchetti di sistema ──
echo ""
echo "[1/10] Installazione pacchetti di sistema..."
apt update
apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx ufw

# ── 2. Configura firewall ──
echo "[2/10] Configurazione firewall..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ── 3. Clona/aggiorna repository ──
echo "[3/10] Clonazione repository..."
if [ -d /opt/audiobook-maker/.git ]; then
    cd /opt/audiobook-maker && git fetch origin main && git reset --hard origin/main
else
    git clone https://github.com/gfrangiamone/audiobook-maker.git /opt/audiobook-maker
fi

# ── 4. Installa dipendenze Python ──
echo "[4/10] Installazione dipendenze Python..."
cd /opt/audiobook-maker
pip install -r requirements.txt --break-system-packages 2>/dev/null || pip install -r requirements.txt
pip install pymupdf --break-system-packages 2>/dev/null || pip install pymupdf

# ── 5. Ripristina credenziali Google Cloud ──
echo "[5/10] Ripristino credenziali Google Cloud..."
mkdir -p /etc/audiobook-maker
if [ -d "$BACKUP_DIR/google" ]; then
    cp "$BACKUP_DIR/google/"*.json /etc/audiobook-maker/ 2>/dev/null || true
    chmod 600 /etc/audiobook-maker/*.json 2>/dev/null || true
    echo "  Credenziali Google ripristinate."
else
    echo "  ATTENZIONE: nessuna credenziale Google trovata nel backup."
fi

# ── 6. Ripristina servizio systemd + variabili d'ambiente ──
echo "[6/10] Ripristino servizio systemd..."
if [ -f "$BACKUP_DIR/systemd/audiobook-maker.service" ]; then
    cp "$BACKUP_DIR/systemd/audiobook-maker.service" /etc/systemd/system/
fi
if [ -d "$BACKUP_DIR/systemd/audiobook-maker.service.d" ]; then
    mkdir -p /etc/systemd/system/audiobook-maker.service.d
    cp "$BACKUP_DIR/systemd/audiobook-maker.service.d/"* /etc/systemd/system/audiobook-maker.service.d/
    echo "  Override con variabili d'ambiente ripristinato."
else
    echo "  ATTENZIONE: override.conf non trovato nel backup!"
    echo "  Dovrai configurare manualmente le variabili d'ambiente."
fi

# ── 7. Ripristina dati applicazione ──
echo "[7/10] Ripristino dati applicazione..."
mkdir -p /opt/audiobook-maker/data
if [ -d "$BACKUP_DIR/data" ]; then
    cp "$BACKUP_DIR/data/"*.json /opt/audiobook-maker/data/ 2>/dev/null || true
    echo "  File dati ripristinati:"
    ls -lh /opt/audiobook-maker/data/*.json 2>/dev/null || true
fi
if [ -d "$BACKUP_DIR/logs" ]; then
    cp "$BACKUP_DIR/logs/activity_"*.log /opt/audiobook-maker/ 2>/dev/null || true
    cp "$BACKUP_DIR/logs/voucher_admin.log" /opt/audiobook-maker/data/ 2>/dev/null || true
    echo "  Log attivita' ripristinati."
fi

# ── 8. Ripristina deploy script ──
echo "[8/10] Ripristino deploy script..."
if [ -f "$BACKUP_DIR/scripts/deploy.sh" ]; then
    cp "$BACKUP_DIR/scripts/deploy.sh" /opt/audiobook-maker/deploy.sh
    chmod +x /opt/audiobook-maker/deploy.sh
fi

# ── 9. Avvia applicazione ──
echo "[9/10] Avvio applicazione..."
systemctl daemon-reload
systemctl enable audiobook-maker
systemctl start audiobook-maker
sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5601 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "  App attiva sulla porta 5601."
else
    echo "  ATTENZIONE: app non risponde (HTTP $HTTP_CODE)."
    echo "  Controlla: journalctl -u audiobook-maker -n 30"
fi

# ── 10. Configura Nginx + SSL ──
echo "[10/10] Configurazione Nginx..."

# Rimuovi config di default
rm -f /etc/nginx/sites-enabled/default
rm -f /etc/nginx/conf.d/default.conf

# Ripristina config nginx
if [ -f "$BACKUP_DIR/nginx/audiobook-maker" ]; then
    cp "$BACKUP_DIR/nginx/audiobook-maker" /etc/nginx/sites-available/audiobook-maker
fi
if [ -f "$BACKUP_DIR/nginx/nginx.conf" ]; then
    cp "$BACKUP_DIR/nginx/nginx.conf" /etc/nginx/nginx.conf
fi

# Assicurati che sites-enabled sia incluso in nginx.conf
if ! grep -q "sites-enabled" /etc/nginx/nginx.conf; then
    sed -i '/http {/a \    include /etc/nginx/sites-enabled/*;' /etc/nginx/nginx.conf
fi

ln -sf /etc/nginx/sites-available/audiobook-maker /etc/nginx/sites-enabled/

# Prova a ripristinare i certificati SSL dal backup
SSL_RESTORED=false
if [ -d "$BACKUP_DIR/letsencrypt/archive" ] && [ -d "$BACKUP_DIR/letsencrypt/renewal" ]; then
    echo "  Ripristino certificati SSL dal backup..."
    mkdir -p /etc/letsencrypt
    cp -r "$BACKUP_DIR/letsencrypt/archive" /etc/letsencrypt/ 2>/dev/null || true
    cp -r "$BACKUP_DIR/letsencrypt/renewal" /etc/letsencrypt/ 2>/dev/null || true
    # Ricrea i symlink in live/
    mkdir -p /etc/letsencrypt/live/audiobook-maker.com
    LATEST=$(ls /etc/letsencrypt/archive/audiobook-maker.com/cert*.pem 2>/dev/null | sort -V | tail -1 | sed 's/.*cert//' | sed 's/.pem//')
    if [ -n "$LATEST" ]; then
        ln -sf "../../archive/audiobook-maker.com/cert${LATEST}.pem" /etc/letsencrypt/live/audiobook-maker.com/cert.pem
        ln -sf "../../archive/audiobook-maker.com/chain${LATEST}.pem" /etc/letsencrypt/live/audiobook-maker.com/chain.pem
        ln -sf "../../archive/audiobook-maker.com/fullchain${LATEST}.pem" /etc/letsencrypt/live/audiobook-maker.com/fullchain.pem
        ln -sf "../../archive/audiobook-maker.com/privkey${LATEST}.pem" /etc/letsencrypt/live/audiobook-maker.com/privkey.pem
        SSL_RESTORED=true
    fi
    cp "$BACKUP_DIR/letsencrypt/options-ssl-nginx.conf" /etc/letsencrypt/ 2>/dev/null || true
    cp "$BACKUP_DIR/letsencrypt/ssl-dhparams.pem" /etc/letsencrypt/ 2>/dev/null || true
fi

if [ "$SSL_RESTORED" = true ]; then
    echo "  Certificati SSL ripristinati dal backup."
    nginx -t && systemctl restart nginx
else
    echo "  Certificati SSL non trovati nel backup. Richiesta nuovo certificato..."
    # Rimuovi le direttive SSL dalla config nginx per far partire nginx su porta 80
    # Certbot le riaggiungerà automaticamente
    TEMP_CONF="/etc/nginx/sites-available/audiobook-maker"
    if grep -q "listen 443 ssl" "$TEMP_CONF"; then
        # Usa una config temporanea solo HTTP per far partire nginx
        cat > /etc/nginx/sites-available/audiobook-maker-temp << 'TMPEOF'
server {
    listen 80;
    listen [::]:80;
    server_name audiobook-maker.com www.audiobook-maker.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        proxy_pass http://127.0.0.1:5601;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
TMPEOF
        ln -sf /etc/nginx/sites-available/audiobook-maker-temp /etc/nginx/sites-enabled/audiobook-maker
        mkdir -p /var/www/html
        nginx -t && systemctl restart nginx
    fi

    # Richiedi nuovo certificato
    ADMIN_EMAIL=$(grep 'ABM_ADMIN_EMAIL' /etc/systemd/system/audiobook-maker.service.d/override.conf 2>/dev/null | sed 's/.*ABM_ADMIN_EMAIL=//' | sed 's/"//' || echo "")
    ADMIN_EMAIL=${ADMIN_EMAIL:-"nextswsrl@gmail.com"}
    certbot --nginx -d audiobook-maker.com -d www.audiobook-maker.com \
        --non-interactive --agree-tos -m "$ADMIN_EMAIL" --redirect

    # Ripristina la config nginx completa originale
    if [ -f "$BACKUP_DIR/nginx/audiobook-maker" ]; then
        cp "$BACKUP_DIR/nginx/audiobook-maker" /etc/nginx/sites-available/audiobook-maker
        ln -sf /etc/nginx/sites-available/audiobook-maker /etc/nginx/sites-enabled/audiobook-maker
        rm -f /etc/nginx/sites-available/audiobook-maker-temp
    fi
fi

nginx -t && systemctl restart nginx

# ── Ripristina chiavi SSH ──
echo ""
echo "--- Ripristino chiavi SSH ---"
if [ -d "$BACKUP_DIR/ssh" ]; then
    mkdir -p ~/.ssh
    chmod 700 ~/.ssh
    if [ -f "$BACKUP_DIR/ssh/authorized_keys" ]; then
        cp "$BACKUP_DIR/ssh/authorized_keys" ~/.ssh/authorized_keys
        chmod 600 ~/.ssh/authorized_keys
        echo "  authorized_keys ripristinato."
    fi
    if [ -f "$BACKUP_DIR/ssh/id_deploy" ]; then
        cp "$BACKUP_DIR/ssh/id_deploy" ~/.ssh/id_deploy
        cp "$BACKUP_DIR/ssh/id_deploy.pub" ~/.ssh/id_deploy.pub 2>/dev/null || true
        chmod 600 ~/.ssh/id_deploy
        echo "  Chiave deploy GitHub Actions ripristinata."
    fi
else
    echo "  ATTENZIONE: chiavi SSH non trovate nel backup."
    echo "  Genera nuova chiave: ssh-keygen -t ed25519 -f ~/.ssh/id_deploy -N ''"
    echo "  Poi aggiorna SSH_PRIVATE_KEY su GitHub Secrets."
fi

# ── Ripristina crontab ──
if [ -f "$BACKUP_DIR/scripts/crontab.txt" ]; then
    crontab "$BACKUP_DIR/scripts/crontab.txt"
    echo "  Crontab ripristinato."
fi

# ── Pulizia ──
rm -rf "$RESTORE_TMP"

# ── Verifica finale ──
echo ""
echo "=========================================="
echo " RESTORE COMPLETATO"
echo "=========================================="
echo ""
echo " Verifiche:"

# App
if systemctl is-active --quiet audiobook-maker; then
    echo "  [OK] audiobook-maker: attivo"
else
    echo "  [!!] audiobook-maker: NON attivo"
fi

# Nginx
if systemctl is-active --quiet nginx; then
    echo "  [OK] nginx: attivo"
else
    echo "  [!!] nginx: NON attivo"
fi

# Porta 5601
if ss -tlnp | grep -q ':5601'; then
    echo "  [OK] Porta 5601: in ascolto"
else
    echo "  [!!] Porta 5601: NON in ascolto"
fi

# Porta 443
if ss -tlnp | grep -q ':443'; then
    echo "  [OK] Porta 443 (SSL): in ascolto"
else
    echo "  [!!] Porta 443 (SSL): NON in ascolto"
fi

# Dati
for f in _download_tokens.json _vouchers.json _payments.json google_tts_usage.json; do
    if [ -f "/opt/audiobook-maker/data/$f" ]; then
        echo "  [OK] $f presente"
    else
        echo "  [--] $f non presente"
    fi
done

# Google credentials
GOOGLE_CREDS=$(grep 'ABM_GOOGLE_CREDENTIALS_FILE' /etc/systemd/system/audiobook-maker.service.d/override.conf 2>/dev/null | sed 's/.*ABM_GOOGLE_CREDENTIALS_FILE=//' | sed 's/"//')
if [ -n "$GOOGLE_CREDS" ] && [ -f "$GOOGLE_CREDS" ]; then
    echo "  [OK] Credenziali Google: $GOOGLE_CREDS"
else
    echo "  [!!] Credenziali Google non trovate"
fi

echo ""
echo " Comandi utili:"
echo "   systemctl status audiobook-maker"
echo "   journalctl -u audiobook-maker -f"
echo "   bash /opt/audiobook-maker/scripts/check_env.sh"
echo "   curl -I https://audiobook-maker.com"
echo ""
echo " Se il server ha un nuovo IP, aggiorna:"
echo "   - DNS di audiobook-maker.com"
echo "   - GitHub Secret SERVER_HOST"
echo "   - GitHub Secret SSH_PRIVATE_KEY (se chiave rigenerata)"
echo "=========================================="
