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
RETAIN_DAYS=5  # mantieni backup degli ultimi 5 giorni

echo "=========================================="
echo " Audiobook Maker - Backup"
echo " $(date)"
echo "=========================================="

mkdir -p "$BACKUP_DIR"

# ── 1. Variabili d'ambiente (override systemd) ──
echo "[1/11] Backup configurazione systemd..."
mkdir -p "$BACKUP_DIR/systemd"
cp /etc/systemd/system/audiobook-maker.service "$BACKUP_DIR/systemd/" 2>/dev/null || true
if [ -d /etc/systemd/system/audiobook-maker.service.d ]; then
    cp -r /etc/systemd/system/audiobook-maker.service.d "$BACKUP_DIR/systemd/"
fi

# ── 2. Nginx config ──
echo "[2/11] Backup configurazione Nginx..."
mkdir -p "$BACKUP_DIR/nginx"
cp /etc/nginx/nginx.conf "$BACKUP_DIR/nginx/"
cp /etc/nginx/sites-available/audiobook-maker "$BACKUP_DIR/nginx/" 2>/dev/null || true
# Salva anche lista dei siti abilitati
ls -la /etc/nginx/sites-enabled/ > "$BACKUP_DIR/nginx/sites-enabled-list.txt" 2>/dev/null || true

# ── 3. Certificati SSL (Let's Encrypt) ──
echo "[3/11] Backup certificati SSL..."
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
echo "[4/11] Backup credenziali Google Cloud..."
mkdir -p "$BACKUP_DIR/google"
if [ -d /etc/audiobook-maker ]; then
    cp /etc/audiobook-maker/*.json "$BACKUP_DIR/google/" 2>/dev/null || true
fi

# ── 5. Dati applicazione (token, voucher, pagamenti, usage) ──
echo "[5/11] Backup dati applicazione..."
DATA_DIR="/opt/audiobook-maker/data"
# Se l'unit systemd imposta ABM_DATA_DIR vale quello: e' la cartella che l'app usa davvero
UNIT_DATA_DIR=$(systemctl show audiobook-maker -p Environment --value 2>/dev/null \
    | tr ' ' '\n' | sed -n 's/^ABM_DATA_DIR=//p' | tail -1)
if [ -n "$UNIT_DATA_DIR" ] && [ -d "$UNIT_DATA_DIR" ]; then
    DATA_DIR="$UNIT_DATA_DIR"
fi
echo "  Data dir: $DATA_DIR"
mkdir -p "$BACKUP_DIR/data"
# File JSON critici (stato persistente)
for f in _download_tokens.json _payments.json _vouchers.json google_tts_usage.json _free_quota.json; do
    if [ -f "$DATA_DIR/$f" ]; then
        cp "$DATA_DIR/$f" "$BACKUP_DIR/data/"
    fi
done

# Cartella del business log: ABM_ACTIVITY_LOG_DIR dell'unit (in prod
# data/logs), altrimenti la cartella dell'app. activity.db sta accanto ai log.
ACT_DIR=$(systemctl show audiobook-maker -p Environment --value 2>/dev/null     | tr ' ' '
' | sed -n 's/^ABM_ACTIVITY_LOG_DIR=//p' | tail -1)
ACT_DIR=${ACT_DIR:-/opt/audiobook-maker}
echo "  Log dir:  $ACT_DIR"

# ── 6. Database SQLite (abm.db account, activity.db business log) ──
# Copia coerente con l'API di backup di SQLite (sicura con l'app in scrittura
# e il WAL attivo: include le pagine ancora nel -wal), poi quick_check sulla
# copia. Sul server non c'e' la CLI sqlite3: si usa il modulo di python3.
# Mai fatale: un intoppo su un DB non deve far saltare il resto del backup.
echo "[6/11] Backup database SQLite..."
backup_sqlite() {
    local src="$1" dst="$BACKUP_DIR/data/$(basename "$1")"
    if [ ! -f "$src" ]; then
        echo "  $(basename "$src"): assente in $(dirname "$src"), saltato"
        return 0
    fi
    if python3 - "$src" "$dst" <<'PYEOF'
import sqlite3, sys
from pathlib import Path
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(Path(src).resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
d = sqlite3.connect(dst)
s.backup(d)
s.close()
esito = d.execute("PRAGMA quick_check").fetchone()[0]
d.close()
if esito != "ok":
    sys.exit(f"quick_check: {esito}")
PYEOF
    then
        echo "  $(basename "$src"): ok ($(du -h "$dst" | cut -f1))"
    else
        echo "  ATTENZIONE: backup di $(basename "$src") fallito, copia a freddo"
        rm -f "$dst"
        cp "$src" "$dst" 2>/dev/null || true
        [ -f "$src-wal" ] && cp "$src-wal" "$BACKUP_DIR/data/" 2>/dev/null || true
    fi
    return 0
}
backup_sqlite "$DATA_DIR/abm.db"
backup_sqlite "$ACT_DIR/activity.db"

# ── 7. Voci campionate degli utenti ──
# user_voices/ contiene il registro (_voice_clones.json + .bak) e, per ogni
# voce, campione, file originale e demo: senza, le voci pagate non si ripristinano.
echo "[7/11] Backup voci campionate..."
if [ -d "$DATA_DIR/user_voices" ]; then
    cp -a "$DATA_DIR/user_voices" "$BACKUP_DIR/data/"
    echo "  Voci: $(find "$BACKUP_DIR/data/user_voices" -mindepth 1 -maxdepth 1 -type d | wc -l) cartelle, $(du -sh "$BACKUP_DIR/data/user_voices" | cut -f1)"
else
    echo "  ATTENZIONE: $DATA_DIR/user_voices non trovata, voci campionate non salvate"
fi

# ── 8. Log attivita' ──
echo "[8/11] Backup log attivita'..."
mkdir -p "$BACKUP_DIR/logs"
# ABM_ACTIVITY_LOG_DIR e posizione storica (cartella dell'app): si copiano
# entrambe, quella dismessa e' vuota.
cp /opt/audiobook-maker/activity_*.log "$BACKUP_DIR/logs/" 2>/dev/null || true
cp "$ACT_DIR"/activity_*.log "$BACKUP_DIR/logs/" 2>/dev/null || true
echo "  Log: $(ls "$BACKUP_DIR/logs"/activity_*.log 2>/dev/null | wc -l) file, $(du -sh "$BACKUP_DIR/logs" | cut -f1)"
cp "$DATA_DIR/voucher_admin.log" "$BACKUP_DIR/logs/" 2>/dev/null || true

# ── 9. Chiavi SSH (per deploy GitHub Actions) ──
echo "[9/11] Backup chiavi SSH..."
mkdir -p "$BACKUP_DIR/ssh"
cp ~/.ssh/authorized_keys "$BACKUP_DIR/ssh/" 2>/dev/null || true
cp ~/.ssh/id_deploy "$BACKUP_DIR/ssh/" 2>/dev/null || true
cp ~/.ssh/id_deploy.pub "$BACKUP_DIR/ssh/" 2>/dev/null || true
chmod 600 "$BACKUP_DIR/ssh/"* 2>/dev/null || true

# ── 10. Deploy script e crontab ──
echo "[10/11] Backup deploy script e crontab..."
mkdir -p "$BACKUP_DIR/scripts"
cp /opt/audiobook-maker/deploy.sh "$BACKUP_DIR/scripts/" 2>/dev/null || true
crontab -l > "$BACKUP_DIR/scripts/crontab.txt" 2>/dev/null || true

# ── 11. Informazioni sistema (per riferimento) ──
echo "[11/11] Salvataggio info sistema..."
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
