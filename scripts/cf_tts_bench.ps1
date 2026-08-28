<#
.SYNOPSIS
Banco di prova Gemini 3.1 Flash TTS su Cloudflare Workers AI.

.DESCRIPTION
Wrapper parametrico: carica le credenziali da cf_tts_bench.env.ps1 (se
presente) e invoca scripts/tts_cloudflare_gemini_test.py. Nessuna logica di
misura vive qui.

Solo i parametri passati esplicitamente vengono inoltrati allo script Python:
i default del wrapper non devono mai sovrascrivere un valore dedotto dal
libro (es. la lingua dichiarata nell'.abm). Vedi il commento su -Langs.

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

    # Se omesso, a -Level book lo script Python usa la lingua dichiarata nel
    # libro. Passarlo sempre (com'era prima) scartava quella lingua e
    # cambiava sia il gate anti-troncamento sia la stima dei token.
    [string[]]$Langs = @('it', 'en'),

    [string[]]$Voices = @('Zephyr'),
    [string[]]$Rates = @('+0%'),

    # ATTENZIONE: gli stili sono passati a Python come lista separata da
    # virgole, quindi uno stile che CONTIENE una virgola viene spezzato in
    # due stili distinti. Limite noto e accettato del formato della CLI:
    # evita le virgole dentro il testo dello stile.
    [string[]]$Styles = @(),

    [int]$ChunkChars = 450,
    [int]$Concurrency = 1,
    [int]$Runs = 1,
    [double]$Temperature = 0.3,
    [double]$MaxSpendUsd = 2.00,
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
    throw "-Level book richiede -Book <percorso .abm|.txt|.epub>"
}
if ($Book -and -not (Test-Path $Book)) {
    throw "File non trovato: $Book"
}

$inv = [System.Globalization.CultureInfo]::InvariantCulture
$py = Join-Path $scriptDir 'tts_cloudflare_gemini_test.py'

# -Level ha sempre un significato (il default 'smoke' e' anche il default
# dello script Python) e --out-dir non puo' essere dedotto dal libro: questi
# due si passano sempre. Tutti gli altri solo se l'utente li ha scritti,
# altrimenti il default del wrapper mascherebbe la logica di Python.
$cliArgs = @(
    $py,
    '--level', $Level,
    '--out-dir', $OutDir
)
if ($PSBoundParameters.ContainsKey('Langs')) { $cliArgs += @('--langs', ($Langs -join ',')) }
if ($PSBoundParameters.ContainsKey('Voices')) { $cliArgs += @('--voices', ($Voices -join ',')) }
if ($PSBoundParameters.ContainsKey('Rates')) { $cliArgs += @('--rates', ($Rates -join ',')) }
if ($PSBoundParameters.ContainsKey('ChunkChars')) { $cliArgs += @('--chunk-chars', $ChunkChars.ToString($inv)) }
if ($PSBoundParameters.ContainsKey('Concurrency')) { $cliArgs += @('--concurrency', $Concurrency.ToString($inv)) }
if ($PSBoundParameters.ContainsKey('Runs')) { $cliArgs += @('--runs', $Runs.ToString($inv)) }
if ($PSBoundParameters.ContainsKey('Temperature')) { $cliArgs += @('--temperature', $Temperature.ToString($inv)) }
if ($PSBoundParameters.ContainsKey('MaxSpendUsd')) { $cliArgs += @('--max-spend-usd', $MaxSpendUsd.ToString($inv)) }
if ($PSBoundParameters.ContainsKey('MaxAttempts')) { $cliArgs += @('--max-attempts', $MaxAttempts.ToString($inv)) }
if ($Styles.Count -gt 0) { $cliArgs += @('--styles', ($Styles -join ',')) }
if ($Book) { $cliArgs += @('--book', $Book) }
if ($Compare) { $cliArgs += @('--compare', $Compare) }

# Il log serve a riprodurre a mano un run che spende denaro: gli argomenti
# vanno quotati, altrimenti un percorso con spazi produce una riga di
# comando che sembra corretta ma non lo e' (rilievo Minor, review Task 12).
Write-Host "[run] python $(($cliArgs | ForEach-Object {
    if ($_ -match '\s') { "'" + $_ + "'" } else { $_ }
}) -join ' ')"
& python @cliArgs
exit $LASTEXITCODE
