# ═══════════════════════════════════════════════════════════════════
# Audiobook Maker — PayPal / LLM pricing env vars setup (User scope)
# ═══════════════════════════════════════════════════════════════════
# Imposta in modo PERMANENTE (profilo utente Windows) le variabili
# d'ambiente necessarie per abilitare i pagamenti PayPal
# sull'ottimizzazione testo AI.
#
# Uso:
#   1. Apri PowerShell (NON come amministratore — scope utente)
#   2. Vai nella cartella del progetto
#   3. Esegui:   .\scripts\set_paypal_env.ps1
#   4. Chiudi e riapri eventuali shell/IDE per vedere le nuove variabili
#
# Per sbloccare l'esecuzione degli script (una tantum):
#   Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
# ═══════════════════════════════════════════════════════════════════

function Set-UserEnv {
    param([string]$Name, [string]$Value)
    [Environment]::SetEnvironmentVariable($Name, $Value, "User")
    # Aggiorna anche la sessione corrente
    Set-Item -Path "Env:$Name" -Value $Value
    Write-Host "  [OK] $Name" -ForegroundColor Green
}

function Read-NonEmpty {
    param([string]$Prompt, [string]$Default = "")
    while ($true) {
        if ($Default) {
            $input = Read-Host "$Prompt (default: $Default)"
            if ([string]::IsNullOrWhiteSpace($input)) { return $Default }
            return $input
        } else {
            $input = Read-Host $Prompt
            if (-not [string]::IsNullOrWhiteSpace($input)) { return $input }
            Write-Host "  Valore obbligatorio." -ForegroundColor Yellow
        }
    }
}

Write-Host ""
Write-Host "=== Audiobook Maker — Setup variabili PayPal (scope utente) ===" -ForegroundColor Cyan
Write-Host ""
Write-Host "Inserirai le credenziali PayPal e i parametri di pricing LLM."
Write-Host "Premi INVIO per accettare il valore di default tra parentesi."
Write-Host ""

# ── Credenziali PayPal (obbligatorie) ──
Write-Host "-- Credenziali PayPal --" -ForegroundColor Yellow
#$clientId = Read-NonEmpty "ABM_PAYPAL_CLIENT_ID"
#$secret   = Read-NonEmpty "ABM_PAYPAL_SECRET"
#$mode     = Read-NonEmpty "ABM_PAYPAL_MODE (sandbox|live)" "sandbox"
#if ($mode -notin @("sandbox","live")) {
#    Write-Host "ATTENZIONE: mode '$mode' non valido, uso 'sandbox'." -ForegroundColor Yellow
#    $mode = "sandbox"
#}

# ── Parametri pricing (con default) ──
Write-Host ""
Write-Host "-- Parametri pricing LLM (INVIO per accettare i default) --" -ForegroundColor Yellow
$rate      = Read-NonEmpty "ABM_LLM_RATE_EUR_PER_MCHAR" "2.20"
$threshold = Read-NonEmpty "ABM_LLM_FREE_THRESHOLD_EUR" "0.50"
$voucherExpiry  = Read-NonEmpty "ABM_VOUCHER_EXPIRY_DAYS"  "180"
$voucherBonus   = Read-NonEmpty "ABM_VOUCHER_BONUS_PERCENT" "10"
$paymentRetention = Read-NonEmpty "ABM_PAYMENT_RETENTION_DAYS" "730"

# ── Scrittura permanente ──
Write-Host ""
Write-Host "Scrivo le variabili nel profilo utente..." -ForegroundColor Cyan
Set-UserEnv "ABM_PAYPAL_CLIENT_ID" $clientId
Set-UserEnv "ABM_PAYPAL_SECRET"    $secret
Set-UserEnv "ABM_PAYPAL_MODE"      $mode
Set-UserEnv "ABM_LLM_RATE_EUR_PER_MCHAR" $rate
Set-UserEnv "ABM_LLM_FREE_THRESHOLD_EUR" $threshold
Set-UserEnv "ABM_VOUCHER_EXPIRY_DAYS"    $voucherExpiry
Set-UserEnv "ABM_VOUCHER_BONUS_PERCENT"  $voucherBonus
Set-UserEnv "ABM_PAYMENT_RETENTION_DAYS" $paymentRetention

Write-Host ""
Write-Host "=== Fatto! ===" -ForegroundColor Green
Write-Host ""
Write-Host "Le variabili sono ora persistenti per l'utente $env:USERNAME."
Write-Host "Riavvia le shell/IDE aperti per farle leggere."
Write-Host ""
Write-Host "Per verificare, apri una NUOVA PowerShell ed esegui:"
Write-Host '  Get-ChildItem Env: | Where-Object { $_.Name -like "ABM_*" }' -ForegroundColor Gray
Write-Host ""
Write-Host "Per rimuovere una variabile:"
Write-Host '  [Environment]::SetEnvironmentVariable("ABM_PAYPAL_CLIENT_ID", $null, "User")' -ForegroundColor Gray
Write-Host ""
