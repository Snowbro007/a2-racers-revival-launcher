#Requires -Version 7.0
<#
.SYNOPSIS
Atlas: wait for and read visibility data from one existing, pinned A2 I trial.
.DESCRIPTION
Checks the trial before querying processes. Observes only the exact race binary
in that trial. Does not start, stop, write to, inject into or focus the game.
The Python monitor verifies process identity, version and readable memory again.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9][a-z0-9-]{0,47}$')][string]$RunName,
    [Parameter(Mandatory = $true)]
    [ValidateNotNullOrEmpty()][string]$PythonPath,
    [ValidateRange(1, 300)][int]$DurationSeconds = 120,
    [ValidateRange(0, 300)][int]$WaitSeconds = 180
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
# ValidatePattern is case-insensitive by default; keep Quick Test names exact.
if ($RunName -cnotmatch '^[a-z0-9][a-z0-9-]{0,47}$') {
    throw 'De zichtmeting vereist een geldige Quick Test-proefnaam.'
}
if (-not [IO.Path]::IsPathRooted($PythonPath) -or
    -not (Test-Path -LiteralPath $PythonPath -PathType Leaf)) {
    throw 'De opgegeven Python-runtime ontbreekt of heeft geen absoluut pad.'
}
$workspaceRoot = Split-Path -Parent $PSScriptRoot
$monitorPath = Join-Path $PSScriptRoot 'visibility_monitor.py'
if (-not (Test-Path -LiteralPath $monitorPath -PathType Leaf)) {
    throw 'De zichtmonitor ontbreekt.'
}

# A failed static ownership/hash check must stop before any process query.
$checkArguments = @('-B', $monitorPath, '--run-name', $RunName, '--check-only')
$checkOutput = & $PythonPath @checkArguments
if ($LASTEXITCODE -ne 0) {
    throw ('De zichtmeting is niet gestart: proefcontrole mislukt. ' + ($checkOutput -join ' '))
}

$racePath = [IO.Path]::GetFullPath((Join-Path $workspaceRoot "local/experiments/a2racer1/$RunName/game/A2SPEL.DAT"))
$timer = [Diagnostics.Stopwatch]::StartNew()
while ($true) {
    $ownedRaces = @(
        foreach ($candidate in @(Get-Process -Name 'A2SPEL', 'A2SPEL.DAT' -ErrorAction SilentlyContinue)) {
            try {
                $candidatePath = $candidate.Path
                $candidateId = $candidate.Id
                if ($candidatePath -is [string] -and [IO.Path]::IsPathRooted($candidatePath) -and
                    [IO.Path]::GetFullPath($candidatePath).Equals($racePath, [StringComparison]::OrdinalIgnoreCase) -and
                    $candidateId -is [int] -and $candidateId -gt 0) {
                    $candidate
                }
            } catch {
                # Inaccessible/exited candidates cannot establish ownership.
                continue
            }
        }
    )
    if ($ownedRaces.Count -gt 1) {
        throw 'De zichtmeting is niet gestart: meerdere races voor dezelfde proef.'
    }
    if ($ownedRaces.Count -eq 1) {
        $observeArguments = @('-B', $monitorPath, '--run-name', $RunName,
            '--pid', [string]$ownedRaces[0].Id, '--seconds', [string]$DurationSeconds)
        & $PythonPath @observeArguments
        if ($LASTEXITCODE -ne 0) {
            Write-Warning 'De zichtmeting is gestopt of geweigerd. Het gameproces is ongemoeid gelaten.'
        }
        return
    }
    $remainingMilliseconds = ($WaitSeconds * 1000) - $timer.Elapsed.TotalMilliseconds
    if ($remainingMilliseconds -le 0) {
        Write-Warning 'Geen race voor deze proef gevonden; er is geen zichtmeting gestart.'
        return
    }
    Start-Sleep -Milliseconds ([int][Math]::Ceiling([Math]::Min(2000, $remainingMilliseconds)))
}
