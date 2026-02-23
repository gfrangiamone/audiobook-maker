#!/bin/bash
# ═══════════════════════════════════════════════════════════
#  setup_server.sh — Prepara il server per i deploy automatici
#  Eseguire UNA SOLA VOLTA sul server come root
# ═══════════════════════════════════════════════════════════
set -e

# ── Configurazione (modifica questi valori) ──
APP_DIR="/opt/audiobook-maker"
SERVICE_NAME="audiobook-maker"
DEPLOY_USER="deploy"                    # utente dedicato per i deploy
GITHUB_REPO="TUO-USERNAME/audiobook-maker"  # ← MODIFICA

echo "═══════════════════════════════════════════"
echo "  Setup server per deploy automatici"
echo "═══════════════════════════════════════════"

# ── 1. Crea utente deploy (se non esiste) ──
if ! id "$DEPLOY_USER" &>/dev/null; then
    echo "→ Creo utente $DEPLOY_USER..."
    useradd -m -s /bin/bash "$DEPLOY_USER"
    echo "  Utente creato."
else
    echo "→ Utente $DEPLOY_USER già esistente."
fi

# ── 2. Genera chiave SSH per il deploy ──
DEPLOY_HOME=$(eval echo ~$DEPLOY_USER)
SSH_DIR="$DEPLOY_HOME/.ssh"

if [ ! -f "$SSH_DIR/id_ed25519" ]; then
    echo "→ Genero chiave SSH..."
    sudo -u "$DEPLOY_USER" mkdir -p "$SSH_DIR"
    sudo -u "$DEPLOY_USER" ssh-keygen -t ed25519 -f "$SSH_DIR/id_ed25519" -N "" -C "deploy@$(hostname)"
    chmod 700 "$SSH_DIR"
    chmod 600 "$SSH_DIR/id_ed25519"
    echo "  Chiave generata."
else
    echo "→ Chiave SSH già esistente."
fi

# ── 3. Configura sudoers (comandi deploy senza password) ──
echo "→ Configuro sudoers..."
cat > /etc/sudoers.d/deploy-audiobook << 'EOF'
# Deploy audiobook-maker — comandi senza password
deploy ALL=(ALL) NOPASSWD: /usr/bin/git fetch *
deploy ALL=(ALL) NOPASSWD: /usr/bin/git checkout *
deploy ALL=(ALL) NOPASSWD: /usr/bin/pip install *
deploy ALL=(ALL) NOPASSWD: /bin/systemctl restart audiobook-maker
deploy ALL=(ALL) NOPASSWD: /bin/systemctl is-active *
deploy ALL=(ALL) NOPASSWD: /bin/mkdir -p /opt/backups/*
deploy ALL=(ALL) NOPASSWD: /bin/tar *
deploy ALL=(ALL) NOPASSWD: /bin/rm *
EOF
chmod 440 /etc/sudoers.d/deploy-audiobook
echo "  Sudoers configurato."

# ── 4. Clona il repo (se la cartella non esiste già) ──
if [ ! -d "$APP_DIR/.git" ]; then
    echo "→ Clono il repository..."
    git clone "https://github.com/$GITHUB_REPO.git" "$APP_DIR"
    chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR"
    echo "  Repository clonato in $APP_DIR"
else
    echo "→ Repository già presente in $APP_DIR"
    # Assicurati che il deploy user abbia i permessi
    chown -R "$DEPLOY_USER:$DEPLOY_USER" "$APP_DIR/.git"
fi

# ── 5. Crea cartella backup ──
mkdir -p /opt/backups/audiobook
chown "$DEPLOY_USER:$DEPLOY_USER" /opt/backups/audiobook
echo "→ Cartella backup: /opt/backups/audiobook"

# ── 6. Crea/aggiorna servizio systemd ──
echo "→ Configuro servizio systemd..."
cat > /etc/systemd/system/$SERVICE_NAME.service << EOF
[Unit]
Description=Audiobook Maker
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=$APP_DIR
ExecStart=/usr/bin/python3 $APP_DIR/audiobook_app.py
Restart=always
RestartSec=5
Environment=PYTHONUNBUFFERED=1

# Limiti di sicurezza
NoNewPrivileges=false
ProtectSystem=false

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME"
echo "  Servizio $SERVICE_NAME configurato."

# ── 7. Riepilogo ──
echo ""
echo "═══════════════════════════════════════════"
echo "  ✅ Setup completato!"
echo "═══════════════════════════════════════════"
echo ""
echo "  Prossimi passi:"
echo ""
echo "  1. Copia questa chiave PRIVATA su GitHub:"
echo "     Settings → Secrets → SSH_PRIVATE_KEY"
echo ""
echo "────────────────────────────────────────"
cat "$SSH_DIR/id_ed25519"
echo "────────────────────────────────────────"
echo ""
echo "  2. Aggiungi gli altri segreti su GitHub:"
echo "     SERVER_HOST = $(curl -s ifconfig.me 2>/dev/null || echo 'IL_TUO_IP')"
echo "     SERVER_USER = $DEPLOY_USER"
echo "     SERVER_PORT = 22"
echo ""
echo "  3. Testa il servizio:"
echo "     sudo systemctl start $SERVICE_NAME"
echo "     sudo systemctl status $SERVICE_NAME"
echo ""
