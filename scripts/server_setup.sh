#!/bin/bash
###############################################################################
# Audiobook Maker - Server Setup Script
# Esegui come root su un server Ubuntu/Debian pulito
# Usage: bash server_setup.sh
###############################################################################
set -e

echo "=========================================="
echo " Audiobook Maker - Server Setup"
echo "=========================================="
echo ""

# ---------- 0. Verifica root ----------
if [ "$(id -u)" -ne 0 ]; then
    echo "ERRORE: esegui come root (sudo bash server_setup.sh)"
    exit 1
fi

# ---------- 1. Raccogli configurazione ----------
echo "--- Configurazione variabili d'ambiente ---"
echo "(premi Invio per accettare il valore default tra parentesi)"
echo ""

read -rp "SMTP Host [smtp.gmail.com]: " SMTP_HOST
SMTP_HOST=${SMTP_HOST:-smtp.gmail.com}

read -rp "SMTP Port [587]: " SMTP_PORT
SMTP_PORT=${SMTP_PORT:-587}

read -rp "SMTP User: " SMTP_USER

read -rsp "SMTP Password: " SMTP_PASS
echo ""

read -rp "SMTP From [noreply@audiobook-maker.com]: " SMTP_FROM
SMTP_FROM=${SMTP_FROM:-noreply@audiobook-maker.com}

read -rp "Admin Email [nextswsrl@gmail.com]: " ADMIN_EMAIL
ADMIN_EMAIL=${ADMIN_EMAIL:-nextswsrl@gmail.com}

read -rsp "DeepSeek API Key: " DEEPSEEK_KEY
echo ""

read -rp "Google Credentials File path sul server [/etc/audiobook-maker/audiobook-maker-488211-e80867ce5414.json]: " GOOGLE_CREDS
GOOGLE_CREDS=${GOOGLE_CREDS:-/etc/audiobook-maker/audiobook-maker-488211-e80867ce5414.json}

read -rsp "PayPal Client ID: " PAYPAL_ID
echo ""

read -rsp "PayPal Secret: " PAYPAL_SECRET
echo ""

read -rp "PayPal Mode [live]: " PAYPAL_MODE
PAYPAL_MODE=${PAYPAL_MODE:-live}

read -rsp "Admin Token (per /admin/vouchers): " ADMIN_TOKEN
echo ""

echo ""
echo "--- Configurazione SSH ---"
echo "Incolla la tua chiave pubblica SSH (per accesso dal tuo PC)."
echo "La trovi sul tuo PC con: cat ~/.ssh/id_rsa.pub"
read -rp "Chiave pubblica SSH: " SSH_PUBKEY

echo ""
echo "=========================================="
echo " Inizio installazione..."
echo "=========================================="

# ---------- 2. Aggiorna sistema e installa dipendenze ----------
echo "[1/10] Aggiornamento sistema e installazione pacchetti..."
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git nginx certbot python3-certbot-nginx ufw

# ---------- 3. Configura firewall ----------
echo "[2/10] Configurazione firewall..."
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# ---------- 4. Configura SSH ----------
echo "[3/10] Configurazione accesso SSH..."
mkdir -p ~/.ssh
chmod 700 ~/.ssh
if [ -n "$SSH_PUBKEY" ]; then
    echo "$SSH_PUBKEY" >> ~/.ssh/authorized_keys
    chmod 600 ~/.ssh/authorized_keys
    echo "    Chiave SSH aggiunta."
else
    echo "    ATTENZIONE: nessuna chiave SSH fornita. Dovrai aggiungerla manualmente."
fi

# ---------- 5. Clona repository ----------
echo "[4/10] Clonazione repository..."
if [ -d /opt/audiobook-maker/.git ]; then
    echo "    Repository gia' presente, aggiornamento..."
    cd /opt/audiobook-maker && git pull origin main
else
    git clone https://github.com/gfrangiamone/audiobook-maker.git /opt/audiobook-maker
fi
cd /opt/audiobook-maker

# ---------- 6. Installa dipendenze Python ----------
echo "[5/10] Installazione dipendenze Python..."
pip install -r requirements.txt --break-system-packages 2>/dev/null || pip install -r requirements.txt
pip install pymupdf --break-system-packages 2>/dev/null || pip install pymupdf

# ---------- 7. Crea directory ----------
echo "[6/10] Creazione directory..."
mkdir -p /opt/audiobook-maker/data
mkdir -p /etc/audiobook-maker

# ---------- 8. Crea servizio systemd ----------
echo "[7/10] Configurazione servizio systemd..."
cat > /etc/systemd/system/audiobook-maker.service << 'SVCEOF'
[Unit]
Description=Audiobook Maker
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/audiobook-maker
ExecStart=/usr/bin/python3 /opt/audiobook-maker/audiobook_app.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

