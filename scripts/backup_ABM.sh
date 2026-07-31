#!/bin/bash
###############################################################################
# Audiobook Maker - Backup giornaliero
# Salva tutti i file necessari per un ripristino completo su nuovo server.
# Usage: bash /opt/audiobook-maker/scripts/backup_ABM.sh
# Cron:  0 3 * * * /opt/audiobook-maker/scripts/backup_ABM.sh >> /var/log/abm_backup.log 2>&1
###############################################################################
set -e

BACKUP_ROOT="/opt/backup"
DATE=$(date +%Y-%m-%d_%H%M)
BACKUP_DIR="${BACKUP_ROOT}/${DATE}"
RETAIN_DAYS=14  # mantieni backup degli ultimi 14 giorni

echo "=========================================="
echo " Audiobook Maker - Backup"
echo " $(date)"
echo "=========================================="

mkdir -p "$BACKUP_DIR"

# ── 1. Variabili d'ambiente (override systemd) ──
echo "[1/9] Backup configurazione systemd..."
mkdir -p "$BACKUP_DIR/systemd"
cp /etc/systemd/system/audiobook-maker.service "$BACKUP_DIR/systemd/" 2>/dev/null || true
if [ -d /etc/systemd/system/audiobook-maker.service.d ]; then
    cp -r /etc/systemd/system/audiobook-maker.service.d "$BACKUP_DIR/systemd/"
fi

# ── 2. Nginx config ──
echo "[2/9] Backup configurazione Nginx..."
mkdir -p "$BACKUP_DIR/nginx"
cp /etc/nginx/nginx.conf "$BACKUP_DIR/nginx/"
cp /etc/nginx/sites-available/audiobook-maker "$BACKUP_DIR/nginx/" 2>/dev/null || true
# Salva anche lista dei siti abilitati
ls -la /etc/nginx/sites-enabled/ > "$BACKUP_DIR/nginx/sites-enabled-list.txt" 2>/dev/null || true

# ── 3. Certificati SSL (Let's Encrypt) ──
echo "[3/9] Backup certificati SSL..."
mkdir -p "$BACKUP_DIR/letsencrypt"
if [ -d /etc/letsencrypt ]; then
    # Copia l'intera directory letsencrypt (include renewal config, archive, live)
    cp -rL /etc/letsencrypt/live "$BACKUP_DIR/letsencrypt/live" 2>/dev/null || true
    cp -r /etc/letsencrypt/renewal "$BACKUP_DIR/letsencrypt/renewal" 2>/dev/null || true
    cp -r /etc/letsencrypt/archive "$BACKUP_DIR/letsencrypt/archive" 2>/dev/null || true
    cp /etc/letsencrypt/options-ssl-nginx.conf "$BACKUP_DIR/letsencrypt/" 2>/dev/null || true
    cp /etc/letsencrypt/ssl-dhparams.pem "$BACKUP_DIR/letsencrypt/" 2>/dev/null || true
fi

# ── 4. Credenziali Google Cloud TTS ──
echo "[4/9] Backup credenziali Google Cloud..."
mkdir -p "$BACKUP_DIR/google"
if [ -d /etc/audiobook-maker ]; then
    cp /etc/audiobook-maker/*.json "$BACKUP_DIR/google/" 2>/dev/null || true
fi

# ── 5. Dati applicazione (token, voucher, pagamenti, usage) ──
echo "[5/9] Backup dati applicazione..."
DATA_DIR="/opt/audiobook-maker/data"
mkdir -p "$BACKUP_DIR/data"
# File JSON critici (stato persistente)
for f in _download_tokens.json _payments.json _vouchers.json google_tts_usage.json _free_quota.json; do
    if [ -f "$DATA_DIR/$f" ]; then
        cp "$DATA_DIR/$f" "$BACKUP_DIR/data/"
    fi
done

# ── 6. Log attivita' ──
echo "[6/9] Backup log attivita'..."
mkdir -p "$BACKUP_DIR/logs"
cp /opt/audiobook-maker/activity_*.log "$BACKUP_DIR/logs/" 2>/dev/null || true
cp "$DATA_DIR/voucher_admin.log" "$BACKUP_DIR/logs/" 2>/dev/null || true

# ── 7. Chiavi SSH (per deploy GitHub Actions) ──
echo "[7/9] Backup chiavi SSH..."
mkdir -p "$BACKUP_DIR/ssh"
cp ~/.ssh/authorized_keys "$BACKUP_DIR/ssh/" 2>/dev/null || true
cp ~/.ssh/id_deploy "$BACKUP_DIR/ssh/" 2>/dev/null || true
cp ~/.ssh/id_deploy.pub "$BACKUP_DIR/ssh/" 2>/dev/null || true
chmod 600 "$BACKUP_DIR/ssh/"* 2>/dev/null || true

# ── 8. Deploy script e crontab ──
echo "[8/9] Backup deploy script e crontab..."
mkdir -p "$BACKUP_DIR/scripts"
cp /opt/audiobook-maker/deploy.sh "$BACKUP_DIR/scripts/" 2>/dev/null || true
crontab -l > "$BACKUP_DIR/scripts/crontab.txt" 2>/dev/null || true

# ── 9. Informazioni sistema (per riferimento) ──
echo "[9/9] Salvataggio info sistema..."
cat > "$BACKUP_DIR/system_info.txt" << SYSEOF
Backup date: $(date)
Hostname: $(hostname)
IP: $(hostname -I | awk '{print $1}')
OS: $(lsb_release -ds 2>/dev/null || cat /etc/os-release | grep PRETTY_NAME | cut -d'"' -f2)
Kernel: $(uname -r)
Python: $(python3 --version 2>&1)
Nginx: $(nginx -v 2>&1)
App version: $(grep '__version__' /opt/audiobook-maker/version.py 2>/dev/null || echo "unknown")
Git commit: $(cd /opt/audiobook-maker && git rev-parse HEAD 2>/dev/null || echo "unknown")
Git branch: $(cd /opt/audiobook-maker && git branch --show-current 2>/dev/null || echo "unknown")
Disk usage: $(df -h / | tail -1)
SYSEOF

# ── Comprimi il backup ──
echo "Compressione backup..."
cd "$BACKUP_ROOT"
tar -czf "${DATE}.tar.gz" "${DATE}/"
rm -rf "${DATE}/"
echo "Backup salvato: ${BACKUP_ROOT}/${DATE}.tar.gz ($(du -h "${DATE}.tar.gz" | cut -f1))"

# ── Pulizia vecchi backup ──
echo "Pulizia backup piu' vecchi di ${RETAIN_DAYS} giorni..."
find "$BACKUP_ROOT" -name "*.tar.gz" -mtime +${RETAIN_DAYS} -delete -print 2>/dev/null | while read f; do
    echo "  Rimosso: $f"
done

echo ""
echo "=========================================="
echo " Backup completato: $(date)"
echo "=========================================="
