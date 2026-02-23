#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Audiobook Maker — Production deployment on Ubuntu 24.04
# Domain: audiobook-maker.com
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

DOMAIN="audiobook-maker.com"
APP_DIR="/opt/audiobook-maker"
APP_USER="audiobook"
VENV="$APP_DIR/venv"
LOG_DIR="/var/log/audiobook-maker"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[✓]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
err()   { echo -e "${RED}[✗]${NC} $1"; exit 1; }

[[ $EUID -ne 0 ]] && err "Eseguire come root: sudo bash setup.sh"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Audiobook Maker — Installazione produzione"
echo "  Dominio: $DOMAIN"
echo "═══════════════════════════════════════════════════"
echo ""

# ── 1. Aggiornamento sistema ──────────────────────────────────────
info "Aggiornamento pacchetti di sistema..."
apt-get update -qq
apt-get upgrade -y -qq

# ── 2. Dipendenze di sistema ──────────────────────────────────────
info "Installazione dipendenze di sistema..."
apt-get install -y -qq \
    python3 python3-venv python3-pip python3-dev \
    ffmpeg \
    nginx \
    certbot python3-certbot-nginx \
    ufw \
    git \
    libjpeg-dev zlib1g-dev libfreetype6-dev  # per Pillow

# ── 3. Utente di servizio ────────────────────────────────────────
if ! id "$APP_USER" &>/dev/null; then
    info "Creazione utente di servizio '$APP_USER'..."
    useradd --system --shell /usr/sbin/nologin --home-dir "$APP_DIR" "$APP_USER"
else
    info "Utente '$APP_USER' già esistente."
fi

# ── 4. Directory applicazione ─────────────────────────────────────
info "Configurazione directory applicazione..."
mkdir -p "$APP_DIR"
mkdir -p "$LOG_DIR"

# ── 5. Copia file applicazione ────────────────────────────────────
# I file devono essere già presenti nella directory corrente
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ ! -f "$SCRIPT_DIR/audiobook_app.py" ]]; then
    err "File audiobook_app.py non trovato in $SCRIPT_DIR."
fi
if [[ ! -f "$SCRIPT_DIR/epub_to_tts.py" ]]; then
    err "File epub_to_tts.py non trovato in $SCRIPT_DIR.
    Entrambi i file (audiobook_app.py e epub_to_tts.py) devono essere nella stessa directory di setup.sh"
fi

info "Copia file applicazione in $APP_DIR..."
cp "$SCRIPT_DIR/audiobook_app.py" "$APP_DIR/"
cp "$SCRIPT_DIR/epub_to_tts.py" "$APP_DIR/"

# ── 6. Virtual environment Python ─────────────────────────────────
info "Creazione virtual environment Python..."
python3 -m venv "$VENV"
source "$VENV/bin/activate"

info "Installazione dipendenze Python..."
pip install --upgrade pip -q
pip install -q \
    flask \
    gunicorn \
    edge-tts \
    ebooklib \
    beautifulsoup4 \
    lxml \
    Pillow

deactivate

# ── 7. Directory temporanea dedicata ──────────────────────────────
info "Configurazione directory temporanea..."
mkdir -p /tmp/audiobook_maker
chown "$APP_USER":"$APP_USER" /tmp/audiobook_maker

# ── 8. Permessi ───────────────────────────────────────────────────
info "Impostazione permessi..."
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
chown -R "$APP_USER":"$APP_USER" "$LOG_DIR"
chmod 750 "$APP_DIR"

# ── 9. Configurazione Gunicorn ────────────────────────────────────
info "Creazione configurazione Gunicorn..."
cat > "$APP_DIR/gunicorn.conf.py" << 'GUNICORN_EOF'
# Gunicorn configuration for Audiobook Maker
import multiprocessing

# Binding — solo localhost, Nginx fa da reverse proxy
bind = "127.0.0.1:5601"

# Workers — 1 worker con più thread per condividere lo stato in memoria (dict jobs)
# L'app usa asyncio per il TTS (I/O-bound), quindi i thread sono sufficienti
workers = 1
worker_class = "gthread"
threads = 8

# Timeout esteso — la generazione audio può essere lunga
timeout = 600       # 10 minuti per richiesta
graceful_timeout = 30
keepalive = 5

# Limiti
max_requests = 500          # Ricicla worker dopo N richieste
max_requests_jitter = 50    # Jitter per evitare riavvii simultanei
limit_request_line = 8190
limit_request_field_size = 8190

# Logging
accesslog = "/var/log/audiobook-maker/access.log"
errorlog = "/var/log/audiobook-maker/error.log"
loglevel = "info"

# Processo
pidfile = "/run/audiobook-maker/gunicorn.pid"
tmp_upload_dir = "/tmp/audiobook_maker"

# Preload per risparmiare memoria
preload_app = False  # False perché ogni worker ha il suo event loop asyncio

# Header di sicurezza
forwarded_allow_ips = "127.0.0.1"
proxy_protocol = False
GUNICORN_EOF

# ── 10. Systemd service ──────────────────────────────────────────
info "Creazione servizio systemd..."
cat > /etc/systemd/system/audiobook-maker.service << SERVICE_EOF
[Unit]
Description=Audiobook Maker — EPUB to MP3 converter
Documentation=https://audiobook-maker.com
After=network.target
Wants=network-online.target

