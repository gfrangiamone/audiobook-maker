<#
.SYNOPSIS
Banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI.

.DESCRIPTION
Wrapper parametrico: carica le credenziali da cf_tts_bench.env.ps1 (se
presente) e invoca scripts/tts_cloudflare_gemini_test.py. Nessuna logica di
misura vive qui.

.EXAMPLE
.\scripts\cf_tts_bench.ps1 -Level smoke

.EXAMPLE
.\scripts\cf_tts_bench.ps1 -Level matrix -Langs it,en -Voices Zephyr,Puck -Runs 2

.EXAMPLE
.\scripts\cf_tts_bench.ps1 -Level book -Book .\test\books\esempio.abm -Compare vertex
#>
[CmdletBinding()]
param(
    [ValidateSet('smoke', 'matrix', 'book')]
    [string]$Level = 'smoke',

    [string]$Book,
    [string[]]$Langs = @('it', 'en'),
    [string[]]$Voices = @('Zephyr'),
    [string[]]$Rates = @('+0%'),
    [string[]]$Styles = @(),

    [int]$ChunkChars = 450,
    [int]$Concurrency = 1,
    [int]$Runs = 1,
    [double]$Temperature = 0.3,
    [double]$MaxSpendEur = 2.00,
    [int]$MaxAttempts = 4,

    [ValidateSet('vertex')]
    [string]$Compare,

    [string]$OutDir = './out'
)

$ErrorActionPreference = 'Stop'
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$envFile = Join-Path $scriptDir 'cf_tts_bench.env.ps1'
if (Test-Path $envFile) {
    Write-Host "[env] carico $envFile"
    . $envFile
}
else {
    Write-Host "[env] $envFile assente: uso le variabili gia' nell'ambiente"
}

if ($Level -eq 'book' -and -not $Book) {
    throw "-Level book richiede -Book <percorso .abm|.txt>"
}
if ($Book -and -not (Test-Path $Book)) {
    throw "File non trovato: $Book"
}

$inv = [System.Globalization.CultureInfo]::InvariantCulture
$py = Join-Path $scriptDir 'tts_cloudflare_gemini_test.py'
$cliArgs = @(
    $py,
    '--level', $Level,
    '--langs', ($Langs -join ','),
    '--voices', ($Voices -join ','),
    '--rates', ($Rates -join ','),
    '--chunk-chars', $ChunkChars.ToString($inv),
    '--concurrency', $Concurrency.ToString($inv),
    '--runs', $Runs.ToString($inv),
    '--temperature', $Temperature.ToString($inv),
    '--max-spend-eur', $MaxSpendEur.ToString($inv),
    '--max-attempts', $MaxAttempts.ToString($inv),
    '--out-dir', $OutDir
)
if ($Styles.Count -gt 0) { $cliArgs += @('--styles', ($Styles -join ',')) }
if ($Book) { $cliArgs += @('--book', $Book) }
if ($Compare) { $cliArgs += @('--compare', $Compare) }

Write-Host "[run] python $($cliArgs -join ' ')"
& python @cliArgs
exit $LASTEXITCODE
