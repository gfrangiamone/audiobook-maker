#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Restrizione SSH — accesso solo da IP autorizzato
# Uso: sudo bash restrict-ssh.sh
# ═══════════════════════════════════════════════════════════════════
set -euo pipefail

ALLOWED_IPS=("176.107.155.86" "80.211.8.90")

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GREEN}[✓]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[✗]${NC} $1"; exit 1; }

[[ $EUID -ne 0 ]] && err "Eseguire come root: sudo bash restrict-ssh.sh"

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Restrizione SSH — solo da: ${ALLOWED_IPS[*]}"
echo "═══════════════════════════════════════════════════"
echo ""

# ── Verifica connessione corrente ─────────────────────────────────
CURRENT_IP=$(echo "$SSH_CLIENT" | awk '{print $1}')
if [[ -n "$CURRENT_IP" ]]; then
    IP_OK=false
    for ip in "${ALLOWED_IPS[@]}"; do [[ "$CURRENT_IP" == "$ip" ]] && IP_OK=true; done
    if [[ "$IP_OK" == false ]]; then
        warn "Attenzione: sei connesso dall'IP $CURRENT_IP"
        warn "Gli IP autorizzati sono: ${ALLOWED_IPS[*]}"
        warn "Se prosegui, la tua connessione corrente NON verrà interrotta"
        warn "ma non potrai riconnetterti da questo IP."
        echo ""
        read -p "Continuare? (si/no): " CONFIRM
        [[ "$CONFIRM" != "si" ]] && { echo "Annullato."; exit 0; }
    fi
fi

# ── Mostra stato attuale ─────────────────────────────────────────
info "Stato firewall attuale:"
ufw status numbered
echo ""

# ── Rimuovi regole SSH generiche ──────────────────────────────────
info "Rimozione regole SSH aperte a tutti..."

# Elimina regole che permettono SSH da qualsiasi IP
# (cicla al contrario per non spostare gli indici)
while ufw status numbered | grep -qE "22(/tcp)?\s+(ALLOW|LIMIT)\s+Anywhere"; do
    RULE_NUM=$(ufw status numbered | grep -E "22(/tcp)?\s+(ALLOW|LIMIT)\s+Anywhere" | head -1 | grep -oP '^\[\s*\K[0-9]+')
    if [[ -n "$RULE_NUM" ]]; then
        echo "y" | ufw delete "$RULE_NUM" > /dev/null 2>&1
        info "  Rimossa regola #$RULE_NUM (SSH aperto a tutti)"
    fi
done

# Rimuovi anche regole IPv6 SSH generiche
while ufw status numbered | grep -qE "22(/tcp)?\s+(ALLOW|LIMIT)\s+Anywhere \(v6\)"; do
    RULE_NUM=$(ufw status numbered | grep -E "22(/tcp)?\s+(ALLOW|LIMIT)\s+Anywhere \(v6\)" | head -1 | grep -oP '^\[\s*\K[0-9]+')
    if [[ -n "$RULE_NUM" ]]; then
        echo "y" | ufw delete "$RULE_NUM" > /dev/null 2>&1
        info "  Rimossa regola #$RULE_NUM (SSH IPv6 aperto a tutti)"
    fi
done

# ── Aggiungi regola SSH limitata all'IP ───────────────────────────
info "Aggiunta regole: SSH consentito solo dagli IP autorizzati..."
for ip in "${ALLOWED_IPS[@]}"; do
    ufw allow from "$ip" to any port 22 proto tcp comment "SSH da $ip"
    info "  Aggiunta regola per $ip"
done

# ── Verifica ──────────────────────────────────────────────────────
echo ""
info "Stato firewall aggiornato:"
ufw status verbose
echo ""

# Controlla che le regole siano attive
ALL_OK=true
for ip in "${ALLOWED_IPS[@]}"; do
    if ufw status | grep -q "$ip.*22/tcp"; then
        info "SSH consentito da $ip"
    else
        warn "Regola per $ip non trovata — verificare con: ufw status"
        ALL_OK=false
    fi
done

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Completato. Riepilogo:"
echo ""
echo "  SSH (porta 22): solo da ${ALLOWED_IPS[*]}"
echo "  HTTP (porta 80): aperta a tutti"
echo "  HTTPS (porta 443): aperta a tutti"
echo ""
echo "  Per ripristinare SSH aperto a tutti:"
for ip in "${ALLOWED_IPS[@]}"; do
echo "    sudo ufw delete allow from $ip to any port 22 proto tcp"
done
echo "    sudo ufw allow ssh"
echo ""
echo "  Per aggiungere un altro IP autorizzato:"
echo "    sudo ufw allow from NUOVO_IP to any port 22 proto tcp"
echo "═══════════════════════════════════════════════════"
