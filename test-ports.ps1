<#
.SYNOPSIS
    Test di sicurezza porte — Audiobook Maker server
.DESCRIPTION
    Verifica che sul server siano aperte SOLO le porte indispensabili (22, 80, 443)
    e che tutte le altre porte comuni siano chiuse.
.USAGE
    .\test-ports.ps1 audiobook-maker.com
    .\test-ports.ps1 203.0.113.10
    .\test-ports.ps1 audiobook-maker.com -Timeout 3000
#>

param(
    [Parameter(Mandatory=$true, Position=0)]
    [string]$Host_,

    [Parameter(Mandatory=$false)]
    [int]$Timeout = 2000
)

# ── Porte attese ──────────────────────────────────────────────────
$expectedOpen = @{
    22  = "SSH"
    80  = "HTTP"
    443 = "HTTPS"
}

# ── Porte che DEVONO essere chiuse ────────────────────────────────
$mustBeClosed = @{
    21    = "FTP"
    23    = "Telnet"
    25    = "SMTP"
    53    = "DNS"
    110   = "POP3"
    135   = "MS-RPC"
    139   = "NetBIOS"
    143   = "IMAP"
    445   = "SMB"
    993   = "IMAPS"
    995   = "POP3S"
    1433  = "MS-SQL"
    1434  = "MS-SQL Browser"
    3306  = "MySQL"
    3389  = "RDP"
    5432  = "PostgreSQL"
    5601  = "Gunicorn diretto"
    5900  = "VNC"
    6379  = "Redis"
    8080  = "HTTP alternativo"
    8443  = "HTTPS alternativo"
    8888  = "HTTP proxy"
    9090  = "Admin panel"
    9200  = "Elasticsearch"
    11211 = "Memcached"
    27017 = "MongoDB"
}

# ── Funzione test singola porta ───────────────────────────────────
function Test-Port {
    param([string]$Target, [int]$Port, [int]$Ms)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $result = $tcp.BeginConnect($Target, $Port, $null, $null)
        $waited = $result.AsyncWaitHandle.WaitOne($Ms, $false)
        if ($waited -and $tcp.Connected) {
            $tcp.Close()
            return $true
        }
        $tcp.Close()
        return $false
    } catch {
        return $false
    }
}

# ── Intestazione ──────────────────────────────────────────────────
$separator = [string]::new([char]0x2550, 56)
Write-Host ""
Write-Host $separator -ForegroundColor Cyan
Write-Host "  Audiobook Maker - Test sicurezza porte" -ForegroundColor Cyan
Write-Host "  Target: $Host_" -ForegroundColor Cyan
Write-Host "  Timeout: ${Timeout}ms" -ForegroundColor Cyan
Write-Host "  $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')" -ForegroundColor Cyan
Write-Host $separator -ForegroundColor Cyan
Write-Host ""

# ── Risoluzione DNS ───────────────────────────────────────────────
Write-Host "[*] Risoluzione DNS..." -ForegroundColor Gray
try {
    $ips = [System.Net.Dns]::GetHostAddresses($Host_) | Where-Object { $_.AddressFamily -eq 'InterNetwork' }
    if ($ips.Count -eq 0) {
        Write-Host "[!] Nessun record A trovato per $Host_" -ForegroundColor Red
        exit 1
    }
    $ip = $ips[0].ToString()
    Write-Host "[+] Risolto: $Host_ -> $ip" -ForegroundColor Green
} catch {
    Write-Host "[!] Impossibile risolvere $Host_" -ForegroundColor Red
    exit 1
}

Write-Host ""
$issues = 0
$totalPorts = $expectedOpen.Count + $mustBeClosed.Count

# ── Test porte che devono essere APERTE ───────────────────────────
Write-Host "--- Porte che devono essere APERTE ---" -ForegroundColor White
Write-Host ""

foreach ($port in ($expectedOpen.Keys | Sort-Object)) {
    $name = $expectedOpen[$port]
    $label = "{0,5} ({1})" -f $port, $name
    Write-Host "  Porta $label ... " -NoNewline

    $open = Test-Port -Target $Host_ -Port $port -Ms $Timeout
    if ($open) {
        Write-Host "APERTA" -ForegroundColor Green
    } else {
        Write-Host "CHIUSA [PROBLEMA]" -ForegroundColor Red
        $issues++
    }
}

Write-Host ""
Write-Host "--- Porte che devono essere CHIUSE ---" -ForegroundColor White
Write-Host ""

# ── Test porte che devono essere CHIUSE ───────────────────────────
foreach ($port in ($mustBeClosed.Keys | Sort-Object)) {
    $name = $mustBeClosed[$port]
    $label = "{0,5} ({1})" -f $port, $name
    Write-Host "  Porta $label ... " -NoNewline

    $open = Test-Port -Target $Host_ -Port $port -Ms $Timeout
    if ($open) {
        Write-Host "APERTA [PROBLEMA]" -ForegroundColor Red
        $issues++
    } else {
        Write-Host "chiusa" -ForegroundColor Green
    }
}

# ── Riepilogo ─────────────────────────────────────────────────────
Write-Host ""
Write-Host $separator -ForegroundColor Cyan

if ($issues -eq 0) {
    Write-Host ""
    Write-Host "  RISULTATO: TUTTO OK" -ForegroundColor Green
    Write-Host "  Solo le porte 22, 80 e 443 sono raggiungibili." -ForegroundColor Green
    Write-Host "  La porta 5601 (Gunicorn) non e' esposta direttamente." -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "  RISULTATO: $issues PROBLEMI RILEVATI" -ForegroundColor Red
    Write-Host "  Verificare la configurazione del firewall (ufw)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Comandi utili sul server:" -ForegroundColor Yellow
    Write-Host "    sudo ufw status verbose" -ForegroundColor Gray
    Write-Host "    sudo ss -tlnp" -ForegroundColor Gray
    Write-Host ""
}

Write-Host $separator -ForegroundColor Cyan
Write-Host ""

exit $issues
