#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Audiobook Maker — Aggiornamento applicazione
# Uso: sudo bash update.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

APP_DIR="/opt/audiobook-maker"
APP_USER="audiobook"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

RED='\033[0;31m'; GREEN='\033[0;32m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

[[ $EUID -ne 0 ]] && err "Eseguire come root: sudo bash update.sh"

# Verifica che i file siano presenti
[[ ! -f "$SCRIPT_DIR/audiobook_app.py" ]] && err "audiobook_app.py non trovato"

info "Backup file corrente..."
cp "$APP_DIR/audiobook_app.py" "$APP_DIR/audiobook_app.py.bak.$(date +%Y%m%d_%H%M%S)"

info "Copia nuovi file..."
cp "$SCRIPT_DIR/audiobook_app.py" "$APP_DIR/"
[[ -f "$SCRIPT_DIR/epub_to_tts.py" ]] && cp "$SCRIPT_DIR/epub_to_tts.py" "$APP_DIR/"

info "Impostazione permessi..."
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"

info "Riavvio servizio..."
systemctl restart audiobook-maker

sleep 2

if systemctl is-active --quiet audiobook-maker; then
    info "Aggiornamento completato — servizio ATTIVO"
else
    echo -e "${RED}[✗]${NC} Servizio non attivo! Ripristino backup..."
    cp "$APP_DIR/audiobook_app.py.bak."* "$APP_DIR/audiobook_app.py" 2>/dev/null || true
    systemctl restart audiobook-maker
    err "Rollback eseguito. Controllare: journalctl -u audiobook-maker -n 50"
fi
