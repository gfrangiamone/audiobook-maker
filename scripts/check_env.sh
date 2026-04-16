#!/bin/bash
###############################################################################
# Audiobook Maker - Environment Variables Check
# Verifica tutte le variabili d'ambiente necessarie per il pieno funzionamento
# Usage: bash /opt/audiobook-maker/scripts/check_env.sh
###############################################################################

echo "=========================================="
echo " Audiobook Maker - ENV Check"
echo "=========================================="
echo ""

# Leggi le variabili dall'override di systemd
OVERRIDE="/etc/systemd/system/audiobook-maker.service.d/override.conf"
if [ -f "$OVERRIDE" ]; then
    echo "[OK] Override file trovato: $OVERRIDE"
    echo ""
else
    echo "[!!] Override file NON trovato: $OVERRIDE"
    echo "     Nessuna variabile d'ambiente configurata!"
    exit 1
fi

# Funzione per controllare una variabile
check_var() {
    local name="$1"
    local required="$2"  # "required" o "optional"
    local desc="$3"
    local default="$4"

    local value
    value=$(grep "Environment=\"${name}=" "$OVERRIDE" 2>/dev/null | sed "s/.*Environment=\"${name}=\(.*\)\"/\1/")

    if [ -n "$value" ]; then
        # Maschera i valori sensibili
        if echo "$name" | grep -qiE "PASS|SECRET|KEY|TOKEN"; then
            echo "[OK] $name = ****$(echo "$value" | tail -c 5)"
        else
            echo "[OK] $name = $value"
        fi
    else
        if [ "$required" = "required" ]; then
            echo "[!!] $name = NON IMPOSTATA  *** NECESSARIA! *** ($desc)"
        else
            echo "[--] $name = non impostata (default: $default) - $desc"
        fi
    fi
}

echo "--- VARIABILI ESSENZIALI (core) ---"
check_var "ABM_BASE_URL"        "required" "URL pubblico del sito" ""
check_var "ABM_DATA_DIR"        "required" "Directory dati applicazione" "/var/lib/audiobook-maker/data"
echo ""

echo "--- EMAIL / NOTIFICHE ---"
check_var "ABM_SMTP_HOST"       "required" "Server SMTP" ""
check_var "ABM_SMTP_PORT"       "optional" "Porta SMTP" "587"
check_var "ABM_SMTP_USER"       "required" "Username SMTP" ""
check_var "ABM_SMTP_PASS"       "required" "Password SMTP" ""
check_var "ABM_SMTP_FROM"       "optional" "Mittente email" "SMTP_USER o noreply@audiobook-maker.com"
check_var "ABM_ADMIN_EMAIL"     "required" "Email per digest amministrativo" ""
echo ""

echo "--- GOOGLE CLOUD TTS ---"
check_var "ABM_GOOGLE_CREDENTIALS_FILE"    "required" "Path file JSON credenziali Google" ""
check_var "ABM_GOOGLE_TTS_MONTHLY_LIMIT"   "optional" "Limite caratteri/mese Google TTS" "1000000"
check_var "ABM_GOOGLE_TTS_RECONCILE_INTERVAL" "optional" "Intervallo riconciliazione usage (sec)" "1800"
echo ""

echo "--- DEEPSEEK LLM (ottimizzazione testo AI) ---"
check_var "ABM_DEEPSEEK_API_KEY"           "required" "API key DeepSeek per ottimizzazione AI" ""
check_var "ABM_MAX_CONCURRENT_LLM_PER_CLIENT" "optional" "Max job LLM concorrenti per client" "1"
echo ""

echo "--- PAYPAL (pagamenti) ---"
check_var "ABM_PAYPAL_CLIENT_ID"           "required" "PayPal REST API client ID" ""
check_var "ABM_PAYPAL_SECRET"              "required" "PayPal REST API secret" ""
check_var "ABM_PAYPAL_MODE"                "required" "Modalita PayPal (sandbox|live)" "sandbox"
check_var "ABM_LLM_RATE_EUR_PER_MCHAR"    "optional" "Tariffa EUR per 1M caratteri" "1.10"
check_var "ABM_LLM_FREE_THRESHOLD_EUR"    "optional" "Soglia gratuita EUR" "0.50"
echo ""

echo "--- VOUCHER ---"
check_var "ABM_VOUCHER_EXPIRY_DAYS"        "optional" "Giorni validita voucher" "180"
check_var "ABM_VOUCHER_BONUS_PERCENT"      "optional" "Percentuale bonus voucher" "10"
check_var "ABM_PAYMENT_RETENTION_DAYS"     "optional" "Giorni retention dati pagamento" "730"
echo ""

echo "--- ADMIN ---"
check_var "ABM_ADMIN_TOKEN"                "required" "Token per accesso /admin/vouchers" ""
check_var "ABM_MAX_CONCURRENT_PER_CLIENT"  "optional" "Max job concorrenti per client" "2"
echo ""

echo "--- VERIFICHE FILE ---"

# Controlla file credenziali Google
GOOGLE_CREDS=$(grep 'Environment="ABM_GOOGLE_CREDENTIALS_FILE=' "$OVERRIDE" 2>/dev/null | sed 's/.*Environment="ABM_GOOGLE_CREDENTIALS_FILE=\(.*\)"/\1/')
if [ -n "$GOOGLE_CREDS" ]; then
    if [ -f "$GOOGLE_CREDS" ]; then
        echo "[OK] File credenziali Google esiste: $GOOGLE_CREDS"
    else
        echo "[!!] File credenziali Google NON TROVATO: $GOOGLE_CREDS"
    fi
else
    echo "[!!] ABM_GOOGLE_CREDENTIALS_FILE non impostata, impossibile verificare il file"
fi

# Controlla directory dati
DATA_DIR=$(grep 'Environment="ABM_DATA_DIR=' "$OVERRIDE" 2>/dev/null | sed 's/.*Environment="ABM_DATA_DIR=\(.*\)"/\1/')
DATA_DIR=${DATA_DIR:-/var/lib/audiobook-maker/data}
if [ -d "$DATA_DIR" ]; then
    echo "[OK] Directory dati esiste: $DATA_DIR"
else
    echo "[!!] Directory dati NON TROVATA: $DATA_DIR"
fi

# Controlla deploy.sh
if [ -x /opt/audiobook-maker/deploy.sh ]; then
    echo "[OK] deploy.sh esiste ed e' eseguibile"
else
    echo "[!!] deploy.sh non trovato o non eseguibile"
fi

echo ""
echo "--- SERVIZI ---"
# Stato servizi
if systemctl is-active --quiet audiobook-maker; then
    echo "[OK] audiobook-maker: attivo"
else
    echo "[!!] audiobook-maker: NON attivo"
fi

if systemctl is-active --quiet nginx; then
    echo "[OK] nginx: attivo"
else
    echo "[!!] nginx: NON attivo"
fi

# Porta 5601
if ss -tlnp | grep -q ':5601'; then
    echo "[OK] Porta 5601: in ascolto"
else
    echo "[!!] Porta 5601: NON in ascolto"
fi

# Porta 443
if ss -tlnp | grep -q ':443'; then
    echo "[OK] Porta 443 (SSL): in ascolto"
else
    echo "[!!] Porta 443 (SSL): NON in ascolto"
fi

echo ""
echo "=========================================="
echo " Check completato"
echo "=========================================="