[Service]
Type=notify
User=$APP_USER
Group=$APP_USER
RuntimeDirectory=audiobook-maker
WorkingDirectory=$APP_DIR
Environment="PATH=$VENV/bin:/usr/local/bin:/usr/bin"
Environment="PYTHONUNBUFFERED=1"
ExecStart=$VENV/bin/gunicorn \
    --config $APP_DIR/gunicorn.conf.py \
    audiobook_app:app
ExecReload=/bin/kill -s HUP \$MAINPID
KillMode=mixed
TimeoutStopSec=30
Restart=always
RestartSec=5

# Sicurezza — sandbox del processo
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=false
ReadWritePaths=$LOG_DIR /tmp/audiobook_maker $APP_DIR
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true

[Install]
WantedBy=multi-user.target
SERVICE_EOF

# ── 11. Nginx — configurazione HTTP iniziale ─────────────────────
info "Configurazione Nginx..."

# Rimuovi default
rm -f /etc/nginx/sites-enabled/default

cat > /etc/nginx/sites-available/audiobook-maker << 'NGINX_EOF'
# Rate limiting: max 10 richieste/sec per IP (burst 20)
limit_req_zone $binary_remote_addr zone=app_limit:10m rate=10r/s;
# Upload limiting: max 3 upload simultanei per IP
limit_req_zone $binary_remote_addr zone=upload_limit:10m rate=3r/m;

server {
    listen 80;
    listen [::]:80;
    server_name audiobook-maker.com www.audiobook-maker.com;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=()" always;

    # Body size (upload EPUB fino a 200MB)
    client_max_body_size 200M;
    client_body_timeout 120s;

    # Let's Encrypt challenge
    location /.well-known/acme-challenge/ {
        root /var/www/html;
    }

    # Proxy generale
    location / {
        limit_req zone=app_limit burst=20 nodelay;
        proxy_pass http://127.0.0.1:5601;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 600s;
        proxy_send_timeout 600s;
        proxy_connect_timeout 10s;
    }

    # Upload EPUB — rate limit più restrittivo
    location /api/analyze {
        limit_req zone=upload_limit burst=5 nodelay;
        proxy_pass http://127.0.0.1:5601;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        client_max_body_size 200M;
        client_body_buffer_size 1M;
    }

    # SSE (Server-Sent Events) per il progresso
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

    # Download — timeout esteso
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

    # Blocca accessi non necessari
    location ~ /\. { deny all; }
}
NGINX_EOF

ln -sf /etc/nginx/sites-available/audiobook-maker /etc/nginx/sites-enabled/

# ── 12. Logrotate ────────────────────────────────────────────────
info "Configurazione logrotate..."
cat > /etc/logrotate.d/audiobook-maker << 'LOGR_EOF'
/var/log/audiobook-maker/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 audiobook audiobook
    sharedscripts
    postrotate
        systemctl reload audiobook-maker 2>/dev/null || true
    endscript
}
LOGR_EOF

# ── 13. Firewall ─────────────────────────────────────────────────
info "Configurazione firewall..."
ufw --force reset > /dev/null 2>&1
ufw default deny incoming
ufw default allow outgoing
ufw allow ssh
ufw allow 'Nginx Full'
ufw --force enable
info "Firewall attivo: SSH + HTTP/HTTPS abilitati."

# ── 14. Attivazione servizi ──────────────────────────────────────
info "Attivazione servizi..."
systemctl daemon-reload
nginx -t && systemctl restart nginx
systemctl enable audiobook-maker
systemctl start audiobook-maker

# ── 15. Verifica stato ───────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
info "Installazione completata!"
echo "═══════════════════════════════════════════════════"
echo ""

if systemctl is-active --quiet audiobook-maker; then
    info "Servizio audiobook-maker: ATTIVO"
else
    warn "Servizio audiobook-maker: NON ATTIVO — controllare i log:"
    echo "  journalctl -u audiobook-maker -n 30"
fi

if systemctl is-active --quiet nginx; then
    info "Nginx: ATTIVO"
else
    warn "Nginx: NON ATTIVO — controllare: nginx -t"
fi

echo ""
echo "═══════════════════════════════════════════════════"
echo "  PROSSIMI PASSI MANUALI"
echo "═══════════════════════════════════════════════════"
echo ""
echo "  1. Verificare che il DNS A record per"
echo "     $DOMAIN punti all'IP di questo server"
echo ""
echo "  2. Ottenere il certificato SSL:"
echo ""
echo "     sudo certbot --nginx -d $DOMAIN -d www.$DOMAIN"
echo ""
echo "  3. Verificare il rinnovo automatico:"
echo ""
echo "     sudo certbot renew --dry-run"
echo ""
echo "  4. Testare l'applicazione:"
echo ""
echo "     curl -I http://$DOMAIN"
echo ""
echo "═══════════════════════════════════════════════════"
echo ""
echo "  Comandi utili:"
echo ""
echo "    Stato servizio:   systemctl status audiobook-maker"
echo "    Log applicazione: journalctl -u audiobook-maker -f"
echo "    Log Nginx:        tail -f /var/log/audiobook-maker/access.log"
echo "    Riavvio:          systemctl restart audiobook-maker"
echo "    Aggiornamento:    cp audiobook_app.py $APP_DIR/ && systemctl restart audiobook-maker"
echo ""
echo "═══════════════════════════════════════════════════"