mkdir -p /etc/systemd/system/audiobook-maker.service.d
cat > /etc/systemd/system/audiobook-maker.service.d/override.conf << ENVEOF
[Service]
Environment="ABM_BASE_URL=https://audiobook-maker.com"
Environment="ABM_DATA_DIR=/opt/audiobook-maker/data"
Environment="ABM_SMTP_HOST=${SMTP_HOST}"
Environment="ABM_SMTP_PORT=${SMTP_PORT}"
Environment="ABM_SMTP_USER=${SMTP_USER}"
Environment="ABM_SMTP_PASS=${SMTP_PASS}"
Environment="ABM_SMTP_FROM=${SMTP_FROM}"
Environment="ABM_ADMIN_EMAIL=${ADMIN_EMAIL}"
Environment="ABM_DEEPSEEK_API_KEY=${DEEPSEEK_KEY}"
Environment="ABM_GOOGLE_CREDENTIALS_FILE=${GOOGLE_CREDS}"
Environment="ABM_PAYPAL_CLIENT_ID=${PAYPAL_ID}"
Environment="ABM_PAYPAL_SECRET=${PAYPAL_SECRET}"
Environment="ABM_PAYPAL_MODE=${PAYPAL_MODE}"
Environment="ABM_ADMIN_TOKEN=${ADMIN_TOKEN}"
ENVEOF

systemctl daemon-reload
systemctl enable audiobook-maker
systemctl start audiobook-maker

echo "    Attendo avvio app..."
sleep 3

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:5601 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
    echo "    App attiva sulla porta 5601."
else
    echo "    ATTENZIONE: app non risponde (HTTP $HTTP_CODE). Controlla con: journalctl -u audiobook-maker -n 30"
fi

# ---------- 9. Configura Nginx ----------
echo "[8/10] Configurazione Nginx..."

# Rimuovi config di default che potrebbe interferire
rm -f /etc/nginx/sites-enabled/default
rm -f /etc/nginx/conf.d/default.conf

cat > /etc/nginx/sites-available/audiobook-maker << 'NGXEOF'
limit_req_zone $binary_remote_addr zone=app_limit:10m rate=10r/s;
limit_req_zone $binary_remote_addr zone=upload_limit:10m rate=3r/m;

server {
    listen 80;
    listen [::]:80;
    server_name audiobook-maker.com www.audiobook-maker.com;

    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    location / {
        limit_req zone=app_limit burst=20 nodelay;
        proxy_pass http://127.0.0.1:5601;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
    }

    location /api/analyze {
        limit_req zone=upload_limit burst=5 nodelay;
        proxy_pass http://127.0.0.1:5601;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        client_max_body_size 200M;
    }

    location /api/progress/ {
        proxy_pass http://127.0.0.1:5601;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 600s;
        chunked_transfer_encoding on;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    location ~ ^/api/download {
        proxy_pass http://127.0.0.1:5601;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_buffering on;
        proxy_buffer_size 128k;
        proxy_buffers 4 256k;
    }

    location ~ /\. { deny all; }

    client_max_body_size 200M;

    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;
}
NGXEOF

# Assicurati che sites-enabled sia incluso in nginx.conf
if ! grep -q "sites-enabled" /etc/nginx/nginx.conf; then
    sed -i '/http {/a \    include /etc/nginx/sites-enabled/*;' /etc/nginx/nginx.conf
fi

ln -sf /etc/nginx/sites-available/audiobook-maker /etc/nginx/sites-enabled/
mkdir -p /var/www/html

nginx -t && systemctl restart nginx

echo "    Nginx configurato."

# ---------- 10. Certificato SSL ----------
echo "[9/10] Installazione certificato SSL Let's Encrypt..."
certbot --nginx -d audiobook-maker.com -d www.audiobook-maker.com \
    --non-interactive --agree-tos -m "$ADMIN_EMAIL" \
    --redirect

# Verifica che ora ascolti su 443
sleep 2
if ss -tlnp | grep -q ':443'; then
    echo "    SSL attivo sulla porta 443."
else
    echo "    ATTENZIONE: porta 443 non attiva. Controlla: nginx -t && systemctl restart nginx"
fi

# ---------- 11. Deploy script per GitHub Actions ----------
echo "[10/10] Creazione deploy.sh per CI/CD..."
cat > /opt/audiobook-maker/deploy.sh << 'DEPLEOF'
#!/bin/bash
set -e
cd /opt/audiobook-maker
git pull origin main
pip install -r requirements.txt --break-system-packages 2>/dev/null || pip install -r requirements.txt
systemctl restart audiobook-maker
echo "Deploy completato: $(date)"
DEPLEOF
chmod +x /opt/audiobook-maker/deploy.sh

# ---------- Riepilogo ----------
echo ""
echo "=========================================="
echo " INSTALLAZIONE COMPLETATA"
echo "=========================================="
echo ""
echo " App:     http://localhost:5601"
echo " Sito:    https://audiobook-maker.com"
echo ""
echo " COSE DA FARE MANUALMENTE:"
echo ""
echo " 1. Copia il file credenziali Google TTS sul server:"
echo "    scp audiobook-maker-488211-e80867ce5414.json root@$(hostname -I | awk '{print $1}'):${GOOGLE_CREDS}"
echo ""
echo " 2. Aggiorna i GitHub Secrets del repository:"
echo "    - SERVER_HOST = $(hostname -I | awk '{print $1}')"
echo "    - SSH_PRIVATE_KEY = (genera con: ssh-keygen -t ed25519)"
echo ""
echo " 3. Verifica il sito: curl -I https://audiobook-maker.com"
echo ""
echo " Comandi utili:"
echo "    systemctl status audiobook-maker    # stato app"
echo "    journalctl -u audiobook-maker -f    # log app"
echo "    systemctl status nginx              # stato nginx"
echo "    nginx -t                            # test config nginx"
echo "    certbot renew --dry-run             # test rinnovo SSL"
echo "=========================================="
